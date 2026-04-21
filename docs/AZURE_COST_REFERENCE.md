# Azure Cost Management Staging Reference

Complete reference for `stg_azure_cost` — every column, its distinct values, meaning,
example, and how RI/SP commitment costs flow through the amortized export.

---

## Column Reference

### Identity & Billing Hierarchy

| Column | Distinct values | Meaning | Example |
|---|---|---|---|
| `billing_account_id` | 1 in synthetic (`EA-9876543210`) | EA (Enterprise Agreement) enrollment ID — the top-level billing entity. All subscriptions under the agreement roll up here. Equivalent to AWS `payer_account_id`. | `EA-9876543210` |
| `account_id` | 6 in synthetic | Azure Subscription ID (UUID). The unit of billing isolation — each subscription maps to a team or environment. Equivalent to AWS `account_id`. | `a1b2c3d4-0001-0001-0001-000000000001` |
| `account_name` | 6 in synthetic | Human-readable subscription name. Makes dashboards readable without a lookup table. | `Platform Production` |
| `account_owner_id` | 6 in synthetic | Email address of the subscription owner. Useful for escalating untagged resources or ownership disputes. | `platform-owner@corp.com` |
| `invoice_section` | ~1–3 per enrollment | Department or cost center within the EA. Azure uses this for sub-billing-account cost grouping (MCA accounts use invoice sections prominently). | `Engineering` |
| `resource_group` | Many | Azure Resource Group — a logical container for related resources in a subscription. Finer grain than subscription for cost grouping. | `platform-prod-rg` |

---

### Timestamps

| Column | Meaning | Example |
|---|---|---|
| `usage_date` | The calendar day this charge was incurred (typed `DATE`). Azure Cost Export is **daily grain** — each resource emits one row per day, not per hour. | `2026-03-15` |
| `billing_month` | Derived `YYYY-MM` string from `usage_date`. Primary partition for all downstream monthly roll-ups. | `2026-03` |

> **Grain difference vs AWS/GCP:** AWS and GCP export hourly rows. Azure exports daily rows.
> Intra-day analysis (e.g. peak-hour attribution) is impossible from Azure Cost Management Export alone.
> Enterprise-scale hourly granularity requires Azure Monitor Metrics, not the billing export.

---

### Resource

| Column | Distinct values | Meaning | Example |
|---|---|---|---|
| `resource_id` | One per resource | Full ARM resource ID — globally unique path to the resource including subscription, resource group, and resource name. Primary join key for tagging and rightsizing. | `/subscriptions/a1b2c3d4.../providers/Microsoft.Compute/virtualMachines/vm-prod-01` |
| `resource_name` | Many | Short display name of the resource, extracted from the tail of the ARM resource ID. More readable than `resource_id` for dashboards. | `vm-prod-01`, `data-lake-raw-prod` |
| `consumed_service` | `Microsoft.Compute`, `Microsoft.Storage`, `Microsoft.Sql`, `Microsoft.SharedInfra` | Azure resource provider namespace. Coarser than `service_name` — good for grouping all Azure Compute resources regardless of VM/AKS/Functions. | `Microsoft.Compute` |
| `product_name` | Many | Full product descriptor. More specific than `service_name`; less specific than `meter_name`. | `Virtual Machines DS Series Windows` |
| `service_name` | `Virtual Machines`, `Storage`, `SQL Database`, `Azure Monitor`, … | MeterCategory — the primary service grouping for cost reports. Maps to `service_category` in the mart. | `Virtual Machines` |
| `service_subcategory` | `DS Series`, `STANDARD`, `General Purpose`, … | MeterSubcategory — the tier or series within a service. | `D/DS Series` |
| `meter_name` | Many | The specific meter being billed. Identifies the exact resource type and pricing unit. | `D4s v3`, `LRS Snapshots`, `Standard SSD` |
| `meter_id` | Many (GUIDs) | Unique ID for the meter. Used to look up pricing in the Azure Retail Prices API. | `c6a6d61b-...` |
| `region` | `eastus`, `westeurope`, `southeastasia`, … | Resource location, normalized to lowercase with whitespace stripped. Azure uses varied formats in the raw export (e.g. `East US`, `eastus2`) — normalization makes grouping reliable. | `eastus` |
| `service_family` | `Compute`, `Storage`, `Databases`, `Management and Governance` | High-level grouping above `service_name`. Fewer distinct values — useful for executive-level pie charts. | `Compute` |
| `charge_type` | `Usage`, `UnusedReservation`, `UnusedSavingsPlan` | What kind of charge this row represents — critical for NEC computation. See full breakdown below. | `Usage` |
| `publisher_type` | `Azure`, `Marketplace` | Distinguishes first-party Azure services from third-party Marketplace products. Filter to `Azure` to exclude vendor spend from team attribution. | `Azure` |
| `vcpus` | `2`, `4`, `8`, `16`, NULL | vCPU count extracted from `AdditionalInfo` JSON. Populated for VM rows only; null for storage, SQL, and shared infra rows. Used for $/vCPU efficiency metrics. | `4` |

**`charge_type` values:**

| Value | What it means | Key columns populated |
|---|---|---|
| `Usage` | A resource ran and incurred cost for the day. If covered by RI/SP, `pricing_model` will be `Reservation` or `SavingsPlan` and cost is already amortized. | `list_cost`, `usage_amount`, `unit_price`, `effective_price`, `payg_price` |
| `UnusedReservation` | An RI had idle capacity for part or all of the day — no VM ran under it, but you still owe the commitment fee. `usage_amount = 0`, `list_cost > 0`. | `list_cost` (waste cost), `benefit_id`, `benefit_name` |
| `UnusedSavingsPlan` | A Savings Plan had unspent commitment for part of the day — actual spend fell below the hourly commitment floor. | `list_cost` (waste cost), `benefit_id`, `benefit_name` |

---

### Usage

| Column | Meaning | Example |
|---|---|---|
| `usage_amount` | Quantity consumed for the day. For VMs = hours the VM ran (up to 24). For storage = GB stored. **Zero on UnusedReservation / UnusedSavingsPlan rows.** | `24.0` (full day VM), `920.0` (GB stored) |
| `usage_unit` | Unit of `usage_amount`. | `1 Hour`, `1 GB/Month`, `10K` |
| `unit_price` | Published list price per unit before any commitment discounts. Reflects on-demand (PAYG) pricing. | `0.1920` ($/hour for D4s v3 on-demand) |
| `currency` | Billing currency for this account. | `USD` |

---

### Cost

| Column | Meaning | Example |
|---|---|---|
| `list_cost` | `CostInBillingCurrency` — the actual amortized cost for this row. For `Usage` rows with a commitment: this is the amortized RI/SP cost, NOT the on-demand price. For `UnusedReservation` rows: this is the waste cost. The name `list_cost` is a simplification — see note below. | `10.00` (daily RI amortized), `2.40` (waste) |
| `pricing_model` | `OnDemand`, `Reservation`, `SavingsPlan` | Discount model applied to this row. More reliable than inferring from `benefit_name` string matching. Null for untagged shared infra rows where no discount applies. | `Reservation` |
| `effective_price` | Amortized per-unit cost after commitment discount. `list_cost / usage_amount` for usage rows. Null/zero for waste rows. **The correct per-unit cost for chargeback.** | `0.0417` ($/hour after RI discount) |
| `payg_price` | Pay-As-You-Go (on-demand) per-unit price — what you would pay with no commitment at all. Divide by `effective_price` to derive the discount multiplier. | `0.1920` ($/hour on-demand) |

> **`list_cost` naming note:** Despite the column name, this is **not** the list/on-demand price.
> It is the actual amortized cost recorded in the billing export. Azure exports two views: *actual*
> (shows $0 on RI-covered days, large charge when RI purchased) and *amortized* (spreads the RI
> cost daily). We use the **amortized** view — `list_cost` is the amortized daily cost.
> The true on-demand equivalent is `payg_price × usage_amount`.

---

### Commitment / RI / SP

| Column | Distinct values | Meaning | Example |
|---|---|---|---|
| `benefit_id` | One per RI or SP | UUID of the specific reservation or savings plan covering this row. Links usage rows back to the commitment purchase. NULL for on-demand rows. | `7f3a1234-...` |
| `benefit_name` | One per RI or SP | Human-readable name of the reservation or savings plan. Used for commitment inventory reporting. NULL for on-demand rows. | `Platform VM Reserved - 1Yr` |
| `has_commitment` | `true` / `false` | Derived flag — `true` when `benefit_name` is non-null. Quick filter for commitment-covered rows without inspecting `pricing_model`. | `true` |
| `is_commitment_waste` | `true` / `false` | Derived flag — `true` when `charge_type` is `UnusedReservation` or `UnusedSavingsPlan`. These rows cost money but delivered zero compute. Primary signal for commitment waste dashboards. | `true` on idle RI rows |

---

### Tags

| Column | Distinct values | Meaning | Example |
|---|---|---|---|
| `tag_team` | `platform`, `data-eng`, `frontend`, `backend`, `ml`, NULL | Owning team. NULL = untagged = cost cannot be directly attributed. Resources in the shared-infra subscription are also untagged and get fanned out across all teams in `int_azure_nec`. | `data-eng` |
| `tag_environment` | `prod`, `staging`, `dev`, NULL | Deployment environment. Used to separate production spend from lower environments. | `prod` |
| `tag_cost_center` | `cc100`–`cc500`, NULL | Finance cost center code. Maps directly to budget lines. | `cc200` (data-eng) |

> **Azure Tags format:** Tags are stored as a JSON blob in the raw export (`{"team": "platform", "environment": "prod", ...}`).
> `stg_azure_cost` extracts them with `json_extract_string(Tags, '$.team')`.
> This differs from AWS (flat columns per tag) and GCP (list of `{key, value}` dicts).

---

### Derived Flags

| Column | Values | Meaning |
|---|---|---|
| `is_tagged` | `true` / `false` | `true` when `tag_team` is non-null. Rows with `is_tagged = false` include: truly untagged resources (attribution gap), shared-infra resources (intentionally untagged, spread by subscription mapping), and `UnusedReservation` / `UnusedSavingsPlan` waste rows (never tagged). |
| `cloud_provider` | `'azure'` | Literal stamp added so `fct_unified_billing` can filter and group by cloud after the UNION ALL. |

---

## Commitment Cost Mechanics

### The Core Difference from AWS

Azure Cost Management offers two export views — **actual** and **amortized**.
This pipeline uses the **amortized** view.

| Export type | RI day (VM ran) | RI day (VM idle) | When RI purchased |
|---|---|---|---|
| **Actual** | `list_cost = $0` (RI covered it) | No row | Large one-time charge row |
| **Amortized** | `list_cost = $10` (daily slice) | `UnusedReservation` row with `list_cost = waste` | No separate purchase row |

The amortized view is correct for per-team NEC calculations because every day has a
cost attached to a resource. The actual view makes RI-covered days look free, which
distorts team attribution.

---

### Reserved Instances — How $3,650/year flows through Azure

$3,650/year = **$10/day = $0.417/hour amortized**

#### Daily row — VM ran (`charge_type = 'Usage'`)

One row per day the VM ran under the reservation.

| Column | Value | Why |
|---|---|---|
| `charge_type` | `Usage` | Resource was actually used |
| `pricing_model` | `Reservation` | Covered by an RI |
| `list_cost` | **~$10.00** | Amortized daily slice of the $3,650 annual commitment |
| `usage_amount` | `24.0` | Hours run (full day) |
| `effective_price` | **~$0.417** | Amortized per-hour cost ($10 / 24 hrs) |
| `payg_price` | **~$0.192** | What D4s v3 costs on-demand |
| `benefit_name` | `Platform VM Reserved - 1Yr` | The RI that covered it |
| `is_commitment_waste` | `false` | Resource ran — no waste |

> **Apparent anomaly:** `effective_price ($0.417) > payg_price ($0.192)`.
> This happens because `payg_price` is the hourly OD rate, but `effective_price` is
> the *amortized* cost of an annual upfront commitment spread per hour. The RI is still
> cheaper in total — the discount shows up in the *annual* commitment cost vs 12 months
> of OD spend, not in a single day's effective vs payg comparison.
> Discount % = `(payg_price - effective_price) / payg_price` is only meaningful when
> both are computed on the same basis.

#### Daily row — RI idle (`charge_type = 'UnusedReservation'`)

One row per day the RI had idle capacity.

| Column | Value | Why |
|---|---|---|
| `charge_type` | `UnusedReservation` | Capacity reserved but nothing ran |
| `pricing_model` | `Reservation` | Still under the reservation |
| `list_cost` | **waste fraction × $10** | You owe the amortized cost even though nothing ran |
| `usage_amount` | **$0.00** | No actual consumption |
| `effective_price` | `null` / `0` | No usage to price |
| `is_commitment_waste` | **`true`** | This row is pure waste |

The sum of `list_cost` across all `UnusedReservation` rows for a month equals
the total wasted RI spend for that month.

---

### Savings Plans — How $3,650/year flows through Azure

$3,650/year = **$10/day commitment floor** — similar to AWS Compute Savings Plans.

#### Daily row — resource covered (`charge_type = 'Usage'`)

| Column | Value | Why |
|---|---|---|
| `charge_type` | `Usage` | Resource was used |
| `pricing_model` | `SavingsPlan` | Covered by an SP |
| `list_cost` | ~SP-adjusted daily cost | Amortized SP rate × hours run |
| `effective_price` | SP-adjusted per-unit rate | Discounted vs PAYG |
| `payg_price` | On-demand per-unit rate | Baseline for savings calc |
| `benefit_name` | `Compute Savings Plan - 1Yr` | The SP covering it |
| `is_commitment_waste` | `false` | Resource ran |

#### Daily row — SP commitment unspent (`charge_type = 'UnusedSavingsPlan'`)

Generated when actual spend for the day is below the daily commitment floor.

| Column | Value | Why |
|---|---|---|
| `charge_type` | `UnusedSavingsPlan` | Committed more than used |
| `list_cost` | gap × daily rate | Cost of the unspent commitment slice |
| `usage_amount` | `0.00` | No additional consumption |
| `is_commitment_waste` | **`true`** | Pure waste |

---

### RI vs SP Side-by-Side (Azure)

| Aspect | Reserved Instance | Savings Plan |
|---|---|---|
| Scope | Specific VM size + region | Any compute in the enrolled scope |
| `pricing_model` on usage rows | `Reservation` | `SavingsPlan` |
| Waste row `charge_type` | `UnusedReservation` | `UnusedSavingsPlan` |
| `usage_amount` on waste rows | `0` | `0` |
| Identify commitment | `benefit_name` contains `Reserved` | `benefit_name` contains `Savings Plan` |
| Cost already amortized? | Yes — in amortized export | Yes |
| Hourly or daily rows? | Daily (one row per day) | Daily (one row per day) |

---

### How `int_azure_nec` Resolves These Into NEC

The intermediate model computes three cost metrics from `billed_cost` and the `is_commitment_waste` flag:

```
nec_used  = billed_cost   for rows where usage_amount > 0  (ChargeType = Usage)
nec_waste = billed_cost   for UnusedReservation and UnusedSavingsPlan rows

nec = nec_used            (NEC excludes waste — waste surfaced separately)

effective_unit_price = billed_cost / usage_amount   (null for waste rows where usage_amount = 0)
```

Where:

- `billed_cost` = `CostInBillingCurrency` = amortized actual paid cost (NOT the on-demand retail price)
- `list_cost` (mart column) = `payg_price × quantity` = on-demand baseline used for savings comparison

All downstream models use `nec` for cost roll-ups and `nec_waste` for commitment utilisation.

---

### Shared Cost Spreading (`int_azure_nec`)

Azure does not perform cross-team cost spreading natively. The intermediate model handles two cases:

**Case 1 — Shared-infra subscription (no team tag by design)**

Resources in the `a1b2c3d4-9999-...-000000000099` subscription (Azure Monitor, Networking,
API Management, Key Vault, Storage) are never tagged with a team — they serve all teams equally.
`int_azure_nec` fans each row out into N copies (one per benefiting team):

```
allocated_nec    = nec_used / 5        (5 teams sharing equally)
allocated_team   = each team in turn
is_shared_cost   = true
```

**Case 2 — Untagged resources in team-owned subscriptions**

Resources in a team's subscription with no `tag_team` get spread across all teams mapped
to that subscription in the `sub_teams` CTE:

```sql
-- sub_teams maps subscription → benefiting teams
-- team-owned subscription: 1 team  → allocated_nec = full nec_used
-- shared subscription:     5 teams → allocated_nec = nec_used / 5
```

Tagged rows pass through unchanged: `allocated_team = tag_team`, `allocated_nec = nec_used`, `is_shared_cost = false`.

---

### Savings & Waste Metrics

| Metric | Formula using staging / intermediate columns |
|---|---|
| RI/SP savings vs PAYG | `(payg_price - effective_price) × usage_amount` (Usage rows only) |
| Total savings | `sum(payg_price × usage_amount) - sum(list_cost)` where not waste |
| Commitment waste cost | `sum(list_cost)` where `is_commitment_waste = true` |
| Waste % of commitment | `sum(nec_waste) / (sum(nec_used) + sum(nec_waste))` |
| RI utilisation % | `sum(usage_amount where pricing_model = 'Reservation') / total_reserved_hours` |
| Effective discount % | `1 - (effective_price / payg_price)` per row (VM rows only) |
| $/vCPU-day | `nec_used / vcpus` (VM rows only; null for storage/SQL) |
| Untagged cost | `sum(nec_used) where is_tagged = false` |
| Shared cost per team | `sum(allocated_nec) where is_shared_cost = true` |

---

### Common Mistakes

| Mistake | Impact | Fix |
|---|---|---|
| Using the **actual** export instead of amortized | RI-covered days show `$0` — team cost is understated; one-time purchase row inflates the purchase month | Always use the **amortized** export |
| Filtering to `charge_type = 'Usage'` only | `UnusedReservation` / `UnusedSavingsPlan` waste rows are invisible — utilisation % breaks | Filter to `ChargeType in ('Usage', 'UnusedReservation', 'UnusedSavingsPlan')` |
| Treating `list_cost` as the on-demand price | `list_cost` is the amortized cost — for PAYG equivalent use `payg_price × usage_amount` | Use `payg_price × usage_amount` for savings baseline |
| Comparing `effective_price > payg_price` and calling it a loss | Amortized annual cost spread hourly is often higher than the hourly OD rate for a single day — savings are realised over the full year | Compare annual commitment total vs 12 months of PAYG, not single-day rates |
| Attributing shared-infra costs to "untagged" | Shared-infra resources are intentionally untagged; attributing them to a catch-all "untagged" bucket overstates untagged coverage gaps | Use subscription mapping (`sub_teams` CTE) to spread shared costs, not heuristic attribution |
| Summing `list_cost` across all rows for a team | Waste rows (`UnusedReservation`) are included — inflates the team's cost | Sum `nec_used` (which excludes waste) for team chargeback |
| Using `benefit_name` string matching for discount type | Inconsistent naming across RI/SP products | Use `pricing_model` column directly — it's a clean enum |
