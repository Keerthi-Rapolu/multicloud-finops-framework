/*
  fct_unified_billing — Cloud-Agnostic Schema (CAS) unified billing fact table

  UNION ALL of AWS + Azure + GCP intermediate NEC models.
  One row per billable line item, with a consistent column set across clouds.

  Key columns:
    nec           — Net Effective Cost (commitment-adjusted)
    list_cost     — Pre-discount / gross cost
    discount_type — ri | sp | on_demand
    cloud_provider, billing_month, tag_team, is_tagged
*/

with aws as (
    select
        cloud_provider,
        billing_month,
        account_id,
        cast(null as varchar)           as account_name,
        usage_start_time                as usage_date,
        resource_id,
        service_name,
        product_name,
        instance_type,
        region,
        usage_amount,
        pricing_unit                    as usage_unit,
        'USD'                           as currency,
        on_demand_cost                  as list_cost,
        nec,
        discount_type,
        tag_team,
        tag_environment,
        tag_cost_center,
        is_tagged
    from {{ ref('int_aws_nec') }}
),

azure as (
    select
        cloud_provider,
        billing_month,
        account_id,
        account_name,
        cast(usage_date as timestamp)   as usage_date,
        resource_id,
        service_name,
        product_name,
        cast(null as varchar)           as instance_type,
        region,
        usage_amount,
        usage_unit,
        currency,
        list_cost,
        nec,
        discount_type,
        tag_team,
        tag_environment,
        tag_cost_center,
        is_tagged
    from {{ ref('int_azure_nec') }}
),

gcp as (
    select
        cloud_provider,
        billing_month,
        account_id,
        account_name,
        usage_start_time                as usage_date,
        resource_id,
        service_name,
        sku_description                 as product_name,
        cast(null as varchar)           as instance_type,
        region,
        usage_amount,
        usage_unit,
        currency,
        list_cost,
        nec,
        discount_type,
        tag_team,
        tag_environment,
        tag_cost_center,
        is_tagged
    from {{ ref('int_gcp_nec') }}
),

unified as (
    select * from aws
    union all
    select * from azure
    union all
    select * from gcp
)

select * from unified
