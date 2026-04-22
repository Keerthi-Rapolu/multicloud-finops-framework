/*
  stg_azure_cost — Azure Cost Management Export staging model (Bronze → Silver)

  Reads raw amortized Parquet files, casts types, parses Tags JSON,
  extracts tag columns, renames to snake_case.

  Passes through UnusedReservation / UnusedSavingsPlan rows so int_azure_nec
  can separate used cost from commitment waste and compute true NEC.
*/

with source as (
    select * from read_parquet('{{ var("data_root") }}/raw/azure/**/*.parquet')
),

staged as (
    select
        -- Identity / billing hierarchy
        nullif(BillingAccountId, '')                                            as billing_account_id,
        SubscriptionId                                                          as account_id,
        SubscriptionName                                                        as account_name,
        nullif(AccountOwnerId,   '')                                            as account_owner_id,
        InvoiceSectionName                                                      as invoice_section,
        ResourceGroup                                                           as resource_group,

        -- Timestamps (daily grain)
        strptime(Date, '%Y-%m-%d')                                              as usage_date,
        strftime(strptime(Date, '%Y-%m-%d'), '%Y-%m')                          as billing_month,

        -- Resource
        ResourceId                                                              as resource_id,
        nullif(trim(ResourceName), '')                                          as resource_name,
        nullif(trim(ConsumedService), '')                                       as consumed_service,
        ProductName                                                             as product_name,
        MeterCategory                                                           as service_name,
        MeterSubcategory                                                        as service_subcategory,
        MeterName                                                               as meter_name,
        MeterId                                                                 as meter_id,
        lower(trim(ResourceLocation))                                           as region,
        ServiceFamily                                                           as service_family,
        ChargeType                                                              as charge_type,
        PublisherType                                                           as publisher_type,

        -- vCPUs from AdditionalInfo JSON (VMs only; null for storage/SQL/shared)
        try_cast(nullif(trim(json_extract_string(AdditionalInfo, '$.vCPUs')), '') as integer) as vcpus,

        -- Usage
        try_cast(Quantity   as double)                                          as usage_amount,
        Unit                                                                    as usage_unit,
        try_cast(UnitPrice  as double)                                          as unit_price,
        BillingCurrency                                                         as currency,

        -- Cost: CostInBillingCurrency from the AMORTIZED export.
        -- This is the actual amortized daily cost — NOT the retail/OD price.
        -- For RI/SP Usage rows: this is the amortized commitment slice (less than OD).
        -- For UnusedReservation/SP rows: this is the waste cost (no usage, cost > 0).
        -- Retail equivalent (true OD price) = payg_price × usage_amount — see below.
        try_cast(CostInBillingCurrency as double)                               as billed_cost,

        -- Retail cost: what this usage would cost at full on-demand (PAYG) rates.
        -- Use this as list_cost for savings calculations vs OD baseline.
        -- Null for UnusedReservation/SP rows where payg_price may not apply.
        try_cast(PayGPrice as double) * try_cast(Quantity as double)            as retail_cost,

        -- Pricing model and effective vs list price
        nullif(trim(PricingModel), '')                                          as pricing_model,
        try_cast(EffectivePrice as double)                                      as effective_price,
        try_cast(PayGPrice      as double)                                      as payg_price,

        -- Commitment / RI / SP
        nullif(BenefitId,   '')                                                 as benefit_id,
        nullif(BenefitName, '')                                                 as benefit_name,
        case
            when nullif(BenefitName, '') is not null then true else false
        end                                                                     as has_commitment,

        -- Waste flag: UnusedReservation / UnusedSavingsPlan rows cost money but ran nothing
        case
            when ChargeType in ('UnusedReservation', 'UnusedSavingsPlan')
            then true else false
        end                                                                     as is_commitment_waste,

        -- Tags — parsed from JSON blob
        -- Azure Tags format: {"team": "platform", "environment": "prod", ...}
        nullif(trim(lower(json_extract_string(Tags, '$.team'))),        '')     as tag_team,
        nullif(trim(lower(json_extract_string(Tags, '$.environment'))), '')     as tag_environment,
        nullif(trim(lower(json_extract_string(Tags, '$.costcenter'))),  '')     as tag_cost_center,

        -- Derived flags
        case
            when nullif(trim(lower(json_extract_string(Tags, '$.team'))), '')
                 is not null
            then true else false
        end                                                                     as is_tagged,

        'azure'                                                                 as cloud_provider

    from source
    -- Keep only rows relevant to NEC: actual usage and unused commitment capacity.
    -- Purchase (upfront RI buy), Tax, and Adjustment rows are excluded intentionally —
    -- they represent billing events, not resource consumption, and distort NEC calculations.
    where ChargeType in ('Usage', 'UnusedReservation', 'UnusedSavingsPlan')
)

select * from staged
