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
        -- Identity / billing
        "identity/LineItemId"                                               as line_item_id,
        "bill/PayerAccountId"                                               as payer_account_id,
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
        nullif(trim(cast("product/vcpu"   as varchar)), '')                 as vcpu,
        nullif(trim("product/memory"),                  '')                 as memory,
        "product/operatingSystem"                                           as operating_system,
        "lineItem/UsageType"                                                as usage_type,
        "lineItem/Operation"                                                as operation,
        "product/region"                                                    as region,
        "lineItem/AvailabilityZone"                                         as availability_zone,

        -- Usage & normalisation
        try_cast("lineItem/UsageAmount"              as double)             as usage_amount,
        try_cast("lineItem/NormalizationFactor"      as double)             as normalization_factor,
        try_cast("lineItem/NormalizedUsageAmount"    as double)             as normalized_usage_amount,
        "pricing/unit"                                                      as pricing_unit,
        try_cast("pricing/publicOnDemandRate"        as double)             as on_demand_rate,
        -- on_demand_cost = publicOnDemandRate × usage_amount = true OD list price.
        -- Used as list_cost in the mart for savings_vs_od calculation.
        try_cast("pricing/publicOnDemandCost"        as double)             as on_demand_cost,

        -- Raw costs (NEC derived in intermediate layer)
        try_cast("lineItem/UnblendedCost"       as double)                  as unblended_cost,
        try_cast("lineItem/BlendedCost"         as double)                  as blended_cost,

        -- RI fields (DiscountedUsage rows: per-hour cost; RIFee rows: monthly summary)
        nullif("reservation/ReservationARN",    '')                         as reservation_arn,
        try_cast("reservation/EffectiveCost"                        as double) as reservation_effective_cost,
        try_cast("reservation/AmortizedUpfrontCostForUsage"         as double) as reservation_amortized_upfront,
        try_cast("reservation/RecurringFeeForUsage"                 as double) as reservation_recurring_fee,
        -- Unused RI capacity (populated on RIFee rows only)
        try_cast("reservation/UnusedQuantity"                       as double) as reservation_unused_quantity,
        try_cast("reservation/UnusedAmortizedUpfrontFeeForBillingPeriod" as double) as reservation_unused_upfront_fee,
        try_cast("reservation/UnusedRecurringFee"                   as double) as reservation_unused_recurring_fee,

        -- SP fields (SavingsPlanCoveredUsage rows: per-hour; SavingsPlanRecurringFee: monthly summary)
        nullif("savingsPlan/SavingsPlanARN",            '')                    as savings_plan_arn,
        try_cast("savingsPlan/SavingsPlanEffectiveCost" as double)             as savings_plan_effective_cost,
        try_cast("savingsPlan/SavingsPlanRate"          as double)             as savings_plan_rate,
        try_cast("savingsPlan/UsedCommitment"           as double)             as savings_plan_used_commitment,
        try_cast("savingsPlan/TotalCommitmentToDate"    as double)             as savings_plan_total_commitment,
        try_cast("savingsPlan/RecurringCommitmentForBillingPeriod" as double)  as savings_plan_recurring_commitment,

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
        -- SavingsPlanNegation rows are intentionally excluded:
        -- they are negative-cost offsets AWS creates to balance SP discounts
        -- and would distort NEC if summed. Effective cost is already correct
        -- on SavingsPlanCoveredUsage rows without including the negation row.
        -- Tax, Support, and Marketplace rows are also excluded — they carry
        -- unblended_cost but no on_demand_cost, which would inflate NEC vs OD baseline.
    )
)

select * from staged
