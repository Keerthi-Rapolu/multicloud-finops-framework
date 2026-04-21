# AWS CUR Staging Reference

Complete reference for `stg_aws_cur` — every column, its distinct values, meaning,
example, and how RI/SP commitment costs flow through the report.

---

## Column Reference

### Identity & Billing

| Column | Distinct values | Meaning | Example |
|---|---|---|---|
| `line_item_id` | Unique per row | UUID-like key AWS assigns to each charge line. Used for deduplication and tracing back to raw CUR. | `a3f9c2d1...` |
| `payer_account_id` | 1 in synthetic (`112233445566`) | The master/payer AWS account in an Org. All member accounts roll up charges here for consolidated billing. Different from `account_id` in multi-account setups. | `112233445566` |
| `account_id` | 3 in synthetic | The member account that actually ran the resource. Maps to a team or business unit in multi-account orgs. | `334455667788` (app-prod) |
| `line_item_type` | 5 values | What kind of charge this row represents — drives which cost columns are populated. See full breakdown below. | `Usage` |

**`line_item_type` values:**

| Value | Grain | Key columns populated |
|---|---|---|
| `Usage` | Hourly | `unblended_cost`, `on_demand_cost` |
| `DiscountedUsage` | Hourly | `reservation_arn`, `reservation_effective_cost`, `reservation_amortized_upfront`, `reservation_recurring_fee` |
| `SavingsPlanCoveredUsage` | Hourly | `savings_plan_arn`, `savings_plan_effective_cost`, `savings_plan_rate`, `savings_plan_used_commitment` |
| `RIFee` | **Monthly** | `reservation_unused_quantity`, `reservation_unused_upfront_fee`, `reservation_unused_recurring_fee` |
| `SavingsPlanRecurringFee` | **Monthly** | `savings_plan_total_commitment`, `savings_plan_recurring_commitment`, `savings_plan_used_commitment` |

---

### Timestamps

| Column | Meaning | Example |
|---|---|---|
| `usage_start_time` | When this billable hour started (UTC). AWS CUR is hourly grain — each resource emits one row per hour. For `RIFee`/`SavingsPlanRecurringFee` rows this is the billing period start. | `2026-03-01 00:00:00` |
| `usage_end_time` | When the hour ended. Always `usage_start_time + 1 hour` for usage rows. Spans the full billing period for monthly fee rows. | `2026-03-01 01:00:00` |
| `billing_month` | Derived `YYYY-MM` string — the primary partition used by all downstream models for monthly roll-ups. | `2026-03` |

---

### Resource

| Column | Distinct values | Meaning | Example |
|---|---|---|---|
| `resource_id` | One per resource | ARN or resource identifier for the specific thing being billed. Joins to tagging, rightsizing, and anomaly tables. | `arn:aws:ec2:us-east-1:112233445566:instance/i-0abc123` |
| `service_name` | `AmazonEC2`, `AmazonS3`, `AmazonRDS` | AWS service code — coarse grouping. | `AmazonEC2` |
| `product_name` | 3 in synthetic | Human-readable product name, more descriptive than service code. | `Amazon Elastic Compute Cloud` |
| `instance_type` | ~8 EC2 + 3 RDS sizes | EC2/RDS instance family and size. Empty for S3/data-transfer rows. | `m5.large`, `db.r5.large` |
| `vcpu` | `2`, `4`, `8`, NULL | Number of vCPUs on the EC2 instance. NULL for S3 and RDS rows. Used to compute $/vCPU efficiency and compare instance families. | `4` |
| `memory` | `"4 GiB"` – `"32 GiB"`, NULL | RAM of the EC2 instance. NULL for S3 and RDS rows. Used for $/GB-RAM efficiency and rightsizing recommendations. | `"16 GiB"` |
| `operating_system` | `Linux`, blank | OS of the compute resource. Blank for non-EC2 services. | `Linux` |
| `usage_type` | Many | Region-prefixed usage descriptor combining region + resource type + operation. | `USE1-BoxUsage:m5.large` |
| `operation` | Many | API operation that generated the charge. | `RunInstances`, `StandardStorage` |
| `region` | `us-east-1`, `us-west-2`, `eu-west-1` | AWS region of the resource. | `us-west-2` |
| `availability_zone` | ~2–3 per region | AZ within the region. Blank for S3/global services and monthly fee rows. | `us-east-1a` |

---

### Usage & Normalisation

| Column | Meaning | Example |
|---|---|---|
| `usage_amount` | Quantity consumed. For EC2 = `1.0` (one instance-hour). For S3 = GB stored in that hour. | `1.0`, `1850.3` |
| `normalization_factor` | AWS size factor for EC2 normalization. Allows comparing RI coverage across instance sizes — a `large=4`, `xlarge=8`, `2xlarge=16`. NULL for S3/RDS. | `8.0` |
| `normalized_usage_amount` | `usage_amount × normalization_factor`. One `xlarge`-hour = 8 normalized units, same as 8 `small`-hours. Used for RI utilisation % across mixed-size fleets. | `8.0` |
| `pricing_unit` | Unit of `usage_amount`. | `Hrs`, `GB-Mo` |
| `on_demand_rate` | Published list price per unit — what you'd pay with no commitment at all. The baseline for discount savings calculation. | `0.096` ($/hr for m5.large) |
| `on_demand_cost` | `on_demand_rate × usage_amount` — gross sticker price before any discounts. | `0.096` |

---

### Raw Costs

| Column | Meaning | When to use |
|---|---|---|
| `unblended_cost` | Actual charge at the rate it was billed. **$0 for RI-covered hours** (the RI pays for it). OD rate for SP-covered hours. Correct only for `Usage` rows. | Spot-checking individual OD charges |
| `blended_cost` | AWS's attempt to spread RI/SP savings evenly across all accounts in an Org. Often misleading for per-team analysis in multi-account setups. | Rarely — prefer `nec` from `int_aws_nec` |

> Neither column alone is correct across all `line_item_type` values. Use `nec` from the intermediate layer which picks the right column per row type.

---

### RI Fields

**Hourly columns** — populated on `DiscountedUsage` rows (per instance-hour covered by RI):

| Column | Meaning | Example |
|---|---|---|
| `reservation_arn` | ARN of the specific RI that covered this hour. Links usage rows back to the RI purchase. | `arn:aws:ec2:...:reserved-instances/...` |
| `reservation_effective_cost` | All-in hourly RI cost = amortized upfront + recurring. **The correct column for chargeback on RI-covered hours.** | `0.061` |
| `reservation_amortized_upfront` | Fraction of the upfront payment amortized into this hour (~15% of effective cost for partial upfront). Zero for no-upfront RIs. | `0.009` |
| `reservation_recurring_fee` | Monthly recurring fee prorated to this hour (~85% of effective for partial upfront). Full effective cost for no-upfront RIs. | `0.052` |

**Monthly columns** — populated on `RIFee` rows only (one row per RI per billing period):

| Column | Meaning | Example |
|---|---|---|
| `reservation_unused_quantity` | Instance-hours the RI was reserved but no instance ran under it. Non-zero = wasted money. | `14.4` hrs out of 72 sampled |
| `reservation_unused_upfront_fee` | Cost of the upfront commitment allocated to those idle hours. | `0.13` |
| `reservation_unused_recurring_fee` | Cost of the recurring fee allocated to those idle hours. | `0.74` |

---

### SP Fields

**Hourly columns** — populated on `SavingsPlanCoveredUsage` rows (per instance-hour covered by SP):

| Column | Meaning | Example |
|---|---|---|
| `savings_plan_arn` | ARN of the Savings Plan covering this hour. | `arn:aws:savingsplans::...:savingsplan/...` |
| `savings_plan_effective_cost` | Actual SP-adjusted cost for this hour. **The correct column for chargeback on SP-covered hours.** | `0.068` |
| `savings_plan_rate` | The committed per-unit rate under this SP. | `0.068` |
| `savings_plan_used_commitment` | Dollar amount of the monthly SP commitment consumed by this hour. Aggregates to SP utilisation. | `0.068` |

**Monthly columns** — populated on `SavingsPlanRecurringFee` rows only (one row per SP per billing period):

| Column | Meaning | Example |
|---|---|---|
| `savings_plan_total_commitment` | Total SP commitment purchased for this billing period. | `4.90` |
| `savings_plan_recurring_commitment` | Monthly fee owed regardless of usage — the spend floor you committed to. | `4.90` |

---

### Tags

| Column | Distinct values | Meaning | Example |
|---|---|---|---|
| `tag_team` | `platform`, `data-eng`, `frontend`, `backend`, `ml`, NULL | Owning team. NULL = untagged = cost cannot be attributed. Primary allocation key in all downstream models. | `data-eng` |
| `tag_environment` | `prod`, `staging`, `dev`, NULL | Deployment environment. Used to split prod vs non-prod spend. | `prod` |
| `tag_cost_center` | `CC100`–`CC500`, NULL | Finance cost center code, maps directly to budget lines. | `CC200` (data-eng) |

---

### Derived Flags

| Column | Values | Meaning |
|---|---|---|
| `is_tagged` | `true` / `false` | `true` when `tag_team` is non-null. Primary signal for tagging coverage — ~13% false in current synthetic data, representing cost that cannot be attributed to any team. |
| `cloud_provider` | `'aws'` | Literal stamp added so `fct_unified_billing` can filter and group by cloud after the UNION ALL. |

---

## Commitment Cost Mechanics

### The Core Problem

When you buy a 1-year RI or Savings Plan, AWS does not put one big charge in a single
row. The cost is distributed across many rows — hourly for actual usage, monthly for
commitment summaries — and split across different columns depending on the payment model.
Using the wrong column gives you the wrong number.

---

### Reserved Instances — How $3,650/year flows through the CUR

$3,650/year = **$10/day = $0.417/hour**

#### Hourly rows (`line_item_type = 'DiscountedUsage'`)

One row per hour the covered instance runs.

| Column | Value | Why |
|---|---|---|
| `unblended_cost` | **$0.00** | The RI already "paid" for this hour — AWS records zero charge on the usage line |
| `on_demand_cost` | ~$0.096 | What you would have paid without any RI (sticker price) |
| `reservation_effective_cost` | **$0.417** | The amortized hourly slice of the full $3,650 commitment |
| `reservation_amortized_upfront` | ~$0.063 | Upfront payment portion (~15%) spread per hour |
| `reservation_recurring_fee` | ~$0.354 | Recurring monthly fee portion (~85%) spread per hour |

`reservation_effective_cost` is the correct column for NEC and chargeback.
`unblended_cost` is $0 on RI hours — using it understates RI cost to zero.

#### Monthly row (`line_item_type = 'RIFee'`)

One row per RI per billing period — summarises full reservation including waste.

| Column | Value | Why |
|---|---|---|
| `reservation_effective_cost` | ~$300 | Total RI cost for the month (720 hrs × $0.417) |
| `reservation_unused_quantity` | e.g. 72 hrs | Hours the RI sat idle — no instance ran under it |
| `reservation_unused_upfront_fee` | ~$4.54 | Upfront cost of those wasted hours |
| `reservation_unused_recurring_fee` | ~$25.49 | Recurring cost of those wasted hours |

The unused columns are **only populated on `RIFee` rows** — they are null on every
`DiscountedUsage` row. Dropping `RIFee` from the filter makes RI waste completely invisible.

#### RI payment models — how upfront vs recurring splits

| Payment model | `reservation_amortized_upfront` | `reservation_recurring_fee` | `reservation_effective_cost` |
|---|---|---|---|
| All upfront | $0.417/hr (100%) | $0.000/hr | $0.417/hr |
| Partial upfront | ~$0.209/hr (50%) | ~$0.209/hr (50%) | $0.417/hr |
| No upfront | $0.000/hr | $0.417/hr (100%) | $0.417/hr |

`reservation_effective_cost` is always the same regardless of payment model — it is the
economically correct per-hour cost. The upfront/recurring split is a cash-flow detail.

#### RI utilisation formula
```
utilisation % = 1 - (reservation_unused_quantity / total_reserved_hours)
```
Below 80% is the typical threshold for an underperforming RI.

---

### Savings Plans — How $3,650/year flows through the CUR

$3,650/year = **$10/day commitment floor** — but SP works differently from RI.
The commitment is a $/hour spend amount, not a reservation of specific instances.

#### Hourly rows (`line_item_type = 'SavingsPlanCoveredUsage'`)

One row per hour the SP discount applies to a resource.

| Column | Value | Why |
|---|---|---|
| `unblended_cost` | **~$0.096** | On-demand rate — SP rows do NOT zero out `unblended_cost` unlike RI |
| `on_demand_cost` | ~$0.096 | Same as unblended for SP rows |
| `savings_plan_effective_cost` | **~$0.068** | Actual SP-adjusted cost (~29% off OD). Use this for chargeback |
| `savings_plan_used_commitment` | ~$0.068 | Monthly commitment consumed by this hour |

**Key difference from RI:** `unblended_cost` is NOT $0 on SP rows. It shows the OD rate.
The discount only appears in `savings_plan_effective_cost`. Using `unblended_cost` for SP
analysis overstates cost — the discount is completely invisible.

#### Monthly row (`line_item_type = 'SavingsPlanRecurringFee'`)

One row per SP per billing period — summarises commitment vs actual usage.

| Column | Value | Why |
|---|---|---|
| `savings_plan_total_commitment` | ~$300 | Total SP commitment for the billing period |
| `savings_plan_recurring_commitment` | ~$300 | Monthly fee owed regardless of usage — your spend floor |
| `savings_plan_used_commitment` | e.g. $240 | Portion of the commitment actually consumed |

#### SP utilisation formula
```
utilisation % = sum(savings_plan_used_commitment) / savings_plan_recurring_commitment
```
Below 80% means you committed to more than you use — the gap is wasted spend.

---

### RI vs SP Side-by-Side

| Aspect | Reserved Instance | Savings Plan |
|---|---|---|
| `unblended_cost` on usage rows | **$0** (RI zeroes it out) | **OD rate** (discount not reflected) |
| Correct cost column | `reservation_effective_cost` | `savings_plan_effective_cost` |
| Covers | Specific instance type + region | Any EC2 usage (Compute SP) or flexible |
| Waste visibility | `reservation_unused_quantity` on `RIFee` rows | `commitment - used_commitment` on `SavingsPlanRecurringFee` rows |
| Monthly summary row | `RIFee` | `SavingsPlanRecurringFee` |

---

### How `int_aws_nec` Resolves These Into a Single `nec`

For the main commitment-related row types in AWS CUR, the intermediate model picks
the correct cost column per `line_item_type` so no downstream model ever has to
think about this:

```
line_item_type = 'Usage'                   → nec_used = unblended_cost
                                             nec_waste = 0

line_item_type = 'DiscountedUsage'         → nec_used = reservation_effective_cost
                                             nec_waste = 0

line_item_type = 'SavingsPlanCoveredUsage' → nec_used = savings_plan_effective_cost
                                             nec_waste = 0

line_item_type = 'RIFee'                   → nec_used = 0
                                             nec_waste = unused_upfront_fee
                                                       + unused_recurring_fee

line_item_type = 'SavingsPlanRecurringFee' → nec_used = 0
                                             nec_waste = recurring_commitment
                                                       - used_commitment
```

`nec = nec_used` — waste is reported separately and not added into usage cost.

This model excludes offset rows such as `SavingsPlanNegation` to prevent double-counting.
The effective cost is already correct on `SavingsPlanCoveredUsage` rows without them.

All downstream models (`fct_unified_billing`, dashboards) use `nec` exclusively.

---

### Savings & Waste Metrics

| Metric | Formula using staging columns |
|---|---|
| RI savings vs OD | `on_demand_cost - reservation_effective_cost` |
| SP savings vs OD | `on_demand_cost - savings_plan_effective_cost` |
| RI wasted spend | `reservation_unused_upfront_fee + reservation_unused_recurring_fee` |
| SP wasted spend | `savings_plan_recurring_commitment - sum(savings_plan_used_commitment)` |
| RI utilisation % | `1 - (reservation_unused_quantity / total_reserved_hours)` |
| SP utilisation % | `sum(savings_plan_used_commitment) / savings_plan_recurring_commitment` |
| $/vCPU-hour | `nec / vcpu` (EC2 only, null for S3/RDS) |
| $/GB-RAM-hour | `nec / numeric memory` (EC2 only) |

---

### Common Mistakes

| Mistake | Impact | Fix |
|---|---|---|
| Using `unblended_cost` for RI hours | Reports $0 cost for all RI-covered resources | Use `reservation_effective_cost` |
| Using `unblended_cost` for SP hours | Reports OD rate — SP discount is invisible | Use `savings_plan_effective_cost` |
| Dropping `RIFee` rows from the filter | RI waste invisible; utilisation % breaks | Keep `RIFee` in `line_item_type` filter |
| Dropping `SavingsPlanRecurringFee` rows | SP commitment baseline missing | Keep in filter |
| Summing `unblended_cost` across all types | Mixes $0 RI rows with OD rows — total is wrong | Use `nec` from `int_aws_nec` |
| Double-counting RI cost | Adding both hourly `DiscountedUsage` and monthly `RIFee` totals | Use `nec` which normalises grain |
