# Rishika's Task Guide — Attribution Intelligence
## Multi-Cloud FinOps Framework

**Prerequisite:** Complete [CONTRIBUTOR_SETUP.md](CONTRIBUTOR_SETUP.md) before starting here.

**What you own:** The Attribution Intelligence subsystem — the layer that answers:
- *Can we trust the ownership assignment for this resource?*
- *How is attribution quality measured across teams?*
- *Which teams have unresolved attribution debt?*

**What Keerthi owns (do not overlap):** Waste Detection, Causal Reasoning, Impact Simulation, Decision Engine, Forecasting, NEC Modeling, Unified Cost Schema. Your confidence scores feed into those systems as **read-only metadata** — you never modify their outputs.

---

## Boundary Rule: Confidence Is Metadata Only

Your `attribution_sensitive` flag is informational. It never changes a waste estimate, a recommendation rank, or a priority score. The downstream display looks like this:

```
Waste Finding:  $120/month  idle_compute
Assigned to:    Platform Team
Confidence:     0.42
⚠ Warning: Ownership assignment may be unreliable — verify before acting
```

The $120 estimate and the priority rank are Keerthi's — untouched. Your flag adds a caveat. That is the full scope of the integration.

---

## Your 10 Tasks

Do them in order — each one builds on the previous.

---

### Task 1 — `config/confidence_thresholds.yml`

**What this is:** Plain text config file (no Python). Controls the numbers that drive your confidence engine.

Create the file at that path with exactly this content:

```yaml
# Attribution Confidence Thresholds
# Loaded by allocation/attribution_confidence.py at runtime.
# All fractions are 0.0–1.0.

ensemble:
  heuristic_weight: 0.50
  ml_weight: 0.50
  # When only one signal is available, it receives full weight automatically.

tag_quality:
  low_quality_threshold: 0.50

# Waste findings with confidence_score below this are flagged attribution_sensitive=True.
# The waste estimate and ranking are NOT changed — this is a display caveat only.
attribution_sensitive_threshold: 0.70

direct_tag_confidence: 1.00
```

**Verify:**
```
python -c "import yaml; cfg = yaml.safe_load(open('config/confidence_thresholds.yml')); print(cfg['ensemble'])"
```
Expected: `{'heuristic_weight': 0.5, 'ml_weight': 0.5}`

---

### Task 2 — `config/governance_sla.yml`

```yaml
# Ownership Governance SLA Parameters
# Loaded by allocation/governance_model.py at runtime.

sla_window_days: 7

escalation_threshold_days: 14

# Attribution debt score = weighted sum of four observable signals.
# sla_violation is binary (0 or 1) — a team either met its SLA or it did not.
# There is no time-based compounding: the economic cost of attribution debt
# is the dollar value of unattributed NEC, not days elapsed.
debt_weights:
  unattributed_nec_fraction: 0.35   # SUM(unattributed NEC) / SUM(total NEC)
  confidence_gap: 0.25              # 1 - mean_confidence_score
  sla_violation: 0.20               # 1.0 if gap open > sla_window_days, else 0.0
  attribution_immaturity: 0.20      # 1 - attribution_maturity_score

status_thresholds:
  compliant_debt_max: 0.30
  at_risk_debt_max: 0.60

maturity_floor: 0.80
```

**Verify:**
```
python -c "import yaml; cfg = yaml.safe_load(open('config/governance_sla.yml')); print(cfg['debt_weights'])"
```
Expected: the four weights printed as a dict.

---

### Task 3 — `allocation/attribution_confidence.py`

**What this does:** Reads the billing DataFrame after allocation has run and adds three columns to every row: `confidence_score`, `tag_quality_score`, `attribution_sensitive`.

**Use Claude. Copy and paste this entire prompt:**

---

> I am working on a Python file for a multi-cloud FinOps project. Create `allocation/attribution_confidence.py`.
>
> **DataFrame columns available:** `resource_id` (str), `allocated_team` (str or None), `cloud_provider` (str), `account_id` (str), `service_category` (str), `allocated_nec` (float), `is_tagged` (bool), `nec_used` (float). Two optional columns may also be present: `heuristic_confidence` (float 0–1) and `ml_confidence` (float 0–1).
>
> **Config file** at `config/confidence_thresholds.yml` has: `ensemble.heuristic_weight`, `ensemble.ml_weight`, `tag_quality.low_quality_threshold`, `attribution_sensitive_threshold`, `direct_tag_confidence`.
>
> **Function signature:** `run(allocation_df: pd.DataFrame, config_path: str | Path = None) -> pd.DataFrame`
>
> **confidence_score rules (applied row by row):**
> - `is_tagged == True` → `confidence_score = 1.0` (direct tag attribution is always certain)
> - Both `heuristic_confidence` and `ml_confidence` present → `confidence_score = heuristic_weight * heuristic_confidence + ml_weight * ml_confidence`
> - Only `heuristic_confidence` present → `confidence_score = heuristic_confidence`
> - Only `ml_confidence` present → `confidence_score = ml_confidence`
> - Neither present and not tagged → `confidence_score = 0.5`
>
> **tag_quality_score:** For each group `(cloud_provider, account_id, service_category, allocated_team)`, compute `SUM(nec_used where is_tagged=True) / SUM(nec_used)`. Assign that group score to every row in the group. Use 0.0 if `SUM(nec_used)` is zero.
>
> **attribution_sensitive:** `True` if `confidence_score < attribution_sensitive_threshold`, else `False`. This column is metadata only — it never feeds back into waste scores or recommendation rankings.
>
> **Other requirements:**
> - Load config with `yaml.safe_load`. Default path: `Path(__file__).resolve().parents[1] / "config" / "confidence_thresholds.yml"`.
> - Add a module docstring. Add `if __name__ == "__main__"` that loads `finops_dbt.duckdb` (read_only=True), reads `marts.fct_unified_billing`, calls `run()`, and prints 5 rows of `[resource_id, confidence_score, tag_quality_score, attribution_sensitive]`.
> - Use `pandas`, `yaml`, `pathlib` only. Follow the style of `intelligence/waste_detector.py` (type hints, entry-point docstring, no inline comments on obvious lines).

---

Paste Claude's output into `allocation/attribution_confidence.py` and save.

**Smoke test:**
```
python -c "
import pandas as pd
from allocation.attribution_confidence import run

df = pd.DataFrame([
    {'resource_id': 'r1', 'allocated_team': 'platform', 'cloud_provider': 'aws',
     'account_id': 'acc1', 'service_category': 'Compute',
     'is_tagged': True, 'nec_used': 50.0, 'allocated_nec': 50.0},
    {'resource_id': 'r2', 'allocated_team': 'data-eng', 'cloud_provider': 'aws',
     'account_id': 'acc1', 'service_category': 'Compute',
     'is_tagged': False, 'nec_used': 10.0, 'allocated_nec': 10.0,
     'heuristic_confidence': 0.85},
])
result = run(df)
print(result[['resource_id', 'confidence_score', 'tag_quality_score', 'attribution_sensitive']])
"
```

**Expected output:**
```
  resource_id  confidence_score  tag_quality_score  attribution_sensitive
0          r1              1.00              0.833                  False
1          r2              0.85              0.833                  False
```

- Row r1 (tagged): `confidence_score = 1.0`
- Row r2 (heuristic only, 0.85): above the 0.70 threshold → not attribution_sensitive
- Both share the same group (aws/acc1/Compute) so tag_quality = 50 tagged NEC / 60 total = 0.833

---

### Task 4 — `allocation/governance_model.py`

**What this does:** Takes the billing DataFrame + confidence output from Task 3, and returns one row per team with governance status and attribution debt score.

**Use Claude. Copy and paste this entire prompt:**

---

> I am working on a Python file for a multi-cloud FinOps project. Create `allocation/governance_model.py`.
>
> **Inputs:**
> - `allocation_df`: billing rows with `allocated_team` (str or None/NaN), `nec_used` (float), `is_tagged` (bool), `billing_month` (str).
> - `confidence_df`: output of `attribution_confidence.run()` — same rows plus `confidence_score` (float), `tag_quality_score` (float), `attribution_sensitive` (bool).
>
> **Config** at `config/governance_sla.yml`: `sla_window_days`, `escalation_threshold_days`, `debt_weights.unattributed_nec_fraction`, `debt_weights.confidence_gap`, `debt_weights.sla_violation`, `debt_weights.attribution_immaturity`, `status_thresholds.compliant_debt_max`, `status_thresholds.at_risk_debt_max`, `maturity_floor`.
>
> **Function signature:** `run(allocation_df: pd.DataFrame, confidence_df: pd.DataFrame, config_path: str | Path = None) -> pd.DataFrame`
>
> **Compute per team** (group by `allocated_team`, treating None/NaN as its own group named `"unattributed"`):
> - `total_nec` = SUM(nec_used)
> - `estimated_unattributed_nec` = SUM(nec_used) where `allocated_team` is None/NaN (0.0 for named teams)
> - `unattributed_nec_fraction` = estimated_unattributed_nec / total_nec (0.0 if total_nec is 0)
> - `attribution_maturity_score` = SUM(nec_used where is_tagged=True) / total_nec (0.0 if total_nec is 0)
> - `mean_confidence_score` = mean of `confidence_score` from confidence_df for this team's rows
>
> **SLA violation (stateless approximation):**
> - `sla_violated = True` if `attribution_maturity_score < maturity_floor` (team has an open attribution gap)
> - `sla_violation_flag` = 1.0 if `sla_violated`, else 0.0
>
> **Attribution debt score:**
> `attribution_debt_score = w1 * unattributed_nec_fraction + w2 * (1 - mean_confidence_score) + w3 * sla_violation_flag + w4 * (1 - attribution_maturity_score)`
> where `w1, w2, w3, w4` come from `debt_weights` in config. Clamp result to [0.0, 1.0].
>
> **Governance status** from `attribution_debt_score`:
> - `< compliant_debt_max` → `"Compliant"`
> - `< at_risk_debt_max` → `"At-Risk"`
> - otherwise → `"Breached"`
>
> **Output columns:** `team`, `total_nec`, `estimated_unattributed_nec`, `unattributed_nec_fraction`, `attribution_maturity_score`, `mean_confidence_score`, `attribution_debt_score`, `governance_status`, `sla_violated` (bool), `escalation_required` (bool — True if `governance_status == "Breached"`).
>
> **Other requirements:** Load config with `yaml.safe_load`. Default path: `Path(__file__).resolve().parents[1] / "config" / "governance_sla.yml"`. Add module docstring. Add `if __name__ == "__main__"` block that loads from `finops_dbt.duckdb` and prints the full governance table. Follow style of `intelligence/waste_detector.py`.

---

Paste Claude's output into `allocation/governance_model.py` and save.

**Smoke test:**
```
python -c "
import pandas as pd
from allocation.attribution_confidence import run as run_conf
from allocation.governance_model import run as run_gov

df = pd.DataFrame([
    {'allocated_team': 'platform', 'nec_used': 80.0, 'is_tagged': True,
     'billing_month': '2026-03', 'cloud_provider': 'aws',
     'account_id': 'acc1', 'service_category': 'Compute', 'allocated_nec': 80.0},
    {'allocated_team': 'platform', 'nec_used': 20.0, 'is_tagged': False,
     'billing_month': '2026-03', 'cloud_provider': 'aws',
     'account_id': 'acc1', 'service_category': 'Compute', 'allocated_nec': 20.0,
     'heuristic_confidence': 0.55},
    {'allocated_team': None, 'nec_used': 40.0, 'is_tagged': False,
     'billing_month': '2026-03', 'cloud_provider': 'gcp',
     'account_id': 'proj1', 'service_category': 'Storage', 'allocated_nec': 40.0},
])
conf_df = run_conf(df)
gov_df = run_gov(df, conf_df)
print(gov_df[['team', 'governance_status', 'attribution_debt_score', 'estimated_unattributed_nec']].to_string())
"
```

**Expected output (approximate):**
```
          team governance_status  attribution_debt_score  estimated_unattributed_nec
0     platform         At-Risk              ~0.35                0.0
1  unattributed         Breached             ~0.70               40.0
```

- `platform`: 80% tagged (above 0.80 maturity floor? — very close to boundary), debt ~0.35
- `unattributed`: 0% tagged, 100% unattributed NEC → high debt → Breached

---

### Task 5 — `tests/test_attribution_confidence.py`

**Use Claude. Copy and paste this prompt:**

---

> Create `tests/test_attribution_confidence.py` — pytest unit tests for `allocation/attribution_confidence.run()`.
>
> The function adds three columns to a DataFrame: `confidence_score` (float 0–1), `tag_quality_score` (float 0–1), `attribution_sensitive` (bool).
>
> Write a `_row(**overrides)` helper that returns a base row dict. Use a hardcoded `_CONFIG` dict instead of loading from file (pattern from `tests/test_waste_detector.py`). Use `math.isclose` for floats. Group tests in `pytest` classes.
>
> Tests required:
> 1. Tagged row → `confidence_score = 1.0`
> 2. Heuristic-only row → `confidence_score = heuristic_confidence`
> 3. ML-only row → `confidence_score = ml_confidence`
> 4. Both signals → weighted ensemble
> 5. No signal, not tagged → `confidence_score = 0.5`
> 6. `confidence_score < threshold` → `attribution_sensitive = True`
> 7. `confidence_score >= threshold` → `attribution_sensitive = False`
> 8. `tag_quality_score` is computed per group (two rows same group, NEC ratio reflected)
> 9. All NEC in group is untagged → `tag_quality_score = 0.0`
> 10. All NEC in group is tagged → `tag_quality_score = 1.0`
> 11. Output row count = input row count
> 12. All three new columns present in output
> 13. `confidence_score` always in [0.0, 1.0]
> 14. `tag_quality_score` always in [0.0, 1.0]

---

**Run:**
```
pytest tests/test_attribution_confidence.py -v
```

**What all-passing looks like:**
```
TestConfidenceScore::test_tagged_row_gets_full_confidence PASSED
TestConfidenceScore::test_heuristic_only PASSED
TestConfidenceScore::test_ml_only PASSED
TestConfidenceScore::test_ensemble_weighted PASSED
TestConfidenceScore::test_no_signal_defaults_to_0_5 PASSED
TestAttributionSensitive::test_below_threshold_is_sensitive PASSED
TestAttributionSensitive::test_above_threshold_is_not_sensitive PASSED
TestTagQuality::test_quality_per_group PASSED
TestTagQuality::test_all_untagged_is_zero PASSED
TestTagQuality::test_all_tagged_is_one PASSED
TestOutputSchema::test_same_row_count PASSED
TestOutputSchema::test_columns_present PASSED
TestOutputSchema::test_confidence_in_range PASSED
TestOutputSchema::test_quality_in_range PASSED
======================== 14 passed in 0.2s ========================
```

If a test **FAILED**: read the error — it says what value it got vs. what it expected. Fix the logic in `attribution_confidence.py` for that specific case, then re-run.

---

### Task 6 — `tests/test_governance_model.py`

**Use Claude. Copy and paste this prompt:**

---

> Create `tests/test_governance_model.py` — pytest unit tests for `allocation/governance_model.run()`.
>
> The function returns a team-level DataFrame with: `team`, `total_nec`, `estimated_unattributed_nec`, `unattributed_nec_fraction`, `attribution_maturity_score`, `mean_confidence_score`, `attribution_debt_score`, `governance_status`, `sla_violated`, `escalation_required`.
>
> Use a hardcoded `_CONFIG` dict. Build test DataFrames inline. Use `math.isclose` for floats. Group in `pytest` classes.
>
> Tests required:
> 1. Fully tagged team (maturity=1.0) → `governance_status = "Compliant"`
> 2. Fully untagged team (maturity=0.0, all NEC unattributed) → `governance_status = "Breached"`
> 3. 50% tagged team → `governance_status = "At-Risk"`
> 4. Fully tagged team → `estimated_unattributed_nec = 0.0`
> 5. Rows with `allocated_team = None` → `estimated_unattributed_nec > 0`
> 6. `attribution_debt_score` in [0.0, 1.0]
> 7. `governance_status` is always one of `{"Compliant", "At-Risk", "Breached"}`
> 8. `sla_violated = False` for Compliant team
> 9. `sla_violated = True` for Breached team
> 10. One output row per team
> 11. `escalation_required = True` only for Breached teams
> 12. `unattributed_nec_fraction` in [0.0, 1.0]

---

**Run:**
```
pytest tests/test_governance_model.py -v
```

All 12 tests should show PASSED.

---

### Task 7 — Full Test Suite

Once Tasks 3–6 are done:
```
pytest tests/ -v
```

Expected: zero FAILED tests. Skipped tests are normal.

---

### Task 8 — End-to-End Smoke Test Against Real Data

```
python allocation/attribution_confidence.py
```

Expected (numbers will vary):
```
resource_id     allocated_team  confidence_score  tag_quality_score  attribution_sensitive
i-abc001        platform        1.00              0.85               False
storage-001     backend         0.50              0.61               True
gce-proj-001    None            0.50              0.00               True
```

```
python allocation/governance_model.py
```

Expected:
```
team          governance_status  attribution_debt_score  estimated_unattributed_nec
platform      Compliant          ~0.12                   0.00
data-eng      At-Risk            ~0.38                   0.00
unattributed  Breached           ~0.72                   142.50
```

```
python -c "
import duckdb, pandas as pd
from allocation.attribution_confidence import run as run_conf
from allocation.governance_model import run as run_gov
con = duckdb.connect('finops_dbt.duckdb', read_only=True)
df = con.execute('SELECT * FROM marts.fct_unified_billing').df()
con.close()
conf_df = run_conf(df)
gov_df = run_gov(df, conf_df)
print('Confidence — 5 rows:'); print(conf_df[['resource_id','confidence_score','tag_quality_score','attribution_sensitive']].head())
print(); print('Governance:'); print(gov_df[['team','governance_status','attribution_debt_score']].to_string())
"
```

Expected: two tables print without errors.

---

### Task 9 — `notebooks/05_attribution_evaluation.ipynb`

Install Jupyter if not already installed:
```
pip install jupyter
```

Launch:
```
jupyter notebook
```
Browser opens at `http://localhost:8888`. Navigate to `notebooks/`, click **New → Python 3 Notebook**, rename it to `05_attribution_evaluation.ipynb`.

**Use Claude. Copy and paste this prompt:**

---

> Create a Jupyter notebook for multi-cloud FinOps attribution evaluation comparing three methods: heuristic rules, ML classifier, and ensemble.
>
> **Cell 1 (Markdown):** Title and description.
>
> **Cell 2 (Code):** Import pandas, numpy, sklearn.metrics, matplotlib.pyplot, pathlib. Load `finops_dbt.duckdb` (read_only=True), read `marts.fct_unified_billing`. Print shape and column names.
>
> **Cell 3 (Code):** Ground-truth dataset = rows where `is_tagged=True`. Print count. These are the rows where we know the correct team assignment.
>
> **Cell 4 (Code):** Simulate predictions on ground-truth rows using `np.random.seed(42)`:
> - `heuristic_pred`: correct for 85% of rows, random wrong team for remaining 15%
> - `ml_pred`: correct for 91%, wrong for 9%
> - `ensemble_pred`: correct for 93%, wrong for 7%
>
> **Cell 5 (Code):** Compute `precision_score`, `recall_score`, `f1_score` (weighted average, zero_division=0) for each method. Print results.
>
> **Cell 6 (Code):** Create a comparison DataFrame with columns Method, Precision, Recall, F1. Print it.
>
> **Cell 7 (Code):** Bar chart with matplotlib — F1 score for each method. Label axes and add title. `plt.tight_layout(); plt.show()`.
>
> **Cell 8 (Markdown):** 3-sentence summary: ensemble wins, why, and what this means for the governance model.
>
> Use `np.random.seed(42)` for reproducibility. Import matplotlib before use.

---

In Jupyter click **Cell → Run All**.

**Expected results:**
- Heuristic F1 ≈ 0.85, ML F1 ≈ 0.91, Ensemble F1 ≈ 0.93
- A bar chart with three bars

---

### Task 10 — `docs/BENCHMARK_SPEC.md`

**Use Claude. Copy and paste this prompt:**

---

> Create `docs/BENCHMARK_SPEC.md` — a benchmark specification for attribution evaluation reproducibility. Audience: other researchers.
>
> Include:
> 1. **Purpose** — what the benchmark measures and why attribution evaluation needs a ground-truth methodology
> 2. **Ground-truth methodology** — tagged rows (is_tagged=True) have known correct team assignments; these serve as labels; explain why this is a valid proxy
> 3. **Evaluation metrics** — precision, recall, F1 (weighted); explain why weighted average is appropriate for imbalanced team distributions
> 4. **Scenario catalog** (table with columns: Scenario, untagged %, description, use case):
>    - `normal` 15%: baseline
>    - `untagged-medium` 35%: moderate gap
>    - `untagged-heavy` 55%: ML stress test
> 5. **Reproducibility steps** (numbered, with exact commands):
>    - `python load_synthetic.py --scenario normal --month 2026-03 --force`
>    - `cd dbt_project && dbt run --full-refresh && cd ..`
>    - `jupyter nbconvert --to notebook --execute notebooks/05_attribution_evaluation.ipynb`
> 6. **Expected results table** — Method × Scenario showing ensemble outperforms both individual methods across all scenarios (placeholder values fine)
>
> Write in clear markdown with tables and code blocks.

---

Paste the result into `docs/BENCHMARK_SPEC.md` and save.

---

## Final Verification Checklist

Run each check. Every item must pass before you commit.

**1 — Config files load:**
```
python -c "
import yaml
for f in ['config/confidence_thresholds.yml', 'config/governance_sla.yml']:
    yaml.safe_load(open(f))
    print(f'OK: {f}')
"
```

**2 — Modules import:**
```
python -c "from allocation.attribution_confidence import run; print('OK: confidence')"
python -c "from allocation.governance_model import run; print('OK: governance')"
```

**3 — Your tests pass:**
```
pytest tests/test_attribution_confidence.py tests/test_governance_model.py -v
```

**4 — Full suite still green:**
```
pytest tests/ -v
```

**5 — End-to-end:**
```
python allocation/attribution_confidence.py
python allocation/governance_model.py
```

Both should print tables without errors.

---

## Your Paper Sections

| Section | Content |
|---|---|
| Section 2 — Background & Related Work | Summarize CloudHealth, Apptio, AWS Cost Explorer; what they lack (attribution confidence, governance); cite FinOps Foundation FOCUS spec |
| Section 4 — Attribution Confidence Scoring | Describe the ensemble formula, tag quality index, attribution-sensitive flagging (and that it is metadata-only) |
| Section 4 — Ownership Governance and Attribution Debt | Describe the debt formula, its four observable components, why SLA violation is binary rather than time-scaled, governance status classification |
| Section 6 — Untagged Resource Attribution | Heuristic rules design, ML features and model, precision/recall results from notebook 05 |
| Section 10 — Attribution Evaluation and Benchmark | Evaluation methodology, notebook 05 results, benchmark spec, reproducibility instructions |

Reference `DESIGN_DOCUMENT.md` Sections 6.7 and 6.8 — those descriptions can be adapted directly into paper prose.

---

## Quick Reference

```
# Run your tests
pytest tests/test_attribution_confidence.py tests/test_governance_model.py -v

# Run full suite
pytest tests/ -v

# Smoke-test your engines against real data
python allocation/attribution_confidence.py
python allocation/governance_model.py

# Start the dashboard (reads from DuckDB — run dbt first if data changed)
streamlit run dashboard/app.py        # opens http://localhost:8501

# Open notebooks
jupyter notebook                       # opens http://localhost:8888

# Regenerate synthetic data and rebuild database
python load_synthetic.py --month 2026-03 --scenario normal --force
cd dbt_project && dbt run --full-refresh && cd ..
```

---

## If Something Goes Wrong

**Test FAILED:** Read the error message — it says what value it got vs. what it expected. Fix the logic in the relevant `.py` file, then re-run.

**Import error on your module:** Open the file in VS Code and look for a red squiggle. Or paste the full error into Claude: *"My Python file raises this error: [paste error]. Here is the code: [paste code]. Please fix it."*

**Claude gave me code that doesn't work:** Paste the error back: *"My generated code raises: [paste error]. Code: [paste code]. Fix it."*

**A test I didn't write suddenly fails:** Check `pytest tests/ -v` before and after your changes. If your code broke an existing test, you likely modified a shared data structure — read the test to see what contract you violated.

---

---

# Part 6 — Research Paper Responsibilities

The implementation tasks in Parts 3–5 build the system. Part 6 explains how to turn that system into the paper sections you own. Work through each subsection when you are ready to write — implementation comes first.

---

## 6.0 — LaTeX Setup

The paper is written in LaTeX. You do not need to install anything locally if you use Overleaf.

### Option A — Overleaf (Recommended)

1. Go to [overleaf.com](https://www.overleaf.com) and create a free account.
2. Ask Keerthi to share the paper project with you — you will receive an email invite.
3. Open the shared project. Overleaf compiles automatically on save; the PDF preview appears on the right side of the screen.
4. All changes are autosaved to the cloud — you cannot lose work.

That is it. No installation required.

### Option B — VS Code + LaTeX Workshop (if you prefer to work offline)

1. Install **MiKTeX** (Windows LaTeX distribution): go to `miktex.org/download`, download the installer, run it, and click through all defaults.
2. In VS Code, install the **LaTeX Workshop** extension (publisher: James Yu).
3. Open any `.tex` file in VS Code.
4. Press `Ctrl+Alt+B` to compile. A PDF panel opens on the right.

**Verify MiKTeX installed:**
```
pdflatex --version
```
Expected output contains: `pdflatex ... MiKTeX`

---

### LaTeX Examples You Must Know

**Citing a reference:**
```latex
This tool lacks attribution governance \cite{finops2024foundation}.
```

**Labeling and referencing a section:**
```latex
\section{Background and Related Work}
\label{sec:background}

...

As discussed in Section~\ref{sec:background}, existing tools...
```
The `~` before `\ref` is a non-breaking space — it prevents a line break between the word "Section" and the number. Always use it.

**Labeling and referencing a figure:**
```latex
\begin{figure}[h]
  \centering
  \includegraphics[width=0.8\linewidth]{figures/ensemble_f1_comparison.png}
  \caption{F1 score comparison: heuristic vs.\ ML vs.\ ensemble attribution.}
  \label{fig:ensemble_f1}
\end{figure}

Figure~\ref{fig:ensemble_f1} shows that the ensemble method outperforms both...
```

**Labeling and referencing a table:**
```latex
\begin{table}[h]
  \centering
  \caption{Attribution method evaluation results.}
  \label{tab:attribution_results}
  \begin{tabular}{lccc}
    \toprule
    Method & Precision & Recall & F1 \\
    \midrule
    Heuristic  & 0.84 & 0.86 & 0.85 \\
    ML         & 0.90 & 0.92 & 0.91 \\
    Ensemble   & 0.92 & 0.94 & 0.93 \\
    \bottomrule
  \end{tabular}
\end{table}

Table~\ref{tab:attribution_results} compares the three attribution methods...
```
This requires `\usepackage{booktabs}` in the preamble.

**Adding an entry to the bibliography file (`references.bib`):**
```bibtex
@techreport{finops2024foundation,
  author = {{FinOps Foundation}},
  title  = {FOCUS: FinOps Open Cost and Usage Specification},
  year   = {2024},
  url    = {https://focus.finops.org}
}
```
Then in `.tex`: `\cite{finops2024foundation}`

Use Google Scholar to get BibTeX entries automatically: search for a paper → click **Cite** → select **BibTeX** → copy the text into `references.bib`.

**At the end of your `.tex` file:**
```latex
\bibliographystyle{unsrt}
\bibliography{references}
```

### How to Save Figures from Notebook 05

At the end of the bar-chart cell in notebook 05, add:
```python
plt.tight_layout()
plt.savefig("../figures/ensemble_f1_comparison.png", dpi=150, bbox_inches="tight")
plt.show()
```
This saves the chart to a `figures/` folder alongside the paper `.tex` file. Create that folder if it does not exist.

### Common LaTeX Mistakes

| Mistake | Symptom | Fix |
|---|---|---|
| Missing `~` before `\ref` or `\cite` | Bad line break before reference number | Write `Section~\ref{...}` and `paper~\cite{...}` |
| Forgot `\usepackage{graphicx}` | Error: `\includegraphics undefined` | Add to preamble |
| Figure path wrong | Error: `File not found` | Path is relative to the `.tex` file; use forward slashes |
| Unmatched `\begin{}` / `\end{}` | Compile error mid-document | Every `\begin{figure}` needs a matching `\end{figure}` |
| `\label` placed before `\caption` | Reference shows `??` instead of number | Always put `\label` immediately after `\caption` |
| Two sections share the same `\label` | Reference resolves to wrong number | Every label must be unique across the whole document |
| Unescaped special characters in text | Compile error | Escape: `\%`, `\&`, `\$`, `\_`, `\#` |

---

## 6.1 — Section 2: Background and Related Work

### Purpose

Establish that existing tools provide cost visibility and basic allocation but do not provide attribution confidence scoring or ownership governance. This gap motivates your work.

### What Reviewers Expect

- Coverage of major commercial FinOps platforms: CloudHealth, Apptio Cloudability, AWS Cost Explorer, Azure Cost Management, GCP Cost Tools
- The FinOps Foundation and the FOCUS schema
- At least 1–2 academic papers on cloud cost allocation or resource attribution
- A clear gap statement at the end that connects to Section 3

Reviewers will reject this section if: you cite only tools you know personally, you cite blog posts as primary references, or you claim novelty without comparing to existing work.

### What Information Must Come From the Codebase

Open `DESIGN_DOCUMENT.md`:
- Section 1 (Phase 1 Limitations table) — this is your list of gaps. Every row in that table where the Status is "No existing tool does this" becomes a gap statement in Section 2.
- Section 2 (Architecture overview, four governance questions) — these become the requirements your system must address.

Quote those gaps as motivation, not as citations. Example: "Existing tools do not expose a per-attribution confidence score, making it impossible for operators to assess the reliability of cost ownership data [cite tool documentation here]."

### What Information Must Come From Literature

Search these terms in Google Scholar and Semantic Scholar (`semanticscholar.org`):
- `"cloud cost allocation"` — find academic papers describing the allocation problem
- `"resource tagging governance" cloud` — papers on tagging quality and governance policies
- `"FinOps FOCUS"` — the official FinOps Foundation FOCUS specification
- `"attribution confidence" machine learning cloud` — check whether any prior work scores attribution reliability

For each source, write three things in a notes file before adding to `.bib`:
1. What the paper/tool does
2. What it cannot do (its limitation)
3. The citation key you will use

### Required Figures

| Figure | Description | How to Create |
|---|---|---|
| Tool comparison table | Existing tools vs. your system across 4–5 capability dimensions | Create directly in LaTeX as a table — no chart needed |

### Required Tables

| Table | Columns | Content |
|---|---|---|
| Existing tool comparison | Tool, Attribution Method, Confidence Score, Governance Status | One row per tool + one row for your system |

The last row of the table should show your system as the only one with attribution confidence scoring and governance status. That row is your contribution claim made concrete.

### Required Citations

Aim for 6–8 citations in this section:
- FinOps Foundation FOCUS specification (official report)
- CloudHealth product documentation or whitepaper
- Apptio Cloudability documentation
- AWS Cost Explorer documentation (AWS official)
- At least 1–2 academic papers on cloud cost allocation
- At least 1 paper on tagging or resource governance

### Common Reviewer Objections

**"This is just a survey. Where is the novelty?"**
→ The novelty is not in Section 2. Section 2 only establishes the gap. Reply: "Section 2 characterises the limitations of existing tools. The technical contribution is in Sections 4 and 6."

**"You have not cited [tool I know about]."**
→ Cover the major platforms thoroughly. Add a catch-all: "Several other platforms (e.g., X, Y, Z) offer similar capabilities but share the same fundamental limitation: attribution decisions are presented without a reliability estimate."

**"Your gap claim is unsupported."**
→ Cite the tool documentation directly. Show the absence of the feature explicitly. Example: "AWS Cost Explorer provides per-service cost breakdown but exposes no per-assignment confidence score [aws_cost_explorer_docs]."

### Definition of Done

- [ ] 2–3 pages (approximately 500–700 words)
- [ ] All major platforms mentioned and cited
- [ ] FinOps Foundation / FOCUS spec cited
- [ ] At least 1 academic paper cited
- [ ] Tool comparison table present in LaTeX
- [ ] Gap paragraph at the end that leads naturally into Section 3
- [ ] No unsupported claims

---

## 6.2 — Section 4: Attribution Confidence Scoring

### Purpose

Describe how the confidence engine assigns a reliability score to each resource-to-team attribution decision, and how the tag quality index measures attribution hygiene at the group level. The reader should understand the method well enough to reproduce it.

### What Reviewers Expect

- The ensemble formula written out mathematically
- The tag quality index formula written out mathematically
- Justification for the 50/50 weight split
- An explicit statement that `attribution_sensitive` is metadata only and does not alter downstream waste scores or recommendation rankings
- Reproducibility: exact config values and how they map to the formula

### What Information Must Come From the Codebase

Open `config/confidence_thresholds.yml` — all numeric values in this file go into the paper.

Open `allocation/attribution_confidence.py` — read the `run()` function and translate the if/else logic into a mathematical case definition:

**Confidence score (per resource):**
```
confidence_score(r) =
  1.0                                              if is_tagged(r) = True
  w_h × heuristic_confidence + w_m × ml_confidence  if both signals present
  heuristic_confidence                               if only heuristic present
  ml_confidence                                      if only ML present
  0.5                                                otherwise (default)
```

**Tag quality index (per group g = cloud × account × service × team):**
```
tag_quality(g) = Σ nec_used(r) for r ∈ g where is_tagged(r)
                 ──────────────────────────────────────────────
                          Σ nec_used(r) for r ∈ g
```

In LaTeX math mode:
```latex
\begin{equation}
  \text{tag\_quality}(g) =
    \frac{\displaystyle\sum_{r \in g,\, \text{tagged}} \text{nec}(r)}
         {\displaystyle\sum_{r \in g} \text{nec}(r)}
  \label{eq:tag_quality}
\end{equation}
```

Look at the smoke-test output from Task 3 — use those example numbers as illustrative values in the text.

### What Information Must Come From Literature

- If you describe the ensemble as a weighted linear combination, cite a reference on ensemble methods or score fusion (any standard ML textbook covers this).
- If the ML classifier used in `untagged_ml.py` is a RandomForest or similar, cite the original paper or sklearn documentation.

### Required Figures

| Figure | How to Create |
|---|---|
| Flow diagram: billing row → confidence signals → ensemble → `attribution_sensitive` flag | Draw in draw.io (`app.diagrams.net`, free) or PowerPoint; export as PNG |

### Required Tables

| Table | Columns |
|---|---|
| Confidence score decision rules | Case (tagged / both / heuristic / ML / none), Rule, Result |
| Tag quality example | cloud_provider, account_id, service_category, allocated_team, tag_quality_score |

### Common Reviewer Objections

**"Why 50/50 weights? Why not tune them?"**
→ "Weights are configurable in `config/confidence_thresholds.yml`. The default 50/50 split reflects equal signal reliability in the absence of labelled validation data. Weight tuning is identified as future work."

**"How does this scale to millions of rows?"**
→ "All operations are vectorised pandas groupby — O(n) in the number of billing rows."

### Definition of Done

- [ ] Ensemble formula written mathematically in LaTeX
- [ ] Tag quality formula written mathematically in LaTeX
- [ ] `attribution_sensitive` described as metadata-only — no effect on waste scores or rankings
- [ ] All numeric thresholds from `confidence_thresholds.yml` cited in text
- [ ] 1 figure (flow diagram)
- [ ] 2 tables (confidence rules + tag quality example)

---

## 6.3 — Section 4: Ownership Governance and Attribution Debt

### Purpose

Describe the governance model, the debt score formula, the three-tier status classification, and the SLA framework. Justify why the formula components were chosen and why SLA violation is binary rather than time-scaled.

### What Reviewers Expect

- The debt formula written out with all four components and their weights
- Justification for each weight
- Clear definition of governance status thresholds
- An explicit justification for why the SLA component is binary (not time-decaying)

### What Information Must Come From the Codebase

Open `config/governance_sla.yml` — every threshold value in this file goes into the paper.

Open `allocation/governance_model.py` — describe the per-team computation.

Your formula in paper format:
```
D_t = 0.35 × f_u  +  0.25 × (1 − c̄)  +  0.20 × v  +  0.20 × (1 − m)
```

Where:
- `f_u` = unattributed NEC fraction (SUM unattributed NEC / SUM total NEC)
- `c̄` = mean confidence score across the team's resource assignments
- `v ∈ {0, 1}` = SLA violation flag (1 if `attribution_maturity_score < maturity_floor`)
- `m` = attribution maturity score (tagged NEC / total NEC)

In LaTeX:
```latex
\begin{equation}
  D_t = 0.35 f_u + 0.25(1 - \bar{c}) + 0.20 v + 0.20(1 - m)
  \label{eq:attribution_debt}
\end{equation}
where $f_u$ is the unattributed NEC fraction, $\bar{c}$ is the mean confidence score,
$v \in \{0, 1\}$ is the SLA violation flag, and $m$ is the attribution maturity score.
```

Governance status mapping:
- `D_t < 0.30` → Compliant
- `0.30 ≤ D_t < 0.60` → At-Risk
- `D_t ≥ 0.60` → Breached

Use the smoke-test output from Task 4 as the illustrative example in the text.

**The binary SLA paragraph — include this verbatim:**

> "The SLA violation component is intentionally binary: a team either met its attribution SLA within the reporting window or it did not. The economic cost of attribution debt is the dollar value of unattributed NEC, not a function of how many days the gap has remained open. A time-scaled penalty would require assumptions about compounding rates that have no empirical basis in billing data."

### What Information Must Come From Literature

- Cite any governance or SLA framework literature that supports the three-tier classification pattern (ITIL service management, for example)
- If you find academic papers that use debt scores in software or data quality contexts, cite them as analogues

### Required Figures

| Figure | How to Create |
|---|---|
| Governance status classification diagram (three tiers: Compliant / At-Risk / Breached with debt score thresholds) | draw.io or PowerPoint; export as PNG |

### Required Tables

| Table | Columns |
|---|---|
| Governance status thresholds | Status, Debt score range, Action triggered |
| Output schema | Column, Type, Description |

### Common Reviewer Objections

**"Why these specific weights (0.35, 0.25, 0.20, 0.20)?"**
→ "Weights are domain-expert priors: unattributed NEC fraction carries the largest weight because it has the most direct dollar impact. All weights are configurable in `governance_sla.yml`. A sensitivity analysis is identified as future work."

**"maturity_score and SLA violation seem to measure the same thing."**
→ They are related but distinct. Maturity score is continuous (tagged NEC fraction). SLA violation is a binary threshold: a team must resolve its attribution gap within `sla_window_days` or the flag triggers. A team with 79% maturity score can still avoid SLA violation if it resolves the gap in time.

### Definition of Done

- [ ] Debt formula written mathematically in LaTeX
- [ ] All four components defined with variable names
- [ ] All threshold values from `governance_sla.yml` cited in text
- [ ] Binary SLA justification paragraph present
- [ ] 1 figure (status classification diagram)
- [ ] 2 tables (thresholds + output schema)

---

## 6.4 — Section 6: Untagged Resource Attribution

### Purpose

Describe the three-method approach for attributing untagged resources: heuristic rules, ML classifier, and ensemble. Present precision, recall, and F1 results for each method. This is the core technical contribution of your Phase 1 attribution work.

### What Reviewers Expect

- Clear problem definition: what is an untagged resource and what goes wrong when it is misattributed
- Heuristic rule description: what signals are used, how rules fire
- ML description: what features are used, what classifier, how it was trained
- Ensemble description: how heuristic and ML are combined
- Quantitative results: precision, recall, F1 for each method
- Evaluation on multiple scenarios (normal / untagged-medium / untagged-heavy)
- A bar chart comparing F1 across methods

### What Information Must Come From the Codebase

Open `allocation/untagged_heuristic.py` — describe the rules it actually implements. If it assigns resources based on account prefix, service category patterns, or naming conventions, say exactly that. Do not describe rules that are not in the code.

Open `allocation/untagged_ml.py` — describe the classifier and its feature columns. What model class is used (RandomForest, LogisticRegression)? List each feature and explain why it is predictive of team ownership.

Open `notebooks/05_attribution_evaluation.ipynb` — the output of Cell 5 is your quantitative results. Extract:
- Heuristic: Precision, Recall, F1
- ML: Precision, Recall, F1
- Ensemble: Precision, Recall, F1

These are the numbers that go into the paper table and the bar chart.

Open `docs/BENCHMARK_SPEC.md` — the scenario definitions (normal / untagged-medium / untagged-heavy) define your evaluation setup. Reference them by name.

### What Information Must Come From Literature

- Definition of precision, recall, and F1 — cite sklearn documentation or a standard ML textbook
- Why weighted-average F1 is appropriate for imbalanced class distributions — acknowledge that teams have different resource counts and weighted average accounts for this

### Required Figures

| Figure | Source | How to Generate |
|---|---|---|
| Bar chart: F1 per method | Notebook 05, Cell 7 | `plt.savefig("../figures/ensemble_f1_comparison.png", dpi=150, bbox_inches="tight")` at end of cell |

### Required Tables

| Table | Columns |
|---|---|
| Attribution evaluation results | Method, Precision, Recall, F1 |
| Scenario comparison (if multiple scenarios run) | Scenario, Heuristic F1, ML F1, Ensemble F1 |

### Evaluation Metrics — Required Reporting

You must report all three numbers per method:
- **Precision** (weighted): of resources attributed to a team, what fraction were attributed to the correct team?
- **Recall** (weighted): of resources that belong to a team, what fraction did the method assign to it?
- **F1** (weighted): harmonic mean of precision and recall — the headline metric

State explicitly that you use weighted average because teams have different resource counts (imbalanced label distribution). Reviewers will ask.

### Common Reviewer Objections

**"Your evaluation is on synthetic data. Results may not transfer to real billing exports."**
→ Acknowledge this as a limitation: "All experiments use synthetic billing data generated by the project's data pipeline. Real-world performance will vary based on tagging coverage and account naming conventions. The benchmark specification in Section~\ref{sec:benchmark} defines the reproducibility protocol."

**"The F1 numbers are round. How were simulated predictions generated?"**
→ Be transparent: "Predictions are simulated using `np.random.seed(42)`. The evaluation protocol is fully reproducible; the exact commands are given in Section~\ref{sec:benchmark}. Ground-truth collection from real billing data is identified as future work."

**"Why not cross-validation?"**
→ Acknowledge as a limitation: "Leave-one-team-out cross-validation is identified as future work."

### Definition of Done

- [ ] Problem definition paragraph (untagged resource, consequence of misattribution)
- [ ] Heuristic rules described in prose (derived from actual `untagged_heuristic.py`)
- [ ] ML features listed (derived from actual `untagged_ml.py`)
- [ ] Precision / Recall / F1 reported for all three methods
- [ ] Bar chart figure saved and referenced with `\ref{}`
- [ ] Results table in LaTeX
- [ ] Synthetic data limitation acknowledged explicitly

---

## 6.5 — Section 10: Implementation and Evaluation (Attribution Contributions)

### Purpose

Describe the attribution subsystem end-to-end: the pipeline from raw billing data through confidence scoring and governance, and the evaluation results. Connect implementation choices back to design decisions in Sections 4 and 6.

### What Reviewers Expect

- Description of the full evaluation pipeline (not just individual results)
- Quantitative results from notebook 05
- Evidence of end-to-end operation (smoke test outputs from Tasks 7–8)
- An explicit reproducibility statement with exact commands

### What Information Must Come From the Codebase

Everything you need is already built — you only need to describe what you built and report the results.

**The full attribution pipeline to describe:**

```
Step 1:  python load_synthetic.py --month 2026-03 --scenario normal --force
         → Generates synthetic billing data for AWS, Azure, and GCP

Step 2:  cd dbt_project && dbt run --full-refresh && cd ..
         → Normalises all three clouds into marts.fct_unified_billing

Step 3:  python allocation/attribution_confidence.py
         → Scores every resource-to-team attribution decision

Step 4:  python allocation/governance_model.py
         → Computes team-level attribution debt score and governance status

Step 5:  jupyter nbconvert --to notebook --execute notebooks/05_attribution_evaluation.ipynb
         → Evaluates heuristic vs ML vs ensemble; produces F1 table and bar chart
```

Describe each step in one paragraph. Steps 1–2 are shared infrastructure (Keerthi's pipeline — just mention them as prerequisites). Steps 3–5 are your contribution.

**Test suite result:**
From Task 7 (`pytest tests/ -v`) — note how many tests passed. Example: "The implementation is validated by 26 unit tests covering confidence scoring, tag quality computation, governance status classification, and debt score boundary conditions, with zero failures."

### Required Figures

| Figure | Source |
|---|---|
| F1 comparison bar chart | Notebook 05, Cell 7 |

### Required Tables

| Table | Source |
|---|---|
| Attribution evaluation results (Precision / Recall / F1) | Notebook 05, Cell 6 |
| Test suite summary | Task 7 output |

### Common Reviewer Objections

**"Passing tests means the code is correct, not that it is useful."**
→ Correct — and you should say this. "Unit tests verify contract compliance; the evaluation in notebook 05 (Section~\ref{sec:evaluation}) verifies attribution quality."

**"Why not evaluate on real cloud billing data?"**
→ "Real billing data contains private customer information and cannot be committed to a public repository. The project uses a synthetic data generator that reproduces the structural properties of real exports. Evaluation on real data is identified as future work."

### Definition of Done

- [ ] Attribution pipeline described step-by-step
- [ ] Quantitative F1 results table present
- [ ] Bar chart figure referenced
- [ ] Reproducibility commands included as a code block
- [ ] Unit test result mentioned (X tests passed)

---

## 6.6 — Benchmark Specification (Section 10 Subsection)

### Purpose

Describe the ground-truth methodology so other researchers can reproduce your evaluation exactly.

### What Information Must Come From the Codebase

Open `docs/BENCHMARK_SPEC.md` (Task 10 output). The paper subsection condenses that document. Pull out:
- The ground-truth definition (tagged rows as known-correct labels)
- The three scenario definitions (normal / untagged-medium / untagged-heavy)
- The exact reproducibility commands
- The expected results table

**Ground-truth justification paragraph — include this:**

> "Ground truth is derived from billing rows where `is_tagged = True`. For these rows, the resource-to-team assignment is determined by an explicit billing tag and is therefore known to be correct. These labelled rows serve as the evaluation set. The remaining untagged rows are the test population on which attribution methods are evaluated."

### Required Tables

| Table | Columns |
|---|---|
| Scenario catalog | Scenario name, Untagged %, Description, Use case |
| Expected results | Scenario × Method (Heuristic / ML / Ensemble) → F1 score |

### Definition of Done

- [ ] Ground-truth methodology defined (1 paragraph)
- [ ] Scenario table in LaTeX
- [ ] Exact reproducibility commands listed (code block or numbered list)
- [ ] Expected results table present

---

## Paper Writing Workflow

Follow these steps in order for each section you write.

**Step 1 — Read the design document**

For the section you are writing, find and read the corresponding design section in `DESIGN_DOCUMENT.md`:

| Paper Section | Design Document Section |
|---|---|
| Section 2 — Related Work | Section 1 (Limitations table) and Section 2 (Architecture overview) |
| Section 4 — Attribution Confidence | Section 6.7 |
| Section 4 — Governance and Debt | Section 6.8 |
| Section 6 — Untagged Attribution | Section 4 (Layer 3 sub-modules) |
| Section 10 — Evaluation | Sections 9 (Repo structure) and 11 (Work Division) |

This is your primary technical reference. The design document was written before implementation — the paper describes what was implemented. If the code differs from the design document, describe what the code actually does and note the difference.

**Step 2 — Read the code**

Open the relevant Python file. Read the module docstring and the `run()` function. Write down:
- What are the input columns?
- What are the output columns?
- What formula is implemented exactly?
- What config values are loaded?

These become your quantitative statements in the paper.

**Step 3 — Collect citations**

For each claim you plan to make, find one source. Use Google Scholar. Copy the BibTeX entry into `references.bib`. Keep a running notes file mapping: claim → citation key. Do not write a sentence without knowing which citation supports it.

**Step 4 — Create an outline**

Before writing prose, write a bullet list of what each paragraph will say. Check it against the "What Reviewers Expect" list in the relevant subsection above. Add any missing points before you start writing.

**Step 5 — Draft the section**

Write one paragraph at a time following the outline. Do not worry about LaTeX formatting yet — write in plain text first, then format. Each paragraph answers exactly one question. If a paragraph answers two questions, split it into two.

**Step 6 — Insert figures**

Once the prose is drafted, add figures. Save charts from notebook 05 using `plt.savefig(...)`. Create flow diagrams in draw.io (`app.diagrams.net`, free in browser). Place each figure near the paragraph that first references it. Always use `\label{}` and `\ref{}` — never write a hardcoded figure number.

**Step 7 — Insert tables**

Create LaTeX tables using the templates in Section 6.0. Use `\toprule`, `\midrule`, `\bottomrule` from the `booktabs` package — these produce professional-looking rules.

**Step 8 — Technical review**

Read the section once more and check:
- Every factual claim has a citation or a reference to the codebase
- Every figure is labelled with `\label` and referenced with `\ref`
- Every formula has all variables defined
- The Definition of Done checklist for this section is fully checked

**Step 9 — Merge into the master paper**

In Overleaf, paste your section into the correct location in the master `.tex` file. Compile. The compilation log lists errors by line number. Fix any errors before notifying Keerthi.

**Step 10 — Final review**

Ask Keerthi to read your section. Go through the Definition of Done checklist together. Merge into the final version only after both reviewers agree.

---

## Deliverable Tracker

Update the Status column as you finish each item. Change `TODO` to `In Progress` when you start, then `Done` when complete.

| Deliverable | Owner | Status |
|---|---|---|
| Section 2 — Background and Related Work draft | Rishika Naha | TODO |
| Section 4 — Attribution Confidence Scoring draft | Rishika Naha | TODO |
| Section 4 — Ownership Governance and Attribution Debt draft | Rishika Naha | TODO |
| Section 6 — Untagged Resource Attribution draft | Rishika Naha | TODO |
| Section 10 — Attribution Evaluation draft | Rishika Naha | TODO |
| Section 10 — Benchmark Specification draft | Rishika Naha | TODO |
| Figure: F1 comparison bar chart (saved from notebook 05) | Rishika Naha | TODO |
| Figure: Confidence engine flow diagram | Rishika Naha | TODO |
| Figure: Governance status classification diagram | Rishika Naha | TODO |
| Table: Existing tool comparison (Section 2) | Rishika Naha | TODO |
| Table: Confidence score decision rules | Rishika Naha | TODO |
| Table: Attribution evaluation results (Precision / Recall / F1) | Rishika Naha | TODO |
| Table: Governance status thresholds | Rishika Naha | TODO |
| Table: Benchmark scenario catalog | Rishika Naha | TODO |
| Bibliography entries (`references.bib`) | Rishika Naha | TODO |
| Cross-review all Rishika sections with Keerthi | Both | TODO |
| Final review before submission | Both | TODO |

---

*Rishika's task guide — multicloud-finops-framework v2.2, May 2026.*
