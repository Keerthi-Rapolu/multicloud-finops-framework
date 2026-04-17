/*
  stg_azure_cost — Azure Cost Management Export staging model (Bronze → Silver)

  Reads raw amortized Parquet files, casts types, parses Tags JSON,
  extracts tag columns, renames to snake_case.
  Does NOT compute NEC — already amortized at source; int_azure_nec adds context.
*/

with source as (
    select * from read_parquet('{{ var("data_root") }}/raw/azure/**/*.parquet')
),

staged as (
    select
        -- Identity
        SubscriptionId                                                          as account_id,
        SubscriptionName                                                        as account_name,
        InvoiceSectionName                                                      as invoice_section,
        ResourceGroup                                                           as resource_group,

        -- Timestamps (daily grain)
        strptime(Date, '%Y-%m-%d')                                              as usage_date,
        strftime(strptime(Date, '%Y-%m-%d'), '%Y-%m')                          as billing_month,

        -- Resource
        ResourceId                                                              as resource_id,
        ProductName                                                             as product_name,
        MeterCategory                                                           as service_name,
        MeterSubcategory                                                        as service_subcategory,
        MeterName                                                               as meter_name,
        MeterId                                                                 as meter_id,
        lower(trim(ResourceLocation))                                           as region,
        ServiceFamily                                                           as service_family,
        ChargeType                                                              as charge_type,
        PublisherType                                                           as publisher_type,

        -- Usage
        try_cast(Quantity   as double)                                          as usage_amount,
        Unit                                                                    as usage_unit,
        try_cast(UnitPrice  as double)                                          as unit_price,
        BillingCurrency                                                         as currency,

        -- Cost (amortized — RI/SP upfront already spread daily)
        try_cast(CostInBillingCurrency as double)                               as list_cost,

        -- Commitment / RI / SP
        nullif(BenefitId,   '')                                                 as benefit_id,
        nullif(BenefitName, '')                                                 as benefit_name,
        case
            when nullif(BenefitName, '') is not null then true else false
        end                                                                     as has_commitment,

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
    where ChargeType = 'Usage'
)

select * from staged
