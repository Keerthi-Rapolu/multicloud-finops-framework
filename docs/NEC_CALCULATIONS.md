# NEC (Net Effective Cost) — How It Is Calculated

**Net Effective Cost** is the true amortized cost of cloud resources after applying
Reserved Instance (RI), Savings Plan (SP), and Committed Use Discount (CUD) pricing.
It separates *used* cost from *wasted* commitment cost, making cross-cloud spend
comparable on a single normalized basis.

---

## Core Concepts

| Term | Meaning |
|---|---|
| `list_cost` | Full on-demand / retail price, no discounts applied |
| `nec_used` | Actual effective cost of resources that ran (discounts applied) |
| `nec_waste` | Commitment cost paid for capacity that was never used |
| `nec` | Alias for `nec_used` — the primary FinOps metric |
| `savings` | `list_cost − nec` — how much commitments saved vs on-demand |
| `discount_type` | `ri` \| `sp` \| `on_demand` — normalized across all clouds |

---

## Per-Cloud Formulas

### AWS

Source: [int_aws_nec.sql](../dbt_project/models/intermediate/int_aws_nec.sql)

AWS Cost and Usage Report (CUR) has a `line_item_type` field that drives all NEC logic.

| `line_item_type` | `discount_type` | `nec_used` formula | `nec_waste` formula |
|---|---|---|---|
| `Usage` | `on_demand` | `unblended_cost` | `0` |
| `DiscountedUsage` | `ri` | `reservation_effective_cost` | `0` |
| `SavingsPlanCoveredUsage` | `sp` | `savings_plan_effective_cost` | `0` |
| `RIFee` | `ri` | `0` | `reservation_unused_upfront_fee + reservation_unused_recurring_fee` |
| `SavingsPlanRecurringFee` | `sp` | `0` | `savings_plan_recurring_commitment − savings_plan_used_commitment` |

**Why not just use `unblended_cost`?**

- RI-covered hours: `unblended_cost = $0` — the instance looks free, hiding the real RI cost.
- SP-covered hours: `unblended_cost = on-demand rate` — the discount is invisible, overstating cost.

`reservation_effective_cost` and `savings_plan_effective_cost` are the amortized per-hour
rates that reflect what you actually paid.

**`RIFee` / `SavingsPlanRecurringFee` rows are kept** (not filtered out) so waste is visible,
but their `nec_used = 0` prevents double-counting with the per-hour effective cost rows.

**`SavingsPlanNegation` rows are excluded** in staging — they are negative offsets that would
double-subtract discounts already reflected in `savings_plan_effective_cost`.

#### AWS Examples

**Example 1 — On-demand EC2 (`Usage`)**
```
unblended_cost = $10.00
→ nec_used  = $10.00   (you paid full OD price)
→ nec_waste = $0.00
→ nec       = $10.00
```

**Example 2 — RI-covered EC2 (`DiscountedUsage`)**
```
unblended_cost             = $0.00  (RI makes it look free in raw billing)
reservation_effective_cost = $6.00  (amortized RI rate for this hour)
→ nec_used  = $6.00   (true cost of this hour under the RI)
→ nec_waste = $0.00
→ nec       = $6.00
savings vs OD = $10.00 list_cost − $6.00 nec = $4.00 (40%)
```

**Example 3 — Idle RI (`RIFee`)**
```
reservation_unused_upfront_fee    = $1.50
reservation_unused_recurring_fee  = $0.50
→ nec_used  = $0.00   (no compute ran on this RI hour)
→ nec_waste = $2.00   (the $2 you paid for capacity no one used)
→ nec       = $0.00
```

**Example 4 — Savings Plan coverage (`SavingsPlanCoveredUsage`)**
```
savings_plan_effective_cost = $7.00  (SP rate applied to this usage)
list_cost (on_demand_cost)  = $10.00
→ nec_used  = $7.00
→ nec_waste = $0.00
→ nec       = $7.00
savings = $3.00 (30%)
```

**Example 5 — Unused SP commitment (`SavingsPlanRecurringFee`)**
```
savings_plan_recurring_commitment = $100.00  (hourly SP spend commitment)
savings_plan_used_commitment      =  $80.00  (only $80 of compute ran)
→ nec_used  = $0.00
→ nec_waste = $20.00  ($20 paid for unused SP capacity this hour)
```

---

### Azure

Source: [int_azure_nec.sql](../dbt_project/models/intermediate/int_azure_nec.sql)

Azure uses the **amortized cost export** (`CostInBillingCurrency`) where reservation
and SP charges are spread hourly rather than charged up-front. The staging model
flags rows with `is_commitment_waste = true` for `ChargeType IN ('UnusedReservation',
'UnusedSavingsPlan')`.

| Row type | `discount_type` | `nec_used` | `nec_waste` |
|---|---|---|---|
| Normal usage (tagged/untagged) | `ri` / `sp` / `on_demand` | `billed_cost` | `0` |
| `UnusedReservation` / `UnusedSavingsPlan` | `ri` / `sp` | `0` | `billed_cost` |

`list_cost` for Azure = `retail_cost` (`payg_price × usage_amount`) — the true OD baseline,
consistent with how AWS and GCP expose it.

`effective_unit_price = nec_used / usage_amount` — the real per-unit cost after discounts.
Waste rows get `null` because `usage_amount = 0` (no compute ran).

#### Azure Shared-Cost Spreading

Resources in the **shared-infra subscription** (`9999…0099`) carry no team tag. Rather than
attributing them to `NULL`, the model fans each row out into one copy per benefiting team,
dividing cost by the number of teams so totals remain correct.

**Subscription → team mapping:**
- `0001…0001` → `platform` (1 team, no split)
- `0002…0002` → `data-eng` (1 team, no split)
- `0003…0003` → `frontend`, `backend`, `ml` (3-way split)
- `9999…0099` → all 5 teams (5-way split)

For untagged rows from unknown subscriptions: `allocated_team = NULL` (left join — rows
surface rather than disappear).

#### Azure Examples

**Example 1 — RI-covered VM (`Reservation`, normal usage)**
```
billed_cost  = $6.00   (amortized RI rate from amortized export)
retail_cost  = $10.00  (what the VM would cost on PAYG)
is_commitment_waste = false
→ nec_used          = $6.00
→ nec_waste         = $0.00
→ nec               = $6.00
→ effective_unit_price = $6.00 / usage_amount
→ list_cost         = $10.00
→ savings           = $4.00 (40%)
```

**Example 2 — Unused reservation**
```
billed_cost = $2.00   (amortized cost of the unused slot)
is_commitment_waste = true
→ nec_used  = $0.00
→ nec_waste = $2.00
→ nec       = $0.00
```

**Example 3 — Untagged VM in shared subscription (`9999…0099`)**
```
billed_cost = $50.00
n_teams     = 5  (platform, data-eng, frontend, backend, ml)
→ 5 output rows created, each with:
   nec_used      = $10.00   ($50 / 5)
   allocated_nec = $10.00
   allocated_team = <each team>
   is_shared_cost = true
→ cloud-level sum: 5 × $10 = $50 ✓  (no double-counting)
```

---

### GCP

Source: [int_gcp_nec.sql](../dbt_project/models/intermediate/int_gcp_nec.sql)

GCP stores discounts as **negative credit amounts** in a JSON array on each line.
Staging sums them into `total_credit_amount` (always ≤ 0).

```
nec_used = list_cost + total_credit_amount
         = list_cost − |credits|
```

`GREATEST(..., 0)` clamps the result — free-tier or promotional credits can push
the effective cost below zero, which is not meaningful for FinOps reporting.

CUD (Committed Use Discount) maps to `discount_type = 'ri'` because it is a
fixed-term commitment, analogous to an AWS RI. SUD (Sustained Use Discount) is
automatic with no commitment, so it maps to `on_demand`.

Idle CUD capacity surfaces via `is_unused_reservation = true` rows:

| Row type | `nec_used` | `nec_waste` |
|---|---|---|
| Normal usage (with or without CUD/SUD credits) | `list_cost + total_credit_amount` | `0` |
| Unused CUD reservation (`is_unused_reservation = true`) | `0` | `list_cost` |

#### GCP Examples

**Example 1 — GCE instance with CUD credit**
```
list_cost            = $10.00
total_credit_amount  = -$3.00  (CUD discount, stored as negative)
→ nec_used  = $10.00 + (-$3.00) = $7.00
→ nec_waste = $0.00
→ nec       = $7.00
→ discount_type = 'ri'  (CUD is a fixed-term commitment)
→ savings   = $3.00 (30%)
```

**Example 2 — GCE instance with SUD credit (automatic discount)**
```
list_cost            = $10.00
total_credit_amount  = -$2.50  (SUD, automatic)
→ nec_used  = $7.50
→ nec_waste = $0.00
→ nec       = $7.50
→ discount_type = 'on_demand'  (no commitment made)
```

**Example 3 — Unused CUD slot**
```
list_cost              = $5.00  (on-demand price of the unused slot)
is_unused_reservation  = true
→ nec_used  = $0.00
→ nec_waste = $5.00
→ nec       = $0.00
```

**Example 4 — Free-tier storage (credits exceed list cost)**
```
list_cost            = $0.50
total_credit_amount  = -$0.80  (promo credit covers more than cost)
raw result           = -$0.30
→ GREATEST(-0.30, 0) → nec_used = $0.00  (clamped; negative NEC is not meaningful)
```

---

## Unified Mart (`fct_unified_billing`)

Source: [fct_unified_billing.sql](../dbt_project/models/marts/fct_unified_billing.sql)

All three intermediate models are UNION ALL'd into a single fact table with a
consistent schema. Key cross-cloud normalizations:

| Column | AWS source | Azure source | GCP source |
|---|---|---|---|
| `list_cost` | `on_demand_cost` | `retail_cost` | `list_cost` |
| `nec` | `nec_used` | `nec_used` | `nec_used` |
| `allocated_team` | `tag_team` (no spreading) | `allocated_team` (after fan-out) | `tag_team` (no spreading) |
| `is_shared_cost` | `false` | `true` when fan-out occurred | `false` |
| `is_commitment_waste` | derived from `line_item_type` | from staging flag | `is_unused_reservation` |

`service_category` is normalized to `Compute | Storage | Database | Analytics | Platform | Other`
using a `CASE` block keyed on `service_name` per cloud.

---

## Python Aggregation Layer

Source: [allocation/nec_model.py](../allocation/nec_model.py)

The Python module reads `fct_unified_billing` from DuckDB and exposes pre-built aggregations.
It never re-derives NEC — all formulas live in the dbt models.

| Function | What it returns |
|---|---|
| `nec_by_cloud(df)` | Total NEC, list cost, waste, savings % by cloud |
| `nec_by_team(df)` | Per-team NEC using `allocated_nec` (reflects Azure fan-out) |
| `nec_by_service_category(df)` | NEC by service category and cloud |
| `nec_trend(df, freq)` | Daily / weekly / monthly NEC trend — rows with null `usage_date` are dropped before aggregation (GCP rows can have null `usage_start_time`) |
| `commitment_utilization(df)` | `nec_used / (nec_used + nec_waste)` by cloud and discount type |
| `savings_vs_on_demand(df)` | `list_cost − nec_used` by cloud and discount type |
| `commitment_waste_detail(df)` | Individual rows where `is_commitment_waste = true` |
| `effective_unit_price_summary(df)` | Avg effective vs list price per service category |

### Commitment Utilization Formula

```
utilization_pct = nec_used / (nec_used + nec_waste) * 100
```

Rows with `discount_type IN ('ri', 'sp')` only. A utilization of 80% means 20% of
your committed capacity was unused (waste).

### Savings Formula

```
savings     = list_cost − nec
savings_pct = savings / list_cost * 100
```

### NECReport — Full Example

```python
from allocation.nec_model import build_nec_report

report = build_nec_report(billing_month="2026-03")
print(report.summary())

# NEC Report — 2026-03
#   List cost :  $ 1,200,000.00
#   NEC (used):  $   840,000.00
#   Savings   :  $   360,000.00  (30.0%)
#
# By cloud:
#   aws    list=$  500,000  nec=$  340,000  waste=$  12,000  savings=32.0%
#   azure  list=$  400,000  nec=$  280,000  waste=$   8,000  savings=30.0%
#   gcp    list=$  300,000  nec=$  220,000  waste=$   5,000  savings=26.7%

print(report.commitment_util)
#  cloud_provider discount_type  nec_used  nec_waste  utilization_pct
#             aws            ri    200000      12000             94.3
#           azure            ri    150000       8000             94.9
#             gcp            ri    100000       5000             95.2
```

---

## Summary: NEC Formula by Cloud

```
AWS   nec = reservation_effective_cost  (RI)
          | savings_plan_effective_cost  (SP)
          | unblended_cost               (OD)

Azure nec = billed_cost                 (amortized export, all charge types except Unused*)
            0                           (UnusedReservation / UnusedSavingsPlan → goes to waste)

GCP   nec = GREATEST(list_cost + total_credit_amount, 0)
            0                           (unused CUD reservation → goes to waste)

All   nec_waste = idle commitment cost  (RI fee not covered by usage, unused SP/CUD slots)
      savings   = list_cost − nec
```