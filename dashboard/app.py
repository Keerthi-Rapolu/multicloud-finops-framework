"""
Multi-Cloud FinOps Dashboard - Streamlit entrypoint.

Run from repo root:
    streamlit run dashboard/app.py
"""

import sys
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from allocation.nec_model import nec_by_cloud, nec_by_team
from intelligence.impact_simulator import run as simulate
from intelligence.waste_detector import run as detect_waste
from dashboard._shared import (
    COLOR_BLOCKER,
    COLOR_INEFFICIENCY,
    COLOR_INFO,
    COLOR_OPTIMIZED,
    LABEL_ESTIMATED_MONTHLY_SAVINGS,
    LABEL_NEC,
    LABEL_UNATTRIBUTED_SPEND,
    compute_maturity,
    diagnose,
    load_scoped_df,
    render_headline,
    render_priority_badge,
)

_DB = Path(__file__).resolve().parents[1] / "finops_dbt.duckdb"
_REPO = _DB.parent


def _db_ready() -> bool:
    """Return True only when the expected mart exists and is queryable."""
    if not _DB.exists():
        return False

    import duckdb

    try:
        with duckdb.connect(str(_DB), read_only=True) as con:
            exists = con.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'marts'
                  AND table_name = 'fct_unified_billing'
                LIMIT 1
                """
            ).fetchone()
            if not exists:
                return False
            con.execute("SELECT COUNT(*) FROM marts.fct_unified_billing").fetchone()
    except Exception:
        return False

    return True


def _bootstrap_db() -> None:
    """Build the DuckDB mart from committed synthetic CSVs on first run."""
    import re

    sys.path.insert(0, str(_REPO))
    from build_mart import build_mart
    from load_synthetic import stage_land, stage_validate

    syn_aws = _REPO / "data" / "synthetic" / "aws"
    months = sorted(
        m.group(1)
        for f in sorted(syn_aws.glob("aws_cur_*.csv"))
        if (m := re.search(r"(\d{4}-\d{2})", f.name))
    )
    if not months:
        st.error(
            "**Auto-bootstrap failed** - no synthetic CSVs found in "
            "`data/synthetic/aws/`. Commit them or run `make pipeline` locally."
        )
        st.stop()

    if _DB.exists():
        _DB.unlink()

    with st.status("First-run setup - building database from synthetic data...", expanded=True) as status:
        for month in months:
            st.write(f"Loading {month}...")
            errors = stage_validate(month)
            if errors:
                st.error(f"**Synthetic data validation failed for {month}.**")
                for cloud_errors in errors.values():
                    for err in cloud_errors:
                        st.write(err)
                st.stop()
            stage_land(month)

        st.write("Building DuckDB mart...")
        try:
            build_mart(_DB, _REPO / "data")
        except Exception as exc:
            st.error(f"**Mart build failed:** {exc}")
            st.stop()
        if not _db_ready():
            st.error("**Mart build failed:** expected `marts.fct_unified_billing` was not created.")
            st.stop()

        status.update(label="Database ready - loading dashboard...", state="complete")

    st.rerun()


st.set_page_config(
    page_title="Multi-Cloud FinOps",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="expanded",
)

if not _db_ready():
    _bootstrap_db()

df, _, _ = load_scoped_df(
    render_sidebar=True,
    show_sidebar_title=True,
)

# ---------------------------------------------------------------------------
# Home page
# ---------------------------------------------------------------------------

st.title("AI-Ready Multi-Cloud FinOps Cost Attribution & Allocation Framework")
st.caption("Research demo - Keerthi Rapolu & Rishika Naha, April 2026 - Synthetic dataset for demo purposes")

diag = diagnose(df)
render_headline(diag)

summary = nec_by_cloud(df)
total_list = summary["list_cost"].sum()
total_nec = summary["nec"].sum()
total_waste = summary["nec_waste"].sum()
savings_pct = (1 - total_nec / total_list) * 100 if total_list else 0

waste_pct = total_waste / total_nec * 100 if total_nec else 0
is_tagged = df["is_tagged"].fillna(False)
untagged_nec = df.loc[~is_tagged, "nec"].sum()
untagged_pct = untagged_nec / total_nec * 100 if total_nec else 0

c1, c2, c3, c4 = st.columns(4)
c1.metric(LABEL_NEC, f"${total_nec:,.0f}", delta=f"{savings_pct:.1f}% discount from list price")
c2.metric(
    "Waste",
    f"${total_waste:,.0f}",
    delta=f"{waste_pct:.1f}% of NEC - idle commitments",
    delta_color="inverse",
)
c3.metric(
    LABEL_UNATTRIBUTED_SPEND,
    f"${untagged_nec:,.0f}",
    delta=f"{untagged_pct:.1f}% has no owner",
    delta_color="inverse",
)
c4.metric(
    LABEL_ESTIMATED_MONTHLY_SAVINGS,
    f"${diag.low_risk_savings:,.0f}/mo",
    delta="low-risk - no service interruption",
)

st.markdown("---")
st.subheader("Spend by cloud")

fig = go.Figure(
    [
        go.Bar(name=LABEL_NEC, x=summary["cloud_provider"], y=summary["nec"], marker_color=COLOR_INFO),
        go.Bar(name="Waste", x=summary["cloud_provider"], y=summary["nec_waste"], marker_color=COLOR_BLOCKER),
        go.Bar(name="Discounts", x=summary["cloud_provider"], y=summary["savings"], marker_color=COLOR_OPTIMIZED),
    ]
)
fig.update_layout(
    barmode="stack",
    xaxis_title="Cloud",
    yaxis_title="USD",
    legend=dict(orientation="h", y=1.12),
    height=350,
    margin=dict(t=10, b=40),
)
st.plotly_chart(fig, use_container_width=True)

st.markdown("---")
st.markdown("### Top risks - ordered by priority")


def _tagging_card() -> None:
    if untagged_pct >= 20:
        badge = render_priority_badge("P0", "P0 - Fix first")
        st.markdown(
            f"{badge} &nbsp; :red_circle: **Tagging gap - PRIMARY BLOCKER**  \n"
            f"**{untagged_pct:.1f}%** of NEC (${untagged_nec:,.0f}) is unattributed. "
            "Every downstream metric (allocation, optimization, chargeback) is unreliable "
            "until this is fixed. Enforce `tag_team` policy at resource creation. "
            "Target: <10% within 60 days. -> **Tagging Coverage**",
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
            f"{badge} &nbsp; :green_circle: **Tagging coverage acceptable** - "
            f"{untagged_pct:.1f}% of NEC is unattributed.",
            unsafe_allow_html=True,
        )


def _waste_card() -> None:
    if waste_pct >= 10:
        badge = render_priority_badge("P0", "P0 - Fix first")
        st.markdown(
            f"{badge} &nbsp; :red_circle: **Commitment waste - PRIMARY BLOCKER**  \n"
            f"**{waste_pct:.1f}%** of NEC (${total_waste:,.0f}) is idle RI/SP capacity. "
            "Release or right-size to recover immediately. -> **Waste & Recommendations**",
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
            f"{badge} &nbsp; :green_circle: **Commitment utilization healthy** - "
            f"waste is {waste_pct:.1f}% of NEC.",
            unsafe_allow_html=True,
        )


if diag.primary_issue == "tagging":
    _tagging_card()
    _waste_card()
else:
    _waste_card()
    _tagging_card()

try:
    team_labels = {
        "data-eng": "Data Engineering",
        "platform": "Platform",
        "frontend": "Frontend",
        "backend": "Backend",
        "ml": "Machine Learning",
    }
    by_team = nec_by_team(df)
    team_totals = by_team.groupby("team")["nec"].sum()
    top_team_key = team_totals.idxmax()
    top_team_label = team_labels.get(top_team_key, top_team_key.replace("-", " ").title())
    top_pct = team_totals.max() / total_nec * 100
    badge_info = render_priority_badge("P2", "INFO")
    st.markdown(
        f"{badge_info} &nbsp; :blue_circle: **Largest cost centre** - {top_team_label} "
        f"accounts for {top_pct:.0f}% of total NEC (${team_totals.max():,.0f}). "
        "-> **Cost Allocation**",
        unsafe_allow_html=True,
    )
except Exception:
    pass

st.markdown("**Top 3 actions** - ordered by impact")
col_a1, col_a2, col_a3 = st.columns(3)
waste_saving_est = total_waste * 0.85


def _action_tagging(col) -> None:
    col.error(
        f"**Fix tagging gaps**  \n"
        f"**${untagged_nec:,.0f}** unattributed ({untagged_pct:.0f}% of spend)  \n"
        f"-> Outcome: unlocks full cost optimization  \n"
        f"Owner: Platform + FinOps - Risk: Low - SLA: **Immediate**  \n"
        f"-> Tagging Coverage"
    )


def _action_waste(col) -> None:
    col.success(
        f"**Release idle commitments**  \n"
        f"Save **${waste_saving_est:,.0f}/month**  \n"
        f"-> Outcome: immediate cost reduction, no downtime  \n"
        f"Owner: Cloud Platform - Risk: Low - SLA: **This week**  \n"
        f"-> Waste & Recommendations"
    )


def _action_team(col) -> None:
    try:
        col.info(
            f"**Right-size {top_team_label}**  \n"
            f"Largest team - ${team_totals.max():,.0f} cloud spend  \n"
            f"-> Outcome: reduce idle compute + commitment waste  \n"
            f"Owner: {top_team_label} - Risk: Medium - SLA: **Next cycle**  \n"
            f"-> Cost Allocation"
        )
    except Exception:
        col.info("**Review largest team** - see Cost Allocation for details.")


if diag.primary_issue == "tagging":
    _action_tagging(col_a1)
    _action_waste(col_a2)
    _action_team(col_a3)
else:
    _action_waste(col_a1)
    _action_tagging(col_a2)
    _action_team(col_a3)

st.markdown("---")

home_recs = simulate(detect_waste(df))
mat = compute_maturity(df, diag, recommendations=home_recs)
overall = mat.overall
overall_color = (
    COLOR_OPTIMIZED
    if overall >= 4
    else COLOR_INEFFICIENCY
    if overall >= 3
    else COLOR_BLOCKER
)

with st.expander(
    f"FinOps Maturity Score - {overall} / 5.0  "
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
            f"| Tagging Maturity | {mat.tagging_score:.1f}/5 | {mat.tagging_level} |\n"
            f"| Ownership Maturity | {mat.ownership_score:.1f}/5 | {mat.ownership_level} |\n"
            f"| Allocation Maturity | {mat.allocation_score:.1f}/5 | {mat.allocation_level} |\n"
            f"| Commitment Efficiency | {mat.commitment_score:.1f}/5 | {mat.commitment_level} |\n"
            f"| Waste Detection | {mat.detect_score:.1f}/5 | {mat.detect_level} |\n"
            f"| Forecasting | {mat.forecasting_score:.1f}/5 | {mat.forecasting_level} |\n"
            f"| Automation Readiness | {mat.automation_score:.1f}/5 | {mat.automation_level} |"
        )
    st.info(":dart: " + mat.guidance)

st.markdown("---")

with st.expander("How this framework is built"):
    st.markdown(
        "**Data ingestion** - Three cloud sources normalised to a unified schema:  \n"
        "- AWS Cost & Usage Report (CUR) -> `data/raw/aws/`  \n"
        "- Azure Cost Export -> `data/raw/azure/`  \n"
        "- GCP Billing Export -> `data/raw/gcp/`  \n"
        "All validated and landed to Parquet via `load_synthetic.py`.\n\n"
        "**dbt transformation** - 7 models run in the `dbt_project/` layer:  \n"
        "- Staging: schema normalisation per cloud  \n"
        "- Intermediate: NEC calculation, tag propagation, shared-cost fan-out  \n"
        "- Mart: `fct_unified_billing` - single queryable table in DuckDB\n\n"
        "**NEC calculation** - Net Effective Cost separates real from waste:  \n"
        "`NEC = nec_used + nec_waste` where `nec_waste` captures idle RI/SP capacity  \n"
        "`savings = list_cost - NEC` (discount value delivered)\n\n"
        "**Allocation logic** - three layers:  \n"
        "1. Direct: rows with `tag_team` go straight to the team  \n"
        "2. Shared: untagged shared infrastructure distributed via `SharedCostDistributor`  \n"
        "3. Heuristic fallback: account-to-team mapping fills remaining gaps\n\n"
        "**Intelligence layer** - `intelligence/` package:  \n"
        "- `waste_detector.py`: classifies idle/zombie/underutilised resources  \n"
        "- `causal_engine.py`: z-score anomaly detection + root-cause attribution  \n"
        "- `impact_simulator.py`: recovery rates x confidence -> savings estimates"
    )

st.caption(
    "Navigate the pages in the sidebar to drill into each dimension. "
    "Start with **Overview** for trends, then **Waste & Recommendations** for cost recovery.  \n"
    ":information_source: Synthetic dataset - figures are for demo purposes only."
)

st.sidebar.markdown("---")
st.sidebar.caption(f"Rows loaded: {len(df):,}")
