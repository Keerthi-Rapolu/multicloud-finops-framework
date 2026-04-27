# Methodology

## Problem Statement

Multi-cloud FinOps tooling usually stops at descriptive reporting: spend is
visualized, but cross-cloud costs remain difficult to compare, ownership is
frequently incomplete, and optimization recommendations are rarely backed by a
reproducible scoring framework. This project addresses that gap by treating
cloud cost management as a decision-engine problem rather than a dashboard
problem.

## Formal Definitions

### Net Effective Cost (NEC)

For each cloud billing record, NEC is the normalized cost that reflects actual
economic consumption after cloud-specific discounts and commitment treatment.
NEC separates used cost from waste:

- `nec_used`: economically attributable cost consumed by workloads
- `nec_waste`: economically attributable idle commitment or unused capacity
- `nec = nec_used + nec_waste` at the scope level

### Waste

Waste is defined as the avoidable share of NEC attributable to one of four
deterministic classes:

- governance gap: unattributed NEC blocks reliable optimization
- idle resource: compute capacity is provisioned above observed need
- zombie resource: low-cost or stale resources remain allocated without purpose
- commitment mismatch: committed coverage exceeds realized demand

## Decision Optimization Framework

The decision engine is organized as a five-step pipeline:

1. Normalize billing and metadata into a cloud-agnostic NEC fact table.
2. Generate canonical signals at team and resource scope.
3. Map signals to root-cause classes and candidate actions.
4. Score each candidate using normalized savings, confidence, risk, urgency,
   and implementation effort.
5. Rank recommendations and persist structured evidence for auditability.

## Scoring Methodology

All bounded scores are normalized to the interval `[0, 1]` except
`effort_score`, which is an ordinal complexity score in `[1, 5]`.

### Confidence Score

`confidence_score = 0.40 * data_completeness + 0.35 * signal_strength + 0.25 * historical_stability`

### Risk Score

`risk_score = 0.35 * criticality + 0.25 * environment + 0.20 * sla + 0.20 * action_type`

### Urgency Score

`urgency_score = 0.60 * normalized_waste_growth_rate + 0.40 * normalized_anomaly_score`

### Priority Score

`priority_score = 0.35 * normalized_savings + 0.25 * confidence_score + 0.20 * (1 - risk_score) + 0.10 * urgency_score + 0.10 * (1 / effort_score)`

This formulation intentionally favors explainability over black-box optimization:
every recommendation can be reproduced from persisted signals and documented
weights.

## Forecasting Method

The forecast layer uses a weighted deterministic model:

- `MTD projection`: linear regression on daily cumulative NEC when at least
  seven daily observations are available
- `Historical projection`: trailing multi-month NEC trend
- `Final forecast`: `0.7 * MTD projection + 0.3 * historical projection`

Waste and unattributed projections are derived from recent weighted ratios, and
confidence intervals are calculated from residual error.

## Contributions

- Cross-cloud NEC normalization for AWS, Azure, and GCP
- Canonical decision signals materialized in SQL
- Reproducible recommendation scoring with explicit formulas
- Structured explanations instead of opaque narrative blobs
- Lightweight forecast with minimum-data checks and uncertainty bounds
- Separation of reporting, reasoning, and lifecycle-ready decision tables

## Why This Is a Decision Engine, Not a Dashboard

The dashboard is only a presentation layer. The core contribution is the
underlying decision system:

- canonical facts (`fct_signals`, `fct_recommendations`, `fct_month_end_forecast`)
- deterministic scoring
- structured explanations
- persistence-ready lifecycle fields

Because decisions are materialized independently of the UI, the system is
auditable, reproducible, and suitable for research positioning as an
explainable FinOps decision engine rather than a reporting interface.
