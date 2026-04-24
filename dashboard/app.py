"""
Multi-Cloud FinOps Dashboard — Streamlit entrypoint.

Run from repo root:
    streamlit run dashboard/app.py
"""

import sys
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from allocation.nec_model import load_billing_data, nec_by_cloud, nec_by_team
from dashboard._shared import (
    COLOR_BLOCKER,
    COLOR_INEFFICIENCY,
    COLOR_INFO,
    COLOR_OPTIMIZED,
    compute_maturity,
    diagnose,
    render_headline,
    render_priority_badge,
)

_DB   = Path(__file__).resolve().parents[1] / "finops_dbt.duckdb"
_REPO = _DB.parent


def _bootstrap_db() -> None:
    """Build the DuckDB mart from committed synthetic CSVs on first run.

    Runs automatically on Streamlit Community Cloud where the generated
    database file is absent (*.duckdb is gitignored; only CSVs are committed).
    """
    import re
    import subprocess

    sys.path.insert(0, str(_REPO))
    from load_synthetic import run as _ls_run
    from scripts.config import GeneratorConfig

    # dbt_project/profiles.yml is gitignored — regenerate it if absent
    profiles_path = _REPO / "dbt_project" / "profiles.yml"
    if not profiles_path.exists():
        profiles_path.write_text(
            "multicloud_finops:\n"
            "  target: dev\n"
            "  outputs:\n"
            "    dev:\n"
            "      type: duckdb\n"
            "      path: \"../finops_dbt.duckdb\"\n"
            "      threads: 4\n",
            encoding="utf-8",
        )

    syn_aws = _REPO / "data" / "synthetic" / "aws"
    months = sorted(
        m.group(1)
        for f in sorted(syn_aws.glob("aws_cur_*.csv"))
        if (m := re.search(r"(\d{4}-\d{2})", f.name))
    )
    if not months:
        st.error(
            "**Auto-bootstrap failed** — no synthetic CSVs found in "
            "`data/synthetic/aws/`. Commit them or run `make pipeline` locally."
        )
        st.stop()

    with st.status("⚙️ First-run setup — building database from synthetic data…", expanded=True) as _status:
        for month in months:
            st.write(f"Loading {month}…")
            _ls_run(billing_month=month, force=True, cfg=GeneratorConfig())

        st.write("Running dbt transformations…")
        result = subprocess.run(
            ["dbt", "run", "--full-refresh"],
            cwd=str(_REPO / "dbt_project"),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            st.error("**dbt failed** — see output below.")
            st.code(result.stdout + "\n" + result.stderr)
            st.stop()

        _status.update(label="✅ Database ready — loading dashboard…", state="complete")

    st.rerun()


@st.cache_data(ttl=30, show_spinner=False)
def _available_months() -> list[str]:
    if not _DB.exists():
        return []
    with duckdb.connect(str(_DB), read_only=True) as con:
        rows = con.execute(
            "SELECT DISTINCT billing_month FROM marts.fct_unified_billing ORDER BY 1 DESC"
        ).fetchall()
    return [r[0] for r in rows]

st.set_page_config(
    page_title="Multi-Cloud FinOps",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Auto-bootstrap: if DuckDB is absent (e.g. fresh Streamlit Cloud deploy),
# build it from the synthetic CSVs that are committed to the repo.
if not _DB.exists():
    _bootstrap_db()


@st.cache_data(show_spinner="Loading billing data…")
def _load(month: str | None):
    return load_billing_data(_DB, billing_month=month or None)


# ---------------------------------------------------------------------------
# Sidebar — global filters (shared with all pages via session_state)
# ---------------------------------------------------------------------------

st.sidebar.title("☁️ FinOps Dashboard")
st.sidebar.markdown("---")
st.sidebar.markdown("### Global scope")
st.sidebar.caption(
    "Applies to every page. Use page-level filters (e.g. Teams, Waste type) "
    "for drill-downs — they appear in the sidebar only on pages that support them."
)

months = _available_months()

if not months:
    st.error(
        "**No data found.** Run `make pipeline` first to generate synthetic data "
        "and build the DuckDB mart, then relaunch the dashboard."
    )
    st.stop()

selected_month = st.sidebar.selectbox(
    "Billing month", ["All"] + months, index=1 if months else 0, key="billing_month"
)
month_filter = None if selected_month == "All" else selected_month

selected_cloud = st.sidebar.selectbox(
    "Cloud provider", ["All", "aws", "azure", "gcp"], index=0
)

df_full = _load(month_filter)
df = df_full if selected_cloud == "All" else df_full[df_full["cloud_provider"] == selected_cloud]

st.session_state["df"] = df
st.session_state["month"] = month_filter
st.session_state["cloud"] = selected_cloud

# ---------------------------------------------------------------------------
# Home page
# ---------------------------------------------------------------------------

st.title("AI-Ready Multi-Cloud FinOps Cost Attribution & Allocation Framework")
st.caption("Research demo — Keerthi Rapolu & Rishika Naha, April 2026 · Synthetic dataset for demo purposes")

# ---------------------------------------------------------------------------
# Executive headline (Critical #1) — the single "so what" at the very top
# ---------------------------------------------------------------------------
diag = diagnose(df)
render_headline(diag)

summary = nec_by_cloud(df)
total_list = summary["list_cost"].sum()
total_nec = summary["nec"].sum()
total_waste = summary["nec_waste"].sum()
savings_pct = (1 - total_nec / total_list) * 100 if total_list else 0

waste_pct    = total_waste / total_nec * 100 if total_nec else 0
is_tagged    = df["is_tagged"].fillna(False)
untagged_nec = df.loc[~is_tagged, "nec"].sum()
untagged_pct = untagged_nec / total_nec * 100 if total_nec else 0

# Three canonical metrics — Cloud Spend · Waste · Recoverable Savings
c1, c2, c3, c4 = st.columns(4)
c1.metric("Cloud Spend",          f"${total_nec:,.0f}",
          delta=f"{savings_pct:.1f}% discount from list price")
c2.metric("Waste",                f"${total_waste:,.0f}",
          delta=f"{waste_pct:.1f}% of spend — idle commitments", delta_color="inverse")
c3.metric("Unattributed Spend",   f"${untagged_nec:,.0f}",
          delta=f"{untagged_pct:.1f}% has no owner", delta_color="inverse")
c4.metric("Recoverable Savings",  f"${diag.low_risk_savings:,.0f}/mo",
          delta="low-risk · no service interruption")

st.markdown("---")
st.subheader("Spend by cloud")

fig = go.Figure([
    go.Bar(name="Cloud Spend", x=summary["cloud_provider"], y=summary["nec"],       marker_color=COLOR_INFO),
    go.Bar(name="Waste",       x=summary["cloud_provider"], y=summary["nec_waste"], marker_color=COLOR_BLOCKER),
    go.Bar(name="Discounts",   x=summary["cloud_provider"], y=summary["savings"],   marker_color=COLOR_OPTIMIZED),
])
fig.update_layout(
    barmode="stack", xaxis_title="Cloud", yaxis_title="USD",
    legend=dict(orientation="h", y=1.12), height=350, margin=dict(t=10, b=40),
)
st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Priority actions (the old "Executive Summary" section is redundant now —
# the diagnostic block above + unified KPI row already cover the same data)
# ---------------------------------------------------------------------------

st.markdown("---")
st.markdown("### Top risks — ordered by priority")

# ---------------------------------------------------------------------------
# Priority-ordered risk cards (Critical #2) — tagging first when it's the P0
# ---------------------------------------------------------------------------

def _tagging_card() -> None:
    if untagged_pct >= 20:
        badge = render_priority_badge("P0", "P0 — Fix first")
        st.markdown(
            f"{badge} &nbsp; :red_circle: **Tagging gap — PRIMARY BLOCKER**  \n"
            f"**{untagged_pct:.1f}%** of NEC (${untagged_nec:,.0f}) is unattributed. "
            "Every downstream metric (allocation, optimization, chargeback) is unreliable "
            "until this is fixed. Enforce `tag_team` policy at resource creation. "
            "Target: <10% within 60 days. → **Tagging Coverage**",
            unsafe_allow_html=True,
        )
    elif untagged_pct >= 10:
        badge = render_priority_badge("P1", "P1")
        st.markdown(
            f"{badge} &nbsp; :orange_circle: **Tagging gap**  \n"
            f"{untagged_pct:.1f}% of NEC (${untagged_nec:,.0f}) cannot be directly allocated. "
            "See **Tagging Coverage** for remediation owners.",
            unsafe_allow_html=True,
        )
    else:
        badge = render_priority_badge("P3", "OK")
        st.markdown(
            f"{badge} &nbsp; :green_circle: **Tagging coverage acceptable** — "
            f"{untagged_pct:.1f}% of NEC is unattributed.",
            unsafe_allow_html=True,
        )

def _waste_card() -> None:
    if waste_pct >= 10:
        badge = render_priority_badge("P0", "P0 — Fix first")
        st.markdown(
            f"{badge} &nbsp; :red_circle: **Commitment waste — PRIMARY BLOCKER**  \n"
            f"**{waste_pct:.1f}%** of NEC (${total_waste:,.0f}) is idle RI/SP capacity. "
            "Release or right-size to recover immediately. → **Waste & Recommendations**",
            unsafe_allow_html=True,
        )
    elif waste_pct >= 5:
        badge = render_priority_badge("P1", "P1")
        st.markdown(
            f"{badge} &nbsp; :orange_circle: **Commitment waste**  \n"
            f"{waste_pct:.1f}% of NEC (${total_waste:,.0f}) unused. Monitor for increase.",
            unsafe_allow_html=True,
        )
    else:
        badge = render_priority_badge("P3", "OK")
        st.markdown(
            f"{badge} &nbsp; :green_circle: **Commitment utilization healthy** — "
            f"waste is {waste_pct:.1f}% of NEC.",
            unsafe_allow_html=True,
        )

# Render in priority order — the primary blocker card appears first
if diag.primary_issue == "tagging":
    _tagging_card()
    _waste_card()
else:
    _waste_card()
    _tagging_card()

# Risk 3 — largest cost centre (informational)
try:
    _team_labels = {"data-eng": "Data Engineering", "platform": "Platform", "frontend": "Frontend", "backend": "Backend", "ml": "Machine Learning"}
    by_team = nec_by_team(df)
    team_totals = by_team.groupby("team")["nec"].sum()
    top_team_key = team_totals.idxmax()
    top_team_label = _team_labels.get(top_team_key, top_team_key.replace("-", " ").title())
    top_pct = team_totals.max() / total_nec * 100
    badge_info = render_priority_badge("P2", "INFO")
    st.markdown(
        f"{badge_info} &nbsp; :blue_circle: **Largest cost centre** — {top_team_label} "
        f"accounts for {top_pct:.0f}% of total NEC (${team_totals.max():,.0f}). "
        "→ **Cost Allocation**",
        unsafe_allow_html=True,
    )
except Exception:
    pass

# Top 3 actions — ordered by primary issue (Critical #2)
st.markdown("**Top 3 actions** — ordered by impact")
col_a1, col_a2, col_a3 = st.columns(3)
waste_saving_est = total_waste * 0.85

def _action_tagging(col) -> None:
    col.error(
        f"**Fix tagging gaps**  \n"
        f"**${untagged_nec:,.0f}** unattributed ({untagged_pct:.0f}% of spend)  \n"
        f"→ Outcome: unlocks full cost optimization  \n"
        f"Owner: Platform + FinOps · Risk: Low · SLA: **Immediate**  \n"
        f"→ Tagging Coverage"
    )

def _action_waste(col) -> None:
    col.success(
        f"**Release idle commitments**  \n"
        f"Save **${waste_saving_est:,.0f}/month**  \n"
        f"→ Outcome: immediate cost reduction, no downtime  \n"
        f"Owner: Cloud Platform · Risk: Low · SLA: **This week**  \n"
        f"→ Waste & Recommendations"
    )

def _action_team(col) -> None:
    try:
        col.info(
            f"**Right-size {top_team_label}**  \n"
            f"Largest team — ${team_totals.max():,.0f} cloud spend  \n"
            f"→ Outcome: reduce idle compute + commitment waste  \n"
            f"Owner: {top_team_label} · Risk: Medium · SLA: **Next cycle**  \n"
            f"→ Cost Allocation"
        )
    except Exception:
        col.info("**Review largest team** — see Cost Allocation for details.")

# Order actions by primary issue
if diag.primary_issue == "tagging":
    _action_tagging(col_a1)
    _action_waste(col_a2)
    _action_team(col_a3)
else:
    _action_waste(col_a1)
    _action_tagging(col_a2)
    _action_team(col_a3)

st.markdown("---")

# ---------------------------------------------------------------------------
# FinOps Maturity Score — collapsed by default (not primary leadership info)
# ---------------------------------------------------------------------------

mat = compute_maturity(df, diag)
overall = mat.overall
overall_color = (
    COLOR_OPTIMIZED    if overall >= 4 else
    COLOR_INEFFICIENCY if overall >= 3 else
    COLOR_BLOCKER
)

with st.expander(
    f"FinOps Maturity Score — {overall} / 5.0  "
    f"({'Implemented' if overall >= 4 else 'Developing' if overall >= 2.5 else 'Initiating'})",
    expanded=False,
):
    col_m1, col_m2 = st.columns([1, 2])
    with col_m1:
        st.markdown(
            f"<h1 style='color:{overall_color}; margin:0'>{overall} / 5.0</h1>"
            f"<p style='color:#6b7280; margin:0'>Overall FinOps Maturity</p>",
            unsafe_allow_html=True,
        )
    with col_m2:
        st.markdown(
            f"| Dimension | Score | Level |\n"
            f"|---|---|---|\n"
            f"| Tagging & Attribution | {mat.tag_score:.0f}/5 | {mat.tag_level} |\n"
            f"| Commitment Efficiency | {mat.waste_score:.0f}/5 | {mat.waste_level} |\n"
            f"| NEC Modeling | {mat.nec_score:.1f}/5 | {mat.nec_level} |\n"
            f"| Waste Detection & AI | {mat.detect_score:.1f}/5 | {mat.detect_level} |"
        )
    st.info(":dart: " + mat.guidance)

st.markdown("---")

# ---------------------------------------------------------------------------
# Data pipeline transparency
# ---------------------------------------------------------------------------

with st.expander("How this framework is built"):
    st.markdown(
        "**Data ingestion** — Three cloud sources normalised to a unified schema:  \n"
        "- AWS Cost & Usage Report (CUR) → `data/raw/aws/`  \n"
        "- Azure Cost Export → `data/raw/azure/`  \n"
        "- GCP Billing Export → `data/raw/gcp/`  \n"
        "All validated and landed to Parquet via `load_synthetic.py`.\n\n"
        "**dbt transformation** — 7 models run in the `dbt_project/` layer:  \n"
        "- Staging: schema normalisation per cloud  \n"
        "- Intermediate: NEC calculation, tag propagation, shared-cost fan-out  \n"
        "- Mart: `fct_unified_billing` — single queryable table in DuckDB\n\n"
        "**NEC calculation** — Net Effective Cost separates real from waste:  \n"
        "`NEC = nec_used + nec_waste` where `nec_waste` captures idle RI/SP capacity  \n"
        "`savings = list_cost − NEC` (discount value delivered)\n\n"
        "**Allocation logic** — three layers:  \n"
        "1. Direct: rows with `tag_team` go straight to the team  \n"
        "2. Shared: untagged shared infrastructure distributed via `SharedCostDistributor`  \n"
        "3. Heuristic fallback: account-to-team mapping fills remaining gaps\n\n"
        "**Intelligence layer** — `intelligence/` package:  \n"
        "- `waste_detector.py`: classifies idle/zombie/underutilised resources  \n"
        "- `causal_engine.py`: z-score anomaly detection + root-cause attribution  \n"
        "- `impact_simulator.py`: recovery rates × confidence → savings estimates"
    )

st.caption(
    "Navigate the pages in the sidebar to drill into each dimension. "
    "Start with **Overview** for trends, then **Waste & Recommendations** for cost recovery.  \n"
    ":information_source: Synthetic dataset — figures are for demo purposes only."
)

st.sidebar.markdown("---")
st.sidebar.caption(f"Rows loaded: {len(df):,}")
