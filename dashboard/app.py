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

from allocation.nec_model import nec_by_team
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
    compute_finops_summary_metrics,
    compute_maturity,
    compute_savings_hierarchy,
    diagnose,
    load_canonical_recommendations,
    load_df,
    load_finops_summary,
    load_scoped_df,
    normalize_canonical_recommendations,
    overlay_recommendation_actions,
    render_demo_banner,
    render_headline,
    render_priority_badge,
)
from dashboard.canonical import load_canonical_metrics

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
    page_icon="☁",
    layout="wide",
    initial_sidebar_state="expanded",
)

if not _db_ready():
    _bootstrap_db()

df, month_filter, selected_cloud = load_scoped_df(
    render_sidebar=True,
    show_sidebar_title=True,
)
summary_df = load_finops_summary(month_filter)
summary_metrics = compute_finops_summary_metrics(
    summary_df,
    clouds=selected_cloud,
    fallback_df=df,
)
canonical_metrics = load_canonical_metrics(month_filter, selected_cloud)

# ---------------------------------------------------------------------------
# Home page
# ---------------------------------------------------------------------------

st.title("Multi-Cloud FinOps Cost Attribution & Allocation Framework")
st.caption(
    "Explainable decision intelligence architecture — rule-based decision support system with statistical scoring. "
    "Research demo — Keerthi Rapolu and Rishika Naha, April 2026 — synthetic dataset for demo purposes."
)
render_demo_banner()

diag = diagnose(df, summary=summary_metrics)
render_headline(diag)

summary = (
    summary_df.groupby("cloud_provider", dropna=False)[
        ["total_list_cost", "total_nec", "total_commitment_waste"]
    ]
    .sum()
    .reset_index()
    if not summary_df.empty
    else None
)
if summary is None or summary.empty:
    summary = (
        df.groupby("cloud_provider", dropna=False)[["list_cost", "nec", "nec_waste"]]
        .sum()
        .reset_index()
        .rename(
            columns={
                "list_cost": "total_list_cost",
                "nec": "total_nec",
                "nec_waste": "total_commitment_waste",
            }
        )
    )

total_list = canonical_metrics.list_cost or summary_metrics.total_list_cost
total_nec = canonical_metrics.nec or summary_metrics.total_nec
total_commitment_waste = canonical_metrics.commitment_waste or summary_metrics.total_commitment_waste
savings_pct = ((total_list - total_nec) / total_list * 100.0) if total_list else 0.0
waste_pct = canonical_metrics.waste_rate * 100.0 if canonical_metrics.nec else summary_metrics.commitment_waste_pct
untagged_nec = canonical_metrics.unattributed_nec or summary_metrics.total_unattributed_cost
untagged_pct = canonical_metrics.tagging_gap * 100.0 if canonical_metrics.nec else summary_metrics.unattributed_pct

# Load recommendations before the KPI row so we can split actionable vs low-risk.
home_recs_df = load_canonical_recommendations(month_filter, selected_cloud)
if not home_recs_df.empty:
    home_recs = overlay_recommendation_actions(normalize_canonical_recommendations(home_recs_df))
else:
    home_recs = simulate(detect_waste(df))
low_risk_recs = [
    r for r in home_recs
    if r.get("risk") == "Low" and r.get("action_status", "recommended") != "rejected"
]
governance_signal_types = {"tagging_gap", "unattributed_cost_gap", "shared_cost_concentration"}
optimization_low_risk_recs = [
    r for r in low_risk_recs
    if r.get("signal_type") not in governance_signal_types and float(r.get("estimated_savings", 0.0) or 0.0) > 0.0
]
governance_low_risk_recs = [
    r for r in low_risk_recs
    if r.get("signal_type") in governance_signal_types or float(r.get("estimated_savings", 0.0) or 0.0) <= 0.0
]
low_risk_savings_total = canonical_metrics.low_risk_savings or sum(r["estimated_savings"] for r in low_risk_recs)
actionable_savings_total = canonical_metrics.actionable_savings or summary_metrics.total_recoverable_savings
projected_savings_total = canonical_metrics.projected_savings or actionable_savings_total

c1, c2, c3, c4 = st.columns(4)
c1.metric(LABEL_NEC, f"${total_nec:,.0f}", delta=f"{savings_pct:.1f}% discount from list price")
c2.metric(
    "Commitment Waste",
    f"${total_commitment_waste:,.0f}",
    delta=f"{waste_pct:.1f}% of NEC - idle RI/SP",
    delta_color="inverse",
)
c3.metric(
    LABEL_UNATTRIBUTED_SPEND,
    f"${untagged_nec:,.0f}",
    delta=f"{untagged_pct:.1f}% of NEC",
    delta_color="inverse",
)
c4.metric(
    LABEL_ESTIMATED_MONTHLY_SAVINGS,
    f"${projected_savings_total:,.0f}/month",
    delta=f"low-risk quick wins: ${low_risk_savings_total:,.0f}/month",
    delta_color="normal",
    help=(
        f"Realization-adjusted projection: best-case actionable (\\${actionable_savings_total:,.0f}/month) "
        f"x {canonical_metrics.realization_rate:.0%} execution probability. "
        f"Low-risk quick wins (\\${low_risk_savings_total:,.0f}/month) are a zero-downtime subset — "
        "always smaller than the full projection. Not contradictory."
    ),
)
top_low_risk_rec = max(low_risk_recs, key=lambda r: r["estimated_savings"]) if low_risk_recs else None
top_low_risk_optimization_rec = (
    max(optimization_low_risk_recs, key=lambda r: r["estimated_savings"])
    if optimization_low_risk_recs else None
)

st.markdown("---")
st.subheader("Spend by cloud")

fig = go.Figure(
    [
        go.Bar(name=LABEL_NEC, x=summary["cloud_provider"], y=summary["total_nec"], marker_color=COLOR_INFO),
        go.Bar(name="Commitment Waste", x=summary["cloud_provider"], y=summary["total_commitment_waste"], marker_color=COLOR_BLOCKER),
        go.Bar(name="Discount Savings", x=summary["cloud_provider"], y=(summary["total_list_cost"] - summary["total_nec"]), marker_color=COLOR_OPTIMIZED),
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
st.caption(
    "All pages use the same canonical NEC baseline from DuckDB. Differences between pages come from "
    "allocation transformations such as shared-cost distribution, team-level fan-out, and display rounding."
)

st.markdown("---")
st.markdown("### Top risks - ordered by priority")


def _tagging_card() -> None:
    if untagged_pct >= 20:
        st.error(
            f"P0 - Tagging gap. {untagged_pct:.1f}% of NEC (\\${untagged_nec:,.0f}) is unattributed. "
            "Every downstream metric remains unreliable until ownership tags are fixed. "
            "Next step: enforce `tag_team` at resource creation and review Tagging Coverage."
        )
    elif untagged_pct >= 10:
        st.warning(
            f"P1 - Tagging gap. {untagged_pct:.1f}% of NEC (\\${untagged_nec:,.0f}) cannot be directly allocated. "
            "See Tagging Coverage for remediation owners."
        )
    else:
        st.success(
            f"P3 - Tagging coverage acceptable. {untagged_pct:.1f}% of NEC is unattributed."
        )


def _waste_card() -> None:
    if waste_pct >= 10:
        st.error(
            f"P0 - Commitment waste. {waste_pct:.1f}% of NEC (\\${total_commitment_waste:,.0f}) is idle RI/SP capacity. "
            "Release or right-size commitments to recover this spend. Review Waste & Recommendations."
        )
    elif waste_pct >= 5:
        st.warning(
            f"P1 - Commitment waste. {waste_pct:.1f}% of NEC (\\${total_commitment_waste:,.0f}) is unused. "
            "Review commitment coverage before it increases."
        )
    else:
        st.success(
            f"P3 - Commitment utilization healthy. Waste is {waste_pct:.1f}% of NEC."
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
    st.info(
        f"INFO - Largest cost centre. {top_team_label} accounts for {top_pct:.0f}% of total NEC "
        f"(\\${team_totals.max():,.0f}, raw billing allocation — before shared-cost distribution). "
        "See Cost Allocation for the post-distribution view, which will show a higher share."
    )
except Exception:
    pass

st.markdown("**Top 3 actions** - ordered by impact")
col_a1, col_a2, col_a3 = st.columns(3)


def _action_tagging(col) -> None:
    col.error(
        f"**Fix tagging gaps**  \n"
        f"\\${untagged_nec:,.0f} of NEC is unattributed ({untagged_pct:.1f}% of spend).  \n"
        "This is attribution risk, not direct savings.  \n"
        "Outcome: restores team accountability and makes optimization reliable.  \n"
        "Owner: Platform + FinOps. Risk: Low. SLA: Immediate.  \n"
        "See Tagging Coverage."
    )


def _action_low_risk(col) -> None:
    if top_low_risk_optimization_rec is not None:
        action_label = str(top_low_risk_optimization_rec.get("action", "")).replace("_", " ").title()
        team_label = str(top_low_risk_optimization_rec.get("allocated_team", "team")).replace("-", " ").title()
        is_billing_proxy = "idle_compute" in str(
            top_low_risk_optimization_rec.get("signal_type", top_low_risk_optimization_rec.get("waste_type", ""))
        )
        col.success(
            f"**{action_label}** — {team_label}  \n"
            f"{'Estimated savings (billing proxy):' if is_billing_proxy else 'Estimated savings:'} "
            f"**\\${top_low_risk_optimization_rec['estimated_savings']:,.0f}/month** "
            f"(zero-downtime, no approval required)  \n"
            f"Guaranteed savings (no approval, no downtime): **\\${low_risk_savings_total:,.0f}/month**  \n"
            f"{len(optimization_low_risk_recs)} low-risk optimization action(s) in scope  \n"
            f"{len(governance_low_risk_recs)} governance action(s): improve attribution but do not count as direct savings.  \n"
            f"Risk: Low. SLA: **This week**  \n"
            "See Waste & Recommendations for full list."
        )
    else:
        col.success(
            f"**Review low-risk quick wins**  \n"
            f"Guaranteed savings (no approval, no downtime): **\\${low_risk_savings_total:,.0f}/month**  \n"
            f"{len(optimization_low_risk_recs)} low-risk optimization action(s) in scope  \n"
            f"{len(governance_low_risk_recs)} governance action(s) improve attribution confidence but do not add direct savings.  \n"
            "Zero-downtime, no approval required.  \n"
            "Waste & Recommendations shows only cost-recovery actions; governance actions are tracked separately."
        )


def _action_team(col) -> None:
    try:
        col.info(
            f"**Right-size {top_team_label}**  \n"
            f"Largest team — \\${team_totals.max():,.0f} cloud spend  \n"
            "Outcome: reduce idle compute + commitment waste.  \n"
            f"Owner: {top_team_label} — Risk: Medium — SLA: Next cycle  \n"
            "See Cost Allocation."
        )
    except Exception:
        col.info("**Review largest team** - see Cost Allocation for details.")


if diag.primary_issue == "tagging":
    _action_tagging(col_a1)
    _action_low_risk(col_a2)
    _action_team(col_a3)
else:
    _action_low_risk(col_a1)
    _action_tagging(col_a2)
    _action_team(col_a3)

st.markdown("---")

history_months = load_df(None)["billing_month"].nunique()
mat = compute_maturity(df, diag, recommendations=home_recs, history_months=history_months)
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
    st.info(mat.guidance)
    st.caption(
        "Automation readiness stays low in this prototype because actions still require manual validation, "
        "and runtime telemetry is not yet wired in to support auto-safe execution."
    )

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
    "Start with Overview for trends, then Waste & Recommendations for cost recovery."
)
st.caption(
    "**Framework-grade prototype**: This system demonstrates a reproducible FinOps decision-support framework "
    "using synthetic billing data that mirrors real-world multi-cloud patterns. "
    "Metrics reflect the framework's analytical behaviors, not a specific production environment. "
    "Production deployment would connect to live AWS CUR, Azure Cost Export, and GCP Billing Export."
)

st.sidebar.markdown("---")
st.sidebar.caption(f"Rows loaded: {len(df):,}")
