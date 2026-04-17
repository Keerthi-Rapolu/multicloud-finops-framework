# Multi-Cloud FinOps Cost Attribution Framework
## Design Document v1.0

**Project:** Research Paper + GitHub Demo  
**Authors:** Keerthi Rapolu + Rishika Naha 
**Date:** April 2026  
**Status:** Draft

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Project Goals](#2-project-goals)
3. [Architecture Overview](#3-architecture-overview)
4. [Data Architecture — 4-Layer Pipeline](#4-data-architecture--4-layer-pipeline)
5. [Unified Cost Allocation Schema (CAS)](#5-unified-cost-allocation-schema-cas)
6. [Core Modules](#6-core-modules)
7. [Technology Stack](#7-technology-stack)
8. [Local Development Setup](#8-local-development-setup)
9. [Repository Structure](#9-repository-structure)
10. [Research Paper Outline](#10-research-paper-outline)
11. [Work Division](#11-work-division)
12. [Task Plan & Milestones](#12-task-plan--milestones)
13. [Constraints & Guardrails](#13-constraints--guardrails)

---

## 1. Problem Statement

Modern enterprises run workloads across AWS, Azure, and GCP simultaneously. Each hyper-scaler uses a different billing schema, tagging convention, and discount model (Reserved Instances, Savings Plans, Committed Use Discounts). Finance and engineering teams lack a unified, accurate way to attribute costs to business units, teams, or products — leading to opaque cloud provider spend, poor accountability, and budget overruns.

### Pain Points

| Pain Point | Description |
|---|---|
| Schema fragmentation | AWS CUR, Azure Cost Export, and GCP Billing Export use incompatible column names, granularities, and discount representations across hyper-scalers |
| Untagged resources | 30–50% of cloud provider resources lack proper cost allocation tags, making direct attribution impossible |
| Shared cost distortion | Shared services (networking, logging, security) inflate per-team costs without principled distribution logic |
| RI/SP amortization | Reservation discounts distort net effective cost per team if not properly amortized |
| No open-source standard | Existing tools (CloudHealth, Apptio) are closed-source and expensive |

---

## 2. Project Goals

### Primary Goal
Build a **free, open-source, cloud-agnostic framework** that:
- Ingests raw billing data from AWS, Azure, and GCP
- Normalizes it to a unified schema
- Allocates shared costs using configurable strategies
- Handles untagged resources via heuristics
- Models Net Effective Cost (NEC) with RI/SP amortization
- Produces per-team/per-product cost reports

### Secondary Goal
Publish a research paper documenting the framework, design decisions, and evaluation results.

### Constraints
- **100% free** — no paid APIs, no paid SaaS, no paid cloud compute
- All processing runs locally or in GitHub Actions free tier
- Synthetic/anonymized data only in the public repo

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                             │
│  ┌───────────┐    ┌───────────────┐    ┌──────────────────┐    │
│  │  AWS CUR  │    │  Azure Cost   │    │  GCP Billing     │    │
│  │  (S3)     │    │  Export(Blob) │    │  Export (BQ)     │    │
│  └─────┬─────┘    └───────┬───────┘    └────────┬─────────┘    │
└────────┼──────────────────┼─────────────────────┼──────────────┘
         │                  │                      │
         ▼                  ▼                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                   LAYER 1: INGESTION (Raw)                      │
│          Python scripts — pull & store as Parquet/CSV           │
│                    Landing zone: local / S3                     │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│              LAYER 2: NORMALIZATION (Bronze → Silver)           │
│   dbt models — cloud-specific normalization (AWS/Azure/GCP)     │
│                       DuckDB engine                             │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│              LAYER 3: ALLOCATION ENGINE (Silver → Gold)         │
│  • Tag-based direct allocation                                  │
│  • Account/project-based allocation                             │
│  • Shared cost distribution (proportional / even / weighted)   │
│  • Untagged attribution (heuristics + optional ML)              │
│  • NEC modeling (RI/SP amortization)                            │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                   LAYER 4: REPORTING (Gold)                     │
│       Streamlit dashboard — per-team, per-cloud, NEC trends     │
│              CSV export / GitHub Pages static demo              │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Data Architecture — 4-Layer Pipeline

### Layer 1 — Ingestion (Raw)

**Purpose:** Pull billing exports from each cloud into a common landing zone.

| Cloud | Source | Export Type | Granularity | Format | Free Tier |
|---|---|---|---|---|---|
| AWS | Cost and Usage Report (CUR) | Standard | Hourly per resource | CSV / Parquet | Free to export |
| Azure | Cost Management Export | Amortized | Daily per resource | CSV | Free to export |
| GCP | Cloud Billing — Detailed Usage Export | Detailed (BigQuery) | Hourly per resource | BigQuery table | 1 TB/mo free |

> **GCP note:** Standard Export is free but daily-per-project only — insufficient for NEC calculations. Detailed Usage Export provides hourly per-resource records needed for accurate CUD/SUD amortization, and fits within BigQuery's 1 TB/month free tier at demo scale.

**Output:** Raw files stored in `/data/raw/{cloud}/YYYY-MM/`

**Notes:**
- For the demo, synthetic CSVs are used instead of real billing data
- Schema versioning tracked in `/ingestion/schemas/`

---

### Synthetic Data Pipeline (`load_synthetic.py`)

All synthetic data is managed through a single entry point that generates, validates, and lands data in one command.

**Run:**
```bash
python load_synthetic.py                        # current month, default config
python load_synthetic.py --month 2026-03        # specific month
python load_synthetic.py --month 2026-03 --force  # skip overwrite confirmation
```

**Three-stage flow:**
1. **Generate** — creates realistic CSV files in `data/synthetic/{cloud}/`
2. **Validate** — checks required columns, row count, date range, cost integrity; aborts if any check fails
3. **Land** — writes raw Parquet to `data/raw/{cloud}/YYYY-MM/`; deletes existing month data before re-landing

If validation fails, raw data is left untouched and the pipeline exits with code 1.

**Configurable parameters:**

| Flag | What it controls | Default |
|---|---|---|
| `--scenario` | Named preset (see below) | — |
| `--untagged-pct` | Fraction of rows with no cost-allocation tags (0.0–1.0) | 0.15 |
| `--ri-pct` | Fraction of compute covered by RI / CUD | 0.20 |
| `--sp-pct` | Fraction of compute covered by Savings Plans / SUD | 0.25 |
| `--sample-hours` | Hours sampled per resource (1–720; 72=dev, 720=full month) | 72 |

Individual flags override scenario values when combined.

**Named scenarios (`scripts/config.py`):**

| Scenario | untagged | RI | SP | Use case |
|---|---|---|---|---|
| `normal` | 15% | 20% | 15% | Default development run |
| `untagged-heavy` | 55% | 20% | 15% | Test untagged attribution logic |
| `ri-heavy` | 15% | 60% | 10% | Test RI amortization |
| `sp-heavy` | 15% | 10% | 60% | Test Savings Plan logic |
| `full-month` | 15% | 20% | 15% | Full 720-hour realistic volume |
| `full-month-untagged` | 55% | 20% | 15% | Full volume with untagged stress test |

```bash
# Examples
python load_synthetic.py --scenario ri-heavy --month 2026-03
python load_synthetic.py --scenario normal --untagged-pct 0.08 --ri-pct 0.35 --sp-pct 0.25
python load_synthetic.py --scenario full-month --force
```

**Synthetic data realism:**
- **AWS**: hourly grain, correct DiscountedUsage / SavingsPlanCoveredUsage line item types, `UnblendedCost=0` on RI rows with `reservation/EffectiveCost` populated
- **Azure**: daily grain, amortized view, `BenefitName` populated for RI/SP rows, Tags as JSON blob
- **GCP**: hourly grain for Compute/Cloud SQL, daily for GCS storage / BQ storage, CUD/SUD credits as list-of-dicts matching real BigQuery export structure

---

### Layer 2 — Normalization (Bronze → Silver)

**Purpose:** Normalize each hyper-scaler's proprietary billing schema into cloud-specific intermediate models. NEC calculations are performed separately per cloud provider at this stage — unification into the CAS happens in the Gold layer.

This is the **core intellectual contribution** of the paper — no open-source tool documents this mapping systematically.

**Tool:** dbt Core + DuckDB (both free, run locally)

**dbt models:**
```
models/
├── staging/
│   ├── stg_aws_cur.sql          # AWS CUR → AWS normalized fields
│   ├── stg_azure_cost.sql       # Azure Cost Export → Azure normalized fields
│   └── stg_gcp_billing.sql      # GCP BigQuery export → GCP normalized fields
├── intermediate/
│   ├── int_aws_nec.sql          # AWS NEC / RI amortization
│   ├── int_azure_nec.sql        # Azure NEC / reservation amortization
│   └── int_gcp_nec.sql          # GCP NEC / CUD amortization
└── marts/
    └── fct_unified_billing.sql  # UNION ALL → unified CAS schema (Gold)
```

---

### Layer 3 — Allocation Engine (Silver → Gold)

**Purpose:** Apply cost allocation strategies and produce attributed cost per team/product.

**Sub-modules:**

| Module | File | Owner |
|---|---|---|
| Tag-based allocation | `allocation/tag_allocator.py` | Rishika Naha |
| Shared cost distribution | `allocation/shared_cost.py` | Keerthi Rapolu |
| NEC / RI amortization | `allocation/nec_model.py` | Keerthi Rapolu |
| Untagged heuristics | `allocation/untagged_heuristic.py` | Rishika Naha |
| ML classifier (optional) | `allocation/untagged_ml.py` | Rishika Naha/Keerthi Rapolu |

---

### Layer 4 — Reporting (Gold)

**Purpose:** Visualize per-team, per-service, per-cloud cost with NEC and tagging coverage.

**Tool:** Streamlit (free tier deploy on Streamlit Cloud)

**Pages:**
1. Overview — total spend by cloud, trend chart
2. Team Allocation — per-team cost table, NEC vs list cost
3. Tagging Coverage — % tagged by cloud, service, account
4. Shared Cost — distribution breakdown
5. Untagged Resources — heuristic attribution confidence

---

## 5. Unified Cost Allocation Schema (CAS)

This is the normalized schema every cloud's data maps to. Agree on this before writing any code.

```sql
CREATE TABLE unified_billing (
    -- Identity
    record_id           VARCHAR,        -- synthetic unique ID
    cloud_provider      VARCHAR,        -- 'aws' | 'azure' | 'gcp'
    billing_period      DATE,           -- first day of billing month
    usage_date          DATE,           -- actual usage date

    -- Resource
    resource_id         VARCHAR,        -- cloud-native resource identifier
    resource_name       VARCHAR,        -- human-readable name
    service_name        VARCHAR,        -- e.g. 'EC2', 'Azure VM', 'Compute Engine'
    service_category    VARCHAR,        -- 'compute' | 'storage' | 'network' | 'database' | 'other'
    region              VARCHAR,        -- normalized region name

    -- Organization
    account_id          VARCHAR,        -- AWS account / Azure subscription / GCP project
    account_name        VARCHAR,

    -- Tags (allocation keys)
    tag_team            VARCHAR,        -- from cost allocation tags
    tag_product         VARCHAR,
    tag_environment     VARCHAR,        -- 'prod' | 'staging' | 'dev'
    tag_cost_center     VARCHAR,
    is_tagged           BOOLEAN,        -- false = needs heuristic attribution

    -- Costs (all in USD)
    list_cost           DECIMAL(18,6),  -- on-demand / list price
    discount_amount     DECIMAL(18,6),  -- RI/SP/CUD savings
    net_effective_cost  DECIMAL(18,6),  -- list_cost - discount_amount (amortized)
    amortized_cost      DECIMAL(18,6),  -- upfront fees spread over usage period

    -- Allocation output (written by Layer 3)
    allocated_team      VARCHAR,        -- final attributed team (post-allocation)
    allocation_method   VARCHAR,        -- 'tag' | 'account' | 'heuristic' | 'ml' | 'shared'
    allocation_confidence DECIMAL(5,2), -- 0.0–1.0, for heuristic/ML methods

    -- Metadata
    ingestion_timestamp TIMESTAMP,
    source_file         VARCHAR
);
```

### Cloud Field Mappings

| CAS Field | AWS CUR Column | Azure Column | GCP Column |
|---|---|---|---|
| `resource_id` | `lineItem/ResourceId` | `ResourceId` | `resource.name` |
| `service_name` | `lineItem/ProductCode` | `ServiceName` | `service.description` |
| `account_id` | `lineItem/UsageAccountId` | `SubscriptionId` | `project.id` |
| `list_cost` | `lineItem/UnblendedCost` | `CostInBillingCurrency` | `cost` |
| `discount_amount` | `savingsPlan/SavingsPlanEffectiveCost` | `BenefitName` | `credits` |
| `tag_team` | `resourceTags/user:Team` | `Tags['team']` | `labels['team']` |
| `is_tagged` | derived | derived | derived |

---

## 6. Core Modules

### 6.1 NEC Modeling (`allocation/nec_model.py`)

Net Effective Cost accounts for Reserved Instance and Savings Plan amortization.

**Formula:**
```
NEC = (UpfrontFee / CommitmentHours) + RecurringFee + OnDemandRemainder
```

**Logic:**
1. Identify RI/SP line items in normalized data
2. Compute hourly amortized rate per commitment
3. Map commitment coverage to resource IDs
4. Apply per-resource NEC = amortized_rate × hours_used
5. Remainder (uncovered usage) billed at on-demand rate

**Why this matters:** Without NEC, a team that benefits from an RI purchased by a central finance team shows $0 compute cost — distorting accountability.

---

### 6.2 Shared Cost Distribution (`allocation/shared_cost.py`)

Three strategies, configurable per service:

| Strategy | When to use | Formula |
|---|---|---|
| `proportional` | Default — fair based on usage | `team_share = team_direct_spend / total_direct_spend` |
| `even` | Small teams, equal footing | `team_share = 1 / num_teams` |
| `weighted` | Contractual SLAs differ | `team_share = team_weight / sum(all_weights)` |

**Shared cost candidates:** VPC networking, CloudTrail/logging, Security Hub, shared databases, monitoring tools.

---

### 6.3 Untagged Attribution (`allocation/untagged_heuristic.py`)

Two-stage approach:

**Stage 1 — Heuristic rules (deterministic):**
```python
RULES = [
    # (pattern, field, assigned_team, confidence)
    (r"^prod-api-.*",       "resource_name", "platform",   0.90),
    (r"^data-pipeline-.*",  "resource_name", "data-eng",   0.90),
    (r".*-dev-.*",          "resource_name", "unknown",    0.70),
]
```

**Stage 2 — ML classifier (optional, `allocation/untagged_ml.py`):**
- Features: `service_name`, `service_category`, `account_id`, `resource_name_tokens`, `usage_pattern`
- Label: `tag_team` (from tagged resources as training data)
- Model: `sklearn.ensemble.RandomForestClassifier` (free, no infra)
- Training data: tagged resources from the same account

---

## 7. Technology Stack

### Selected Tools (all free)

| Layer | Tool | Why |
|---|---|---|
| Data transform | dbt Core + DuckDB | SQL-first, version-controlled, runs locally, no infra |
| Processing | Python 3.11 + pandas | Universal, sufficient for demo scale |
| Orchestration | GitHub Actions | Free 2000 min/mo, CI/CD + pipeline trigger |
| Dashboard | Streamlit Cloud | Free tier deploy, Python-native |
| ML (optional) | scikit-learn | Lightweight classifier, no GPU needed |
| Version control | GitHub | Repo + Actions + Pages, all free |
| Notebook demos | Google Colab | No setup, shareable, free GPU |
| Task tracking | GitHub Projects | Kanban, linked to Issues/PRs, unlimited free |
| Docs | MkDocs + GitHub Pages | Versioned with code, free deploy |

### Why NOT these tools

| Tool | Decision | Reason |
|---|---|---|
| PySpark | Not in demo | DuckDB is faster for < 50GB; mention as enterprise scale-out path in paper |
| LangGraph / LangChain | Not needed (yet) | No multi-agent workflow required; add in Phase 2 if NL query interface is added |
| Notion | Replaced by GitHub Projects | Block limits on free tier; GitHub Projects is unlimited and code-integrated |
| Airflow | Replaced by GitHub Actions | Zero infra overhead for demo-scale orchestration |
| Paid cloud compute | Not used | All processing local or GitHub Actions |

### VS Code + Claude Integration

You have Claude integrated in VS Code — use it for:
- Writing dbt SQL models
- Generating Python allocation logic from spec
- Writing paper sections from code comments
- Generating synthetic test billing data
- Reviewing normalization field mappings

> **Paper note:** Mention AI-assisted development in the methodology section. This is a real differentiator and aligns with modern data engineering practice.

---

## 8. Local Development Setup

### Querying DuckDB Interactively (VS Code)

All dbt models materialize into `finops.duckdb` at the repo root. To browse schemas and run ad-hoc SQL without leaving VS Code:

**Install two VS Code extensions:**
1. **SQLTools** (Matheus Teixeira) — base SQL client framework
2. **DuckDB Sql Tools** (Random Fractals Inc.) — DuckDB driver

**Connect:**
1. Click the database icon in the VS Code sidebar
2. Add New Connection → DuckDB
3. Database file: `c:\<path-to-repo>\multicloud-finops-framework\finops.duckdb`
4. Save → the schema tree appears with all materialized models

**Available schemas after `dbt run`:**

| Schema | Type | Contents |
|---|---|---|
| `main_staging` | Views | `stg_aws_cur`, `stg_azure_cost`, `stg_gcp_billing` |
| `main_intermediate` | Tables | `int_aws_nec`, `int_azure_nec`, `int_gcp_nec` |
| `main_marts` | Tables | `fct_unified_billing` |

> **Note:** Staging models are views — they read from raw Parquet on every query. Intermediate and marts are materialized tables stored in DuckDB.

**Useful queries:**
```sql
-- Row counts per cloud in unified table
SELECT cloud_provider, COUNT(*) as rows, ROUND(SUM(nec), 2) as total_nec
FROM main_marts.fct_unified_billing
GROUP BY cloud_provider;

-- Tagging coverage by cloud
SELECT cloud_provider,
       ROUND(AVG(CASE WHEN is_tagged THEN 1.0 ELSE 0.0 END) * 100, 1) as tagged_pct
FROM main_marts.fct_unified_billing
GROUP BY cloud_provider;

-- NEC vs list cost savings by discount type
SELECT cloud_provider, discount_type,
       ROUND(SUM(list_cost), 2) as list_cost,
       ROUND(SUM(nec), 2) as nec,
       ROUND(SUM(list_cost) - SUM(nec), 2) as savings
FROM main_marts.fct_unified_billing
GROUP BY 1, 2 ORDER BY 1, 2;
```

### Running the Full Pipeline

```bash
# 1. Generate synthetic data + land to raw
python load_synthetic.py --month 2026-03 --force

# 2. Run all dbt models (staging → intermediate → marts)
cd dbt_project
python -m dbt.cli.main run

# 3. Query results in VS Code via SQLTools or Python
python -c "
import duckdb
con = duckdb.connect('finops.duckdb')
print(con.execute('SELECT * FROM main_marts.fct_unified_billing LIMIT 10').df())
"
```

> Always run dbt from inside the `dbt_project/` directory — staging views use a relative path (`../data/raw/`) that resolves correctly only from there.

---

## 9. Repository Structure

```
multicloud-finops-framework/
│
├── .gitignore
├── README.md
├── DESIGN_DOCUMENT.md          ← this file
├── PAPER_OUTLINE.md
├── requirements.txt
├── pyproject.toml
├── mkdocs.yml
│
├── data/
│   ├── raw/                    # real billing exports — gitignored, never committed
│   │   ├── aws/
│   │   ├── azure/
│   │   └── gcp/
│   └── synthetic/              # generated test data — committed to repo
│       ├── aws/
│       ├── azure/
│       └── gcp/
│
├── load_synthetic.py           # single entry point: generate → validate → land raw
│
├── scripts/                    # synthetic data generators + shared config
│   ├── config.py               # GeneratorConfig dataclass + named SCENARIOS
│   ├── generate_aws_cur.py
│   ├── generate_azure_cost.py
│   └── generate_gcp_billing.py
│
├── ingestion/
│   ├── __init__.py
│   ├── aws_ingestor.py
│   ├── azure_ingestor.py
│   ├── gcp_ingestor.py
│   └── schemas/                # schema versioning per cloud
│       ├── aws_cur_schema.py
│       ├── azure_cost_schema.py
│       └── gcp_billing_schema.py
│
├── dbt_project/                # dbt Core project
│   ├── dbt_project.yml
│   ├── profiles.yml.example    # template — real profiles.yml is gitignored
│   ├── macros/                 # reusable dbt Jinja macros
│   ├── seeds/                  # static reference CSVs (e.g. team mappings)
│   └── models/
│       ├── staging/
│       │   ├── sources.yml     # dbt source definitions for raw inputs
│       │   ├── stg_aws_cur.sql
│       │   ├── stg_azure_cost.sql
│       │   └── stg_gcp_billing.sql
│       ├── intermediate/
│       │   ├── int_aws_nec.sql
│       │   ├── int_azure_nec.sql
│       │   └── int_gcp_nec.sql
│       └── marts/
│           └── fct_unified_billing.sql
│
├── config/                     # allocation strategy configs (YAML)
│   ├── shared_cost_weights.yml
│   └── heuristic_rules.yml
│
├── allocation/
│   ├── __init__.py
│   ├── tag_allocator.py        # Rishika Naha
│   ├── shared_cost.py          # Keerthi Rapolu
│   ├── nec_model.py            # Keerthi Rapolu
│   ├── untagged_heuristic.py   # Rishika Naha
│   └── untagged_ml.py          # Rishika Naha / Keerthi Rapolu (optional)
│
├── dashboard/
│   ├── app.py                  # Streamlit entrypoint
│   └── pages/
│       ├── 01_overview.py
│       ├── 02_team_allocation.py
│       ├── 03_tagging_coverage.py
│       ├── 04_shared_costs.py
│       └── 05_untagged_resources.py
│
├── tests/
│   ├── test_normalization.py
│   ├── test_nec_model.py
│   ├── test_shared_cost.py
│   └── test_untagged.py
│
├── notebooks/
│   ├── 01_schema_exploration.ipynb
│   ├── 02_nec_modeling_demo.ipynb
│   └── 03_untagged_attribution_demo.ipynb
│
├── docs/                       # MkDocs source — deployed via GitHub Pages
│   └── index.md
│
└── .github/
    └── workflows/
        ├── ci.yml              # run tests on push
        └── pipeline.yml        # run full pipeline on schedule
```

---

## 10. Research Paper Outline

**Title:** A Scalable Framework for Multi-Cloud Cost Allocation Using Data Engineering Principles

**Target venues:**
- arXiv preprint (immediate visibility — post first)
- IEEE CLOUD Conference
- ICDE / VLDB data engineering workshop track

### Sections

#### 1. Introduction
- Multi-cloud growth trends across hyper-scalers (AWS, Azure, GCP)
- FinOps as a discipline (FinOps Foundation reference)
- Gap: no open-source, data-engineering-native cost allocation framework
- Paper contributions (bulleted list)

#### 2. Background & Related Work
- **FinOps basics:** What FinOps is, the FinOps lifecycle (Inform → Optimize → Operate), FinOps Foundation principles
- **Cloud cost optimization basics:** Cloud pricing models (on-demand, reserved, spot), discount mechanisms (RI, Savings Plans, CUDs), blended vs unblended vs net effective cost
- **Multi-cloud cost management:** Challenges of managing spend across hyper-scalers, schema heterogeneity, tagging inconsistencies, attribution gaps
- Existing tools: CloudHealth, Apptio, AWS Cost Explorer (closed-source, expensive)
- Academic work on cloud cost modeling
- FinOps Foundation FOCUS schema (acknowledge but differentiate)
- Our angle: open-source, reproducible, data-engineering-native

#### 3. Unified Cost Schema Design ← **core novelty**
- Schema normalization across all three clouds
- Field mapping table (AWS CUR / Azure / GCP)
- Handling schema evolution (cloud providers change columns)
- Design decisions and tradeoffs

#### 4. Cost Allocation Strategies
- Tag-based, account-based, hybrid
- Shared cost distribution algorithms (with math)
- Tagging coverage analysis methodology
- Real-world challenges (missing tags, inconsistent naming)

#### 5. Net Effective Cost Modeling
- RI/SP/CUD amortization methodology
- Blended vs unblended vs net effective cost
- Formula and implementation
- Validation: compare NEC output vs AWS Cost Explorer

#### 6. Untagged Resource Attribution
- Heuristic rule design
- ML classifier approach (features, model, evaluation)
- Precision/recall results on synthetic dataset
- When heuristics beat ML and vice versa

#### 7. Implementation & Evaluation
- GitHub repo walkthrough
- Synthetic dataset statistics
- Dashboard screenshots
- Pipeline performance (rows/sec, memory)
- Limitations

#### 8. Conclusion & Future Work
- FinOps certification context
- Enterprise scale-out path (PySpark, streaming)
- Real-time cost allocation (future)
- Open questions

---

## 11. Work Division

Division is **by functionality** — both contribute across all three hyper-scalers (AWS, Azure, GCP).

### Keerthi Rapolu

**Core strength:** dbt, Snowflake, FinOps (ServiceNow), NEC modeling

| Deliverable | File(s) |
|---|---|
| dbt project setup & design | `dbt_project/` |
| Azure billing ingestion & normalization | `ingestion/azure_ingestor.py`, `stg_azure_cost.sql` |
| GCP billing normalization | `stg_gcp_billing.sql`, `int_gcp_nec.sql` |
| Azure NEC / reservation amortization | `int_azure_nec.sql` |
| NEC / RI amortization module | `allocation/nec_model.py` |
| Shared cost distribution engine | `allocation/shared_cost.py` |
| Streamlit dashboard (all pages) | `dashboard/` |
| Paper sections 3, 4, 5 | Schema design, allocation strategies, NEC |

---

### Rishika Naha

**Core strength:** AWS, GCP, ML

| Deliverable | File(s) |
|---|---|
| AWS billing ingestion & normalization | `ingestion/aws_ingestor.py`, `stg_aws_cur.sql`, `int_aws_nec.sql` |
| GCP billing ingestion | `ingestion/gcp_ingestor.py`, `int_gcp_nec.sql` |
| Tag-based allocation module | `allocation/tag_allocator.py` |
| Untagged heuristic attribution engine | `allocation/untagged_heuristic.py` |
| ML classifier (optional) | `allocation/untagged_ml.py` |
| Synthetic data generation (all clouds) | `data/synthetic/generate_*.py` |
| GitHub Actions CI/CD | `.github/workflows/` |
| Paper sections 2, 6, 7 | Background, untagged attribution, demo |

---

### Shared

| Deliverable | Notes |
|---|---|
| CAS schema agreement | Must agree before writing any code — Week 1 |
| Unified gold model | `fct_unified_billing.sql` — UNION ALL of all three normalized models |
| Paper intro & conclusion | Write together |
| Cross-review paper sections | Swap sections before submission |
| DuckDB schema | Design together, implement individually |

---

## 12. Task Plan & Milestones

> **Tracking:** Use GitHub Projects → Board view. One Issue per task. Labels: `aws`, `azure`, `gcp`, `paper`, `infra`, `engine`, `dashboard`.

### Phase 1 — Foundation (Weeks 1–2)

**Infra & Schema (Both)**
- [ ] Create GitHub repo + branch strategy (`main`, `dev`, feature branches)
- [ ] Agree on and document CAS schema (this doc, Section 5)
- [ ] Set up DuckDB + dbt project skeleton (Keerthi Rapolu)

**Ingestion — all hyper-scalers**
- [ ] Generate synthetic AWS CUR data + AWS ingestion (Rishika Naha)
- [ ] Generate synthetic Azure Cost Export data + Azure ingestion (Keerthi Rapolu)
- [ ] Generate synthetic GCP Billing Export data + GCP ingestion (Rishika Naha)

**Normalization — staging models**
- [ ] `stg_azure_cost.sql` — Azure → normalized fields (Keerthi Rapolu)
- [ ] `stg_aws_cur.sql` — AWS → normalized fields (Rishika Naha)
- [ ] `stg_gcp_billing.sql` — GCP → normalized fields (Rishika Naha)

### Phase 2 — Core Engine (Weeks 3–4)

**NEC calculations per hyper-scaler (Silver layer)**
- [ ] `int_aws_nec.sql` — AWS RI/SP amortization (Rishika Naha)
- [ ] `int_azure_nec.sql` — Azure reservation amortization (Keerthi Rapolu)
- [ ] `int_gcp_nec.sql` — GCP CUD amortization (Keerthi Rapolu / Rishika Naha)

**Unification & Allocation (Gold layer)**
- [ ] `fct_unified_billing.sql` — UNION ALL → CAS schema (Both)
- [ ] NEC / RI amortization module — `allocation/nec_model.py` (Keerthi Rapolu)
- [ ] Shared cost distribution engine — `allocation/shared_cost.py` (Keerthi Rapolu)
- [ ] Tag-based allocation module — `allocation/tag_allocator.py` (Rishika Naha)
- [ ] Untagged heuristic attribution — `allocation/untagged_heuristic.py` (Rishika Naha)
- [ ] ML classifier for untagged — `allocation/untagged_ml.py` (Rishika Naha — optional)
- [ ] Unit tests for all modules

### Phase 3 — Demo + Paper (Weeks 5–6)

**Dashboard**
- [ ] Streamlit dashboard — Overview + Team Allocation pages (Keerthi Rapolu)
- [ ] Streamlit dashboard — Tagging + Shared + Untagged pages (Keerthi Rapolu)

**CI/CD**
- [ ] GitHub Actions: CI pipeline (run tests on push) (Rishika Naha)
- [ ] GitHub Actions: pipeline run (weekly schedule) (Rishika Naha)

**Paper**
- [ ] Section 2 — Background (FinOps basics, cost optimization, multi-cloud mgmt) (Rishika Naha)
- [ ] Section 3 — Schema design (Keerthi Rapolu)
- [ ] Section 4 — Allocation strategies (Keerthi Rapolu)
- [ ] Section 5 — NEC modeling (Keerthi Rapolu)
- [ ] Section 6 — Untagged attribution (Rishika Naha)
- [ ] Section 7 — Implementation & evaluation (Rishika Naha)
- [ ] Intro + Conclusion (Both)
- [ ] Cross-review all paper sections
- [ ] Post arXiv preprint

### GitHub Labels to Create

```
aws        (blue)
azure      (teal)
gcp        (orange)
paper      (purple)
infra      (gray)
engine     (yellow)
dashboard  (green)
keerthi    (pink)
rishika-naha  (light blue)
```

---

## 13. Constraints & Guardrails

| Constraint | Rule |
|---|---|
| Cost | Every tool and service must be free. No exceptions. |
| Real billing data | Never commit real billing data to the repo. Use synthetic data only. |
| Scope creep | Do not add LangGraph/LangChain unless a specific NL feature is agreed upon. |
| PySpark | Not in demo. Mention as enterprise scale-out path in the paper only. |
| Cloud preference | Both contribute across all hyper-scalers. Divide by functionality: NEC/shared-cost → Keerthi Rapolu; tag/untagged → Rishika Naha. |
| AI use | Claude (VS Code integration) is acceptable for code + paper writing. Document usage in paper methodology. |
| Paper scope | One unified framework paper (Option 1). Do not split into three separate papers. |

---

## Appendix A — Synthetic Data Schema

Synthetic data must match the real billing format closely enough to validate the normalization logic.

**AWS CUR synthetic columns (minimum):**
`lineItem/UsageAccountId`, `lineItem/ProductCode`, `lineItem/UsageType`, `lineItem/UnblendedCost`, `lineItem/ResourceId`, `resourceTags/user:Team`, `savingsPlan/SavingsPlanEffectiveCost`, `lineItem/UsageStartDate`

**Azure Cost Export synthetic columns (minimum):**
`SubscriptionId`, `ResourceGroup`, `ResourceId`, `ServiceName`, `CostInBillingCurrency`, `Tags`, `Date`, `BenefitName`

**GCP Billing Export synthetic columns (minimum):**
`project.id`, `service.description`, `resource.name`, `cost`, `credits`, `labels`, `usage_start_time`

---

## Appendix B — FinOps Certification Alignment

Keerthi Rapolu is pursuing FinOps certification alongside this project. Relevant overlap:

| FinOps Domain | Paper Section | Module |
|---|---|---|
| Cost Allocation | Section 4 | `tag_allocator.py`, `shared_cost.py` |
| Rate Optimization (RI/SP) | Section 5 | `nec_model.py` |
| Usage Optimization | Section 6 | `untagged_heuristic.py` |
| Reporting & Analytics | Section 7 | `dashboard/` |

> The NEC modeling work in this project directly supports the FinOps certification study material on Reserved Instance and Savings Plan amortization.

---

*Last updated: April 2026*
