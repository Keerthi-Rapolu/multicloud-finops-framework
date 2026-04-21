# GCP Billing Staging Reference

Complete reference for `stg_gcp_billing` — every column, its distinct values, meaning,
example, and how CUD/SUD commitment discounts flow through the Detailed Usage Export.

---

## Column Reference

### Identity & Project Hierarchy

| Column | Distinct values | Meaning | Example |
|---|---|---|---|
| `billing_account_id` | 1 in synthetic (`ABCDEF-123456-ABCDEF`) | GCP Cloud Billing account ID — the top-level billing entity. All projects under it are charged here. Equivalent to AWS `payer_account_id` and Azure `billing_account_id`. | `ABCDEF-123456-ABCDEF` |
| `account_id` | 4 in synthetic | GCP project ID (string slug). The unit of billing isolation — each project maps to a team or workload. Equivalent to AWS `account_id` and Azure `subscription_id`. | `platform-prod-001` |
| `account_name` | 4 in synthetic | Human-readable project display name. Stable across project ID renames. | `Platform Production` |
| `project_number` | 4 in synthetic | Numeric project identifier assigned by Google. Immutable — project IDs can be re-used after deletion, project numbers cannot. More reliable as a join key in long-lived pipelines. | `100000000001` |
| `project_ancestry` | 4 in synthetic | Slash-delimited path of project/folder/org numbers from leaf to root. Used for org-level hierarchy roll-ups without a separate API call. | `100000000001/222111000/123456789` |

> **GCP hierarchy:** Organisation → Folders → Projects → Resources.
> Billing happens at the project level. `project_ancestry` encodes the full path upward
> so you can aggregate costs by folder (department) or organisation without a resource-manager API join.

---

### Service & SKU

| Column | Distinct values | Meaning | Example |
|---|---|---|---|
| `service_id` | 3 in synthetic | Internal GCP service identifier — stable across region and SKU changes. Used when joining to the GCP Pricing API. | `6F81-5844-456A` (Compute Engine) |
| `service_name` | `Compute Engine`, `Cloud Storage`, `BigQuery`, `Cloud SQL` | Human-readable service name (`service.description`). The primary dimension for service-level cost grouping. Equivalent to AWS `service_name` (ProductCode) and Azure `service_name` (MeterCategory). | `Compute Engine` |
| `sku_id` | Many (GUIDs) | Unique ID for the specific SKU being billed. Used to look up unit pricing in the GCP Cloud Billing Catalog API. | `9A64-0562-6F31` |
| `sku_description` | Many | Human-readable description of the exact resource type billed. The most granular service label — equivalent to Azure `meter_name`. Includes machine type and region for GCE. | `n2-standard-4 running in us-central1` |

---

### Timestamps

| Column | Meaning | Example |
|---|---|---|
| `usage_start_time` | When the billable window started (UTC, typed `TIMESTAMP`). **Hourly** for Compute Engine and Cloud SQL. **Daily (midnight)** for Cloud Storage and BigQuery storage. | `2026-03-15 14:00:00` (hourly GCE) / `2026-03-15 00:00:00` (daily GCS) |
| `usage_end_time` | When the billable window ended. `start + 1 hour` for compute; `start + 1 day` for storage. | `2026-03-15 15:00:00` |
| `billing_month` | Derived `YYYY-MM` string from `usage_start_time`. Primary partition for all downstream monthly roll-ups. | `2026-03` |
| `invoice_month` | GCP invoice month in `YYYYMM` format from the billing export. May differ from `billing_month` for cross-month adjustments. | `202603` |

> **Mixed grain:** GCE and Cloud SQL emit one row per hour; Cloud Storage and BigQuery storage
> emit one row per day. Downstream aggregations must not assume hourly grain for all GCP rows.
> Group by `DATE(usage_start_time)` for daily totals; never divide by 24 to estimate hourly rates.

---

### Resource

| Column | Meaning | Example |
|---|---|---|
| `resource_id` | Cloud resource path (`resource.name`) — identifies the specific instance, bucket, or dataset being billed. Primary join key for tagging and rightsizing. | `projects/platform-prod-001/zones/us-central1-a/instances/vm-n2standard4-a` |
| `resource_global_name` | Fully qualified global resource identifier (`resource.global_name`) using the `//service.googleapis.com/...` format. Stable across project moves; used in IAM and asset inventory joins. | `//compute.googleapis.com/projects/platform-prod-001/zones/us-central1-a/instances/vm-n2standard4-a` |

---

### Location

| Column | Distinct values | Meaning | Example |
|---|---|---|---|
| `region` | `us-central1`, `europe-west1`, `asia-east1`, `us-east1` | GCP region of the resource. Normalized directly from `location.region` — already lowercase, no transformation needed. | `us-central1` |
| `zone` | `us-central1-a`, `us-central1-b`, … | Specific zone within the region. Blank for regional resources (Cloud Storage multi-region, BigQuery). | `us-central1-a` |
| `country` | `US`, `EU`, `APAC` | Country/continent rollup from `location.country`. Useful for data residency reporting and regional spend breakdowns. | `US` |

---

### Compute Metadata (GCE only)

These three columns are extracted from the `system_labels` JSON array using the `extract_gcp_label` macro. They are populated **only for Compute Engine VM rows** — all other services (Cloud Storage, BigQuery, Cloud SQL) have `NULL`.

| Column | Distinct values | Meaning | Example |
|---|---|---|---|
| `compute_cores` | `2`, `4`, `8`, `16`, NULL | vCPU count of the GCE VM instance. Parsed from `system_labels` key `compute_cores`. Used for $/vCPU efficiency metrics and rightsizing. | `4` |
| `compute_memory_gb` | `8`, `16`, `32`, `64`, `128`, NULL | RAM in GiB of the GCE VM instance. Parsed from `system_labels` key `compute_memory`. Used for $/GB-RAM efficiency and memory rightsizing. | `16` |
| `is_unused_reservation` | `true` / `false` | Whether this GCE hour was billed under a CUD reservation but the VM was idle. Parsed from `system_labels` key `is_unused_reservation`. Maps to `is_commitment_waste` in `fct_unified_billing`. | `false` |

> **`system_labels` format:** `[{"key": "compute_cores", "value": "4"}, {"key": "compute_memory", "value": "16"}, {"key": "is_unused_reservation", "value": "false"}]`
> The same `extract_gcp_label` macro used for billing labels is reused here.

---

### Usage

| Column | Meaning | Example |
|---|---|---|
| `usage_amount` | Quantity consumed in the billing window. For GCE = `1.0` (one instance-hour). For Cloud Storage = GiB stored. For BigQuery = TiB scanned. | `1.0` (GCE hour), `18500.0` (GiB stored) |
| `usage_unit` | Unit of `usage_amount` as billed. | `hour`, `gibibyte month`, `tebibyte` |
| `pricing_unit` | Unit used in the GCP Pricing API for rate lookup. Usually matches `usage_unit` but can differ for complex SKUs. | `hour`, `gibibyte month` |

---

### Cost

| Column | Meaning | Example |
|---|---|---|
| `list_cost` | Raw on-demand cost for this row **before any credits** (`cost` in the BigQuery export). This is GCP's list price × usage quantity. Credits (CUD, SUD) are subtracted separately. | `0.1826` ($/hr n2-standard-2 at OD rate) |
| `cost_at_list` | Same as `list_cost` in this export — the on-demand price before credits. Kept as a separate column for explicitness; distinguishes gross cost from post-credit cost in downstream joins. | `0.1826` |
| `currency` | Billing currency. | `USD` |
| `cost_type` | `regular`, `tax`, `adjustment`, `rounding_error` | Type of charge. **Only `regular` rows are kept** in staging. Tax, adjustments, and rounding corrections are filtered out. | `regular` |

> **`list_cost` vs Azure `list_cost`:** In Azure, `list_cost` is the **amortized** RI/SP cost
> (already discounted). In GCP, `list_cost` is the **on-demand price before discounts** — credits
> subtract from it. These are opposite semantics. Use `net_cost` (GCP) or `nec` (all clouds)
> for cross-cloud cost comparisons.

---

### Credits

GCP discounts are not applied to the cost figure — they are recorded as separate negative
entries in a JSON array on the **same row** as the usage cost. This is the most important
structural difference between GCP billing and AWS/Azure billing.

| Column | Meaning | Example |
|---|---|---|
| `credits_raw` | Full JSON array of all credits applied to this row. Kept raw so `int_gcp_nec` and ad-hoc queries can inspect individual credit types and amounts. | `[{"name": "Committed Use Discount", "type": "COMMITTED_USAGE_DISCOUNT", "amount": -0.0675}]` |
| `total_credit_amount` | Sum of all `amount` fields in `credits_raw` for credit types: `COMMITTED_USAGE_DISCOUNT`, `COMMITTED_USAGE_DISCOUNT_DOLLAR_BASE`, `SUSTAINED_USE_DISCOUNT`, `FREE_TIER`, `PROMOTION`. Always ≤ 0 (negative = savings). | `-0.0675` |
| `net_cost` | `list_cost + total_credit_amount` — the actual cost after all discounts. The GCP equivalent of AWS `nec` and Azure `nec_used`. | `0.1151` |

**Credit types in `credits_raw`:**

| `type` | Meaning | Applies to |
|---|---|---|
| `COMMITTED_USAGE_DISCOUNT` | Resource-based CUD — commit to specific vCPU/memory for 1 or 3 years | GCE VMs, Cloud SQL |
| `COMMITTED_USAGE_DISCOUNT_DOLLAR_BASE` | Spend-based CUD — commit to a dollar amount per month | GCE, Cloud Run |
| `SUSTAINED_USE_DISCOUNT` | Automatic discount when usage exceeds 25% of the month — no purchase needed | GCE VMs only |
| `FREE_TIER` | Monthly free allowance (e.g. Cloud Storage first 5 GB free) | Various |
| `PROMOTION` | Trial credits, promotional credits from Google | Various |

---

### Labels

| Column | Distinct values | Meaning | Example |
|---|---|---|---|
| `tag_team` | `platform`, `data-eng`, `frontend`, `backend`, `ml`, NULL | Owning team. NULL = untagged. Primary allocation key in all downstream models. | `data-eng` |
| `tag_environment` | `prod`, `staging`, `dev`, NULL | Deployment environment. | `prod` |
| `tag_cost_center` | `cc100`–`cc500`, NULL | Finance cost center code. | `cc200` |

> **GCP labels format:** Labels in the BigQuery billing export are a **list of `{key, value}` dicts**:
> `[{"key": "team", "value": "platform"}, {"key": "environment", "value": "prod"}, ...]`
>
> The `extract_gcp_label` macro uses DuckDB's `unnest` to scan the array and return the value
> for a given key. This is structurally different from AWS (flat `resourceTags/user:Team` columns)
> and Azure (JSON object `{"team": "platform", ...}` with direct `$.team` path extraction).

---

### Derived Flags

| Column | Values | Meaning |
|---|---|---|
| `is_tagged` | `true` / `false` | `true` when `tag_team` is non-null. False for untagged VMs, Cloud Storage buckets with no labels, and BigQuery datasets. Unlike Azure, GCP has no shared-infrastructure concept in staging — untagged rows go straight to downstream attribution. |
| `cloud_provider` | `'gcp'` | Literal stamp added so `fct_unified_billing` can filter and group by cloud after the UNION ALL. |

---

## Commitment Discount Mechanics

### The Core Difference from AWS and Azure

| Aspect | AWS | Azure | GCP |
|---|---|---|---|
| Where discounts appear | Separate rows (`DiscountedUsage`, `RIFee`) + different cost columns | Separate `UnusedReservation` rows; `pricing_model` on usage rows | **Credits JSON on the same row** — no separate rows |
| Waste visibility | `RIFee` rows with `reservation_unused_quantity` | `UnusedReservation` / `UnusedSavingsPlan` rows | `is_unused_reservation` system_label only — no dedicated waste row |
| Purchase required | Yes (RI / SP) | Yes (Reservation / Savings Plan) | CUD: Yes. SUD: **No — automatic** |
| Discount type column | `line_item_type` | `pricing_model` | Inferred from `credits_raw` credit type |

GCP never generates a separate "fee" row (like AWS `RIFee`) or a separate "unused" row
(like Azure `UnusedReservation`). The discount is a credit attached to the usage row,
and idle capacity shows up only as `is_unused_reservation = true` on the usage row —
not as a dedicated waste row with a cost.

---

### Committed Use Discounts (CUD) — How $3,650/year flows through GCP

$3,650/year ÷ 8,760 hours = **$0.417/hour commitment**

Assume: CUD purchases 37% discount on n2-standard-4 (OD rate: $0.365/hr).
Post-CUD rate: $0.365 × (1 − 0.37) = **$0.230/hr**

#### Hourly row — VM ran under CUD

One row per hour the covered VM ran.

| Column | Value | Why |
|---|---|---|
| `list_cost` | `0.3652` | On-demand price for this hour — always the OD rate regardless of CUD |
| `cost_at_list` | `0.3652` | Same as `list_cost` — gross OD cost |
| `credits_raw` | `[{"type": "COMMITTED_USAGE_DISCOUNT", "amount": -0.1351}]` | The 37% discount as a negative credit entry |
| `total_credit_amount` | `-0.1351` | Sum of all credit amounts (negative = you save this) |
| `net_cost` | `0.2301` | `list_cost + total_credit_amount` = actual cost after CUD |
| `is_unused_reservation` | `false` | VM ran — no idle waste |
| `discount_type` (int layer) | `'ri'` | Derived from `COMMITTED_USAGE_DISCOUNT` in `credits_raw` |

`net_cost` is the correct column for chargeback and NEC. `list_cost` alone overstates
actual cost by the full CUD discount.

#### Hourly row — VM idle under CUD (`is_unused_reservation = true`)

GCP does **not** create a separate waste row. The usage row itself carries the waste signal.

| Column | Value | Why |
|---|---|---|
| `list_cost` | `0.3652` | OD cost is still recorded — GCP billed the commitment |
| `credits_raw` | `[]` or no CUD credit | No actual credit applied — idle hours receive no discount |
| `total_credit_amount` | `0.0` | No credit on wasted hours |
| `net_cost` | `0.3652` | Full OD rate — no discount, VM was idle |
| `is_unused_reservation` | **`true`** | Waste signal — commitment paid, nothing ran |
| `is_commitment_waste` (mart) | **`true`** | Mapped from `is_unused_reservation` |

> **Key insight:** On idle CUD hours, GCP charges the **on-demand rate** (no discount applied)
> because the discount is only credited when the instance actually runs. AWS and Azure
> amortize the commitment cost regardless of utilisation. GCP's "waste" is paying OD price
> for hours you intended to cover with a committed discount.

---

### Sustained Use Discounts (SUD) — Automatic, No Purchase Required

SUD applies automatically when a GCE VM runs for more than 25% of the billing month.
Discount scales linearly up to **30% at 100% usage**. No RI/SP purchase needed.

| Usage % of month | SUD discount |
|---|---|
| 0–25% | 0% |
| 25–50% | up to 10% |
| 50–75% | up to 20% |
| 75–100% | up to 30% |

#### Hourly row — SUD applied

| Column | Value | Why |
|---|---|---|
| `list_cost` | `0.1826` | OD hourly rate — unchanged |
| `credits_raw` | `[{"type": "SUSTAINED_USE_DISCOUNT", "amount": -0.0365}]` | ~20% SUD credit for this hour |
| `total_credit_amount` | `-0.0365` | Discount amount (negative) |
| `net_cost` | `0.1461` | Effective cost after SUD |
| `discount_type` (int layer) | `'sp'` | SUD mapped to `sp` (analogous to SP — automatic commitment-style discount) |

#### CUD + SUD on the same row

Both can appear simultaneously if a VM has a CUD and also qualifies for SUD:

```json
[
  {"type": "COMMITTED_USAGE_DISCOUNT", "amount": -0.1351},
  {"type": "SUSTAINED_USE_DISCOUNT",   "amount": -0.0365}
]
```

`total_credit_amount = -0.1351 + (-0.0365) = -0.1716`
`net_cost = 0.3652 - 0.1716 = 0.1936`

`discount_type` is set to `'ri'` when CUD is present (CUD takes precedence over SUD in detection).

---

### CUD vs SUD Side-by-Side

| Aspect | CUD (Committed Use Discount) | SUD (Sustained Use Discount) |
|---|---|---|
| Purchase required | Yes — 1-year or 3-year commitment | No — applied automatically by GCP |
| Discount rate | ~37% (1-yr), ~55% (3-yr) | Up to 30% at 100% monthly usage |
| Credit type in export | `COMMITTED_USAGE_DISCOUNT` | `SUSTAINED_USE_DISCOUNT` |
| `discount_type` in mart | `'ri'` | `'sp'` |
| Applies to | Specific resource type + region | Any GCE VM (not Cloud SQL) |
| Waste if idle | `is_unused_reservation = true` on that hour | N/A — no commitment to waste |
| Can both apply? | Yes — credits stack on the same row | Yes |

---

### How `int_gcp_nec` Resolves These Into a Single `nec`

This pipeline uses the **GCP Detailed Usage Export**, where `list_cost` represents the
pre-credit on-demand usage cost and credits are recorded as separate negative amounts on the
same row. (The Standard Export is different: `cost` is already post-credit and requires no
subtraction.)

The intermediate model uses the pre-computed `total_credit_amount` from staging:

```
nec = GREATEST(list_cost + total_credit_amount, 0.0)
    = GREATEST(list_cost − |credits|, 0.0)   (credits are negative)

-- total_credit_amount covers: COMMITTED_USAGE_DISCOUNT, COMMITTED_USAGE_DISCOUNT_DOLLAR_BASE,
--   SUSTAINED_USE_DISCOUNT, FREE_TIER, PROMOTION.
-- It does NOT include negotiated contract discounts or support credits.

discount_type = 'ri'        when credits_raw LIKE '%COMMITTED_USAGE_DISCOUNT%'
discount_type = 'sp'        when credits_raw LIKE '%SUSTAINED_USE_DISCOUNT%'
discount_type = 'on_demand' otherwise
```

`GREATEST(..., 0.0)` is a reporting guardrail to prevent negative NEC in cases where
promotional or free-tier credits exceed the pre-credit usage cost. Negative NEC is
meaningful for credit tracking but distorts team cost roll-ups, so it is clamped to zero
as a deliberate design choice.

No per-row-type column switching needed (unlike AWS which must pick between
`unblended_cost`, `reservation_effective_cost`, and `savings_plan_effective_cost`).
GCP's credit-on-same-row design means one formula works for all rows.

---

### Billing Grain by Service

| Service | Grain | Rows per resource per month |
|---|---|---|
| Compute Engine | **Hourly** | Up to 720 (one per hour the VM ran) |
| Cloud SQL | **Hourly** | Up to 720 |
| BigQuery — analysis | **Per query** (sporadic hours) | ~30% of hours have a query (~216 rows) |
| BigQuery — storage | **Daily** | 28–31 rows per dataset |
| Cloud Storage | **Daily** | 28–31 rows per bucket |

> Never assume all GCP rows are hourly. Aggregating `usage_amount` with a time-based denominator
> without checking the service will produce wrong per-unit rates for storage rows.

---

### Savings & Waste Metrics

| Metric | Formula using staging / intermediate columns |
|---|---|
| CUD savings | `sum(-total_credit_amount)` where `credits_raw LIKE '%COMMITTED_USAGE_DISCOUNT%'` |
| SUD savings | `sum(-total_credit_amount)` where `credits_raw LIKE '%SUSTAINED_USE_DISCOUNT%'` |
| Total discount savings | `sum(list_cost - net_cost)` = `sum(-total_credit_amount)` |
| Discount % | `sum(-total_credit_amount) / sum(list_cost)` |
| CUD waste cost | `sum(list_cost)` where `is_unused_reservation = true` |
| Effective discount on idle hours | `0%` — GCP applies no credit to unused reservation hours |
| $/vCPU-hour | `net_cost / compute_cores` (GCE rows only) |
| $/GB-RAM-hour | `net_cost / compute_memory_gb` (GCE rows only) |
| Untagged cost | `sum(net_cost)` where `is_tagged = false` |

---

### Common Mistakes

| Mistake | Impact | Fix |
|---|---|---|
| Using `list_cost` without subtracting credits | Overstates actual spend by the full CUD/SUD discount — GCP costs look 20–37% higher than reality | Use `net_cost` or `nec` from `int_gcp_nec` |
| Assuming discounts create separate rows | Looking for "RI rows" or "discount rows" — they don't exist in GCP | Credits are embedded in the usage row's `credits_raw` array |
| Treating `cost_type != 'regular'` rows as discounts | `tax` and `adjustment` rows are filtered out in staging — no action needed | The `WHERE cost_type = 'regular'` filter handles this |
| Treating labels as a flat dict (AWS-style) | `labels['team']` fails — GCP uses list-of-dicts | Use `extract_gcp_label` macro: `[{"key": "team", "value": "platform"}]` |
| Treating all GCP rows as hourly | Dividing daily storage cost by 24 to get hourly rates | Check `service_name` — Cloud Storage and BigQuery storage are daily |
| Ignoring `is_unused_reservation` for waste | CUD waste is invisible without this flag — no dedicated waste rows exist | Filter `is_unused_reservation = true` for commitment waste analysis |
| Comparing GCP `list_cost` to Azure `list_cost` | Azure `list_cost` is amortized (post-discount); GCP `list_cost` is on-demand (pre-discount) — same column name, opposite semantics | Use `net_cost` (GCP) and `nec_used` (Azure) for like-for-like comparison |
| Assuming SUD applies to Cloud SQL | SUD only applies to GCE VMs | Cloud SQL uses resource-based CUDs only |
