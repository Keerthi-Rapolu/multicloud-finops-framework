# Staging Layer (Bronze → Silver)

Staging models read raw Parquet files, standardize schema, and prepare clean rows for the intermediate layer. No business logic or cost derivations happen here.

## Models

### `stg_aws_cur`
**Source:** `data/raw/aws/**/*.parquet` (AWS Cost and Usage Report)
**Grain:** One row per hourly line item (Usage/DiscountedUsage/SPCoveredUsage) or one row per monthly commitment summary (RIFee/SavingsPlanRecurringFee)

**What it does:**
- Renames CUR columns (e.g. `lineItem/UnblendedCost`) to `snake_case`
- Parses `UsageStartDate` / `UsageEndDate` with `strptime` → typed timestamps
- Derives `billing_month` (`YYYY-MM`) from `UsageStartDate`
- Exposes `payer_account_id` (master account) alongside `account_id` (member account) for org-level roll-ups
- Casts all cost/usage fields with `try_cast` (nulls on bad data rather than errors)
- Exposes `normalization_factor` and `normalized_usage_amount` for RI coverage calculations across mixed instance sizes
- Exposes `vcpu` and `memory` for rightsizing and $/vCPU efficiency metrics (EC2 only; null for S3/RDS)
- Preserves RI hourly fields (`reservation_effective_cost`, `reservation_amortized_upfront`, `reservation_recurring_fee`) and RI monthly waste fields (`reservation_unused_quantity`, `reservation_unused_upfront_fee`, `reservation_unused_recurring_fee`) from `RIFee` rows
- Preserves SP hourly fields (`savings_plan_effective_cost`, `savings_plan_used_commitment`) and SP monthly commitment fields (`savings_plan_total_commitment`, `savings_plan_recurring_commitment`) from `SavingsPlanRecurringFee` rows
- Extracts flat tag columns: `resourceTags/user:Team` → `tag_team`, etc.
- Derives `is_tagged` (true if `tag_team` is non-null)

**Row filter:** `lineItem/LineItemType` in `Usage`, `DiscountedUsage`, `SavingsPlanCoveredUsage`, `RIFee`, `SavingsPlanRecurringFee`

> RI and SP costs are distributed across multiple row types and columns in non-obvious ways.
> See [AWS_CUR_REFERENCE.md](AWS_CUR_REFERENCE.md) for the full column reference and a complete
> explanation of which column to use for chargeback, waste, and utilisation — and why
> `unblended_cost` alone is wrong for RI/SP hours.

---

### `stg_azure_cost`
**Source:** `data/raw/azure/**/*.parquet` (Azure Cost Management amortized export)
**Grain:** One row per daily resource charge (Usage) or unused commitment entry

**What it does:**
- Renames Azure columns (PascalCase) to `snake_case`
- Exposes `billing_account_id` (EA enrollment) and `account_owner_id` for billing hierarchy
- Parses `Date` string → typed date; derives `billing_month`
- Casts `Quantity`, `UnitPrice`, `CostInBillingCurrency`, `EffectivePrice`, `PayGPrice` to double
- Normalizes `ResourceLocation` (lowercase + trim) → `region`
- Exposes `resource_name` and `consumed_service` (Azure resource provider namespace)
- Extracts `vcpus` from `AdditionalInfo` JSON (VMs only; null for storage/SQL)
- Exposes `pricing_model` (`OnDemand` / `Reservation` / `SavingsPlan`), `effective_price`, and `payg_price` for discount analysis
- Parses Tags JSON blob with `json_extract_string`: `$.team` → `tag_team`, etc.
- Derives `is_tagged` and `has_commitment` (true if `BenefitName` present)
- Derives `is_commitment_waste` — true for `UnusedReservation` / `UnusedSavingsPlan` rows (RI/SP capacity that ran idle but still incurred cost)
- Cost is already **amortized** at source (RI/SP upfront spread daily); `int_azure_nec` splits it into `nec_used` vs `nec_waste` and computes `effective_unit_price`

**Row filter:** `ChargeType in ('Usage', 'UnusedReservation', 'UnusedSavingsPlan')` — Purchase (upfront RI buy), Tax, and Adjustment rows are excluded intentionally: they represent billing events, not resource consumption, and would distort NEC calculations.

> Azure's amortized vs actual export distinction, RI/SP daily row mechanics, shared cost spreading,
> and effective vs PAYG price semantics are explained in full in [AZURE_COST_REFERENCE.md](AZURE_COST_REFERENCE.md).

---

### `stg_gcp_billing`
**Source:** `data/raw/gcp/**/*.parquet` (GCP Detailed Usage Export)
**Grain:** One row per hourly usage record (daily for Cloud Storage / BigQuery storage SKUs)

**What it does:**
- Renames nested GCP fields (`project.id`, `service.description`, etc.) to `snake_case`
- Exposes `project_number` and `project_ancestry` (org/folder/project path) for hierarchy roll-ups
- Parses `usage_start_time` / `usage_end_time` → typed timestamps; derives `billing_month`
- Casts usage and cost fields with `try_cast`
- Exposes `cost_at_list` (on-demand price before credits) alongside `list_cost`
- Keeps `credits` JSON array as `credits_raw` for `int_gcp_nec` to aggregate
- Computes `total_credit_amount` using the `sum_gcp_credits` dbt macro (sums CUD/SUD/PROMOTION credits)
- Derives `net_cost = list_cost + total_credit_amount` (post-discount cost)
- Parses `system_labels` list-of-dicts via `extract_gcp_label` macro → `compute_cores`, `compute_memory_gb`, `is_unused_reservation` (GCE only; null for Storage/BQ/SQL)
- Parses labels list-of-dicts (`[{"key": "team", "value": "..."}]`) via `extract_gcp_label` macro → `tag_team`, etc.
- Derives `is_tagged`

**Row filter:** `cost_type = 'regular'`

**Removed fields (unnecessary for FinOps):** `currency_conversion_rate` (always 1.0 in USD), `usage.amount_in_pricing_units` (duplicate of usage_amount), `adjustment_info.*` (always empty for regular rows)

> CUD/SUD credit mechanics, mixed billing grain (hourly vs daily by service), `credits_raw` JSON structure,
> `is_unused_reservation` waste detection, and label format differences vs AWS/Azure are explained in full
> in [GCP_BILLING_REFERENCE.md](GCP_BILLING_REFERENCE.md).

---

## Shared Conventions

| Convention | Detail |
|---|---|
| Column naming | All output columns `snake_case` |
| Timestamps | `strptime` with cloud-specific format strings |
| Cost casting | `try_cast(...as double)` — bad values become NULL, not errors |
| Tag columns | `tag_team`, `tag_environment`, `tag_cost_center` across all three clouds |
| Tagging flag | `is_tagged = true` when `tag_team` is non-null |
| Waste flag | `is_commitment_waste` = true when a row carries idle commitment cost with no actual compute. Azure: set on `UnusedReservation`/`UnusedSavingsPlan` rows (dedicated waste rows with `usage_amount = 0`). GCP: derived from `is_unused_reservation` system label — since GCP has no dedicated waste rows, this is the only signal for GCP commitment waste; `nec_waste` remains 0. AWS: derived from `RIFee`/`SavingsPlanRecurringFee` rows where unused cost > 0. |
| Cloud stamp | `cloud_provider` literal (`'aws'`, `'azure'`, `'gcp'`) on every row |
| NEC | **Not computed here** — deferred to intermediate layer |
| Billing account | `payer_account_id` (AWS master account); `billing_account_id` (Azure EA enrollment + GCP billing account) |
| Rightsizing fields | `vcpu`/`memory` on AWS EC2 rows; `vcpus` on Azure VM rows; `compute_cores`/`compute_memory_gb` on GCP GCE rows; null for storage/SQL rows |
| Normalisation fields | `normalization_factor` and `normalized_usage_amount` on AWS EC2 rows for RI coverage analysis across mixed instance sizes |
| Pricing detail | `pricing_model`/`effective_price`/`payg_price` on Azure rows; `cost_at_list` on GCP rows; `on_demand_rate`/`on_demand_cost` on AWS rows |
| Net cost | `net_cost` on GCP rows (= `list_cost` + `total_credit_amount`); computed by intermediate layer for AWS and Azure |

---

## What Staging Does NOT Do

- No NEC / net effective cost computation
- No cross-cloud normalization or unioning (that is the marts layer)
- No allocation or tagging enrichment
- No filtering by date range (pass `--vars` at dbt run time if needed)
