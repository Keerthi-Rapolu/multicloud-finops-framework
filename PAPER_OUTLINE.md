# Paper Outline

**Title:** A Scalable Framework for Multi-Cloud Cost Allocation Using Data Engineering Principles

**Target venues:**
- arXiv preprint (immediate visibility — post first)
- IEEE CLOUD Conference
- ICDE / VLDB data engineering workshop track

**Authors:** Keerthi Rapolu, Rishika Naha

---

## Section Responsibilities

| Section | Owner | Status |
|---|---|---|
| 1 — Introduction | Both | [ ] |
| 2 — Background & Related Work | Rishika Naha | [ ] |
| 3 — Unified Cost Schema Design | Keerthi Rapolu | [ ] |
| 4 — Cost Allocation Strategies | Keerthi Rapolu | [ ] |
| 5 — Net Effective Cost Modeling | Keerthi Rapolu | [ ] |
| 6 — Untagged Resource Attribution | Rishika Naha | [ ] |
| 7 — Implementation & Evaluation | Rishika Naha | [ ] |
| 8 — Conclusion & Future Work | Both | [ ] |

---

## Section 1 — Introduction

- Multi-cloud growth trends across hyper-scalers (AWS, Azure, GCP)
- FinOps as a discipline (FinOps Foundation reference)
- Gap: no open-source, data-engineering-native cost allocation framework
- Paper contributions:
  - A Unified Cost Allocation Schema (CAS) mapping across all three cloud billing formats
  - A systematic field-mapping reference for AWS CUR, Azure Cost Management, and GCP Billing Export
  - NEC modeling methodology with per-cloud RI/SP/CUD amortization formulas
  - Three shared-cost distribution strategies (proportional, even, weighted) with empirical comparison
  - An untagged resource attribution engine combining heuristic rules and an optional ML classifier
  - An open-source reference implementation with a Streamlit dashboard and reproducible synthetic dataset

---

## Section 2 — Background & Related Work

**FinOps basics:**
- What FinOps is, the FinOps lifecycle (Inform → Optimize → Operate), FinOps Foundation principles

**Cloud cost optimization basics:**
- Cloud pricing models (on-demand, reserved, spot)
- Discount mechanisms (RI, Savings Plans, CUDs)
- Blended vs unblended vs net effective cost — why unblended is insufficient for chargeback

**Multi-cloud cost management:**
- Challenges of managing spend across hyper-scalers
- Schema heterogeneity, tagging inconsistencies, attribution gaps
- 30–50% untagged resource rates observed in practice

**Existing tools:**
- CloudHealth, Apptio, AWS Cost Explorer (closed-source, expensive)
- FinOps Foundation FOCUS schema — acknowledge but differentiate (FOCUS is a specification; this is a working implementation)

**Academic work:**
- Cloud cost modeling literature
- Our angle: open-source, reproducible, data-engineering-native

---

## Section 3 — Unified Cost Schema Design ← *core novelty*

- Schema normalization across all three clouds
- The 31-column CAS and design decisions
- Field mapping table (AWS CUR → CAS, Azure → CAS, GCP → CAS)
- Handling schema evolution (cloud providers change columns without notice)
- Key tradeoffs: hourly vs daily grain, list_cost semantics per cloud, discount column selection

**Why this matters:** No open-source tool systematically documents this mapping. Without it, engineers re-derive the same mappings independently — often incorrectly.

---

## Section 4 — Cost Allocation Strategies

- Tag-based direct allocation: when it works and when it fails
- Account/subscription/project-based allocation as a fallback
- Shared cost distribution algorithms with math:
  - Proportional: `team_share = team_direct_nec / total_direct_nec`
  - Even: `team_share = 1 / N`
  - Weighted: `team_share = team_weight / Σ weights`
- Tagging coverage analysis methodology
- Real-world challenges: missing tags, inconsistent naming, shared subscriptions
- Evaluation: strategy comparison on synthetic dataset showing allocation spread per team

---

## Section 5 — Net Effective Cost Modeling

- Why `unblended_cost` is wrong for RI/SP chargeback:
  - RI-covered hours: `unblended_cost = $0` — instance looks free
  - SP-covered hours: `unblended_cost = OD rate` — discount invisible
- NEC formula per cloud:
  - AWS: `reservation_effective_cost` / `savings_plan_effective_cost` / `unblended_cost`
  - Azure: amortized `billed_cost` with `UnusedReservation`/`UnusedSavingsPlan` → waste
  - GCP: `GREATEST(list_cost + Σ credits, 0)`
- Waste isolation: `nec_waste = idle commitment cost` (RI fee rows, unused SP/CUD slots)
- Validation: NEC output vs AWS Cost Explorer reference values
- Commitment utilization formula: `nec_used / (nec_used + nec_waste) * 100`

---

## Section 6 — Untagged Resource Attribution

- Problem scope: 30–50% of cloud resources lack team tags in real deployments
- Two-stage attribution approach:
  - **Stage 1 — Heuristic rules (deterministic):** resource name patterns → team assignment with confidence score
  - **Stage 2 — ML classifier (optional):** features from service, account, resource name; trained on tagged rows; `RandomForestClassifier`
- Feature engineering: `service_name`, `service_category`, `account_id`, resource name tokens, usage pattern
- Training data: tagged rows from the same account (no external label requirement)
- Evaluation: precision/recall on synthetic dataset with known labels
- When heuristics beat ML (sparse data, clear naming patterns) vs when ML wins (diverse accounts, ambiguous names)

---

## Section 7 — Implementation & Evaluation

- GitHub repo walkthrough and component overview
- Synthetic dataset statistics: 48-col AWS, 32-col Azure, 27-col GCP; configurable untagged % and RI/SP coverage
- Scenario analysis using named presets (`normal`, `untagged-heavy`, `ri-heavy`, `sp-heavy`, `full-month`)
- Dashboard screenshots: Overview, Team Allocation, Tagging Coverage, Shared Costs, Untagged Resources
- Pipeline performance: rows/sec, memory footprint on laptop hardware (DuckDB)
- Limitations:
  - Synthetic data approximates but does not perfectly replicate all real billing edge cases
  - GCP waste detection relies on `is_unused_reservation` system label which is not available in Standard Export
  - ML classifier requires sufficient tagged training data (sparse at low tagging coverage)
  - No real-time streaming — batch ingestion only

---

## Section 8 — Conclusion & Future Work

- Summary of contributions and open-source value
- FinOps certification context (RI/SP amortization aligns with FinOps certification study material)
- Enterprise scale-out path: replace DuckDB with Apache Spark; replace GitHub Actions with Airflow/Prefect
- Real-time cost allocation via streaming billing events (future)
- NL query interface over the mart (future — potential LangGraph integration)
- Open questions: cross-cloud RI arbitrage, optimal commitment sizing under variable workloads

---

## Writing notes

- Mention AI-assisted development (Claude, VS Code) in the methodology section — aligns with modern data engineering practice
- All figures should be reproducible from the open-source repo
- Include the CAS field-mapping table as a key reference table in the paper
- Target length: 10–12 pages (IEEE double-column format)
