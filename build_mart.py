"""
Pure-DuckDB equivalent of the dbt billing mart build.

This keeps the local/dashboard bootstrap path aligned with the dbt models.
"""

from pathlib import Path

import duckdb


def build_mart(db_path: Path, data_root: Path) -> None:
    """Execute the full pipeline: staging -> intermediate -> mart."""
    dr = str(data_root).replace("\\", "/")

    with duckdb.connect(str(db_path)) as con:
        con.execute("CREATE SCHEMA IF NOT EXISTS staging")
        con.execute("CREATE SCHEMA IF NOT EXISTS intermediate")
        con.execute("CREATE SCHEMA IF NOT EXISTS marts")

        con.execute(
            f"""
            CREATE OR REPLACE VIEW staging.stg_aws_cur AS
            WITH source AS (
                SELECT * FROM read_parquet('{dr}/raw/aws/**/*.parquet')
            ),
            staged AS (
                SELECT
                    "identity/LineItemId" AS line_item_id,
                    "bill/PayerAccountId" AS payer_account_id,
                    "lineItem/UsageAccountId" AS account_id,
                    "lineItem/LineItemType" AS line_item_type,
                    strptime("lineItem/UsageStartDate", '%Y-%m-%dT%H:%M:%SZ') AS usage_start_time,
                    strptime("lineItem/UsageEndDate", '%Y-%m-%dT%H:%M:%SZ') AS usage_end_time,
                    strftime(strptime("lineItem/UsageStartDate", '%Y-%m-%dT%H:%M:%SZ'), '%Y-%m') AS billing_month,
                    "lineItem/ResourceId" AS resource_id,
                    "lineItem/ProductCode" AS service_name,
                    "product/ProductName" AS product_name,
                    "product/instanceType" AS instance_type,
                    nullif(trim(CAST("product/vcpu" AS VARCHAR)), '') AS vcpu,
                    nullif(trim("product/memory"), '') AS memory,
                    "product/operatingSystem" AS operating_system,
                    "lineItem/UsageType" AS usage_type,
                    "lineItem/Operation" AS operation,
                    "product/region" AS region,
                    "lineItem/AvailabilityZone" AS availability_zone,
                    try_cast("resourceMetrics/cpuUtilizationPct" AS DOUBLE) AS cpu_util_pct,
                    try_cast("resourceMetrics/memoryUtilizationPct" AS DOUBLE) AS memory_util_pct,
                    try_cast("resourceMetrics/diskUtilizationPct" AS DOUBLE) AS disk_util_pct,
                    try_cast("resourceMetrics/idleHours" AS DOUBLE) AS idle_hours,
                    try_strptime("resourceMetrics/lastActivityAt", '%Y-%m-%dT%H:%M:%SZ') AS last_activity_at,
                    try_cast("lineItem/UsageAmount" AS DOUBLE) AS usage_amount,
                    try_cast("lineItem/NormalizationFactor" AS DOUBLE) AS normalization_factor,
                    try_cast("lineItem/NormalizedUsageAmount" AS DOUBLE) AS normalized_usage_amount,
                    "pricing/unit" AS pricing_unit,
                    try_cast("pricing/publicOnDemandRate" AS DOUBLE) AS on_demand_rate,
                    try_cast("pricing/publicOnDemandCost" AS DOUBLE) AS on_demand_cost,
                    try_cast("lineItem/UnblendedCost" AS DOUBLE) AS unblended_cost,
                    try_cast("lineItem/BlendedCost" AS DOUBLE) AS blended_cost,
                    nullif("reservation/ReservationARN", '') AS reservation_arn,
                    try_cast("reservation/EffectiveCost" AS DOUBLE) AS reservation_effective_cost,
                    try_cast("reservation/AmortizedUpfrontCostForUsage" AS DOUBLE) AS reservation_amortized_upfront,
                    try_cast("reservation/RecurringFeeForUsage" AS DOUBLE) AS reservation_recurring_fee,
                    try_cast("reservation/UnusedQuantity" AS DOUBLE) AS reservation_unused_quantity,
                    try_cast("reservation/UnusedAmortizedUpfrontFeeForBillingPeriod" AS DOUBLE) AS reservation_unused_upfront_fee,
                    try_cast("reservation/UnusedRecurringFee" AS DOUBLE) AS reservation_unused_recurring_fee,
                    nullif("savingsPlan/SavingsPlanARN", '') AS savings_plan_arn,
                    try_cast("savingsPlan/SavingsPlanEffectiveCost" AS DOUBLE) AS savings_plan_effective_cost,
                    try_cast("savingsPlan/SavingsPlanRate" AS DOUBLE) AS savings_plan_rate,
                    try_cast("savingsPlan/UsedCommitment" AS DOUBLE) AS savings_plan_used_commitment,
                    try_cast("savingsPlan/TotalCommitmentToDate" AS DOUBLE) AS savings_plan_total_commitment,
                    try_cast("savingsPlan/RecurringCommitmentForBillingPeriod" AS DOUBLE) AS savings_plan_recurring_commitment,
                    nullif(trim(lower("resourceTags/user:Team")), '') AS tag_team,
                    nullif(trim(lower("resourceTags/user:Environment")), '') AS tag_environment,
                    nullif(trim(lower("resourceTags/user:CostCenter")), '') AS tag_cost_center,
                    CASE
                        WHEN nullif(trim(lower("resourceTags/user:Team")), '') IS NOT NULL THEN true
                        ELSE false
                    END AS is_tagged,
                    'aws' AS cloud_provider
                FROM source
                WHERE "lineItem/LineItemType" IN (
                    'Usage', 'DiscountedUsage', 'SavingsPlanCoveredUsage',
                    'RIFee', 'SavingsPlanRecurringFee'
                )
            )
            SELECT * FROM staged
            """
        )

        con.execute(
            f"""
            CREATE OR REPLACE VIEW staging.stg_azure_cost AS
            WITH source AS (
                SELECT * FROM read_parquet('{dr}/raw/azure/**/*.parquet')
            ),
            staged AS (
                SELECT
                    nullif(BillingAccountId, '') AS billing_account_id,
                    SubscriptionId AS account_id,
                    SubscriptionName AS account_name,
                    nullif(AccountOwnerId, '') AS account_owner_id,
                    InvoiceSectionName AS invoice_section,
                    ResourceGroup AS resource_group,
                    strptime(Date, '%Y-%m-%d') AS usage_date,
                    strftime(strptime(Date, '%Y-%m-%d'), '%Y-%m') AS billing_month,
                    ResourceId AS resource_id,
                    nullif(trim(ResourceName), '') AS resource_name,
                    nullif(trim(ConsumedService), '') AS consumed_service,
                    ProductName AS product_name,
                    MeterCategory AS service_name,
                    MeterSubcategory AS service_subcategory,
                    MeterName AS meter_name,
                    MeterId AS meter_id,
                    lower(trim(ResourceLocation)) AS region,
                    ServiceFamily AS service_family,
                    ChargeType AS charge_type,
                    PublisherType AS publisher_type,
                    try_cast(nullif(trim(json_extract_string(AdditionalInfo, '$.vCPUs')), '') AS INTEGER) AS vcpus,
                    try_cast(nullif(trim(json_extract_string(AdditionalInfo, '$.cpuUtilPct')), '') AS DOUBLE) AS cpu_util_pct,
                    try_cast(nullif(trim(json_extract_string(AdditionalInfo, '$.memoryUtilPct')), '') AS DOUBLE) AS memory_util_pct,
                    try_cast(nullif(trim(json_extract_string(AdditionalInfo, '$.diskUtilPct')), '') AS DOUBLE) AS disk_util_pct,
                    try_cast(nullif(trim(json_extract_string(AdditionalInfo, '$.idleHours')), '') AS DOUBLE) AS idle_hours,
                    try_strptime(json_extract_string(AdditionalInfo, '$.lastActivityAt'), '%Y-%m-%dT%H:%M:%SZ') AS last_activity_at,
                    try_cast(Quantity AS DOUBLE) AS usage_amount,
                    Unit AS usage_unit,
                    try_cast(UnitPrice AS DOUBLE) AS unit_price,
                    BillingCurrency AS currency,
                    try_cast(CostInBillingCurrency AS DOUBLE) AS billed_cost,
                    try_cast(PayGPrice AS DOUBLE) * try_cast(Quantity AS DOUBLE) AS retail_cost,
                    nullif(trim(PricingModel), '') AS pricing_model,
                    try_cast(EffectivePrice AS DOUBLE) AS effective_price,
                    try_cast(PayGPrice AS DOUBLE) AS payg_price,
                    nullif(BenefitId, '') AS benefit_id,
                    nullif(BenefitName, '') AS benefit_name,
                    CASE WHEN nullif(BenefitName, '') IS NOT NULL THEN true ELSE false END AS has_commitment,
                    CASE
                        WHEN ChargeType IN ('UnusedReservation', 'UnusedSavingsPlan') THEN true
                        ELSE false
                    END AS is_commitment_waste,
                    nullif(trim(lower(json_extract_string(Tags, '$.team'))), '') AS tag_team,
                    nullif(trim(lower(json_extract_string(Tags, '$.environment'))), '') AS tag_environment,
                    nullif(trim(lower(json_extract_string(Tags, '$.costcenter'))), '') AS tag_cost_center,
                    nullif(trim(lower(json_extract_string(Tags, '$.business_unit'))), '') AS tag_business_unit,
                    nullif(trim(lower(json_extract_string(Tags, '$.application'))), '') AS tag_application,
                    nullif(trim(lower(json_extract_string(Tags, '$.owner_email'))), '') AS tag_owner_email,
                    nullif(trim(lower(json_extract_string(Tags, '$.support_group'))), '') AS tag_support_group,
                    nullif(trim(lower(json_extract_string(Tags, '$.workload_criticality'))), '') AS tag_workload_criticality,
                    nullif(trim(lower(json_extract_string(Tags, '$.sla_tier'))), '') AS tag_sla_tier,
                    CASE
                        WHEN nullif(trim(lower(json_extract_string(Tags, '$.team'))), '') IS NOT NULL THEN true
                        ELSE false
                    END AS is_tagged,
                    'azure' AS cloud_provider
                FROM source
                WHERE ChargeType IN ('Usage', 'UnusedReservation', 'UnusedSavingsPlan')
            )
            SELECT * FROM staged
            """
        )

        con.execute(
            f"""
            CREATE OR REPLACE VIEW staging.stg_gcp_billing AS
            WITH source AS (
                SELECT * FROM read_parquet('{dr}/raw/gcp/**/*.parquet')
            ),
            staged AS (
                SELECT
                    billing_account_id,
                    "project.id" AS account_id,
                    "project.name" AS account_name,
                    "project.number" AS project_number,
                    "project.ancestry_numbers" AS project_ancestry,
                    "service.id" AS service_id,
                    "service.description" AS service_name,
                    "sku.id" AS sku_id,
                    "sku.description" AS sku_description,
                    strptime("usage_start_time", '%Y-%m-%dT%H:%M:%SZ') AS usage_start_time,
                    strptime("usage_end_time", '%Y-%m-%dT%H:%M:%SZ') AS usage_end_time,
                    strftime(strptime("usage_start_time", '%Y-%m-%dT%H:%M:%SZ'), '%Y-%m') AS billing_month,
                    "invoice.month" AS invoice_month,
                    "resource.name" AS resource_id,
                    "resource.global_name" AS resource_global_name,
                    "location.region" AS region,
                    "location.zone" AS zone,
                    "location.country" AS country,
                    try_cast(nullif((
                        SELECT item->>'value'
                        FROM (SELECT unnest(try_cast(system_labels AS JSON[])) AS item)
                        WHERE item->>'key' = 'compute_cores' LIMIT 1
                    ), '') AS INTEGER) AS compute_cores,
                    try_cast(nullif((
                        SELECT item->>'value'
                        FROM (SELECT unnest(try_cast(system_labels AS JSON[])) AS item)
                        WHERE item->>'key' = 'compute_memory' LIMIT 1
                    ), '') AS INTEGER) AS compute_memory_gb,
                    try_cast(nullif((
                        SELECT item->>'value'
                        FROM (SELECT unnest(try_cast(system_labels AS JSON[])) AS item)
                        WHERE item->>'key' = 'cpu_util_pct' LIMIT 1
                    ), '') AS DOUBLE) AS cpu_util_pct,
                    try_cast(nullif((
                        SELECT item->>'value'
                        FROM (SELECT unnest(try_cast(system_labels AS JSON[])) AS item)
                        WHERE item->>'key' = 'memory_util_pct' LIMIT 1
                    ), '') AS DOUBLE) AS memory_util_pct,
                    try_cast(nullif((
                        SELECT item->>'value'
                        FROM (SELECT unnest(try_cast(system_labels AS JSON[])) AS item)
                        WHERE item->>'key' = 'disk_util_pct' LIMIT 1
                    ), '') AS DOUBLE) AS disk_util_pct,
                    try_cast(nullif((
                        SELECT item->>'value'
                        FROM (SELECT unnest(try_cast(system_labels AS JSON[])) AS item)
                        WHERE item->>'key' = 'idle_hours' LIMIT 1
                    ), '') AS DOUBLE) AS idle_hours,
                    try_strptime((
                        SELECT item->>'value'
                        FROM (SELECT unnest(try_cast(system_labels AS JSON[])) AS item)
                        WHERE item->>'key' = 'last_activity_at' LIMIT 1
                    ), '%Y-%m-%dT%H:%M:%SZ') AS last_activity_at,
                    CASE
                        WHEN (
                            SELECT item->>'value'
                            FROM (SELECT unnest(try_cast(system_labels AS JSON[])) AS item)
                            WHERE item->>'key' = 'is_unused_reservation' LIMIT 1
                        ) = 'true' THEN true
                        ELSE false
                    END AS is_unused_reservation,
                    try_cast("usage.amount" AS DOUBLE) AS usage_amount,
                    "usage.unit" AS usage_unit,
                    "usage.pricing_unit" AS pricing_unit,
                    try_cast(cost AS DOUBLE) AS list_cost,
                    try_cast(cost_at_list AS DOUBLE) AS cost_at_list,
                    currency,
                    cost_type,
                    credits AS credits_raw,
                    coalesce((
                        SELECT sum(try_cast(item->>'amount' AS DOUBLE))
                        FROM (SELECT unnest(try_cast(credits AS JSON[])) AS item)
                        WHERE item->>'type' IN (
                            'COMMITTED_USAGE_DISCOUNT', 'COMMITTED_USAGE_DISCOUNT_DOLLAR_BASE',
                            'SUSTAINED_USE_DISCOUNT', 'FREE_TIER', 'PROMOTION'
                        )
                    ), 0.0) AS total_credit_amount,
                    try_cast(cost AS DOUBLE) + coalesce((
                        SELECT sum(try_cast(item->>'amount' AS DOUBLE))
                        FROM (SELECT unnest(try_cast(credits AS JSON[])) AS item)
                        WHERE item->>'type' IN (
                            'COMMITTED_USAGE_DISCOUNT', 'COMMITTED_USAGE_DISCOUNT_DOLLAR_BASE',
                            'SUSTAINED_USE_DISCOUNT', 'FREE_TIER', 'PROMOTION'
                        )
                    ), 0.0) AS net_cost,
                    nullif(trim(lower((
                        SELECT item->>'value'
                        FROM (SELECT unnest(try_cast(labels AS JSON[])) AS item)
                        WHERE item->>'key' = 'team' LIMIT 1
                    ))), '') AS tag_team,
                    nullif(trim(lower((
                        SELECT item->>'value'
                        FROM (SELECT unnest(try_cast(labels AS JSON[])) AS item)
                        WHERE item->>'key' = 'environment' LIMIT 1
                    ))), '') AS tag_environment,
                    nullif(trim(lower((
                        SELECT item->>'value'
                        FROM (SELECT unnest(try_cast(labels AS JSON[])) AS item)
                        WHERE item->>'key' = 'cost_center' LIMIT 1
                    ))), '') AS tag_cost_center,
                    nullif(trim(lower((
                        SELECT item->>'value'
                        FROM (SELECT unnest(try_cast(labels AS JSON[])) AS item)
                        WHERE item->>'key' = 'business_unit' LIMIT 1
                    ))), '') AS tag_business_unit,
                    nullif(trim(lower((
                        SELECT item->>'value'
                        FROM (SELECT unnest(try_cast(labels AS JSON[])) AS item)
                        WHERE item->>'key' = 'application' LIMIT 1
                    ))), '') AS tag_application,
                    nullif(trim(lower((
                        SELECT item->>'value'
                        FROM (SELECT unnest(try_cast(labels AS JSON[])) AS item)
                        WHERE item->>'key' = 'owner_email' LIMIT 1
                    ))), '') AS tag_owner_email,
                    nullif(trim(lower((
                        SELECT item->>'value'
                        FROM (SELECT unnest(try_cast(labels AS JSON[])) AS item)
                        WHERE item->>'key' = 'support_group' LIMIT 1
                    ))), '') AS tag_support_group,
                    nullif(trim(lower((
                        SELECT item->>'value'
                        FROM (SELECT unnest(try_cast(labels AS JSON[])) AS item)
                        WHERE item->>'key' = 'workload_criticality' LIMIT 1
                    ))), '') AS tag_workload_criticality,
                    nullif(trim(lower((
                        SELECT item->>'value'
                        FROM (SELECT unnest(try_cast(labels AS JSON[])) AS item)
                        WHERE item->>'key' = 'sla_tier' LIMIT 1
                    ))), '') AS tag_sla_tier,
                    CASE
                        WHEN nullif(trim(lower((
                            SELECT item->>'value'
                            FROM (SELECT unnest(try_cast(labels AS JSON[])) AS item)
                            WHERE item->>'key' = 'team' LIMIT 1
                        ))), '') IS NOT NULL THEN true
                        ELSE false
                    END AS is_tagged,
                    'gcp' AS cloud_provider
                FROM source
                WHERE cost_type = 'regular'
            )
            SELECT * FROM staged
            """
        )

        con.execute(
            """
            CREATE OR REPLACE TABLE intermediate.int_aws_nec AS
            WITH staged AS (SELECT * FROM staging.stg_aws_cur),
            nec AS (
                SELECT
                    line_item_id, payer_account_id, account_id, billing_month,
                    usage_start_time, usage_end_time, resource_id, service_name,
                    product_name, instance_type, operating_system, region,
                    availability_zone, cpu_util_pct, memory_util_pct, disk_util_pct,
                    idle_hours, last_activity_at, usage_amount, pricing_unit, vcpu, memory,
                    unblended_cost, on_demand_cost, reservation_arn, savings_plan_arn,
                    CASE
                        WHEN line_item_type IN ('DiscountedUsage', 'RIFee') THEN 'ri'
                        WHEN line_item_type IN ('SavingsPlanCoveredUsage', 'SavingsPlanRecurringFee') THEN 'sp'
                        ELSE 'on_demand'
                    END AS discount_type,
                    CASE
                        WHEN line_item_type = 'DiscountedUsage' THEN coalesce(reservation_effective_cost, 0.0)
                        WHEN line_item_type = 'SavingsPlanCoveredUsage' THEN coalesce(savings_plan_effective_cost, 0.0)
                        WHEN line_item_type IN ('RIFee', 'SavingsPlanRecurringFee') THEN 0.0
                        ELSE coalesce(unblended_cost, 0.0)
                    END AS nec_used,
                    CASE
                        WHEN line_item_type = 'RIFee' THEN coalesce(reservation_unused_upfront_fee, 0.0) + coalesce(reservation_unused_recurring_fee, 0.0)
                        WHEN line_item_type = 'SavingsPlanRecurringFee' THEN greatest(
                            coalesce(savings_plan_recurring_commitment, 0.0) - coalesce(savings_plan_used_commitment, 0.0),
                            0.0
                        )
                        ELSE 0.0
                    END AS nec_waste,
                    CASE
                        WHEN line_item_type = 'RIFee'
                            AND (coalesce(reservation_unused_upfront_fee, 0.0) + coalesce(reservation_unused_recurring_fee, 0.0)) > 0 THEN true
                        WHEN line_item_type = 'SavingsPlanRecurringFee'
                            AND coalesce(savings_plan_recurring_commitment, 0.0) > coalesce(savings_plan_used_commitment, 0.0) THEN true
                        ELSE false
                    END AS is_commitment_waste,
                    tag_team, tag_environment, tag_cost_center, is_tagged, cloud_provider
                FROM staged
            )
            SELECT *, nec_used AS nec FROM nec
            """
        )

        con.execute(
            """
            CREATE OR REPLACE TABLE intermediate.int_azure_nec AS
            WITH staged AS (SELECT * FROM staging.stg_azure_cost),
            sub_teams(account_id, team) AS (
                VALUES
                    ('a1b2c3d4-0001-0001-0001-000000000001', 'platform'),
                    ('a1b2c3d4-0002-0002-0002-000000000002', 'data-eng'),
                    ('a1b2c3d4-0003-0003-0003-000000000003', 'frontend'),
                    ('a1b2c3d4-0003-0003-0003-000000000003', 'backend'),
                    ('a1b2c3d4-0003-0003-0003-000000000003', 'ml'),
                    ('a1b2c3d4-9999-9999-9999-000000000099', 'platform'),
                    ('a1b2c3d4-9999-9999-9999-000000000099', 'data-eng'),
                    ('a1b2c3d4-9999-9999-9999-000000000099', 'frontend'),
                    ('a1b2c3d4-9999-9999-9999-000000000099', 'backend'),
                    ('a1b2c3d4-9999-9999-9999-000000000099', 'ml')
            ),
            sub_team_counts AS (
                SELECT account_id, team, count(*) OVER (PARTITION BY account_id) AS n_teams
                FROM sub_teams
            ),
            nec_base AS (
                SELECT
                    *,
                    CASE WHEN is_commitment_waste THEN 0.0 ELSE coalesce(billed_cost, 0.0) END AS nec_used,
                    CASE WHEN is_commitment_waste THEN coalesce(billed_cost, 0.0) ELSE 0.0 END AS nec_waste,
                    CASE
                        WHEN NOT is_commitment_waste THEN billed_cost / nullif(usage_amount, 0)
                        ELSE NULL
                    END AS effective_unit_price,
                    CASE
                        WHEN pricing_model = 'Reservation' THEN 'ri'
                        WHEN pricing_model = 'SavingsPlan' THEN 'sp'
                        ELSE 'on_demand'
                    END AS discount_type
                FROM staged
            ),
            tagged AS (
                SELECT
                    nb.*,
                    nb.tag_team AS allocated_team,
                    nb.nec_used AS allocated_nec,
                    nb.nec_waste AS allocated_nec_waste,
                    1 AS allocation_n_teams,
                    false AS is_shared_cost
                FROM nec_base nb
                WHERE nb.is_tagged = true
            ),
            untagged_fanout AS (
                SELECT
                    nb.* EXCLUDE (nec_used, nec_waste, retail_cost),
                    nb.nec_used / coalesce(stc.n_teams, 1) AS nec_used,
                    nb.nec_waste / coalesce(stc.n_teams, 1) AS nec_waste,
                    nb.retail_cost / coalesce(stc.n_teams, 1) AS retail_cost,
                    stc.team AS allocated_team,
                    nb.nec_used / coalesce(stc.n_teams, 1) AS allocated_nec,
                    nb.nec_waste / coalesce(stc.n_teams, 1) AS allocated_nec_waste,
                    coalesce(stc.n_teams, 1) AS allocation_n_teams,
                    stc.team IS NOT NULL AS is_shared_cost
                FROM nec_base nb
                LEFT JOIN sub_team_counts stc ON nb.account_id = stc.account_id
                WHERE nb.is_tagged = false
            ),
            combined AS (
                SELECT
                    billing_account_id, account_id, account_name, billing_month, usage_date,
                    resource_id, resource_name, resource_group, invoice_section, product_name,
                    service_name, service_subcategory, meter_name, region, service_family,
                    charge_type, vcpus, cpu_util_pct, memory_util_pct, disk_util_pct,
                    idle_hours, last_activity_at, usage_amount, usage_unit, unit_price, currency,
                    benefit_id, benefit_name, has_commitment, is_commitment_waste,
                    discount_type, billed_cost, retail_cost, nec_used,
                    allocated_nec_waste AS nec_waste, nec_used AS nec, effective_unit_price,
                    tag_team, tag_environment, tag_cost_center,
                    tag_business_unit, tag_application, tag_owner_email, tag_support_group,
                    tag_workload_criticality, tag_sla_tier,
                    is_tagged, allocated_team, allocated_nec, allocation_n_teams,
                    is_shared_cost, cloud_provider
                FROM tagged
                UNION ALL
                SELECT
                    billing_account_id, account_id, account_name, billing_month, usage_date,
                    resource_id, resource_name, resource_group, invoice_section, product_name,
                    service_name, service_subcategory, meter_name, region, service_family,
                    charge_type, vcpus, cpu_util_pct, memory_util_pct, disk_util_pct,
                    idle_hours, last_activity_at, usage_amount, usage_unit, unit_price, currency,
                    benefit_id, benefit_name, has_commitment, is_commitment_waste,
                    discount_type, billed_cost, retail_cost, nec_used,
                    allocated_nec_waste AS nec_waste, nec_used AS nec, effective_unit_price,
                    tag_team, tag_environment, tag_cost_center,
                    tag_business_unit, tag_application, tag_owner_email, tag_support_group,
                    tag_workload_criticality, tag_sla_tier,
                    is_tagged, allocated_team, allocated_nec, allocation_n_teams,
                    is_shared_cost, cloud_provider
                FROM untagged_fanout
            )
            SELECT * FROM combined
            """
        )

        con.execute(
            """
            CREATE OR REPLACE TABLE intermediate.int_gcp_nec AS
            WITH staged AS (SELECT * FROM staging.stg_gcp_billing),
            nec AS (
                SELECT
                    billing_account_id, account_id, account_name, project_number,
                    project_ancestry, billing_month, invoice_month, usage_start_time,
                    usage_end_time, resource_id, resource_global_name, service_id,
                    service_name, sku_id, sku_description, region, zone, country,
                    usage_amount, usage_unit, pricing_unit, currency, cost_type,
                    compute_cores, compute_memory_gb, cpu_util_pct, memory_util_pct,
                    disk_util_pct, idle_hours, last_activity_at, is_unused_reservation,
                    list_cost, cost_at_list, total_credit_amount, credits_raw,
                    CASE
                        WHEN is_unused_reservation THEN 0.0
                        ELSE greatest(coalesce(list_cost, 0.0) + coalesce(total_credit_amount, 0.0), 0.0)
                    END AS nec_used,
                    CASE
                        WHEN is_unused_reservation THEN coalesce(list_cost, 0.0)
                        ELSE 0.0
                    END AS nec_waste,
                    net_cost,
                    CASE
                        WHEN credits_raw LIKE '%COMMITTED_USAGE_DISCOUNT%' THEN 'ri'
                        ELSE 'on_demand'
                    END AS discount_type,
                    tag_team, tag_environment, tag_cost_center,
                    tag_business_unit, tag_application, tag_owner_email, tag_support_group,
                    tag_workload_criticality, tag_sla_tier,
                    is_tagged, cloud_provider
                FROM staged
            )
            SELECT *, nec_used AS nec FROM nec
            """
        )

        con.execute(
            """
            CREATE OR REPLACE TABLE marts.fct_unified_billing AS
            WITH aws AS (
                SELECT
                    cloud_provider,
                    payer_account_id AS billing_account_id,
                    billing_month,
                    account_id,
                    CAST(NULL AS VARCHAR) AS account_name,
                    usage_start_time AS usage_date,
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
                    pricing_unit AS usage_unit,
                    'USD' AS currency,
                    on_demand_cost AS list_cost,
                    nec,
                    nec_used,
                    nec_waste,
                    CAST(NULL AS DOUBLE) AS effective_unit_price,
                    discount_type,
                    try_cast(vcpu AS INTEGER) AS vcpu,
                    try_cast(regexp_extract(memory, '(\\d+)', 1) AS INTEGER) AS memory_gb,
                    tag_team,
                    tag_environment,
                    tag_cost_center,
                    CAST(NULL AS VARCHAR) AS tag_business_unit,
                    CAST(NULL AS VARCHAR) AS tag_application,
                    CAST(NULL AS VARCHAR) AS tag_owner_email,
                    CAST(NULL AS VARCHAR) AS tag_support_group,
                    CAST(NULL AS VARCHAR) AS tag_workload_criticality,
                    CAST(NULL AS VARCHAR) AS tag_sla_tier,
                    is_tagged,
                    tag_team AS allocated_team,
                    nec AS allocated_nec,
                    false AS is_shared_cost,
                    is_commitment_waste
                FROM intermediate.int_aws_nec
            ),
            azure AS (
                SELECT
                    cloud_provider, billing_account_id, billing_month, account_id, account_name,
                    CAST(usage_date AS TIMESTAMP) AS usage_date,
                    resource_id, service_name, product_name,
                    CAST(NULL AS VARCHAR) AS instance_type,
                    region, cpu_util_pct, memory_util_pct, disk_util_pct,
                    idle_hours, last_activity_at, usage_amount, usage_unit, currency,
                    retail_cost AS list_cost,
                    nec, nec_used, nec_waste, effective_unit_price, discount_type,
                    vcpus AS vcpu,
                    CAST(NULL AS INTEGER) AS memory_gb,
                    tag_team, tag_environment, tag_cost_center,
                    tag_business_unit, tag_application, tag_owner_email, tag_support_group,
                    tag_workload_criticality, tag_sla_tier,
                    is_tagged, allocated_team, allocated_nec, is_shared_cost, is_commitment_waste
                FROM intermediate.int_azure_nec
            ),
            gcp AS (
                SELECT
                    cloud_provider, billing_account_id, billing_month, account_id, account_name,
                    usage_start_time AS usage_date,
                    resource_id, service_name,
                    sku_description AS product_name,
                    CAST(NULL AS VARCHAR) AS instance_type,
                    region, cpu_util_pct, memory_util_pct, disk_util_pct,
                    idle_hours, last_activity_at, usage_amount, usage_unit, currency, list_cost,
                    nec, nec_used, nec_waste,
                    CAST(NULL AS DOUBLE) AS effective_unit_price,
                    discount_type,
                    compute_cores AS vcpu,
                    compute_memory_gb AS memory_gb,
                    tag_team, tag_environment, tag_cost_center,
                    tag_business_unit, tag_application, tag_owner_email, tag_support_group,
                    tag_workload_criticality, tag_sla_tier,
                    is_tagged, tag_team AS allocated_team, nec AS allocated_nec,
                    false AS is_shared_cost, is_unused_reservation AS is_commitment_waste
                FROM intermediate.int_gcp_nec
            ),
            unified AS (
                SELECT * FROM aws
                UNION ALL
                SELECT * FROM azure
                UNION ALL
                SELECT * FROM gcp
            ),
            classified AS (
                SELECT
                    *,
                    CASE
                        WHEN cloud_provider = 'aws' THEN
                            CASE
                                WHEN service_name IN ('AmazonEC2','AWSLambda','AmazonECS','AmazonEKS','AWSFargate','AmazonLightsail') THEN 'Compute'
                                WHEN service_name IN ('AmazonS3','AmazonEFS','AmazonGlacier','AWSBackup') THEN 'Storage'
                                WHEN service_name IN ('AmazonRDS','AmazonDynamoDB','AmazonRedshift','AmazonElastiCache','AmazonDocDB') THEN 'Database'
                                WHEN service_name IN ('AWSGlue','AmazonAthena','AmazonEMR','AmazonKinesis','AWSDataSync') THEN 'Analytics'
                                ELSE 'Other'
                            END
                        WHEN cloud_provider = 'azure' THEN
                            CASE
                                WHEN service_name IN ('Virtual Machines','Container Instances','Azure Kubernetes Service','App Service','Azure Functions') THEN 'Compute'
                                WHEN service_name IN ('Storage','Azure Blob Storage','Azure Files','Azure Data Lake Storage') THEN 'Storage'
                                WHEN service_name IN ('SQL Database','Azure Cosmos DB','Azure Database for PostgreSQL','Azure Cache for Redis','Azure SQL Managed Instance') THEN 'Database'
                                WHEN service_name IN ('Azure Monitor','API Management','Key Vault','Azure Networking','Virtual Network','Azure Firewall') THEN 'Platform'
                                WHEN service_name IN ('Azure Synapse Analytics','Azure Data Factory','Azure Databricks') THEN 'Analytics'
                                ELSE 'Other'
                            END
                        WHEN cloud_provider = 'gcp' THEN
                            CASE
                                WHEN service_name = 'Compute Engine' THEN 'Compute'
                                WHEN service_name = 'Cloud Storage' THEN 'Storage'
                                WHEN service_name = 'Cloud SQL' THEN 'Database'
                                WHEN service_name = 'BigQuery' THEN 'Analytics'
                                ELSE 'Other'
                            END
                        ELSE 'Other'
                    END AS service_category
                FROM unified
            )
            SELECT
                *,
                coalesce(tag_environment, 'prod') AS environment,
                upper(coalesce(
                    tag_cost_center,
                    CASE allocated_team
                        WHEN 'platform' THEN 'CC100'
                        WHEN 'data-eng' THEN 'CC200'
                        WHEN 'frontend' THEN 'CC300'
                        WHEN 'backend' THEN 'CC400'
                        WHEN 'ml' THEN 'CC500'
                        ELSE 'CC999'
                    END
                )) AS cost_center,
                coalesce(
                    tag_business_unit,
                    CASE allocated_team
                        WHEN 'platform' THEN 'engineering'
                        WHEN 'data-eng' THEN 'data'
                        WHEN 'frontend' THEN 'product'
                        WHEN 'backend' THEN 'product'
                        WHEN 'ml' THEN 'ai'
                        ELSE 'shared-services'
                    END
                ) AS business_unit,
                coalesce(
                    tag_application,
                    CASE allocated_team
                        WHEN 'platform' THEN 'platform-core'
                        WHEN 'data-eng' THEN 'data-platform'
                        WHEN 'frontend' THEN 'customer-web'
                        WHEN 'backend' THEN 'core-api'
                        WHEN 'ml' THEN 'ml-platform'
                        ELSE 'unassigned'
                    END
                ) AS application,
                coalesce(
                    tag_owner_email,
                    CASE allocated_team
                        WHEN 'platform' THEN 'platform-owner@company.com'
                        WHEN 'data-eng' THEN 'data-eng-owner@company.com'
                        WHEN 'frontend' THEN 'frontend-owner@company.com'
                        WHEN 'backend' THEN 'backend-owner@company.com'
                        WHEN 'ml' THEN 'ml-owner@company.com'
                        ELSE 'unassigned-owner@company.com'
                    END
                ) AS owner_email,
                coalesce(
                    tag_support_group,
                    CASE allocated_team
                        WHEN 'platform' THEN 'platform-operations'
                        WHEN 'data-eng' THEN 'data-platform-ops'
                        WHEN 'frontend' THEN 'customer-experience-support'
                        WHEN 'backend' THEN 'api-operations'
                        WHEN 'ml' THEN 'ml-platform-sre'
                        ELSE 'finops-governance'
                    END
                ) AS support_group,
                coalesce(
                    tag_workload_criticality,
                    CASE
                        WHEN coalesce(tag_environment, 'prod') = 'prod' AND allocated_team = 'platform' THEN 'mission_critical'
                        WHEN coalesce(tag_environment, 'prod') = 'prod' THEN 'high'
                        WHEN coalesce(tag_environment, 'prod') IN ('staging', 'test', 'qa', 'nonprod') THEN 'medium'
                        ELSE 'low'
                    END
                ) AS workload_criticality,
                coalesce(
                    tag_sla_tier,
                    CASE
                        WHEN coalesce(
                            tag_workload_criticality,
                            CASE
                                WHEN coalesce(tag_environment, 'prod') = 'prod' AND allocated_team = 'platform' THEN 'mission_critical'
                                WHEN coalesce(tag_environment, 'prod') = 'prod' THEN 'high'
                                WHEN coalesce(tag_environment, 'prod') IN ('staging', 'test', 'qa', 'nonprod') THEN 'medium'
                                ELSE 'low'
                            END
                        ) = 'mission_critical' THEN 'platinum'
                        WHEN coalesce(
                            tag_workload_criticality,
                            CASE
                                WHEN coalesce(tag_environment, 'prod') = 'prod' AND allocated_team = 'platform' THEN 'mission_critical'
                                WHEN coalesce(tag_environment, 'prod') = 'prod' THEN 'high'
                                WHEN coalesce(tag_environment, 'prod') IN ('staging', 'test', 'qa', 'nonprod') THEN 'medium'
                                ELSE 'low'
                            END
                        ) = 'high' THEN 'gold'
                        WHEN coalesce(
                            tag_workload_criticality,
                            CASE
                                WHEN coalesce(tag_environment, 'prod') = 'prod' AND allocated_team = 'platform' THEN 'mission_critical'
                                WHEN coalesce(tag_environment, 'prod') = 'prod' THEN 'high'
                                WHEN coalesce(tag_environment, 'prod') IN ('staging', 'test', 'qa', 'nonprod') THEN 'medium'
                                ELSE 'low'
                            END
                        ) = 'medium' THEN 'silver'
                        ELSE 'bronze'
                    END
                ) AS sla_tier
            FROM classified
            """
        )
