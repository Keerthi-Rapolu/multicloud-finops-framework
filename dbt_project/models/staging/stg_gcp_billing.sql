/*
  stg_gcp_billing — GCP Billing Detailed Usage Export staging model (Bronze → Silver)

  Reads raw hourly Parquet files, casts types, parses labels (list-of-dicts)
  and credits (list-of-dicts) JSON arrays using DuckDB macros,
  renames to snake_case.
  Does NOT compute NEC — credit aggregation for NEC happens in int_gcp_nec.
*/

with source as (
    select * from read_parquet('{{ var("data_root") }}/raw/gcp/**/*.parquet')
),

staged as (
    select
        -- Identity
        billing_account_id                                                      as billing_account_id,
        "project.id"                                                            as account_id,
        "project.name"                                                          as account_name,
        "project.number"                                                        as project_number,

        -- Service / SKU
        "service.id"                                                            as service_id,
        "service.description"                                                   as service_name,
        "sku.id"                                                                as sku_id,
        "sku.description"                                                       as sku_description,

        -- Timestamps (hourly for compute; daily for storage SKUs)
        strptime("usage_start_time", '%Y-%m-%dT%H:%M:%SZ')                     as usage_start_time,
        strptime("usage_end_time",   '%Y-%m-%dT%H:%M:%SZ')                     as usage_end_time,
        strftime(
            strptime("usage_start_time", '%Y-%m-%dT%H:%M:%SZ'),
            '%Y-%m'
        )                                                                       as billing_month,
        "invoice.month"                                                         as invoice_month,

        -- Resource
        "resource.name"                                                         as resource_id,
        "resource.global_name"                                                  as resource_global_name,

        -- Location
        "location.region"                                                       as region,
        "location.zone"                                                         as zone,
        "location.country"                                                      as country,

        -- Usage
        try_cast("usage.amount"                 as double)                      as usage_amount,
        "usage.unit"                                                            as usage_unit,
        try_cast("usage.amount_in_pricing_units" as double)                     as usage_amount_pricing,
        "usage.pricing_unit"                                                    as pricing_unit,

        -- Cost (before credits)
        try_cast(cost                           as double)                      as list_cost,
        currency                                                                as currency,
        cost_type                                                               as cost_type,

        -- Credits JSON — raw string kept for int_gcp_nec to aggregate
        credits                                                                 as credits_raw,

        -- Total credit amount from discount types (negative = savings)
        {{ sum_gcp_credits("credits") }}                                        as total_credit_amount,

        -- Labels — parsed from list-of-dicts
        -- GCP labels format: [{"key": "team", "value": "platform"}, ...]
        nullif(trim(lower({{ extract_gcp_label("labels", "team") }})),        '') as tag_team,
        nullif(trim(lower({{ extract_gcp_label("labels", "environment") }})), '') as tag_environment,
        nullif(trim(lower({{ extract_gcp_label("labels", "cost_center") }})), '') as tag_cost_center,

        -- Derived flags
        case
            when nullif(trim(lower({{ extract_gcp_label("labels", "team") }})), '')
                 is not null
            then true else false
        end                                                                     as is_tagged,

        'gcp'                                                                   as cloud_provider

    from source
    where cost_type = 'regular'
)

select * from staged
