# Technical Details

This note keeps the main README short. It captures the research-facing definitions and the mapping from the conceptual PBCP pipeline to the current implementation layout in this repository.

## Canonical Definitions

- **IFS**: cosine similarity between intent embeddings and behavior embeddings.
- **CPS**: prevention-oriented cost impact metric used to quantify how much avoidable spend was prevented.
- **ESR**: execution and savings realization metric used in system roll-ups.

Dashboard sub-scores are interpretability aids. They should not replace the canonical research definitions above.

## Core Pipeline

```text
Natural Language Workload
-> Intent Inference
-> FAISS KNN Retrieval
-> Pre-Execution Simulation
-> EV Decision Engine
-> Runtime Optimizer
-> CPS + IFS Tracking
-> Policy Learning Loop
```

## Intervention Surface

- `BLOCK`: reject a request before provisioning.
- `AUTO_CORRECT`: rewrite the configuration to a safer or cheaper option.
- `SUGGEST`: surface a recommended change and rationale.
- `PASS`: allow the workload unchanged.

## Repository Mapping

The conceptual PBCP framing is intentionally concise in the README. In the current checkout, the closest code locations are:

- `intent_model/`
- `simulation_engine/`
- `policy_engine/`
- `runtime_optimizer/`
- `cps_metrics/`
- `dashboard/`
- `evaluation/`
- `data/`
- `config/`

Some folders retain legacy naming from earlier iterations of the project, but the README now presents them through the PBCP/IACG v2.0 research framing.

## Design Material

For the longer design narrative, see [../DESIGN_DOCUMENT.md](../DESIGN_DOCUMENT.md).
