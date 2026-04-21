# Multi-Cloud FinOps Cost Attribution Framework

**Authors:** Keerthi Rapolu & Rishika Naha | **April 2026**

A free, open-source framework for normalizing, allocating, and visualizing cloud costs across AWS, Azure, and GCP — without paid tooling or proprietary SaaS.

---

## What this project does

Modern enterprises run workloads across multiple cloud providers simultaneously. Each hyper-scaler uses a different billing schema, tagging convention, and discount model. This framework provides a reproducible pipeline that:

1. **Ingests** raw billing exports from AWS CUR, Azure Cost Management, and GCP Billing
2. **Normalizes** them to a Unified Cost Allocation Schema (CAS) via dbt + DuckDB
3. **Allocates** costs to teams using tag-based, shared-cost, and heuristic strategies
4. **Models Net Effective Cost (NEC)** — the true amortized cost after RI/SP/CUD discounts
5. **Visualizes** per-team, per-cloud, and per-service cost in a Streamlit dashboard

---

## Quick start

```bash
# Full pipeline + dashboard in one command
make demo

# Or run steps individually
make data       # generate synthetic billing data
make dbt        # run all dbt models (staging → intermediate → marts)
make test       # run unit tests
make dashboard  # launch the Streamlit dashboard

# Override month or scenario
make pipeline MONTH=2026-04 SCENARIO=untagged-heavy
```

---

## Architecture

```
AWS CUR / Azure Cost Export / GCP Billing Export
         ↓  load_synthetic.py  (generate → validate → land)
     data/raw/{cloud}/YYYY-MM/*.parquet
         ↓  dbt staging models
     stg_aws_cur / stg_azure_cost / stg_gcp_billing  (Bronze)
         ↓  dbt intermediate models
     int_aws_nec / int_azure_nec / int_gcp_nec  (Silver — NEC computed)
         ↓  dbt mart
     fct_unified_billing  (Gold — 31-column unified CAS)
         ↓  Python allocation layer + Streamlit
     Per-team / per-cloud cost reports + dashboard
```

---

## Documentation

| Doc | What it covers |
|---|---|
| [STAGING.md](STAGING.md) | Staging layer — what each dbt model does, columns, filters, and conventions |
| [NEC_CALCULATIONS.md](NEC_CALCULATIONS.md) | Net Effective Cost formulas per cloud with worked examples |
| [AWS_CUR_REFERENCE.md](AWS_CUR_REFERENCE.md) | Full AWS CUR column reference and RI/SP cost flow |
| [AZURE_COST_REFERENCE.md](AZURE_COST_REFERENCE.md) | Azure amortized export semantics, RI/SP rows, shared-cost spreading |
| [GCP_BILLING_REFERENCE.md](GCP_BILLING_REFERENCE.md) | GCP Detailed Usage Export — credits JSON, CUD/SUD mechanics, label format |
| [../DESIGN_DOCUMENT.md](../DESIGN_DOCUMENT.md) | Full architecture, CAS schema, module design, and task plan |
| [../PAPER_OUTLINE.md](../PAPER_OUTLINE.md) | Research paper outline and section responsibilities |

---

## Key concepts

### Net Effective Cost (NEC)
The true amortized cost after commitment discounts — what you actually paid, not what the invoice shows at OD rates or after RI coverage zeroes out hours.

```
AWS   nec = reservation_effective_cost  (RI-covered hours)
          | savings_plan_effective_cost  (SP-covered hours)
          | unblended_cost               (on-demand hours)

Azure nec = billed_cost  (amortized export — RI/SP spread daily)
            waste rows → nec_waste, not counted in nec

GCP   nec = GREATEST(list_cost + total_credit_amount, 0)
```

### Shared cost distribution
Unowned shared-infrastructure rows (networking, logging, security) are spread across teams using one of three configurable strategies: **proportional** (by direct spend), **even** (equal split), or **weighted** (by configured SLA weights).

### Unified Cost Allocation Schema (CAS)
A 31-column normalized schema that every cloud's billing data is mapped to. Key columns: `cloud_provider`, `billing_month`, `account_id`, `service_category`, `list_cost`, `nec`, `nec_used`, `nec_waste`, `discount_type`, `tag_team`, `allocated_team`, `allocated_nec`, `is_shared_cost`, `is_commitment_waste`.

---

## Technology stack

| Layer | Tool |
|---|---|
| Data transform | dbt Core + DuckDB |
| Processing | Python 3.11 + pandas |
| Orchestration | GitHub Actions |
| Dashboard | Streamlit |
| ML (optional) | scikit-learn |
| Docs | MkDocs + GitHub Pages |

All tools are free and run locally or in GitHub Actions free tier.
