/*
  fct_unified_billing

  Cloud-agnostic billing fact table with:
    - NEC / waste measures
    - shared-cost allocation fields
    - normalized service_category
    - workload metadata used by the dashboard decision engine
*/

with aws as (
    select
        cloud_provider,
        payer_account_id as billing_account_id,
        billing_month,
        account_id,
        cast(null as varchar) as account_name,
        usage_start_time as usage_date,
        resource_id,
        service_name,
        product_name,
        instance_type,
        region,
        cpu_util_pct,
        memory_util_pct,
        disk_util_pct,
        idle_hours,
        last_activity_at,
        usage_amount,
        pricing_unit as usage_unit,
        'USD' as currency,
        on_demand_cost as list_cost,
        nec,
        nec_used,
        nec_waste,
        cast(null as double) as effective_unit_price,
        discount_type,
        try_cast(vcpu as integer) as vcpu,
        try_cast(regexp_extract(memory, '(\d+)', 1) as integer) as memory_gb,
        tag_team,
        tag_environment,
        tag_cost_center,
        cast(null as varchar) as tag_business_unit,
        cast(null as varchar) as tag_application,
        cast(null as varchar) as tag_owner_email,
        cast(null as varchar) as tag_workload_criticality,
        cast(null as varchar) as tag_sla_tier,
        is_tagged,
        tag_team as allocated_team,
        nec as allocated_nec,
        false as is_shared_cost,
        is_commitment_waste
    from {{ ref('int_aws_nec') }}
),

azure as (
    select
        cloud_provider,
        billing_account_id,
        billing_month,
        account_id,
        account_name,
        cast(usage_date as timestamp) as usage_date,
        resource_id,
        service_name,
        product_name,
        cast(null as varchar) as instance_type,
        region,
        cpu_util_pct,
        memory_util_pct,
        disk_util_pct,
        idle_hours,
        last_activity_at,
        usage_amount,
        usage_unit,
        currency,
        retail_cost as list_cost,
        nec,
        nec_used,
        nec_waste,
        effective_unit_price,
        discount_type,
        vcpus as vcpu,
        cast(null as integer) as memory_gb,
        tag_team,
        tag_environment,
        tag_cost_center,
        tag_business_unit,
        tag_application,
        tag_owner_email,
        tag_workload_criticality,
        tag_sla_tier,
        is_tagged,
        allocated_team,
        allocated_nec,
        is_shared_cost,
        is_commitment_waste
    from {{ ref('int_azure_nec') }}
),

gcp as (
    select
        cloud_provider,
        billing_account_id,
        billing_month,
        account_id,
        account_name,
        usage_start_time as usage_date,
        resource_id,
        service_name,
        sku_description as product_name,
        cast(null as varchar) as instance_type,
        region,
        cpu_util_pct,
        memory_util_pct,
        disk_util_pct,
        idle_hours,
        last_activity_at,
        usage_amount,
        usage_unit,
        currency,
        list_cost,
        nec,
        nec_used,
        nec_waste,
        cast(null as double) as effective_unit_price,
        discount_type,
        compute_cores as vcpu,
        compute_memory_gb as memory_gb,
        tag_team,
        tag_environment,
        tag_cost_center,
        tag_business_unit,
        tag_application,
        tag_owner_email,
        tag_workload_criticality,
        tag_sla_tier,
        is_tagged,
        tag_team as allocated_team,
        nec as allocated_nec,
        false as is_shared_cost,
        is_unused_reservation as is_commitment_waste
    from {{ ref('int_gcp_nec') }}
),

unified as (
    select * from aws
    union all
    select * from azure
    union all
    select * from gcp
),

classified as (
    select
        *,
        case
            when cloud_provider = 'aws' then
                case
                    when service_name in ('AmazonEC2', 'AWSLambda', 'AmazonECS', 'AmazonEKS', 'AWSFargate', 'AmazonLightsail') then 'Compute'
                    when service_name in ('AmazonS3', 'AmazonEFS', 'AmazonGlacier', 'AWSBackup') then 'Storage'
                    when service_name in ('AmazonRDS', 'AmazonDynamoDB', 'AmazonRedshift', 'AmazonElastiCache', 'AmazonDocDB') then 'Database'
                    when service_name in ('AWSGlue', 'AmazonAthena', 'AmazonEMR', 'AmazonKinesis', 'AWSDataSync') then 'Analytics'
                    else 'Other'
                end
            when cloud_provider = 'azure' then
                case
                    when service_name in ('Virtual Machines', 'Container Instances', 'Azure Kubernetes Service', 'App Service', 'Azure Functions') then 'Compute'
                    when service_name in ('Storage', 'Azure Blob Storage', 'Azure Files', 'Azure Data Lake Storage') then 'Storage'
                    when service_name in ('SQL Database', 'Azure Cosmos DB', 'Azure Database for PostgreSQL', 'Azure Cache for Redis', 'Azure SQL Managed Instance') then 'Database'
                    when service_name in ('Azure Monitor', 'API Management', 'Key Vault', 'Azure Networking', 'Virtual Network', 'Azure Firewall') then 'Platform'
                    when service_name in ('Azure Synapse Analytics', 'Azure Data Factory', 'Azure Databricks') then 'Analytics'
                    else 'Other'
                end
            when cloud_provider = 'gcp' then
                case
                    when service_name = 'Compute Engine' then 'Compute'
                    when service_name = 'Cloud Storage' then 'Storage'
                    when service_name = 'Cloud SQL' then 'Database'
                    when service_name = 'BigQuery' then 'Analytics'
                    else 'Other'
                end
            else 'Other'
        end as service_category
    from unified
)

select
    *,
    coalesce(tag_environment, 'prod') as environment,
    upper(
        coalesce(
            tag_cost_center,
            case allocated_team
                when 'platform' then 'CC100'
                when 'data-eng' then 'CC200'
                when 'frontend' then 'CC300'
                when 'backend' then 'CC400'
                when 'ml' then 'CC500'
                else 'CC999'
            end
        )
    ) as cost_center,
    coalesce(
        tag_business_unit,
        case allocated_team
            when 'platform' then 'engineering'
            when 'data-eng' then 'data'
            when 'frontend' then 'product'
            when 'backend' then 'product'
            when 'ml' then 'ai'
            else 'shared-services'
        end
    ) as business_unit,
    coalesce(
        tag_application,
        case allocated_team
            when 'platform' then 'platform-core'
            when 'data-eng' then 'data-platform'
            when 'frontend' then 'customer-web'
            when 'backend' then 'core-api'
            when 'ml' then 'ml-platform'
            else 'unassigned'
        end
    ) as application,
    coalesce(
        tag_owner_email,
        case allocated_team
            when 'platform' then 'platform-owner@company.com'
            when 'data-eng' then 'data-eng-owner@company.com'
            when 'frontend' then 'frontend-owner@company.com'
            when 'backend' then 'backend-owner@company.com'
            when 'ml' then 'ml-owner@company.com'
            else 'unassigned-owner@company.com'
        end
    ) as owner_email,
    coalesce(
        tag_workload_criticality,
        case
            when coalesce(tag_environment, 'prod') = 'prod' and allocated_team = 'platform' then 'mission_critical'
            when coalesce(tag_environment, 'prod') = 'prod' then 'high'
            when coalesce(tag_environment, 'prod') in ('staging', 'test', 'qa', 'nonprod') then 'medium'
            else 'low'
        end
    ) as workload_criticality,
    coalesce(
        tag_sla_tier,
        case
            when coalesce(
                tag_workload_criticality,
                case
                    when coalesce(tag_environment, 'prod') = 'prod' and allocated_team = 'platform' then 'mission_critical'
                    when coalesce(tag_environment, 'prod') = 'prod' then 'high'
                    when coalesce(tag_environment, 'prod') in ('staging', 'test', 'qa', 'nonprod') then 'medium'
                    else 'low'
                end
            ) = 'mission_critical' then 'gold'
            when coalesce(
                tag_workload_criticality,
                case
                    when coalesce(tag_environment, 'prod') = 'prod' and allocated_team = 'platform' then 'mission_critical'
                    when coalesce(tag_environment, 'prod') = 'prod' then 'high'
                    when coalesce(tag_environment, 'prod') in ('staging', 'test', 'qa', 'nonprod') then 'medium'
                    else 'low'
                end
            ) = 'high' then 'silver'
            else 'bronze'
        end
    ) as sla_tier
from classified
