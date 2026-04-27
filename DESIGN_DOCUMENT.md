# Multi-Cloud FinOps Decision Engine
## Design Document v2.2

**Project:** Research Paper + GitHub Demo  
**Authors:** Keerthi Rapolu + Rishika Naha  
**Date:** April 2026  
**Status:** Implemented as a post-billing multi-cloud FinOps decision engine with canonical NEC, governance, recommendation, forecast, and action-validation layers

---

## Project Evolution: Cost Allocation Framework → FinOps Decision Engine

### Overview

The project began as a multi-cloud cost ingestion, normalization, and attribution framework covering AWS, Azure, and GCP. Phase 1 established the financial accuracy and ownership layer; later phases added deterministic reasoning, canonical FinOps decision tables, recommendation scoring, month-end forecasting, and closed-loop action validation.

The repository should now be positioned as a **post-billing multi-cloud FinOps decision engine**. It consumes billing, tagging, allocation, NEC, and waste signals after spend occurs, then produces explainable recommendations and validation outputs. It does **not** perform workload-intent modeling, pre-provisioning policy enforcement, runtime autoscaling, spot migration, or LLM/vector-based workload governance.

### Decision-Engine Positioning

This repository is not just a dashboard. Its primary system contribution is the backend decision model:

- one canonical NEC source across AWS, Azure, and GCP
- one canonical unattributed-cost and tagging-governance source
- canonical FinOps signal, recommendation, decision, lifecycle, and forecast tables
- deterministic recommendation scoring based on recoverable savings, confidence, governance severity, urgency, and low-risk bonus
- closed-loop validation using expected versus realized savings

Implemented canonical marts and views now include:

- `marts.fct_finops_signals`
- `marts.fct_finops_recommendations`
- `marts.fct_finops_decisions`
- `marts.fct_action_lifecycle`
- `marts.fct_month_end_forecast`
- `marts.fct_forecast_backtest`
- `marts.fct_model_accuracy`
- `marts.fct_finops_decision_metrics`

Recommendation confidence is calibrated rather than treated as a fixed heuristic. The current calibration raises confidence when a signal persists across periods or is corroborated by multiple FinOps signals, and applies a penalty when the recommendation is supported only by anomaly-style evidence without broader corroboration.

### Novelty of the Implemented System

The publishable contribution is the combination of:

- a canonical FinOps decision model that separates waste signal, recoverable savings, actionable savings, and realization-adjusted projected savings
- explicit signal-to-action mapping instead of page-local recommendation text
- confidence-calibrated recommendation scoring with auditable components
- forecast backtesting through a canonical mart rather than projection-only reporting
- lifecycle and realized-savings readiness through canonical action and model-accuracy tables
- a reproducible synthetic benchmark that can be rebuilt locally with dbt, DuckDB, and Python tests

### Current Limitations

- The benchmark dataset is synthetic and should not be presented as real enterprise validation.
- The system is explainable decision intelligence, not autonomous remediation.
- Idle-compute detection is currently billing-proxy based; telemetry-backed CPU/memory validation remains phase 2 work.
- Real-world action history and realized-savings evidence are not yet available in this repository.

The Streamlit application is only a presentation layer over those outputs.

### Boundary with Intent-Aware Cloud Governance

This repository is intentionally separate from `intent-aware-cloud-governance`.

**`multicloud-finops-framework` covers:**
- multi-cloud billing normalization
- NEC modeling
- allocation and chargeback
- tagging and ownership governance
- waste classification
- recommendation scoring
- month-end forecasting
- action lifecycle validation

**`multicloud-finops-framework` does not cover:**
- intent vectors or semantic workload embeddings
- pre-provisioning workload guardrails
- runtime adaptive scaling
- spot migration logic
- vector database or LLM-based workload governance
- runtime application optimization

System boundary summary:
- **This repo:** post-billing FinOps accountability and decision support
- **Intent-aware cloud governance repo:** pre-runtime workload governance and provisioning intelligence

---

### Phase 1 — Cost Allocation Framework ✅ Complete

#### Multi-Cloud Ingestion and Normalization

Billing exports from all three hyper-scalers are ingested via Python validators and landed as Parquet, then normalized through dbt into a cloud-agnostic schema. Each cloud's proprietary column structure (48 AWS CUR columns, 32 Azure Cost Management columns, 27 GCP Billing Export columns) is mapped to the 31-column Unified Cost Allocation Schema (CAS).

Pricing model differences — on-demand, Reserved Instances, Savings Plans, Committed Use Discounts — are handled explicitly rather than treated as pass-through. The staging and intermediate dbt layers resolve each cloud's discount representation so downstream consumers work with a consistent `nec_used` / `nec_waste` split regardless of provider.

#### Net Effective Cost (NEC) Layer

`unblended_cost` and raw billing cost systematically misrepresent spend for commitment-covered resources: RI-covered hours appear at `$0`, SP-covered hours appear at full on-demand rate. NEC corrects both distortions by reading from commitment-specific cost fields.

The model emits two orthogonal signals per row:
- `nec_used` — cost attributable to actual consumed usage after commitment discount amortization
- `nec_waste` — cost of idle commitment capacity (unused RI hours, SP recurring fee shortfall)

These signals propagate through the Gold layer and drive both accurate team chargeback and waste identification downstream.

#### Cost Attribution Layer *(Rishika Naha)*

Resolves resource ownership for every billing row using a two-stage pipeline:
1. **Tag-based direct allocation** — resources with a `team` tag are attributed deterministically
2. **Untagged heuristic attribution** — resources without a tag are matched against configurable rule patterns (`config/heuristic_rules.yml`) based on resource name, account, and service; an optional `RandomForestClassifier` (`allocation/untagged_ml.py`) provides probabilistic attribution when tagging coverage is sufficient

**Output:** `resource_id → allocated_team → confidence_score`

#### Unified Cost Data Model

All three clouds' data converges in `fct_unified_billing` — a single DuckDB mart that serves every downstream consumer: the allocation engine, the intelligence layer, and the dashboard. Shared-cost distribution (proportional / even / weighted) is applied in the Azure intermediate layer and propagates through the Gold UNION ALL.

---

### Phase 1 Limitations — Addressed by Phase 2

| Gap | Description |
|---|---|
| No waste identification | Cannot identify idle or inefficient resources by type |
| No root cause analysis | Detects cost magnitude but cannot explain why it changed |
| No actionable recommendations | No guidance on what to do or in what order |
| No impact estimation | Cannot answer "If I act on this, how much will I recover?" |
| Descriptive only | System is reporting-oriented; analysis requires manual investigation |

---

### Phase 2 — Cost Intelligence Layer ✅ Complete

To address these gaps, a **Cost Intelligence Layer** (`intelligence/`) was implemented as Keerthi Rapolu's Phase 2 contribution. It operates entirely on the normalized billing data — no external observability signals (CloudWatch, Azure Monitor) are required.

#### Architecture

```
fct_unified_billing  (Gold mart — NEC + attribution)
           ↓
  ┌────────────────────────────────────────────┐
  │         COST INTELLIGENCE LAYER            │
  │                                            │
  │  waste_detector.py                         │
  │    → list[WasteFinding]                    │
  │       (resource, team, type, confidence,   │
  │        estimated_waste)                    │
  │           ↓                                │
  │  causal_engine.py                          │
  │    → list[CausalInsight]                   │
  │       (team, root_causes[], trend,         │
  │        anomaly_flag, confidence)           │
  │           ↓                                │
  │  impact_simulator.py                       │
  │    → list[Recommendation]                  │
  │       (action, savings, risk,              │
  │        priority_score, rationale)          │
  └────────────────────────────────────────────┘
           ↓
     Dashboard Pages 04 + 05
```

#### Waste Detection Engine (`intelligence/waste_detector.py`)

Scans the unified billing mart and classifies inefficiencies into a four-category waste taxonomy. Thresholds are read from `config/waste_thresholds.yml` at runtime — no code changes are required to tune sensitivity.

| Waste Type | Detection Signal | Example Finding |
|---|---|---|
| `unused_commitment` | `is_commitment_waste = true` with `nec_waste > floor` | RI running at 0% utilization for a billing period |
| `idle_compute` | `nec_used / vcpu < idle_cost_per_vcpu_threshold` | EC2 instance consuming $0.003/vCPU-hr vs $0.05 baseline |
| `zombie_resource` | `0 < total_nec_used < monthly_floor` over full period | Orphaned EBS snapshot costing $0.40/month |
| `underutilized_commitment` | `used_commitment / total_commitment < utilization_threshold` | Savings Plan at 42% vs 70% configured threshold |

Each `WasteFinding` contains: `resource_id`, `allocated_team`, `cloud_provider`, `waste_type`, `estimated_waste`, `confidence` (0–1), and `service_category`. The confidence score is derived from signal strength — `unused_commitment` findings are deterministic (confidence = 1.0); idle compute findings carry lower confidence because vCPU-normalized cost is a billing-side proxy, not a direct utilization metric.

#### Causal Reasoning Engine (`intelligence/causal_engine.py`)

Derives structured *facts* from billing patterns and assembles them into ranked root cause chains — one `CausalInsight` per team. The engine operates in two modes depending on data availability:

**Single-month mode** — produces fact-based insights from the current billing period alone:
- Commitment waste presence and magnitude
- Idle resource count by type
- Untagged NEC fraction (attribution gap)
- Dominant service category and its NEC share

**Multi-month mode** (activated when ≥ 2 months of data are loaded) — adds temporal reasoning:
- Month-over-month NEC change (direction + percentage)
- Z-score anomaly detection: `z = (current_nec − rolling_mean) / rolling_std`; z ≥ 2.0 triggers an anomaly finding
- Trend classification: `increasing` / `decreasing` / `stable`

The six fact types the engine reasons over are: `commitment_waste_identified`, `idle_resources_detected`, `untagged_cost_gap`, `service_category_dominance`, `team_cost_spike`, `team_cost_decrease`. Each `RootCause` object carries a `fact_type`, human-readable `description`, and a `confidence` score. Root causes are sorted by confidence descending before being surfaced in the dashboard.

#### Impact Simulation Engine (`intelligence/impact_simulator.py`)

Converts `WasteFinding` objects into prioritised `Recommendation` dicts. Savings estimates use conservative, per-action-type recovery rates derived from industry benchmarks:

| Action Type | Recovery Rate | Risk Level | Risk Weight |
|---|---|---|---|
| `release_commitment` (fully unused) | 100% of `nec_waste` | Low | 0.1 |
| `resize_down` (idle compute) | 60% of waste signal | Low | 0.2 |
| `remove_resource` (zombie) | 90% of `nec_used` | Medium | 0.4 |
| `release_commitment` (underutilized) | 50% of waste signal | Medium | 0.4 |

Priority score formula:

`priority_score = 0.35 * normalized_savings + 0.25 * confidence + 0.20 * governance_severity + 0.10 * urgency + 0.10 * low_risk_bonus`

Definitions:
- `normalized_savings = recommendation_savings / max_savings_in_scope`
- `governance_severity = 1.0` for severe attribution gaps, `0.8` for shared-cost concentration, `0.65` for anomaly or forecast risk, `0.35` for commitment waste, and `0.30` for idle or zombie resource signals, with `+0.10` for missing ownership and `+0.10` for SLA breach
- `urgency = 0.60 * normalized_waste_growth_rate + 0.40 * normalized_anomaly_score`
- `low_risk_bonus` is highest for no-downtime, no-approval actions

This ranking ensures that high-savings, high-confidence, low-risk actions surface before noisier or operationally riskier candidates. The Waste page renders only recoverable optimization actions; governance gaps and forecast risks remain in the Insights page.

---

### Key Innovation

The distinguishing contribution is not any individual engine but the **integrated pipeline** from raw billing data to prioritised, evidence-backed recommendations:

| Capability | Traditional FinOps Tools | This System |
|---|---|---|
| Cost visibility | ✅ | ✅ |
| Tag-based allocation | ✅ | ✅ |
| Shared cost distribution | Partial | ✅ (3 configurable strategies) |
| Commitment waste identification | Basic flags | ✅ (4-type taxonomy + confidence) |
| Root cause explanation | ❌ | ✅ (fact-based, evidence-ranked) |
| Impact quantification | ❌ | ✅ (conservative recovery rates + risk scoring) |
| Prioritised recommendations | ❌ | ✅ (priority\_score = savings × risk adjustment) |
| Open-source, zero cost | ❌ | ✅ |

---

### Contributor Responsibilities

| Contributor | Phase 1 | Phase 2 |
|---|---|---|
| **Keerthi Rapolu** | dbt project, Azure/GCP normalization, NEC modeling, shared cost engine, Streamlit dashboard (all pages) | Waste detection engine, causal reasoning engine, impact simulation engine, dashboard pages 04–05, `_shared.py`, `waste_thresholds.yml` |
| **Rishika Naha** | AWS normalization, tag allocator, untagged heuristic engine, ML classifier, synthetic data generators, GitHub Actions CI/CD | Background & related work (paper), untagged attribution paper section, implementation & evaluation |

---

### Value Delivered

| Dimension | Value |
|---|---|
| **Technical** | Moves FinOps from reporting to intelligence; deterministic causal reasoning over billing data; modular three-engine architecture with clear input/output contracts |
| **Business** | Identifies recoverable waste with team ownership and dollar estimates; prioritises actions by ROI and risk; reduces investigation time from hours to seconds |
| **Research** | First open-source framework to combine multi-cloud NEC normalization, waste taxonomy, causal billing reasoning, and impact simulation in a single reproducible pipeline |
| **Strategic** | Transforms FinOps posture from reactive (investigate alerts after the fact) to proactive (surface optimization opportunities continuously) |

---

## Table of Contents

**Phase 1 — Cost Allocation Framework** ✅ Complete  
**Phase 2 — Cost Intelligence Layer** ✅ Complete

1. [Problem Statement](#1-problem-statement)
2. [Project Goals](#2-project-goals)
3. [Architecture Overview](#3-architecture-overview) ← updated with Layer 4 intelligence
4. [Data Architecture — 4-Layer Pipeline](#4-data-architecture--4-layer-pipeline)
5. [Unified Cost Allocation Schema (CAS)](#5-unified-cost-allocation-schema-cas)
6. [Core Modules](#6-core-modules)
7. [Technology Stack](#7-technology-stack)
8. [Local Development Setup](#8-local-development-setup)
9. [Repository Structure](#9-repository-structure) ← updated with `intelligence/` + new pages
10. [Research Paper Outline](#10-research-paper-outline) ← updated title + 11 sections
11. [Work Division](#11-work-division) ← updated Phase 1 ✅ / Phase 2 🔲
12. [Task Plan & Milestones](#12-task-plan--milestones) ← updated with Phase 2 todos
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
│  • Tag-based direct allocation           (Rishika Naha)         │
│  • Account/project-based allocation      (Rishika Naha)         │
│  • Shared cost distribution              (Keerthi Rapolu)       │
│  • Untagged attribution (heuristics + ML)(Rishika Naha)         │
│  • NEC modeling (RI/SP amortization)     (Keerthi Rapolu)       │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│              LAYER 4: COST INTELLIGENCE ENGINE  ← NEW           │
│  ┌──────────────────────┐  ┌──────────────────────────────┐    │
│  │  Waste Detection     │  │  Causal Reasoning Engine     │    │
│  │  Engine              │  │  (why did cost change?)      │    │
│  │  (idle / zombie /    │  │  structured facts →          │    │
│  │   underutil.)        │  │  root cause + confidence     │    │
│  └──────────────────────┘  └──────────────────────────────┘    │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Impact Simulation Engine                                │  │
│  │  (resize / remove waste → estimated savings + risk)      │  │
│  └──────────────────────────────────────────────────────────┘  │
│                         (Keerthi Rapolu)                        │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                   LAYER 5: REPORTING (Gold)                     │
│   Streamlit dashboard — cost visibility + intelligence pages    │
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
| `untagged-medium` | 35% | 20% | 15% | Moderate tagging gap — used for April demo data |
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

**Synthetic data realism (48 / 32 / 27 columns per cloud):**
- **AWS** (48 cols): hourly grain; correct `DiscountedUsage` / `SavingsPlanCoveredUsage` line item types; `UnblendedCost=0` on RI rows with `reservation/EffectiveCost` populated; monthly `RIFee` + `SavingsPlanRecurringFee` summary rows; `vcpu` and `memory` per instance type; RI unused quantity fields; SP total/used/recurring commitment fields; `payer_account_id` for consolidated billing
- **Azure** (32 cols): daily grain, amortized export; `BenefitName` / `BenefitId` for RI/SP rows; `UnusedReservation` / `UnusedSavingsPlan` charge type rows for waste; Tags as JSON blob; `PricingModel`, `EffectivePrice`, `PayGPrice` for discount analysis; `vcpus` from AdditionalInfo JSON; `BillingAccountId` (EA enrollment); shared-infra subscription rows with no team tag for shared cost spreading
- **GCP** (27 cols): hourly grain for Compute Engine / Cloud SQL, daily for Cloud Storage / BigQuery storage; CUD/SUD credits as list-of-dicts matching real BigQuery export structure; `system_labels` with `compute_cores`, `compute_memory`, `is_unused_reservation` for GCE VMs; `cost_at_list` alongside `cost`; `project.ancestry_numbers` for org hierarchy; labels as list-of-dicts

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

**Home page (`app.py`):** Portfolio KPIs (list cost, NEC, savings vs list cost, waste); spend-by-cloud stacked bar; executive health summary — three traffic-light signals (red/orange/green) for commitment waste %, tagging gap %, and top cost centre; navigation guidance pointing to detail pages.

**Detail pages:**
1. **Overview** (`01_overview.py`) — 5 KPI tiles (list cost, NEC, savings vs list cost, waste, waste %); daily NEC trend with z-score anomaly markers; savings by pricing model (on_demand / RI / SP); top commitment waste contributors; cloud summary table; 3 insight callouts with actionable recommendations
2. **Cost Allocation** (`02_allocation.py`) — per-team NEC breakdown; commitment utilization (RI/SP) with 100% target line; shared cost distribution by strategy (proportional / even / weighted — Platform 30%, Data Engineering 25%, Frontend 20%, Backend 15%, ML 10%); idle commitment waste detail table; merges former Team Allocation and Shared Costs pages
3. **Tagging & Attribution** (`03_tagging.py`) — coverage analytics by cloud / service / account; ownership assignment UI; SLA-based escalation tracker (7-day fix-it SLA per unattributed account); tag quality scoring; enforcement alerts when untagged NEC ≥ 10%; merges former Tagging Coverage and Untagged Resources pages
4. **Waste & Recommendations** (`04_waste_recommendations.py`) — 5-step waste-to-action pipeline: (1) waste breakdown by type (unused_commitment / idle_compute / zombie_resource / underutilized_commitment) and team; (2) cross-cloud inefficiency charts absolute and relative; (3) prioritised action list with estimated savings and risk scores; (4) quick wins (low risk); (5) projected before/after impact with scenario comparison
5. **Cost Intelligence** (`05_insights.py`) — decision intelligence engine: top 3 weekly ROI actions; team decision cards with root cause analysis, evidence chains, and confidence scores; cost trend by team with MoM change; anomaly explanations with statistical z-score attribution; system reasoning layer transparency view

---

## 5. Unified Cost Allocation Schema (CAS)

This is the normalized schema every cloud's data maps to. Agree on this before writing any code.

The schema below reflects the actual `fct_unified_billing` mart as implemented. All 31 columns are present on every row; cloud-specific fields are NULL where not applicable.

```sql
CREATE TABLE fct_unified_billing (
    -- Identity
    cloud_provider      VARCHAR,        -- 'aws' | 'azure' | 'gcp'
    billing_account_id  VARCHAR,        -- AWS payer account / Azure EA enrollment / GCP billing account
    billing_month       VARCHAR,        -- 'YYYY-MM'
    account_id          VARCHAR,        -- AWS member account / Azure subscription / GCP project ID
    account_name        VARCHAR,        -- human-readable account/subscription/project name

    -- Time
    usage_date          TIMESTAMP,      -- hourly for AWS/GCP; daily (midnight) for Azure

    -- Resource
    resource_id         VARCHAR,        -- cloud-native resource identifier
    service_name        VARCHAR,        -- cloud-native service name (ProductCode / MeterCategory / service.description)
    product_name        VARCHAR,        -- product detail (product/ProductName / ProductName / sku.description)
    instance_type       VARCHAR,        -- EC2 instance type (AWS only; null for Azure/GCP)
    region              VARCHAR,        -- normalized lowercase region

    -- Usage
    usage_amount        DOUBLE,         -- quantity consumed
    usage_unit          VARCHAR,        -- unit of usage (hour / GB-Mo / tebibyte / etc.)
    currency            VARCHAR,        -- billing currency (USD)

    -- Cost
    list_cost           DOUBLE,         -- gross/on-demand cost before discounts
    nec                 DOUBLE,         -- Net Effective Cost (used cost after commitment discounts; excludes waste)
    nec_used            DOUBLE,         -- cost attributable to actual resource usage
    nec_waste           DOUBLE,         -- cost of idle commitment capacity (RI/SP unused hours)
    effective_unit_price DOUBLE,        -- nec_used / usage_amount — true per-unit cost after discounts
    discount_type       VARCHAR,        -- 'ri' | 'sp' | 'on_demand'

    -- Compute sizing (null for storage/database/analytics rows)
    vcpu                INTEGER,        -- vCPU count (EC2, Azure VM, GCE only)
    memory_gb           INTEGER,        -- memory in GiB (EC2 and GCE only; null for Azure)

    -- Tags (normalized across all clouds)
    tag_team            VARCHAR,        -- cost allocation tag: team
    tag_environment     VARCHAR,        -- cost allocation tag: environment
    tag_cost_center     VARCHAR,        -- cost allocation tag: cost center
    is_tagged           BOOLEAN,        -- true if tag_team is non-null

    -- Allocation (computed by int_azure_nec; pass-through for AWS/GCP)
    allocated_team      VARCHAR,        -- team after shared-cost spreading (= tag_team for tagged rows)
    allocated_nec       DOUBLE,         -- NEC share attributed to allocated_team
    is_shared_cost      BOOLEAN,        -- true when cost was split across multiple teams
    is_commitment_waste BOOLEAN,        -- true for unused RI/SP/CUD rows

    -- Normalized service category (derived in mart)
    service_category    VARCHAR         -- 'Compute' | 'Storage' | 'Database' | 'Analytics' | 'Platform' | 'Other'
);
```

### Cloud Field Mappings

| Mart Column | AWS Source | Azure Source | GCP Source |
|---|---|---|---|
| `billing_account_id` | `bill/PayerAccountId` | `BillingAccountId` | `billing_account_id` |
| `account_id` | `lineItem/UsageAccountId` | `SubscriptionId` | `project.id` |
| `account_name` | null (not in CUR) | `SubscriptionName` | `project.name` |
| `usage_date` | `lineItem/UsageStartDate` (hourly) | `Date` (daily) | `usage_start_time` (hourly) |
| `resource_id` | `lineItem/ResourceId` | `ResourceId` | `resource.name` |
| `service_name` | `lineItem/ProductCode` (`AmazonEC2`) | `MeterCategory` (`Virtual Machines`) | `service.description` (`Compute Engine`) |
| `service_category` | derived from service_name | derived from service_name | derived from service_name |
| `list_cost` | `pricing/publicOnDemandCost` | `CostInBillingCurrency` (amortized) | `cost` (pre-credit) |
| `nec` | `reservation/EffectiveCost` or `savingsPlan/SavingsPlanEffectiveCost` or `unblended_cost` | `list_cost` minus waste rows | `cost` + sum(credits amounts) |
| `nec_waste` | 0 (AWS waste on separate RIFee rows) | `list_cost` where `ChargeType = UnusedReservation/SP` | 0 (not isolated) |
| `discount_type` | derived from `lineItem/LineItemType` | derived from `BenefitName` | derived from credits JSON `type` field |
| `vcpu` | `product/vcpu` (string cast to int) | `AdditionalInfo['vCPUs']` | `system_labels['compute_cores']` |
| `memory_gb` | `product/memory` ("8 GiB" → int) | null (not in Azure billing) | `system_labels['compute_memory']` |
| `tag_team` | `resourceTags/user:Team` | `Tags['team']` (JSON extract) | `labels[key='team']` (list-of-dicts) |
| `is_commitment_waste` | false (AWS uses RIFee rows, filtered) | `ChargeType in (UnusedReservation, UnusedSavingsPlan)` | `system_labels['is_unused_reservation']` |
| `allocated_team` | = `tag_team` (pass-through) | fan-out across teams for untagged/shared subs | = `tag_team` (pass-through) |
| `is_shared_cost` | false | true for untagged rows spread across N teams | false |

---

## 6. Core Modules

### 6.1 NEC Modeling

Net Effective Cost (NEC) = actual cost paid after discounts, split into used cost and idle commitment waste.

```
nec       = cost tied to real consumed usage (nec_used)
nec_waste = idle or unused commitment cost (surfaced separately, not added into nec)
```

**Per-cloud formula (for the main commitment-related row types):**

| Cloud | Formula |
|---|---|
| AWS `Usage` | `nec_used = unblended_cost` |
| AWS `DiscountedUsage` (RI) | `nec_used = reservation_effective_cost` |
| AWS `SavingsPlanCoveredUsage` | `nec_used = savings_plan_effective_cost` |
| AWS `RIFee` | `nec_used = 0; nec_waste = unused_upfront + unused_recurring` |
| AWS `SavingsPlanRecurringFee` | `nec_used = 0; nec_waste = recurring_commitment − used_commitment` |
| Azure `Usage` rows | `nec_used = billed_cost` (amortized actual cost from amortized export) |
| Azure `UnusedReservation/SP` | `nec_waste = billed_cost` |
| GCP (Detailed Export) | `nec = GREATEST(list_cost + total_credit_amount, 0.0)` |

**Why not `unblended_cost` for AWS?** RI-covered hours show `$0` (usage looks free); SP-covered hours show full OD rate (discount invisible in `unblended_cost`).

**Why this matters:** Without NEC, a team that benefits from an RI purchased by a central finance team shows $0 compute cost — distorting accountability.

---

### 6.2 Shared Cost Distribution (`allocation/shared_cost.py`)

Three strategies, configurable per service:

| Strategy | When to use | Formula |
|---|---|---|
| `proportional` | Default — fair based on usage | `team_share = team_direct_spend / total_direct_spend` |
| `even` | Small teams, equal footing | `team_share = 1 / num_teams` |
| `weighted` | Headcount or contractual SLA differences — weights defined in `config/shared_cost_weights.yml`: Platform 30%, Data Engineering 25%, Frontend 20%, Backend 15%, ML 10% | `team_share = team_weight / sum(all_weights)` |

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

### 6.4 Waste Detection Engine (`intelligence/waste_detector.py`)

Entry point: `run(df: pd.DataFrame) → list[WasteFinding]`

Reads `fct_unified_billing` as a DataFrame and applies four independent detectors. All numeric thresholds are read from `config/waste_thresholds.yml` via `_load_thresholds()` — sensitivity can be adjusted without modifying code.

**`WasteFinding` dataclass fields:**
```
resource_id         str
allocated_team      str   # 'unattributed' if None/NaN
cloud_provider      str
service_category    str
waste_type          str   # one of the four taxonomy values
estimated_waste     float # dollars
confidence          float # 0.0–1.0
detail              str   # human-readable evidence string
```

**Detector logic:**

| Detector | Source column(s) | Confidence basis |
|---|---|---|
| `unused_commitment` | `is_commitment_waste`, `nec_waste` | Deterministic — 1.0 when `nec_waste > floor` |
| `idle_compute` | `nec_used`, `vcpu`, `service_category == 'Compute'` | Proportional to how far below the idle threshold the per-vCPU cost falls |
| `zombie_resource` | `nec_used` aggregated per `resource_id` for billing month | Fixed at 0.85 — no utilization data, billing-side approximation only |
| `underutilized_commitment` | `nec_used`, `list_cost`, `discount_type in ('ri','sp')` | Proportional to distance below utilization threshold |

**Design constraint:** The engine operates on billing data only. Real CPU/memory utilization metrics (CloudWatch, Azure Monitor, GCP Cloud Monitoring) are not available in this implementation. `idle_compute` and `zombie_resource` findings are therefore estimates, not ground truth, and carry sub-1.0 confidence scores accordingly.

---

### 6.5 Causal Reasoning Engine (`intelligence/causal_engine.py`)

Entry point: `run(df: pd.DataFrame, waste_findings: list[WasteFinding]) → list[CausalInsight]`

**Key dataclasses:**

```python
@dataclass
class RootCause:
    fact_type:   str    # e.g. 'commitment_waste_identified'
    description: str    # human-readable, team-scoped explanation
    confidence:  float  # 0.0–1.0

@dataclass
class CausalInsight:
    team:         str
    root_causes:  list[RootCause]   # sorted by confidence DESC
    trend:        str               # 'increasing' | 'decreasing' | 'stable' | 'insufficient_data'
    anomaly:      bool
    anomaly_zscore: float | None
    period_nec:   float             # current period total NEC
    mom_change_pct: float | None    # None if < 2 months available
```

**Processing pipeline:**
1. `build_nec_trend(df)` — aggregate NEC per team per `billing_month`; compute `pct_change` between consecutive months
2. `compute_zscore_anomaly(trend_df)` — for the latest period, `z = (nec − mean(prior)) / std(prior)`; requires ≥ 3 periods
3. `build_causal_facts(df, waste_findings)` — derive fact signals per team from: commitment waste presence, idle resource count, untagged NEC fraction, dominant service category NEC share, MoM direction
4. `reason(facts, trend, scope)` → `CausalInsight` for one team — converts each fact to a `RootCause` with a contextual description and evidence-scaled confidence score

**Fact-to-confidence mapping:**

| Fact type | Confidence | Escalation condition |
|---|---|---|
| `commitment_waste_identified` | 0.95 | `waste_pct > 20%` → 0.99 |
| `idle_resources_detected` | 0.80 | count > 5 → 0.90 |
| `untagged_cost_gap` | 0.75 | untagged fraction > 40% → 0.88 |
| `service_category_dominance` | 0.65 | dominant share > 70% → 0.78 |
| `team_cost_spike` | 0.88 | z-score ≥ 3.0 → 0.95 |
| `team_cost_decrease` | 0.70 | — |

---

### 6.6 Impact Simulation Engine (`intelligence/impact_simulator.py`)

Entry point: `run(waste_findings: list[WasteFinding]) → list[Recommendation]`

**`Recommendation` TypedDict fields:**
```python
{
    "resource_id":        str,
    "allocated_team":     str,
    "waste_type":         str,
    "action":             str,        # ACTION_MAP[waste_type]
    "estimated_savings":  float,
    "savings_pct":        float,      # fraction of estimated_waste recoverable
    "risk":               str,        # 'Low' | 'Medium' | 'High'
    "priority_score":     float,      # canonical weighted score from savings, confidence, governance severity, urgency, and low-risk bonus
    "rationale":          str,        # 1–2 sentence justification
    "cloud_provider":     str,
    "service_category":   str,
    "confidence":         float,
}
```

**Recovery rates and risk classification:**

```python
RECOVERY_RATES = {
    "unused_commitment":        1.00,  # 100% — entire waste stream is recoverable
    "idle_compute":             0.60,  # 60%  — right-sizing, not full removal
    "zombie_resource":          0.90,  # 90%  — near-full recovery; 10% buffer for egress
    "underutilized_commitment": 0.50,  # 50%  — partial release or exchange
}

RISK_LEVELS = {
    "unused_commitment":        "Low",
    "idle_compute":             "Low",
    "zombie_resource":          "Medium",
    "underutilized_commitment": "Medium",
}
```

Output is sorted by `priority_score` descending. The dashboard's Waste & Recommendations page (page 04) uses this ranked list to render the action table, quick-wins panel, and before/after scenario comparison.

---

## 7. Technology Stack

### Selected Tools (all free)

| Layer | Tool | Why |
|---|---|---|
| Data transform | dbt Core + DuckDB | SQL-first, version-controlled, runs locally, no infra |
| Processing | Python 3.11 + pandas + PyArrow | Universal, sufficient for demo scale; PyArrow for Parquet I/O |
| Intelligence | Python + PyYAML + NumPy | Deterministic waste detection, causal reasoning, impact simulation — config-driven, no LLM required |
| Orchestration | GitHub Actions | Free 2000 min/mo, CI/CD + pipeline trigger |
| Dashboard | Streamlit + Plotly | Free tier deploy, Python-native, Plotly for interactive charts |
| ML (optional) | scikit-learn | Lightweight `RandomForestClassifier` for untagged attribution, no GPU needed |
| Version control | GitHub | Repo + Actions + Pages, all free |
| Notebook demos | Jupyter / Google Colab | No setup, shareable, free GPU |
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

All dbt models materialize into `finops_dbt.duckdb` at the repo root. To browse schemas and run ad-hoc SQL without leaving VS Code:

**Install two VS Code extensions:**
1. **SQLTools** (Matheus Teixeira) — base SQL client framework
2. **DuckDB Sql Tools** (Random Fractals Inc.) — DuckDB driver

**Connect:**
1. Click the database icon in the VS Code sidebar
2. Add New Connection → DuckDB
3. Database file: `c:\<path-to-repo>\multicloud-finops-framework\finops_dbt.duckdb`
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
-- Spend by cloud and service category
SELECT cloud_provider, service_category,
       COUNT(*) as rows, ROUND(SUM(nec), 2) as total_nec
FROM main_marts.fct_unified_billing
GROUP BY 1, 2 ORDER BY 1, 3 DESC;

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

-- Commitment waste by cloud
SELECT cloud_provider,
       ROUND(SUM(CASE WHEN is_commitment_waste THEN nec_waste ELSE 0 END), 2) as waste_cost,
       ROUND(SUM(nec_used), 2) as used_cost
FROM main_marts.fct_unified_billing
GROUP BY cloud_provider;

-- Team spend with billing account context
SELECT billing_account_id, cloud_provider, allocated_team,
       ROUND(SUM(allocated_nec), 2) as team_nec
FROM main_marts.fct_unified_billing
GROUP BY 1, 2, 3 ORDER BY 4 DESC;
```

### Running the Full Pipeline

```bash
# Full pipeline + dashboard in one command
make demo

# Or run steps individually
make data       # generate synthetic data and land to data/raw/
make dbt        # run all dbt models (staging → intermediate → marts)
make test       # run unit tests
make dashboard  # launch the Streamlit dashboard

# Override month or scenario
make pipeline MONTH=2026-04 SCENARIO=untagged-heavy
make data SCENARIO=ri-heavy MONTH=2026-03
```

> `make dbt` runs dbt from inside `dbt_project/` automatically — staging views use a relative path (`../data/raw/`) that resolves correctly only from there.

To query results directly:

```python
import duckdb
con = duckdb.connect('finops_dbt.duckdb')
print(con.execute('SELECT * FROM main_marts.fct_unified_billing LIMIT 10').df())
```

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
├── config/                     # allocation + intelligence configs (YAML)
│   ├── shared_cost_weights.yml
│   ├── heuristic_rules.yml
│   └── waste_thresholds.yml    # NEW — idle/utilization thresholds per service type
│
├── allocation/                 # Phase 1 — attribution layer (Rishika Naha + Keerthi Rapolu)
│   ├── __init__.py
│   ├── tag_allocator.py        # Rishika Naha
│   ├── shared_cost.py          # Keerthi Rapolu
│   ├── nec_model.py            # Keerthi Rapolu
│   ├── untagged_heuristic.py   # Rishika Naha
│   └── untagged_ml.py          # Rishika Naha (optional)
│
├── intelligence/               # NEW — Phase 2 cost intelligence layer (Keerthi Rapolu)
│   ├── __init__.py
│   ├── waste_detector.py       # idle / zombie / underutilized resource detection
│   ├── causal_engine.py        # root cause reasoning over cost trends + events
│   └── impact_simulator.py     # estimate savings + risk for optimization actions
│
├── dashboard/
│   ├── app.py                  # Streamlit entrypoint
│   ├── _shared.py              # shared UI helpers, color constants, diagnose()
│   └── pages/
│       ├── 01_overview.py
│       ├── 02_allocation.py         # Cost Allocation (team NEC + commitments + shared costs)
│       ├── 03_tagging.py            # Tagging & Attribution (coverage + SLA tracker)
│       ├── 04_waste_recommendations.py  # Waste & Recommendations (5-step pipeline)
│       └── 05_insights.py           # Cost Intelligence (causal engine + decision cards)
│
├── tests/
│   ├── test_normalization.py
│   ├── test_nec_model.py
│   ├── test_shared_cost.py
│   ├── test_untagged.py
│   ├── test_waste_detector.py       # waste detection across all four waste types
│   ├── test_causal_engine.py        # causal fact building + root cause reasoning
│   └── test_impact_simulator.py     # savings estimation + risk scoring
│
├── notebooks/
│   ├── 01_schema_exploration.ipynb
│   ├── 02_nec_modeling_demo.ipynb
│   ├── 03_untagged_attribution_demo.ipynb
│   └── 04_cost_intelligence_demo.ipynb  # end-to-end intelligence layer walkthrough
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

**Title:** A Multi-Cloud Cost Intelligence Framework: Attribution, Waste Detection, Causal Reasoning, and Impact Simulation

**Target venues:**
- arXiv preprint (immediate visibility — post first)
- IEEE CLOUD Conference
- ICDE / VLDB data engineering workshop track

### Sections

#### 1. Introduction (Both)
- Multi-cloud growth trends across hyper-scalers (AWS, Azure, GCP)
- FinOps as a discipline (FinOps Foundation reference)
- Gap 1: no open-source, data-engineering-native cost allocation framework
- Gap 2: existing tools are descriptive, not analytical or prescriptive
- Paper contributions (bulleted list): unified schema, NEC modeling, attribution, waste detection, causal reasoning, impact simulation

#### 2. Background & Related Work (Rishika Naha)
- **FinOps basics:** What FinOps is, the FinOps lifecycle (Inform → Optimize → Operate), FinOps Foundation principles
- **Cloud cost optimization:** Cloud pricing models (on-demand, reserved, spot), discount mechanisms (RI, Savings Plans, CUDs), blended vs unblended vs net effective cost
- **Multi-cloud cost management:** Schema heterogeneity, tagging inconsistencies, attribution gaps
- **Causal reasoning in observability:** Existing root cause analysis approaches (Prometheus, OpenTelemetry) — gap in cost domain
- Existing FinOps tools: CloudHealth, Apptio, AWS Cost Explorer (closed-source, expensive, no causal layer)
- FinOps Foundation FOCUS schema (acknowledge but differentiate)
- Our angle: open-source, reproducible, intelligence-first

#### 3. Unified Cost Schema Design ← **core novelty** (Keerthi Rapolu)
- Schema normalization across all three clouds
- Field mapping table (AWS CUR / Azure / GCP)
- Handling schema evolution (cloud providers change columns)
- Design decisions and tradeoffs

#### 4. Cost Allocation Strategies (Rishika Naha + Keerthi Rapolu)
- Tag-based, account-based, hybrid (Rishika Naha)
- Shared cost distribution algorithms with math (Keerthi Rapolu)
- Tagging coverage analysis methodology
- Real-world challenges (missing tags, inconsistent naming)

#### 5. Net Effective Cost Modeling (Keerthi Rapolu)
- RI/SP/CUD amortization methodology
- Blended vs unblended vs net effective cost
- Formula and per-cloud implementation
- Validation: compare NEC output vs AWS Cost Explorer

#### 6. Untagged Resource Attribution (Rishika Naha)
- Heuristic rule design
- ML classifier approach (features, model, evaluation)
- Precision/recall results on synthetic dataset
- When heuristics beat ML and vice versa

#### 7. Waste Detection Engine (Keerthi Rapolu) ← **new**
- Taxonomy of waste: idle compute, zombie infra, low utilization, underutilized commitments
- Detection methodology: threshold-based + pattern matching over NEC time series
- Confidence scoring approach
- Per-team waste breakdown with ownership attribution
- Evaluation: precision on labelled synthetic waste records

#### 8. Causal Reasoning Engine (Keerthi Rapolu) ← **new**
- Architecture: structured fact graph (cost trends + usage patterns + events)
- Root cause identification algorithm
- Confidence scoring and evidence chain representation
- Example walkthrough: deployment → retry spike → cost increase
- Comparison vs manual investigation baseline

#### 9. Impact Simulation Engine (Keerthi Rapolu) ← **new**
- Simulation model: resource resizing, configuration changes, waste removal
- Savings estimation methodology
- Risk scoring (Low / Medium / High)
- Optimization priority ranking
- Validation: compare estimated vs actual savings on held-out scenarios

#### 10. Implementation & Evaluation (Rishika Naha)
- GitHub repo walkthrough
- Synthetic dataset statistics (all three clouds, both phases)
- Dashboard screenshots (Phase 1 + Phase 2 pages)
- End-to-end pipeline performance (rows/sec, memory)
- Limitations and future work

#### 11. Conclusion (Both)
- FinOps certification context
- Enterprise scale-out path (PySpark, streaming)
- Real-time cost intelligence (future)
- Open questions

---

## 11. Work Division

Division is **by functionality** — both contribute across all three hyper-scalers (AWS, Azure, GCP).

### Keerthi Rapolu

**Core strength:** dbt, Snowflake, FinOps (ServiceNow), NEC modeling, cost intelligence

**Phase 1 — Completed**

| Deliverable | File(s) | Status |
|---|---|---|
| dbt project setup & design | `dbt_project/` | ✅ Done |
| Azure billing ingestion & normalization | `ingestion/azure_ingestor.py`, `stg_azure_cost.sql` | ✅ Done |
| GCP billing normalization | `stg_gcp_billing.sql`, `int_gcp_nec.sql` | ✅ Done |
| Azure NEC / reservation amortization | `int_azure_nec.sql` | ✅ Done |
| NEC / RI amortization module | `allocation/nec_model.py` | ✅ Done |
| Shared cost distribution engine | `allocation/shared_cost.py` | ✅ Done |
| Streamlit dashboard — all Phase 1 pages | `dashboard/pages/01–05_*.py` | ✅ Done |

**Phase 2 — Complete (Cost Intelligence Layer)**

| Deliverable | File(s) | Status |
|---|---|---|
| Waste Detection Engine | `intelligence/waste_detector.py` | ✅ Done |
| Causal Reasoning Engine | `intelligence/causal_engine.py` | ✅ Done |
| Impact Simulation Engine | `intelligence/impact_simulator.py` | ✅ Done |
| Waste config (idle/utilization thresholds) | `config/waste_thresholds.yml` | ✅ Done |
| Dashboard — Waste & Recommendations page | `dashboard/pages/04_waste_recommendations.py` | ✅ Done |
| Dashboard — Cost Intelligence page | `dashboard/pages/05_insights.py` | ✅ Done |
| Shared dashboard utilities | `dashboard/_shared.py` | ✅ Done |
| Intelligence unit tests | `tests/test_waste_detector.py`, `test_causal_engine.py`, `test_impact_simulator.py` | ✅ Done |
| Intelligence demo notebook | `notebooks/04_cost_intelligence_demo.ipynb` | ✅ Done |
| Paper sections 3, 5, 7, 8, 9 | Schema design, NEC, Waste Detection, Causal Reasoning, Impact Simulation | 🔲 Todo |

---

### Rishika Naha

**Core strength:** AWS, GCP, ML, CI/CD

**Phase 1 — Completed**

| Deliverable | File(s) | Status |
|---|---|---|
| AWS billing ingestion & normalization | `ingestion/aws_ingestor.py`, `stg_aws_cur.sql`, `int_aws_nec.sql` | ✅ Done |
| GCP billing ingestion | `ingestion/gcp_ingestor.py`, `int_gcp_nec.sql` | ✅ Done |
| Tag-based allocation module | `allocation/tag_allocator.py` | ✅ Done |
| Untagged heuristic attribution engine | `allocation/untagged_heuristic.py` | ✅ Done |
| ML classifier for untagged resources | `allocation/untagged_ml.py` | ✅ Done (optional) |
| Synthetic data generation (all clouds) | `scripts/generate_*.py`, `load_synthetic.py` | ✅ Done |
| GitHub Actions CI/CD | `.github/workflows/` | ✅ Done |

**Phase 2 — Pending**

| Deliverable | File(s) | Status |
|---|---|---|
| Paper section 2 — Background & Related Work | — | 🔲 Todo |
| Paper section 4 — Cost Allocation Strategies (tag/untagged half) | — | 🔲 Todo |
| Paper section 6 — Untagged Attribution | — | 🔲 Todo |
| Paper section 10 — Implementation & Evaluation | — | 🔲 Todo |

---

### Shared

| Deliverable | Notes | Status |
|---|---|---|
| CAS schema agreement | Documented in Section 5 | ✅ Done |
| Unified gold model | `fct_unified_billing.sql` — UNION ALL of all three normalized models | ✅ Done |
| Intelligence layer interface design | Agree on input/output contracts for `intelligence/` modules before implementation | 🔲 Todo |
| Paper intro & conclusion | Write together | 🔲 Todo |
| Cross-review all paper sections | Swap before submission | 🔲 Todo |
| Post arXiv preprint | After cross-review | 🔲 Todo |

---

## 12. Task Plan & Milestones

> **Tracking:** Use GitHub Projects → Board view. One Issue per task. Labels: `aws`, `azure`, `gcp`, `paper`, `infra`, `engine`, `dashboard`, `intelligence`, `keerthi`, `rishika`.

---

### Phase 1 — Cost Allocation Framework ✅ COMPLETE

**Infra & Schema**
- [x] Create GitHub repo + branch strategy (`main`, `dev`, feature branches) — Both
- [x] Agree on and document CAS schema (this doc, Section 5) — Both
- [x] Set up DuckDB + dbt project skeleton — Keerthi Rapolu

**Ingestion — all hyper-scalers**
- [x] Synthetic AWS CUR data + AWS ingestion — Rishika Naha
- [x] Synthetic Azure Cost Export data + Azure ingestion — Keerthi Rapolu
- [x] Synthetic GCP Billing Export data + GCP ingestion — Rishika Naha

**Normalization — staging models**
- [x] `stg_azure_cost.sql` — Azure → normalized fields — Keerthi Rapolu
- [x] `stg_aws_cur.sql` — AWS → normalized fields — Rishika Naha
- [x] `stg_gcp_billing.sql` — GCP → normalized fields — Rishika Naha

**NEC calculations — Silver layer**
- [x] `int_aws_nec.sql` — AWS RI/SP amortization — Rishika Naha
- [x] `int_azure_nec.sql` — Azure reservation amortization — Keerthi Rapolu
- [x] `int_gcp_nec.sql` — GCP CUD amortization — Keerthi Rapolu / Rishika Naha

**Unification & Allocation — Gold layer**
- [x] `fct_unified_billing.sql` — UNION ALL → CAS schema — Both
- [x] NEC / RI amortization module — `allocation/nec_model.py` — Keerthi Rapolu
- [x] Shared cost distribution engine — `allocation/shared_cost.py` — Keerthi Rapolu
- [x] Tag-based allocation module — `allocation/tag_allocator.py` — Rishika Naha
- [x] Untagged heuristic attribution — `allocation/untagged_heuristic.py` — Rishika Naha
- [x] ML classifier for untagged — `allocation/untagged_ml.py` — Rishika Naha
- [x] Unit tests for all Phase 1 modules

**Dashboard — Phase 1 pages**
- [x] Overview + Team Allocation pages — Keerthi Rapolu
- [x] Tagging Coverage + Shared Costs + Untagged Resources pages — Keerthi Rapolu

**CI/CD**
- [x] GitHub Actions: CI pipeline (run tests on push) — Rishika Naha
- [x] GitHub Actions: pipeline run (weekly schedule) — Rishika Naha

---

### Phase 2 — Cost Intelligence Layer ✅ COMPLETE

**Intelligence layer design (Both)**
- [x] Agree on input/output contracts for all three `intelligence/` modules
- [x] Define waste taxonomy and threshold config schema (`config/waste_thresholds.yml`)
- [x] Define causal fact schema

**Waste Detection Engine (Keerthi Rapolu)**
- [x] Implement `intelligence/waste_detector.py` — idle / zombie / underutilized detection
- [x] Add per-service utilization thresholds to `config/waste_thresholds.yml`
- [x] Write unit tests — `tests/test_waste_detector.py`
- [x] Dashboard page — `dashboard/pages/04_waste_recommendations.py`

**Causal Reasoning Engine (Keerthi Rapolu)**
- [x] Implement `intelligence/causal_engine.py` — structured fact graph + root cause logic
- [x] Write unit tests — `tests/test_causal_engine.py`
- [x] Dashboard page — `dashboard/pages/05_insights.py`

**Impact Simulation Engine (Keerthi Rapolu)**
- [x] Implement `intelligence/impact_simulator.py` — savings estimation + risk scoring
- [x] Write unit tests — `tests/test_impact_simulator.py`

**Shared dashboard utilities (Keerthi Rapolu)**
- [x] `dashboard/_shared.py` — color constants, `diagnose()`, badge renderers, action ops

**Intelligence demo notebook (Keerthi Rapolu)**
- [x] `notebooks/04_cost_intelligence_demo.ipynb` — end-to-end walkthrough of all three engines

---

### Phase 3 — Paper 🔲 TODO

**Keerthi Rapolu**
- [ ] Section 3 — Unified Cost Schema Design
- [ ] Section 5 — Net Effective Cost Modeling
- [ ] Section 7 — Waste Detection Engine
- [ ] Section 8 — Causal Reasoning Engine
- [ ] Section 9 — Impact Simulation Engine

**Rishika Naha**
- [ ] Section 2 — Background & Related Work
- [ ] Section 4 — Cost Allocation Strategies (tag/untagged half)
- [ ] Section 6 — Untagged Resource Attribution
- [ ] Section 10 — Implementation & Evaluation

**Both**
- [ ] Section 1 — Introduction
- [ ] Section 11 — Conclusion
- [ ] Cross-review all sections before submission
- [ ] Post arXiv preprint

---

### GitHub Labels

```
aws          (blue)
azure        (teal)
gcp          (orange)
paper        (purple)
infra        (gray)
engine       (yellow)
intelligence (red)
dashboard    (green)
keerthi      (pink)
rishika      (light blue)
```

---

## 13. Constraints & Guardrails

| Constraint | Rule |
|---|---|
| Cost | Every tool and service must be free. No exceptions. |
| Real billing data | Never commit real billing data to the repo. Use synthetic data only. |
| Intelligence layer scope | Waste detection and causal reasoning operate on structured billing + NEC data only — no external observability signals (Prometheus, CloudWatch) in Phase 2. |
| LangGraph / LangChain | Not in scope. Intelligence layer uses deterministic logic + confidence scoring — no LLM inference pipeline unless explicitly agreed. |
| PySpark | Not in demo. Mention as enterprise scale-out path in the paper only. |
| Work division | Phase 1 NEC / shared cost / intelligence layer → Keerthi Rapolu. Phase 1 tag / untagged / CI/CD → Rishika Naha. |
| Interface contracts | `intelligence/` module inputs/outputs must be agreed before implementation starts — do not code against undefined schemas. |
| AI use | Claude (VS Code integration) is acceptable for code + paper writing. Document usage in paper methodology section. |
| Paper scope | One unified framework paper covering both Phase 1 and Phase 2. Do not split into separate papers. |
| Dashboard pages 04–05 | Intelligence functionality (waste detection, causal reasoning, recommendations) is consolidated into pages 04 and 05 — both implemented after corresponding modules were tested. |

---

## Appendix A — Synthetic Data Schema

Synthetic data must match the real billing format closely enough to validate the normalization logic.

**AWS CUR synthetic columns (48 total — key ones):**
`bill/PayerAccountId`, `lineItem/UsageAccountId`, `lineItem/LineItemType`, `lineItem/ProductCode`, `lineItem/UsageStartDate`, `lineItem/UsageEndDate`, `lineItem/ResourceId`, `lineItem/UnblendedCost`, `lineItem/BlendedCost`, `lineItem/UsageAmount`, `lineItem/NormalizationFactor`, `lineItem/NormalizedUsageAmount`, `pricing/publicOnDemandCost`, `pricing/publicOnDemandRate`, `product/vcpu`, `product/memory`, `product/instanceType`, `product/region`, `reservation/ReservationARN`, `reservation/EffectiveCost`, `reservation/UnusedQuantity`, `reservation/UnusedRecurringFee`, `reservation/UnusedAmortizedUpfrontFeeForBillingPeriod`, `savingsPlan/SavingsPlanARN`, `savingsPlan/SavingsPlanEffectiveCost`, `savingsPlan/UsedCommitment`, `savingsPlan/TotalCommitmentToDate`, `savingsPlan/RecurringCommitmentForBillingPeriod`, `resourceTags/user:Team`, `resourceTags/user:Environment`, `resourceTags/user:CostCenter`

**Azure Cost Export synthetic columns (32 total — key ones):**
`BillingAccountId`, `SubscriptionId`, `SubscriptionName`, `AccountOwnerId`, `ResourceId`, `ResourceName`, `ResourceGroup`, `ConsumedService`, `MeterCategory`, `MeterSubcategory`, `MeterName`, `MeterId`, `ServiceFamily`, `ProductName`, `ResourceLocation`, `ChargeType`, `Date`, `CostInBillingCurrency`, `BillingCurrency`, `Quantity`, `Unit`, `UnitPrice`, `PricingModel`, `EffectivePrice`, `PayGPrice`, `BenefitId`, `BenefitName`, `Tags`, `AdditionalInfo` (contains vcpus JSON)

**GCP Billing Export synthetic columns (27 total — key ones):**
`billing_account_id`, `project.id`, `project.name`, `project.number`, `project.ancestry_numbers`, `service.id`, `service.description`, `sku.id`, `sku.description`, `usage_start_time`, `usage_end_time`, `location.region`, `location.zone`, `location.country`, `resource.name`, `resource.global_name`, `cost`, `cost_at_list`, `currency`, `usage.amount`, `usage.unit`, `usage.pricing_unit`, `credits`, `system_labels`, `labels`, `invoice.month`, `cost_type`

---

## Appendix B — FinOps Certification Alignment

Keerthi Rapolu is pursuing FinOps certification alongside this project. Relevant overlap:

| FinOps Domain | Paper Section | Module |
|---|---|---|
| Cost Allocation | Section 4 | `allocation/tag_allocator.py`, `allocation/shared_cost.py` |
| Rate Optimization (RI/SP) | Section 5 | `allocation/nec_model.py` |
| Usage Optimization | Section 6 | `allocation/untagged_heuristic.py` |
| Waste Identification | Section 7 | `intelligence/waste_detector.py` |
| Anomaly Detection / Root Cause | Section 8 | `intelligence/causal_engine.py` |
| Optimization Recommendations | Section 9 | `intelligence/impact_simulator.py` |
| Reporting & Analytics | Section 10 | `dashboard/` |

> The NEC modeling and waste detection work in this project directly supports FinOps certification study material on Reserved Instance / Savings Plan amortization and cloud efficiency optimization.

---

*Last updated: April 2026 — v2.1: Phase 2 complete; dashboard restructured to 5 pages (02_allocation, 03_tagging, 04_waste_recommendations, 05_insights); intelligence layer implemented and tested*
