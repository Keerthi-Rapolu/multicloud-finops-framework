/*
  fct_unified_billing — Cloud-Agnostic Schema (CAS) unified billing fact table

  UNION ALL of AWS + Azure + GCP intermediate NEC models.
  One row per billable line item, with a consistent column set across clouds.

  Key columns:
    billing_account_id   — payer account (AWS) / EA billing account (Azure) / billing account (GCP)
    nec                  — Net Effective Cost (used cost only; excludes waste)
    nec_waste            — Unused RI/SP commitment cost (Azure only today)
    list_cost            — Pre-discount / gross cost
    effective_unit_price — nec / usage_amount; true per-unit cost after discounts
    vcpu                 — vCPU count (EC2, Azure VMs, GCE only; null for storage/DB)
    memory_gb            — Memory in GiB (EC2 and GCE only; null for Azure/storage/DB)
    service_category     — Normalized: Compute | Storage | Database | Analytics | Platform | Other
    allocated_team       — team charged after shared-cost spreading (Azure)
    is_shared_cost       — true when cost was split across multiple teams (Azure)
    is_commitment_waste  — true for UnusedReservation / UnusedSavingsPlan rows
    discount_type        — ri | sp | on_demand
*/

with aws as (
    select
        cloud_provider,
        payer_account_id                as billing_account_id,
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
        nec_used,
        nec_waste,
        -- AWS does not compute effective_unit_price in the intermediate layer
        cast(null as double)            as effective_unit_price,
        discount_type,
        -- Compute sizing (EC2 only; null for S3/RDS rows)
        try_cast(vcpu as integer)                                            as vcpu,
        try_cast(regexp_extract(memory, '(\d+)', 1) as integer)             as memory_gb,
        tag_team,
        tag_environment,
        tag_cost_center,
        is_tagged,
        tag_team                        as allocated_team,
        nec                             as allocated_nec,
        false                           as is_shared_cost,
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
        cast(usage_date as timestamp)   as usage_date,
        resource_id,
        service_name,
        product_name,
        cast(null as varchar)           as instance_type,
        region,
        usage_amount,
        usage_unit,
        currency,
        -- retail_cost = payg_price × usage_amount = true OD baseline (consistent with AWS/GCP)
        -- billed_cost = CostInBillingCurrency (amortized actual cost) — used for NEC
        retail_cost                     as list_cost,
        nec,
        nec_used,
        nec_waste,
        effective_unit_price,
        discount_type,
        -- Compute sizing (VMs only; null for storage/SQL rows)
        vcpus                           as vcpu,
        cast(null as integer)           as memory_gb,
        tag_team,
        tag_environment,
        tag_cost_center,
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
        nec_used,
        nec_waste,
        cast(null as double)            as effective_unit_price,
        discount_type,
        -- Compute sizing (GCE only; null for Cloud Storage/BigQuery/Cloud SQL rows)
        compute_cores                   as vcpu,
        compute_memory_gb               as memory_gb,
        tag_team,
        tag_environment,
        tag_cost_center,
        is_tagged,
        tag_team                        as allocated_team,
        nec                             as allocated_nec,
        false                           as is_shared_cost,
        is_unused_reservation           as is_commitment_waste
    from {{ ref('int_gcp_nec') }}
),

unified as (
    select * from aws
    union all
    select * from azure
    union all
    select * from gcp
)

select
    *,
    -- Normalized service category — consistent across clouds for cross-cloud dashboards
    case
        when cloud_provider = 'aws' then
            case
                when service_name in ('AmazonEC2', 'AWSLambda', 'AmazonECS', 'AmazonEKS',
                                      'AWSFargate', 'AmazonLightsail')              then 'Compute'
                when service_name in ('AmazonS3', 'AmazonEFS', 'AmazonGlacier',
                                      'AWSBackup')                                  then 'Storage'
                when service_name in ('AmazonRDS', 'AmazonDynamoDB', 'AmazonRedshift',
                                      'AmazonElastiCache', 'AmazonDocDB')           then 'Database'
                when service_name in ('AWSGlue', 'AmazonAthena', 'AmazonEMR',
                                      'AmazonKinesis', 'AWSDataSync')               then 'Analytics'
                else 'Other'
            end
        when cloud_provider = 'azure' then
            case
                when service_name in ('Virtual Machines', 'Container Instances',
                                      'Azure Kubernetes Service', 'App Service',
                                      'Azure Functions')                             then 'Compute'
                when service_name in ('Storage', 'Azure Blob Storage',
                                      'Azure Files', 'Azure Data Lake Storage')     then 'Storage'
                when service_name in ('SQL Database', 'Azure Cosmos DB',
                                      'Azure Database for PostgreSQL',
                                      'Azure Cache for Redis', 'Azure SQL Managed Instance') then 'Database'
                when service_name in ('Azure Monitor', 'API Management',
                                      'Key Vault', 'Azure Networking',
                                      'Virtual Network', 'Azure Firewall')          then 'Platform'
                when service_name in ('Azure Synapse Analytics',
                                      'Azure Data Factory', 'Azure Databricks')     then 'Analytics'
                else 'Other'
            end
        when cloud_provider = 'gcp' then
            case
                when service_name = 'Compute Engine'    then 'Compute'
                when service_name = 'Cloud Storage'     then 'Storage'
                when service_name = 'Cloud SQL'         then 'Database'
                when service_name = 'BigQuery'          then 'Analytics'
                else 'Other'
            end
        else 'Other'
    end                                 as service_category

from unified
