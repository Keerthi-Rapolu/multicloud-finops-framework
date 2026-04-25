/*
  stg_gcp_billing — GCP Billing Detailed Usage Export staging model (Bronze → Silver)

  Reads raw Parquet files, casts types, parses system_labels and labels
  (list-of-dicts) JSON arrays using DuckDB macros, renames to snake_case.
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
        "project.ancestry_numbers"                                              as project_ancestry,

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

        -- Compute metadata from system_labels (GCE only; null for Storage/BQ/SQL)
        -- system_labels format: [{"key": "compute_cores", "value": "4"}, ...]
        try_cast(
            nullif({{ extract_gcp_label("system_labels", "compute_cores") }},   '')
        as integer)                                                             as compute_cores,
        try_cast(
            nullif({{ extract_gcp_label("system_labels", "compute_memory") }},  '')
        as integer)                                                             as compute_memory_gb,
        try_cast(
            nullif({{ extract_gcp_label("system_labels", "cpu_util_pct") }}, '')
        as double)                                                              as cpu_util_pct,
        try_cast(
            nullif({{ extract_gcp_label("system_labels", "memory_util_pct") }}, '')
        as double)                                                              as memory_util_pct,
        try_cast(
            nullif({{ extract_gcp_label("system_labels", "disk_util_pct") }}, '')
        as double)                                                              as disk_util_pct,
        try_cast(
            nullif({{ extract_gcp_label("system_labels", "idle_hours") }}, '')
        as double)                                                              as idle_hours,
        try_strptime(
            {{ extract_gcp_label("system_labels", "last_activity_at") }},
            '%Y-%m-%dT%H:%M:%SZ'
        )                                                                       as last_activity_at,
        case
            when {{ extract_gcp_label("system_labels", "is_unused_reservation") }} = 'true'
            then true else false
        end                                                                     as is_unused_reservation,

        -- Usage
        try_cast("usage.amount"   as double)                                    as usage_amount,
        "usage.unit"                                                            as usage_unit,
        "usage.pricing_unit"                                                    as pricing_unit,

        -- Cost (before credits = list/on-demand price)
        try_cast(cost             as double)                                    as list_cost,
        try_cast(cost_at_list     as double)                                    as cost_at_list,
        currency                                                                as currency,
        cost_type                                                               as cost_type,

        -- Credits JSON — raw string kept for int_gcp_nec to aggregate
        credits                                                                 as credits_raw,

        -- Total credit amount from CUD/SUD/promotion (negative = savings)
        {{ sum_gcp_credits("credits") }}                                        as total_credit_amount,

        -- Net cost after all credits
        try_cast(cost as double) + ({{ sum_gcp_credits("credits") }})          as net_cost,

        -- Labels — parsed from list-of-dicts
        -- GCP labels format: [{"key": "team", "value": "platform"}, ...]
        nullif(trim(lower({{ extract_gcp_label("labels", "team") }})),        '') as tag_team,
        nullif(trim(lower({{ extract_gcp_label("labels", "environment") }})), '') as tag_environment,
        nullif(trim(lower({{ extract_gcp_label("labels", "cost_center") }})), '') as tag_cost_center,
        nullif(trim(lower({{ extract_gcp_label("labels", "business_unit") }})), '') as tag_business_unit,
        nullif(trim(lower({{ extract_gcp_label("labels", "application") }})), '') as tag_application,
        nullif(trim(lower({{ extract_gcp_label("labels", "owner_email") }})), '') as tag_owner_email,
        nullif(trim(lower({{ extract_gcp_label("labels", "support_group") }})), '') as tag_support_group,
        nullif(trim(lower({{ extract_gcp_label("labels", "workload_criticality") }})), '') as tag_workload_criticality,
        nullif(trim(lower({{ extract_gcp_label("labels", "sla_tier") }})), '') as tag_sla_tier,

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
