/*
  stg_aws_cur — AWS Cost and Usage Report staging model (Bronze → Silver)

  Reads raw Parquet files, casts types, renames columns to snake_case,
  and derives is_tagged. Does NOT compute NEC — that happens in int_aws_nec.
*/

with source as (
    select * from read_parquet('{{ var("data_root") }}/raw/aws/**/*.parquet')
),

staged as (
    select
        -- Identity
        "identity/LineItemId"                                               as line_item_id,
        "lineItem/UsageAccountId"                                           as account_id,
        "lineItem/LineItemType"                                             as line_item_type,

        -- Timestamps (hourly grain)
        strptime("lineItem/UsageStartDate", '%Y-%m-%dT%H:%M:%SZ')          as usage_start_time,
        strptime("lineItem/UsageEndDate",   '%Y-%m-%dT%H:%M:%SZ')          as usage_end_time,
        strftime(
            strptime("lineItem/UsageStartDate", '%Y-%m-%dT%H:%M:%SZ'),
            '%Y-%m'
        )                                                                   as billing_month,

        -- Resource
        "lineItem/ResourceId"                                               as resource_id,
        "lineItem/ProductCode"                                              as service_name,
        "product/ProductName"                                               as product_name,
        "product/instanceType"                                              as instance_type,
        "product/operatingSystem"                                           as operating_system,
        "lineItem/UsageType"                                                as usage_type,
        "lineItem/Operation"                                                as operation,
        "product/region"                                                    as region,
        "lineItem/AvailabilityZone"                                         as availability_zone,

        -- Usage
        try_cast("lineItem/UsageAmount"         as double)                  as usage_amount,
        "pricing/unit"                                                      as pricing_unit,
        try_cast("pricing/publicOnDemandRate"   as double)                  as on_demand_rate,
        try_cast("pricing/publicOnDemandCost"   as double)                  as on_demand_cost,

        -- Raw costs (NEC derived in intermediate layer)
        try_cast("lineItem/UnblendedCost"       as double)                  as unblended_cost,
        try_cast("lineItem/BlendedCost"         as double)                  as blended_cost,

        -- RI fields (populated only when line_item_type = 'DiscountedUsage')
        nullif("reservation/ReservationARN",    '')                         as reservation_arn,
        try_cast("reservation/EffectiveCost"    as double)                  as reservation_effective_cost,
        try_cast("reservation/AmortizedUpfrontCostForUsage" as double)      as reservation_amortized_upfront,
        try_cast("reservation/RecurringFeeForUsage"         as double)      as reservation_recurring_fee,

        -- SP fields (populated only when line_item_type = 'SavingsPlanCoveredUsage')
        nullif("savingsPlan/SavingsPlanARN",            '')                 as savings_plan_arn,
        try_cast("savingsPlan/SavingsPlanEffectiveCost" as double)          as savings_plan_effective_cost,
        try_cast("savingsPlan/SavingsPlanRate"          as double)          as savings_plan_rate,

        -- Tags (raw → normalised)
        nullif(trim(lower("resourceTags/user:Team")),        '')            as tag_team,
        nullif(trim(lower("resourceTags/user:Environment")), '')            as tag_environment,
        nullif(trim(lower("resourceTags/user:CostCenter")),  '')            as tag_cost_center,

        -- Derived flags
        case
            when nullif(trim(lower("resourceTags/user:Team")), '') is not null
            then true else false
        end                                                                 as is_tagged,

        'aws'                                                               as cloud_provider

    from source
    where "lineItem/LineItemType" in (
        'Usage',
        'DiscountedUsage',
        'SavingsPlanCoveredUsage',
        'RIFee',
        'SavingsPlanRecurringFee'
    )
)

select * from staged
