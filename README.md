# Multi-Cloud FinOps Decision Engine

> **A rule-based, explainable framework that converts multi-cloud billing data into prioritized, evidence-backed cost optimization decisions — with auditable scoring, realization-adjusted savings projection, and recommendation lifecycle tracking.**

**Authors:** Keerthi Rapolu and Rishika Naha  
**Date:** April 2026  
**Status:** Research prototype — reproducible synthetic benchmark, open methodology

[![CI](https://github.com/Keerthi-Rapolu/multicloud-finops-framework/actions/workflows/ci.yml/badge.svg)](https://github.com/Keerthi-Rapolu/multicloud-finops-framework/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)
[![dbt](https://img.shields.io/badge/dbt-DuckDB-orange.svg)](https://www.getdbt.com/)

---

> **This is not a dashboard — it is a decision system with explainable reasoning and execution tracking.**

### Why this matters

- Most FinOps tools show cost data. They do not tell you what to do about it.
- Engineers spend hours interpreting dashboards before they can act.
- This system converts billing data into prioritized, evidence-backed decisions — with confidence scores, risk reasons, and lifecycle tracking per recommendation.
- The savings pipeline is strictly separated: raw signal ≠ recoverable ≠ actionable ≠ projected. Collapsing these into one number, as most tools do, produces estimates that cannot be safely acted on.

---

## Live Demo

**[multicloud-finops-framework.streamlit.app](https://multicloud-finops-framework.streamlit.app/)**

The live app runs against the reproducible synthetic benchmark committed to this repo. What you will see:

- **Portfolio overview** — NEC, Optimized NEC (realization-adjusted), commitment waste, and daily cost trend with anomaly markers per cloud
- **Decision engine** — savings pipeline (signal → recoverable → actionable → projected), team decision cards with root cause, evidence, and confidence score
- **Prioritized recommendations** — ranked action table with savings estimate, risk score, approval posture, effort, and time-to-savings per action
- **Action lifecycle tracker** — full state machine from `recommended → approved → implemented → verified`, with realized vs projected savings comparison
- **Attribution governance** — unattributed NEC %, tagging coverage by cloud and service, SLA escalation tracker

> Run `make demo` to reproduce locally, or deploy `dashboard/` to [Streamlit Community Cloud](https://streamlit.io/cloud) for free.

---

## What This System Does

Most cloud cost tools answer **"how much did we spend?"**

This system answers **"what should we do about it, why, and how confident are we?"**

It ingests AWS, Azure, and GCP billing exports, normalizes them into a canonical cost model, then runs a four-stage intelligence pipeline:

| Stage | Input | Output |
|---|---|---|
| **1. Waste detection** | Billing rows | Typed inefficiency signals per resource |
| **2. Causal reasoning** | Billing patterns | Ranked root causes per team, with evidence |
| **3. Impact simulation** | Waste signals | Prioritized recommendations with savings estimates and risk scores |
| **4. Realization modeling** | Recommendations | Projected savings adjusted for execution probability |

Every decision is **explainable**: each recommendation carries its evidence source, confidence score, risk reason, approval posture, and next-best action — not just a dollar number.

---

## The Problem

Multi-cloud billing is fragmented. AWS, Azure, and GCP expose different schemas, discount semantics, and attribution fields. Existing tools can show **where** money was spent. They almost never answer:

- **What portion of spend is unattributed** and therefore not optimization-ready?
- **Which inefficiency signals are technically recoverable** after risk and feasibility filters?
- **What month-end cost is likely** if no action is taken vs. if recommended actions are executed?
- **What evidence supports each recommendation**, and how confident should we be?

Without these answers, engineers interpret dashboards instead of acting on them.

---

## Key Innovation

### 1. Separated savings layers — not a single "savings" number

```
Inefficiency signal  →  Recoverable opportunity  →  Actionable savings  →  Realization-adjusted projection
    (raw billing)          (× recovery rate)         (low/med risk only)       (× execution probability)
```

Each layer is strictly smaller than the previous, computed separately, and labeled explicitly. Collapsing these into a single figure — as most tools do — produces numbers that cannot be acted on safely.

### 2. Deterministic, auditable scoring

Every recommendation is produced by a canonical signal/action pair. The priority score is fully auditable:

```
priority_score = 0.35 × normalized_savings
               + 0.25 × confidence
               + 0.20 × governance_severity
               + 0.10 × urgency
               + 0.10 × low_risk_bonus
```

Governance signals (attribution gaps, tagging failures) are scored separately from optimization signals (commitment waste, idle compute) and never ranked against each other.

### 3. Recommendation lifecycle with realized-savings validation

The system tracks the full lifecycle: `recommended → approved/rejected → implemented → verified`. Realized savings are compared against projected savings to calibrate the realization rate for future recommendations — a closed feedback loop absent from most FinOps tools.

---

## Results — Reproducible Benchmark

On the synthetic multi-cloud dataset shipped in this repo (4 billing months, ~28,000 rows, AWS + Azure + GCP):

- **~$7,500/month unattributed cost identified** — 58% of NEC is not tied to an accountable team, making optimization unreliable until fixed
- **~$1,500/month recoverable opportunity detected** — commitment waste and idle compute signals after recovery rates applied
- **~$947/month realistic savings projection** — after execution probability and risk filters (62–70% realization rate)
- **19 prioritized recommendations** — each with risk score, approval posture, effort estimate, and time-to-savings
- **103 canonical signals** across 5 teams, deduplicated and ranked by deterministic scoring formula
- **Forecast confidence scored 0–1** — derived from data quality, signal strength, and historical stability

> All figures are from the reproducible synthetic benchmark. Run `make demo` to reproduce locally.

---

## Architecture

```mermaid
flowchart LR
    A["Synthetic AWS / Azure / GCP billing data"]
    B["dbt staging + intermediate normalization"]
    C["fct_unified_billing NEC mart"]
    D["fct_finops_signals"]
    E["fct_finops_recommendations"]
    F["fct_finops_decisions"]
    G["fct_action_lifecycle"]
    H["fct_month_end_forecast"]
    I["fct_forecast_backtest"]
    J["fct_model_accuracy"]
    K["fct_finops_decision_metrics"]
    L["Streamlit dashboard"]

    A --> B --> C
    C --> D --> E --> F
    E --> G
    C --> H
    H --> I
    G --> J
    E --> J
    F --> K
    G --> K
    H --> K
    J --> K
    K --> L
```

Five pipeline stages:

1. **Ingest** — synthetic AWS CUR, Azure Cost Export, GCP Billing Export validated and landed to Parquet
2. **Normalize** — dbt staging and intermediate models unify billing semantics and compute NEC per cloud
3. **Materialize** — `fct_unified_billing`: a 31-column Unified Cost Allocation Schema queryable in DuckDB
4. **Compute** — canonical signals, recommendations, decisions, lifecycle rows, forecasts, backtest rows
5. **Render** — Streamlit reads canonical marts; no page recomputes business logic

---

## Quick Start

```bash
# Clone and install
git clone https://github.com/Keerthi-Rapolu/multicloud-finops-framework.git
cd multicloud-finops-framework
pip install -r requirements.txt

# Build data + marts + tests + dashboard (single command)
make demo
```

```bash
# Or run stages individually
make data        # generate and validate synthetic billing CSVs
make dbt         # run dbt models → finops_dbt.duckdb
make test        # pytest full test suite
make dashboard   # streamlit run dashboard/app.py
```

---

## What Is Different From Existing Tools

| Capability | Most FinOps tools | This system |
|---|---|---|
| Multi-cloud normalization | Dashboard only | Canonical 31-column CAS with per-cloud NEC formulas |
| Savings estimate | Single number | 4-layer separated pipeline (signal → recoverable → actionable → projected) |
| Recommendation scoring | Heuristic / opaque | Deterministic formula, fully auditable |
| Attribution governance | Tagging % only | Unattributed NEC %, SLA escalation, owner assignment tracking |
| Explainability | "You can save $X" | Root cause + evidence + confidence + risk reason + next-best action per rec |
| Realization modeling | None | Execution probability applied; confidence floor scenario |
| Lifecycle tracking | None | recommended → approved → implemented → verified with realized vs projected |
| Forecast validation | None | `fct_forecast_backtest` compares projections against actuals |
| Reproducibility | Vendor-dependent | Fully reproducible: synthetic data + dbt + DuckDB + deterministic Python |

---

## Intelligence Layer

### 1. Waste Detection Engine

Classifies every resource across four waste categories:

| Waste Type | Detection Logic | Typical Cause |
|---|---|---|
| `unused_commitment` | `is_commitment_waste = true` with `nec_waste > threshold` | RI or SP purchased beyond actual usage |
| `idle_compute` | Compute rows with `nec_used / vcpu` below idle floor | Over-provisioned instance left running without load |
| `zombie_resource` | `0 < nec_used < monthly_floor` for full billing period | Forgotten resource — not decommissioned |
| `underutilized_commitment` | RI/SP rows where `used / total_commitment < utilization_threshold` | Commitment purchased for a workload later downsized |

Each finding carries an `estimated_waste` amount, a `confidence` score (0–1), and `allocated_team` from the attribution layer.

### 2. Causal Reasoning Engine

Explains **why** a team's cost looks the way it does. For each team it produces a `CausalInsight` containing:

- **Root causes** — ordered list with `fact_type`, human-readable description, and `confidence`
- **MoM trend signal** — direction and magnitude of month-over-month NEC change (requires ≥ 2 months)
- **Anomaly flag** — z-score deviation from rolling baseline; score ≥ 2.0 triggers an anomaly explanation

### 3. Impact Simulation Engine

Converts findings into prioritized recommendations using conservative recovery rates:

| Action | Recovery Rate | Risk Level |
|---|---|---|
| `release_commitment` (unused) | 100% of `nec_waste` | Low |
| `resize_down` (idle compute) | 60% of waste signal | Low |
| `remove_resource` (zombie) | 90% of `nec_used` | Medium |
| `release_commitment` (underutilized) | 50% of waste signal | Medium |

### 4. Explainable Decision Support Layer

- **Reasoning engine** — structured decisions with `root_cause`, `evidence`, `recommended_action`, `action_justification`, `confidence_score`, `risk_score`, `approval_required`, `next_best_action`
- **Lightweight forecasting** — projects month-end NEC and action-adjusted savings using weighted smoothing (`0.7 × run_rate + 0.3 × trailing_3m_avg`)
- **Action lifecycle tracking** — `recommended → approved/rejected → implemented → verified` with owner, expected savings, realized savings, and verification notes

---

## Project Structure

```
multicloud-finops-framework/
│
├── load_synthetic.py           # Pipeline entry point: generate → validate → land
├── build_mart.py               # DuckDB mart builder (all canonical tables)
├── Makefile
├── requirements.txt
│
├── scripts/                    # Synthetic data generators per cloud
├── ingestion/                  # Schema validators + Parquet writers per cloud
│
├── dbt_project/models/
│   ├── staging/                # Bronze: rename, cast, extract tags
│   ├── intermediate/           # Silver: NEC / RI / SP amortization
│   └── marts/                  # Gold: fct_unified_billing + all canonical tables
│
├── allocation/                 # Python allocation engine
│   ├── nec_model.py            # NEC aggregations
│   ├── shared_cost.py          # Shared cost distribution (3 strategies)
│   ├── tag_allocator.py        # Tag-based direct allocation
│   └── untagged_heuristic.py   # Rule-based attribution for untagged rows
│
├── intelligence/               # Cost intelligence layer
│   ├── waste_detector.py       # Idle / zombie / underutilized detection
│   ├── causal_engine.py        # Root cause reasoning over billing patterns
│   ├── impact_simulator.py     # Savings estimation + risk scoring
│   ├── forecasting.py          # Month-end NEC projection
│   └── reasoning_engine.py     # Explainable decision output
│
├── dashboard/
│   ├── app.py                  # Home page (executive summary)
│   ├── _shared.py              # Canonical helpers, savings hierarchy, scoring
│   └── pages/
│       ├── 01_overview.py
│       ├── 02_allocation.py
│       ├── 03_tagging.py
│       ├── 04_waste_recommendations.py
│       └── 05_insights.py
│
├── tests/                      # Full test suite (NEC, shared cost, waste, causal, impact)
├── config/                     # waste_thresholds.yml, shared_cost_weights.yml, heuristic_rules.yml
└── docs/                       # MkDocs → GitHub Pages
```

---

## Technology Stack

| Layer | Tool | Why |
|---|---|---|
| Data transform | **dbt Core + DuckDB** | SQL-first, version-controlled, runs entirely in-process |
| Processing | **Python 3.11 + pandas + PyArrow** | Parquet I/O, schema validation, allocation engine |
| Intelligence | **Python + NumPy + PyYAML** | Deterministic — no LLM, no black box |
| Dashboard | **Streamlit + Plotly** | Python-native, free Streamlit Cloud deploy |
| Orchestration | **GitHub Actions** | CI on push + weekly synthetic pipeline run |
| ML (optional) | **scikit-learn** | `RandomForestClassifier` for untagged resource attribution |

Everything runs free. No cloud compute, no paid APIs, no proprietary SaaS.

---

## Canonical Definitions

| Term | Definition |
|---|---|
| `list_cost` | Pre-discount cloud cost (on-demand rate) |
| `nec` | Net Effective Cost — actual billed cost after commitment pricing |
| `nec_used` | NEC for capacity actually consumed |
| `nec_waste` | NEC for idle RI/SP commitment capacity |
| `unattributed_nec` | NEC without accountable team attribution |
| `waste_signal` | Raw detected inefficiency magnitude — before recovery or execution filters |
| `recoverable_savings` | Technically recoverable amount after recovery rate applied |
| `actionable_savings` | Risk-screened savings — low and medium risk only |
| `projected_savings` | Realization-adjusted expected savings (× execution probability) |
| `optimized_nec` | Projected month-end NEC minus projected savings |
| `commitment_waste` | Unused RI, SP, or CUD capacity |
| `tagging_gap` | Unattributed NEC ÷ NEC |
| `waste_rate` | Commitment waste ÷ NEC |

See [docs/NEC_CALCULATIONS.md](docs/NEC_CALCULATIONS.md) for per-cloud NEC formulas and [DESIGN_DOCUMENT.md](DESIGN_DOCUMENT.md) for the full CAS schema.

---

## Reproducibility

- Synthetic billing data for 4 months is committed to the repo — no credentials required
- dbt models produce all canonical marts from source CSVs
- Python reasoning and forecast layers are fully deterministic
- Tests validate numeric consistency, scoring determinism, and cross-mart invariants
- Forecast outputs are backtested against historical synthetic months (`fct_forecast_backtest`)
- Lifecycle rows are persisted locally and re-materialized into canonical marts on rebuild

Six named data scenarios cover normal, untagged-heavy, RI-heavy, SP-heavy, and full-month configurations. Run any with:

```bash
make pipeline SCENARIO=untagged-heavy MONTH=2026-04
```

---

## Evaluation Metrics

The system reports evaluation-oriented metrics, not unsupported production claims:

- Attribution coverage % and unattributed NEC %
- Commitment waste % of NEC
- Recoverable, actionable, and projected savings (separated layers)
- Recommendation counts, risk breakdown, and actionability rate
- Confidence-weighted projected savings
- Forecast confidence score and bounded projection range
- Forecast backtest error metrics (`fct_forecast_backtest`)
- Action lifecycle accuracy (`fct_action_lifecycle` + `fct_model_accuracy`)

---

## Limitations

- Synthetic dataset — treat as a reproducible benchmark, not enterprise validation
- No autonomous remediation — the system produces recommendations and lifecycle state only
- `idle_compute_proxy` is billing-derived and does not use runtime CPU/memory telemetry; telemetry-backed detection is phase 2 work
- Real-world validation pending — current evaluation is against synthetic benchmark only

**Future work:** CloudWatch / Azure Monitor / GCP Monitoring telemetry, deployment/change correlation, unit economics, production persistence for approval workflows, Jira/ServiceNow integration.

---

## Scope Boundary

This repository covers post-billing FinOps: normalization, NEC modeling, allocation, tagging governance, waste detection, recommendation scoring, month-end forecasting, and action lifecycle validation.

It does **not** implement intent-aware provisioning, runtime optimization, vector search, or LLM-based policy reasoning. Those belong to the separate `intent-aware-cloud-governance` repository.

---

## Research Paper

> **A Multi-Cloud Cost Intelligence Framework: Attribution, Waste Detection, Causal Reasoning, and Impact Simulation**  
> Keerthi Rapolu, Rishika Naha — 2026

**Phase 1:** Unified Cost Allocation Schema (CAS), per-cloud NEC amortization formulas, three shared-cost distribution strategies, two-stage untagged resource attribution.

**Phase 2:** Taxonomy-driven waste detection, causal reasoning with MoM trend and anomaly detection, 4-layer impact simulation with deterministic scoring, recommendation lifecycle with realized-savings calibration.

---

## Documentation

| Doc | What it covers |
|---|---|
| [docs/STAGING.md](docs/STAGING.md) | Every column in `stg_aws_cur`, `stg_azure_cost`, `stg_gcp_billing` |
| [docs/NEC_CALCULATIONS.md](docs/NEC_CALCULATIONS.md) | NEC formulas per cloud with worked dollar examples |
| [docs/AWS_CUR_REFERENCE.md](docs/AWS_CUR_REFERENCE.md) | AWS CUR column reference, RI/SP cost flow |
| [docs/AZURE_COST_REFERENCE.md](docs/AZURE_COST_REFERENCE.md) | Azure amortized vs actual export, RI/SP daily row mechanics |
| [docs/GCP_BILLING_REFERENCE.md](docs/GCP_BILLING_REFERENCE.md) | GCP credits JSON structure, CUD/SUD mechanics |
| [DESIGN_DOCUMENT.md](DESIGN_DOCUMENT.md) | Full architecture, CAS schema decisions, module design |

---

## CI

On every push to `main` or `dev`, GitHub Actions runs:

1. `pytest tests/ -v` — full test suite
2. `python load_synthetic.py --month 2026-03 --force` — smoke test all three cloud schemas
3. `dbt run` — materialize all models
4. `dbt test` — run dbt schema tests

---

## License

MIT
