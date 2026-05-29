# Contributor Setup Guide
## Multi-Cloud FinOps Framework

**Who this is for:** New contributors setting up the project for the first time.  
**Time required:** 20–30 minutes.

After completing this guide, open [RISHIKA_TASKS.md](RISHIKA_TASKS.md) for your specific coding tasks.

---

## Part 0 — What This Project Does (2-Minute Overview)

The project ingests billing data from AWS, Azure, and GCP, normalizes it into one database table, then runs analysis to find wasted spend, explain why costs changed, and suggest actions. Everything lives in a single folder on your laptop — no paid cloud services, no accounts needed.

The final output is a local dashboard you open in your browser. All data is synthetic (fake) — no real billing data is ever committed to the repo.

---

## Part 1 — Install Everything (One-Time Setup)

---

### Step 1 — Install Python

1. Open your browser and go to `https://www.python.org/downloads/`
2. Click the yellow **Download Python 3.11.x** button (any 3.11 version is fine)
3. Run the installer
4. **IMPORTANT:** On the first screen, check **"Add Python to PATH"** before clicking Install
5. Click **Install Now**

**Verify it worked:** Open a new Command Prompt (Windows key → type `cmd` → Enter):
```
python --version
```
Expected: `Python 3.11.x`. If you see an error, restart your computer and try again.

---

### Step 2 — Install Git

1. Go to `https://git-scm.com/download/win`
2. Download the Windows installer and run it
3. Click Next through all the default options
4. Click Install

**Verify:**
```
git --version
```
Expected: `git version 2.x.x`

---

### Step 3 — Install VS Code

1. Go to `https://code.visualstudio.com/`
2. Click **Download for Windows** and run the installer
3. During install, check **"Add to PATH"** and **"Add 'Open with Code' to context menu"**

After installing, open VS Code and install these three extensions (click the Extensions icon — four squares — in the left sidebar):

| Extension | Publisher | What it does |
|---|---|---|
| Python | Microsoft | Python language support |
| SQLTools | Matheus Teixeira | SQL client — lets you run queries visually |
| DuckDB SQL Tools | Random Fractals Inc. | Connects SQLTools to the DuckDB database |

---

### Step 4 — Get the Project Code

In Command Prompt, navigate to where you want the project:
```
cd C:\Users\YourName\Documents
```

Clone the repo (ask Keerthi for the exact GitHub URL):
```
git clone https://github.com/keerthi-rapolu/multicloud-finops-framework.git
cd multicloud-finops-framework
```

---

### Step 5 — Install Project Dependencies

Make sure you are inside the `multicloud-finops-framework` folder, then run:
```
pip install -r requirements.txt
```

This prints a lot of lines — that is normal. Wait 1–3 minutes for it to finish.

**What gets installed:**

| Library | What it does |
|---|---|
| `duckdb` | The local database that stores all billing data |
| `pandas` | Reads and processes data tables in Python |
| `pyarrow` | Reads Parquet files (billing export format) |
| `pyyaml` | Reads `.yml` config files |
| `dbt-duckdb` | Runs the data transformation pipeline |
| `streamlit` | Runs the dashboard website locally |
| `plotly` | Makes the charts in the dashboard |
| `pytest` | Runs automated tests |
| `scikit-learn` | ML classifier for untagged resource attribution |

**Verify:**
```
python -c "import duckdb, pandas, streamlit; print('All good')"
```
Expected: `All good`

---

## Part 2 — Run the Existing System

These steps get all the data flowing so you can see the dashboard and understand what has already been built. Run them in order.

---

### Step 6 — Generate Synthetic Billing Data

```
python load_synthetic.py --month 2026-03 --scenario normal --force
```

**What this does:** Creates realistic fake billing CSV files for AWS, Azure, and GCP, converts them to Parquet format, and saves them to `data/raw/`.

**What you will see printed:**
```
[generate] AWS: 1440 rows written to data/synthetic/aws/2026-03/
[generate] Azure: 960 rows written to data/synthetic/azure/2026-03/
[generate] GCP: 720 rows written to data/synthetic/gcp/2026-03/
[validate] AWS: schema OK, 1440 rows, date range OK
...
Pipeline complete.
```

**Files created:**

| Folder | What it contains |
|---|---|
| `data/synthetic/aws/2026-03/` | AWS fake billing CSVs (48 columns per row) |
| `data/synthetic/azure/2026-03/` | Azure fake billing CSVs (32 columns per row) |
| `data/synthetic/gcp/2026-03/` | GCP fake billing CSVs (27 columns per row) |
| `data/raw/aws/2026-03/*.parquet` | Converted to Parquet for the database |
| `data/raw/azure/2026-03/*.parquet` | |
| `data/raw/gcp/2026-03/*.parquet` | |

---

### Step 7 — Load Data into the Database

```
cd dbt_project
dbt run --full-refresh
cd ..
```

**What this does:** dbt reads the Parquet files, normalizes all three cloud formats into one schema, calculates Net Effective Cost (NEC), and writes everything into `finops_dbt.duckdb` in the project root.

**What you will see printed:**
```
Running with dbt=1.x.x
  1 of 7 OK created view staging.stg_aws_cur .................. [OK in 0.1s]
  2 of 7 OK created view staging.stg_azure_cost ............... [OK in 0.1s]
  3 of 7 OK created view staging.stg_gcp_billing .............. [OK in 0.1s]
  4 of 7 OK created table intermediate.int_aws_nec ............ [OK in 0.5s]
  5 of 7 OK created table intermediate.int_azure_nec .......... [OK in 0.5s]
  6 of 7 OK created table intermediate.int_gcp_nec ............ [OK in 0.5s]
  7 of 7 OK created table marts.fct_unified_billing ........... [OK in 0.8s]
Finished running 7 models.
```

**Tables now in your database** (`finops_dbt.duckdb`):

| Schema | Table | What it contains |
|---|---|---|
| `staging` | `stg_aws_cur` | AWS billing (view — reads raw files live) |
| `staging` | `stg_azure_cost` | Azure billing (view) |
| `staging` | `stg_gcp_billing` | GCP billing (view) |
| `intermediate` | `int_aws_nec` | AWS with NEC calculations |
| `intermediate` | `int_azure_nec` | Azure with NEC calculations |
| `intermediate` | `int_gcp_nec` | GCP with NEC calculations |
| `marts` | `fct_unified_billing` | **All three clouds merged** — 31 columns, one row per billing line |

---

### Step 8 — Connect VS Code to the Database

1. Click the database icon in the VS Code left sidebar (cylinder shape)
2. Click **Add New Connection** → select **DuckDB**
3. **Database file** field — enter the full path:
   ```
   C:\Users\YourName\Documents\multicloud-finops-framework\finops_dbt.duckdb
   ```
4. Click **Save** — the schema tree appears

**Try a query** — click any table in the tree, or open a new SQL editor and run:
```sql
SELECT cloud_provider, COUNT(*) as rows, ROUND(SUM(nec), 2) as total_nec
FROM marts.fct_unified_billing
GROUP BY cloud_provider;
```
Expected: three rows — `aws`, `azure`, `gcp` — each with hundreds of rows and NEC in the hundreds of dollars.

---

### Step 9 — Run the Tests

```
pytest tests/ -v
```

**What passing looks like:**
```
tests/test_normalization.py::... PASSED
tests/test_nec_model.py::... PASSED
tests/test_waste_detector.py::TestDetectUnusedCommitments::test_flags_commitment_waste_row PASSED
... (many more lines)
======================== X passed, Y skipped in Z.Xs ========================
```

`SKIPPED` tests are normal — they skip when certain optional data is absent. If anything shows `FAILED`, take a screenshot and message Keerthi.

---

### Step 10 — Launch the Dashboard

```
streamlit run dashboard/app.py
```

**What you will see in the terminal:**
```
  You can now view your Streamlit app in your browser.
  Local URL: http://localhost:8501
```

Open your browser and go to: **`http://localhost:8501`**

**What to look for on each page:**

| Page | Where to find it | What you see |
|---|---|---|
| Home | `http://localhost:8501` | KPI tiles (total NEC, waste %, tagging %), traffic lights |
| Overview | sidebar → Overview | Daily NEC trend chart, spend by pricing model |
| Cost Allocation | sidebar → Cost Allocation | Per-team NEC bars, commitment utilization |
| Tagging & Attribution | sidebar → Tagging & Attribution | Tagging coverage by cloud, SLA tracker |
| Waste & Recommendations | sidebar → Waste & Recommendations | Waste breakdown chart, prioritised action list |
| Cost Intelligence | sidebar → Cost Intelligence | Root cause cards, anomaly explanations |

Press `Ctrl+C` in the terminal to stop the dashboard.

---

## You're Set Up

You now have:
- All software installed
- The full project running locally
- The database populated with synthetic billing data
- The dashboard visible in your browser
- All existing tests passing

**Next step:** Open [RISHIKA_TASKS.md](RISHIKA_TASKS.md) and start on your Phase 2 coding tasks.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'duckdb'`**  
→ Run `pip install -r requirements.txt` — you probably skipped Step 5.

**`FileNotFoundError: finops_dbt.duckdb not found`**  
→ Run Steps 6 and 7 first — you need to generate data and run dbt before the database exists.

**`dbt: command not found`**  
→ Run `pip install dbt-duckdb` then try again.

**dbt fails with `source not found` or `profile not found`**  
→ Make sure you ran `cd dbt_project` before `dbt run`. The command must run from inside that folder.

**Streamlit shows a blank page or error**  
→ Make sure dbt has finished running first (Step 7). The dashboard reads from the database.
