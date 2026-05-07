# PBCP — Pre-Billing Cost Prevention Framework

> Intent-aware cloud governance system that prevents compute waste before billing using hybrid NLP, FAISS KNN retrieval, and decision-theoretic intervention.

<div align="center">

![Research Prototype](https://img.shields.io/badge/Research_Prototype-Evaluation-blue)
![Streamlit Demo](https://img.shields.io/badge/Streamlit-Demo-ff4b4b?logo=streamlit&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FAISS](https://img.shields.io/badge/FAISS-KNN-0b7285)
![DuckDB](https://img.shields.io/badge/DuckDB-Analytics-f7c948)
![Cloud Governance](https://img.shields.io/badge/Cloud-Governance-0f766e)

[![Live Demo](https://img.shields.io/badge/Live_Demo-Launch-0ea5e9?style=for-the-badge&logo=streamlit&logoColor=white)](https://intent-aware-cloud-governance.streamlit.app/)
[![Design Document](https://img.shields.io/badge/Design-Document-111827?style=for-the-badge)](DESIGN_DOCUMENT.md)
[![Experiments](https://img.shields.io/badge/Research-Experiments-1d4ed8?style=for-the-badge)](docs/EXPERIMENTS.md)
[![Source Code](https://img.shields.io/badge/Source-Code-059669?style=for-the-badge&logo=github&logoColor=white)](./)

</div>

> PBCP is a controlled cloud systems research prototype and evaluation benchmark. It is not a production governance platform. Production deployment would require calibration against an organization's own telemetry and enforcement stack.

[![Launch Live Demo](assets/pbcp_demo_banner.png)](https://intent-aware-cloud-governance.streamlit.app/)

<!-- Add assets/pbcp_live_demo.gif here after recording a short Streamlit walkthrough -->

## What PBCP Does

- Infers workload intent from natural-language descriptions before infrastructure is provisioned.
- Predicts waste before provisioning by retrieving similar historical cases with FAISS KNN and running pre-execution simulation.
- Applies `BLOCK`, `AUTO_CORRECT`, `SUGGEST`, or `PASS` interventions through an expected-value decision engine.
- Tracks impact using CPS, ESR, and IFS across prevention, runtime correction, and policy learning.

## Why This Matters

A concise example: a user submits a 20-node cluster request for a job whose intent and expected runtime do not justify that footprint. Traditional FinOps surfaces the waste after the month closes. PBCP intervenes before billing, either blocking the request or auto-correcting it to a lower-cost configuration.

## Architecture

PBCP is organized around a simple loop: **Prevent -> Correct -> Learn**.

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

- **Prevent**: infer intent, retrieve similar workloads, simulate expected cost and behavior, and decide whether to block or reshape the request.
- **Correct**: apply runtime interventions such as `AUTO_CORRECT` when live behavior diverges from declared intent.
- **Learn**: update policy quality using downstream CPS and IFS outcomes.

## Evaluation Notes

- **IFS** is the cosine similarity between intent embeddings and behavior embeddings.
- Dashboard sub-scores provide interpretability only; they are not the canonical research definition of IFS.

## Key Results

| Experiment | Result |
| --- | --- |
| Calibration | Utilization MAE 0.054 |
| Pre-Provision | Showcase CPS 0.500 |
| Runtime | $97.92 prevented in runaway ML scenario |
| IBD Detection | IFS F1 0.761 vs CPU baseline 0.605 |
| System Roll-up | Valid CPS 0.559; ESR 0.981 |
| Convergence | Peak CPS 0.733; 58x vs no-Phase-3 |

## Dashboard

| Overview | Prevention Engine |
| --- | --- |
| [![Overview](assets/screenshots/overview.png)](https://intent-aware-cloud-governance.streamlit.app/) | [![Prevention Engine](assets/screenshots/prevention_engine.png)](https://intent-aware-cloud-governance.streamlit.app/) |

| Runtime & Savings | Learning System |
| --- | --- |
| [![Runtime Savings](assets/screenshots/runtime_savings.png)](https://intent-aware-cloud-governance.streamlit.app/) | [![Learning System](assets/screenshots/learning_system.png)](https://intent-aware-cloud-governance.streamlit.app/) |

## Quick Start

```bash
git clone https://github.com/Keerthi-Rapolu/multicloud-finops-framework.git
cd multicloud-finops-framework
pip install -r requirements.txt

# Generate the benchmark dataset
python load_synthetic.py --month 2026-03 --scenario showcase --force

# Run the benchmark pipeline
dbt run --project-dir dbt_project --full-refresh
pytest tests/ -v

# Launch Streamlit
streamlit run dashboard/app.py
```

## Repository Structure

- `intent_model/` - intent parsing, embeddings, and retrieval hooks
- `simulation_engine/` - pre-execution simulation components
- `policy_engine/` - intervention policy and expected-value decisions
- `runtime_optimizer/` - runtime correction logic
- `cps_metrics/` - prevention metrics and roll-up scoring
- `evaluation/` - experiment runners and evaluation outputs
- `dashboard/` - Streamlit application
- `data/` - synthetic datasets and benchmark artifacts
- `config/` - thresholds, scenarios, and configuration

## Further Reading

- [Technical Details](docs/TECHNICAL_DETAILS.md)
- [Experiments](docs/EXPERIMENTS.md)
- [Dashboard Guide](docs/DASHBOARD_GUIDE.md)

## Citation

```bibtex
@misc{rapolu2026pbcp,
  title  = {PBCP: A Pre-Billing Cost Prevention Framework for Intent-Aware Cloud Governance},
  author = {Rapolu, Keerthi and Katta, Sreeja},
  year   = {2026},
  note   = {IACG v2.0 Research Prototype}
}
```
