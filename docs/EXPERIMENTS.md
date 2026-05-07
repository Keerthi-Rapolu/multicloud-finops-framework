# Experiments

This repository is positioned as a controlled research prototype and benchmark. The table below is the concise set of headline results surfaced in the README.

| Experiment | Result |
| --- | --- |
| Calibration | Utilization MAE 0.054 |
| Pre-Provision | Showcase CPS 0.500 |
| Runtime | $97.92 prevented in runaway ML scenario |
| IBD Detection | IFS F1 0.761 vs CPU baseline 0.605 |
| System Roll-up | Valid CPS 0.559; ESR 0.981 |
| Convergence | Peak CPS 0.733; 58x vs no-Phase-3 |

## Evaluation Scope

- Pre-provision intent inference and workload shaping
- Retrieval-augmented prevention decisions using FAISS KNN
- Runtime intervention behavior, including `AUTO_CORRECT`
- Metric roll-ups across CPS, ESR, and IFS
- Learning-loop convergence under repeated policy updates

## Reproduction Entry Points

```bash
python load_synthetic.py --month 2026-03 --scenario showcase --force
dbt run --project-dir dbt_project --full-refresh
pytest tests/ -v
streamlit run dashboard/app.py
```

Use the live application for reviewer-facing walkthroughs:

- https://intent-aware-cloud-governance.streamlit.app/
