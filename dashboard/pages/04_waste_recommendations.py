"""
Page 4 - Waste & Recommendations

Full waste-to-action pipeline: detects recoverable waste, explains root causes,
and surfaces prioritized recommendations with savings estimates and risk scores.
Flow: Problem -> Root Cause -> Action -> Savings -> Risk
"""

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from intelligence.impact_simulator import run as simulate
from intelligence.reasoning_engine import from_recommendation
from intelligence.waste_detector import run as detect_waste
from dashboard._shared import (
    ACTION_OPS,
    COLOR_BLOCKER,
    COLOR_INEFFICIENCY,
    COLOR_OPTIMIZED,
    LABEL_ACTIONABLE_OPPORTUNITY,
    LABEL_ESTIMATED_MONTHLY_SAVINGS,
    LABEL_UNATTRIBUTED_SPEND,
    SAVINGS_NOISE_THRESHOLD_USD,
    SIGNAL_ACTION_MAP,
    SavingsHierarchy,
    compute_finops_summary_metrics,
    compute_savings_hierarchy,
    diagnose,
    load_canonical_forecast,
    load_finops_summary,
    enrich_recommendation,
    load_canonical_recommendations,
    load_scoped_df,
    normalize_canonical_recommendations,
    overlay_recommendation_actions,
    render_demo_banner,
    render_headline,
    render_priority_badge,
    save_recommendation_action,
)
from dashboard.exporters import jira_action_csv_bytes, recommendation_csv_bytes
from dashboard.canonical import load_canonical_metrics

_TYPE_COLORS = {
    "governance_gap":        "#ef4444",
    "tagging_gap":           "#ef4444",
    "unattributed_cost_gap": "#ef4444",
    "commitment_mismatch":   "#2563eb",
    "commitment_waste":      "#2563eb",
    "idle_resource":         "#f97316",
    "idle_compute_proxy":    "#f97316",
    "zombie_resource":       "#8b5cf6",
    "unused_commitment":        "#ef4444",
    "idle_compute":             "#f97316",
    "underutilized_commitment": "#eab308",
    "shared_cost_concentration": "#0ea5e9",
    "cost_anomaly":             "#b45309",
    "forecasted_month_end_risk": "#7c3aed",
}
_TYPE_LABELS = {
    "governance_gap":        "Governance Gap",
    "tagging_gap":           "Tagging Gap",
    "unattributed_cost_gap": "Unattributed Cost Gap",
    "commitment_mismatch":   "Commitment Mismatch",
    "commitment_waste":      "Commitment Waste",
    "idle_resource":         "Right-sizing Candidate",
    "idle_compute_proxy":    "Right-sizing Candidate",
    "zombie_resource":       "Zombie Resource",
    "unused_commitment":        "Unused Commitment",
    "idle_compute":             "Right-sizing Candidate",
    "underutilized_commitment": "Underutilized Commitment",
    "shared_cost_concentration": "Shared Cost Concentration",
    "cost_anomaly":             "Cost Anomaly",
    "forecasted_month_end_risk": "Forecasted Month-End Risk",
}
_ACTION_COLORS = {
    "enforce_tags":       "#ef4444",
    "release_commitment": "#2563eb",
    "resize_down":        "#f97316",
    "remove_resource":    "#8b5cf6",
}
_ACTION_LABELS = {
    "enforce_tags":       "Enforce Tags",
    "release_commitment": "Release Commitment",
    "resize_down":        "Resize Down",
    "remove_resource":    "Remove Resource",
}
_RECOVERABLE_SIGNAL_TYPES = {
    "commitment_waste",
    "commitment_mismatch",
    "unused_commitment",
    "underutilized_commitment",
    "idle_compute_proxy",
    "idle_resource",
    "idle_compute",
    "zombie_resource",
}
_TEAM_LABELS = {
    "data-eng":    "Data Engineering",
    "platform":    "Platform",
    "frontend":    "Frontend",
    "backend":     "Backend",
    "ml":          "Machine Learning",
    "unattributed":"Unattributed",
}

st.set_page_config(page_title="Waste & Recommendations", layout="wide")
st.title("Waste & Recommendations")
st.caption("Where is recoverable cost leaking, and what should you do about it?")
render_demo_banner()

df, month_filter, selected_cloud = load_scoped_df(render_sidebar=True)
summary_df = load_finops_summary(month_filter)

# Executive headline (Critical #1)
summary_metrics = compute_finops_summary_metrics(
    summary_df,
    clouds=selected_cloud,
    fallback_df=df,
)
canonical_page_metrics = load_canonical_metrics(month_filter, selected_cloud)
diag = diagnose(df, summary=summary_metrics)
render_headline(diag)

# ---------------------------------------------------------------------------
# Run pipeline (cached per DataFrame identity)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Scanning for waste and simulating impact...")
def _run_pipeline(df_hash: int, _df: pd.DataFrame):
    findings = detect_waste(_df)
    recs = simulate(findings)
    return findings, recs

# Content-based hash so cache hits when the data is unchanged
# (id(df) changes on every reload, which defeats the cache).
_df_hash = int(pd.util.hash_pandas_object(df, index=True).sum())
canonical_recs_df   = load_canonical_recommendations(month_filter, selected_cloud)
canonical_forecast_df = load_canonical_forecast(month_filter, selected_cloud)
# Canonical forecast values — used to keep page 4 and page 5 mathematically consistent.
_forecast_realization_rate: float | None = None
_forecast_realized_savings: float | None = None
_forecast_optimized_nec: float | None = None
if not canonical_forecast_df.empty:
    if "realization_rate" in canonical_forecast_df.columns:
        _forecast_realization_rate = float(canonical_forecast_df["realization_rate"].mean())
    if "projected_realized_savings_usd" in canonical_forecast_df.columns:
        _forecast_realized_savings = float(canonical_forecast_df["projected_realized_savings_usd"].sum())
    if "optimized_month_end_nec" in canonical_forecast_df.columns:
        _forecast_optimized_nec = float(canonical_forecast_df["optimized_month_end_nec"].sum())
if not canonical_recs_df.empty:
    recs = normalize_canonical_recommendations(canonical_recs_df)
    findings = [
        {
            "resource_id": rec.get("resource_id") or f"{rec['allocated_team']}::{rec.get('signal_type', 'issue')}",
            "cloud_provider": rec["cloud_provider"],
            "allocated_team": rec["allocated_team"],
            "waste_type": rec.get("signal_type", rec.get("waste_type", "issue")),
            "nec_waste": float(rec["current_cost"]) if rec.get("signal_type") in _RECOVERABLE_SIGNAL_TYPES else 0.0,
            "nec_used": 0.0,
            "confidence": float(rec["confidence"]),
        }
        for rec in recs
        if rec.get("signal_type") in _RECOVERABLE_SIGNAL_TYPES
    ]
    st.caption("Using canonical recoverable-waste recommendation tables from DuckDB.")
else:
    findings, recs = _run_pipeline(_df_hash, df)
    st.caption("Canonical recommendation tables are unavailable for this scope; using the fallback page-local pipeline.")

waste_recs = [
    r for r in recs
    if r.get("signal_type") in _RECOVERABLE_SIGNAL_TYPES
    and float(r.get("estimated_savings", 0.0) or 0.0) >= SAVINGS_NOISE_THRESHOLD_USD
] if recs else []

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------

st.sidebar.markdown("---")
st.sidebar.subheader("Page filters")
st.sidebar.caption("Drill-down only - the global month/cloud filters still apply.")

all_types  = sorted({r.get("waste_type", r.get("signal_type", "issue")) for r in waste_recs}) if waste_recs else sorted({f["waste_type"] for f in findings}) if findings else []
team_pool = set(df["allocated_team"].fillna("unattributed").astype(str).unique())
team_pool.update(r["allocated_team"] for r in waste_recs)
team_pool.update(f["allocated_team"] for f in findings)
all_teams = sorted(team_pool)
cloud_pool = set(df["cloud_provider"].fillna("").astype(str).unique())
cloud_pool.update(r["cloud_provider"] for r in waste_recs)
cloud_pool.update(f["cloud_provider"] for f in findings)
all_clouds = sorted(c for c in cloud_pool if c)

sel_types  = st.sidebar.multiselect("Waste type", all_types,  default=all_types)
sel_teams  = st.sidebar.multiselect("Team",        all_teams,  default=all_teams)
sel_clouds = st.sidebar.multiselect("Cloud",       all_clouds, default=all_clouds)
sel_risks  = st.sidebar.multiselect("Risk level",  ["Low", "Medium", "High"], default=["Low", "Medium", "High"])

filtered_findings = [
    f for f in findings
    if f["waste_type"]     in sel_types
    and f["allocated_team"] in sel_teams
    and f["cloud_provider"] in sel_clouds
] if findings else []

scope_df = df[
    df["allocated_team"].isin(sel_teams)
    & df["cloud_provider"].isin(sel_clouds)
].copy()
scope_summary = compute_finops_summary_metrics(
    summary_df,
    clouds=sel_clouds,
    teams=sel_teams,
    fallback_df=scope_df,
)
canonical_metrics = load_canonical_metrics(
    month_filter,
    selected_cloud if selected_cloud != "All" else (sel_clouds[0] if len(sel_clouds) == 1 else "All"),
    teams=sel_teams,
)
_scope_total_nec = float(scope_summary.total_nec)
_scope_commitment_waste = float(scope_summary.total_commitment_waste)
_scope_commitment_utilization = max(
    0.0,
    100.0 - ((_scope_commitment_waste / _scope_total_nec * 100) if _scope_total_nec else 0.0),
)

filtered_recs = [
    r for r in waste_recs
    if r["allocated_team"]      in sel_teams
    and r.get("cloud_provider") in sel_clouds
    and r.get("waste_type")     in sel_types
    and r["risk"]               in sel_risks
] if recs else []
filtered_recs = overlay_recommendation_actions(filtered_recs)

_scope_untagged_nec = float(scope_summary.total_unattributed_cost)
_scope_untagged_pct = (_scope_untagged_nec / _scope_total_nec * 100) if _scope_total_nec else 0.0
_scope_tagging_coverage = max(0.0, 100.0 - _scope_untagged_pct)

def _owner_status(rec: dict) -> str:
    owner = str(rec.get("action_owner") or rec.get("owner_email") or "").strip().lower()
    return "assigned" if owner and "unassigned" not in owner else "missing"

def _sla_status(rec: dict) -> str:
    return "breached" if _owner_status(rec) != "assigned" else "within_sla"

filtered_recs = [
    {
        **rec,
        "reasoning": from_recommendation(
            rec,
            nec=_scope_total_nec,
            waste_amount=float(rec.get("current_cost", 0.0)),
            waste_pct=(float(rec.get("current_cost", 0.0)) / _scope_total_nec * 100) if _scope_total_nec else 0.0,
            unattributed_spend=float(_scope_untagged_nec),
            unattributed_pct=float(_scope_untagged_pct),
            tagging_coverage_pct=float(_scope_tagging_coverage),
            commitment_utilization_pct=_scope_commitment_utilization,
            commitment_waste=_scope_commitment_waste,
            owner_status=_owner_status(rec),
            sla_status=_sla_status(rec),
            trend_direction="stable",
            month_over_month_change_pct=0.0,
        ),
    }
    for rec in filtered_recs
]

# ---------------------------------------------------------------------------
# KPI row
# ---------------------------------------------------------------------------

total_nec = canonical_metrics.nec or scope_summary.total_nec
total_commitment_waste = canonical_metrics.commitment_waste or scope_summary.total_commitment_waste
total_unattributed_cost = canonical_metrics.unattributed_nec or scope_summary.total_unattributed_cost
recoverable_savings = canonical_metrics.recoverable_savings or scope_summary.total_recoverable_savings or sum(
    r["estimated_savings"] for r in filtered_recs
)
actionable_savings = canonical_metrics.actionable_savings or recoverable_savings
projected_savings = canonical_metrics.projected_savings or actionable_savings
savings_pct_of_nec = projected_savings / total_nec * 100 if total_nec else 0
commitment_waste_pct = total_commitment_waste / total_nec * 100 if total_nec else 0
unattributed_pct = total_unattributed_cost / total_nec * 100 if total_nec else 0
total_waste_detected = total_commitment_waste
waste_pct = commitment_waste_pct
n_quick_wins   = sum(1 for r in filtered_recs if r["risk"] == "Low")

_n_low  = sum(1 for r in filtered_recs if r.get("risk") == "Low")
_n_med  = sum(1 for r in filtered_recs if r.get("risk") == "Medium")
_n_high = sum(1 for r in filtered_recs if r.get("risk") == "High")

ck1, ck2, ck3, ck4 = st.columns(4)
ck1.metric(
    LABEL_UNATTRIBUTED_SPEND,
    f"${total_unattributed_cost:,.0f}",
    delta=f"{unattributed_pct:.1f}% of NEC",
    delta_color="inverse",
    help="Current-period NEC with missing tag_team attribution in the canonical filter scope.",
)
ck2.metric("Commitment Waste", f"${total_commitment_waste:,.0f}",
           delta=f"{commitment_waste_pct:.1f}% of NEC", delta_color="inverse")
ck3.metric(
    "Recommendations",
    str(len(filtered_recs)),
    help=(
        f"Total canonical signals: {len(filtered_recs)}. "
        f"Low-risk quick wins: {_n_low} (zero-downtime, act now). "
        f"Medium-risk: {_n_med} (needs approval). "
        f"High-risk: {_n_high} (excluded from savings estimates)."
    ),
)
ck4.metric(
    LABEL_ESTIMATED_MONTHLY_SAVINGS,
    f"${projected_savings:,.0f}",
    delta=f"best-case: ${actionable_savings:,.0f}",
    help=(
        f"Realization-adjusted = best-case actionable (\\${actionable_savings:,.0f}) "
        f"x {canonical_metrics.realization_rate:.0%} execution probability. "
        f"Low-risk quick wins only: \\${sum(r['estimated_savings'] for r in filtered_recs if r.get('risk') == 'Low'):,.0f}/month."
    ),
)
st.caption(
    f"Recommendation counts: **{len(filtered_recs)} total** canonical signals "
    f"— {_n_low} low-risk (quick wins, no downtime), "
    f"{_n_med} medium-risk (approval required), "
    f"{_n_high} high-risk (excluded from projected savings). "
    f"**Best-case actionable** (\\${actionable_savings:,.0f}) includes low+medium risk. "
    f"**Realization-adjusted** (\\${projected_savings:,.0f}) applies the {canonical_metrics.realization_rate:.0%} execution rate."
)

if not filtered_findings:
    st.success(
        "No waste detected in the selected filters. "
        "Try loading more months or broadening the sidebar filters."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Savings hierarchy banner — anchored to canonical forecast for cross-page consistency.
# Use all canonical recs (not just recoverable-waste subset) so actionable matches page 5.
# ---------------------------------------------------------------------------
_all_recs_for_banner = (
    overlay_recommendation_actions(normalize_canonical_recommendations(canonical_recs_df))
    if not canonical_recs_df.empty else (filtered_recs or [])
)
_hier_preview = SavingsHierarchy(
    inefficiency_signal=canonical_metrics.waste_signal or compute_savings_hierarchy(_all_recs_for_banner, realization_rate=_forecast_realization_rate).inefficiency_signal,
    recoverable_opportunity=canonical_metrics.recoverable_savings or compute_savings_hierarchy(_all_recs_for_banner, realization_rate=_forecast_realization_rate).recoverable_opportunity,
    actionable_savings=canonical_metrics.actionable_savings or compute_savings_hierarchy(_all_recs_for_banner, realization_rate=_forecast_realization_rate).actionable_savings,
    realized_projection=canonical_metrics.projected_savings or compute_savings_hierarchy(_all_recs_for_banner, realization_rate=_forecast_realization_rate).realized_projection,
    realization_rate=canonical_metrics.realization_rate or (_forecast_realization_rate or 0.70),
)
# Anchor realized to the canonical forecast row — removes per-page computation drift.
if _forecast_realized_savings is not None:
    _hier_preview.realized_projection = _forecast_realized_savings
_signal_share = f"{_hier_preview.inefficiency_signal / total_nec * 100:.1f}%" if total_nec else "n/a"
_realized_share = f"{_hier_preview.realized_projection / total_nec * 100:.1f}%" if total_nec else "n/a"
st.markdown(
    f'<div style="background:#eff6ff; border-left:4px solid #2563eb; '
    f'padding:10px 14px; border-radius:4px; font-size:0.93rem;">'
    f"{_hier_preview.layer_label_html()}"
    f"<br/><span style='color:#6b7280; font-size:0.85rem;'>"
    f"Signal intensity: <b>{_signal_share} of NEC</b> (can exceed 100% — signals overlap; "
    f"not additive; for example, the same resource can be flagged by both idle-compute and zombie-resource logic) &nbsp;|&nbsp; "
    f"Realized reduction: <b>{_realized_share} of NEC</b> &nbsp;|&nbsp; "
    f"Signal &ne; savings &mdash; raw billing problem before recovery rates and risk filters."
    f"</span></div>",
    unsafe_allow_html=True,
)

st.markdown("---")

# ---------------------------------------------------------------------------
# Step 1 - Where is the waste
# ---------------------------------------------------------------------------

st.subheader("Step 1 - Where is the waste")
st.caption(
    "NEC always includes both used cost and embedded waste components. "
    "This page does not redefine NEC — it breaks NEC into governance blockers, commitment waste, "
    "and recoverable optimization signals for action planning."
)
st.caption(
    "Formula: inefficiency_score = 0.6 * relative_signal_intensity + 0.4 * absolute_leakage."
)
st.caption(
    "Terminology (used consistently across all pages): "
    "**unattributed** = NEC rows with missing `tag_team` (attribution gap); "
    "**unassigned** = recommendations with no saved owner email (accountability gap); "
    "**untagged** = resources missing one or more required governance tags. "
    "These are governance blockers, not recoverable waste — they are excluded from this page's savings estimates."
)

fdf = pd.DataFrame(filtered_findings)
fdf["cost_impact"] = fdf.apply(
    lambda r: r["nec_waste"] if r["nec_waste"] > 0 else r["nec_used"], axis=1
)
fdf["team_label"] = (
    fdf["allocated_team"].map(_TEAM_LABELS)
    .fillna(fdf["allocated_team"].str.replace("-", " ").str.title())
)

by_type = (
    fdf.groupby("waste_type")["cost_impact"]
    .sum().reset_index()
    .sort_values("cost_impact", ascending=True)
)
by_type["label"] = by_type["waste_type"].map(_TYPE_LABELS).fillna(by_type["waste_type"])

col_chart, col_actions = st.columns([3, 2])

with col_chart:
    fig_type = px.bar(
        by_type, x="cost_impact", y="label", orientation="h",
        color="waste_type",
        color_discrete_map=_TYPE_COLORS,
        labels={"cost_impact": "NEC Impact (USD)", "label": "Waste Type"},
        text=by_type["cost_impact"].map("${:,.0f}".format),
    )
    fig_type.update_traces(textposition="outside")
    fig_type.update_layout(height=240, margin=dict(t=10, b=40, r=160),
                           showlegend=False, yaxis_title=None)
    st.plotly_chart(fig_type, use_container_width=True)
    st.caption(
        "Unused Commitment = billing-confirmed idle RI/SP capacity. "
        "Idle Compute Proxy = billing-side right-sizing candidate (underutilization proxy; "
        "runtime CPU/memory telemetry confirmation required before acting). "
        "Zombie Resource = near-zero-cost inactive resource. "
        "Underutilized Commitment = commitment utilization below 70%."
    )

with col_actions:
    _action_map = {
        "commitment_mismatch":      "Release or rebalance commitments",
        "idle_resource":            "Right-size (billing-side right-sizing candidate — confirm with runtime telemetry)",
        "zombie_resource":          "Decommission and delete",
        "unused_commitment":        "Release / downsize the commitment",
        "underutilized_commitment": "Partially release commitment",
        "idle_compute":             "Right-size (billing-side right-sizing candidate — confirm with runtime telemetry)",
        "idle_compute_proxy":       "Right-size (billing-side right-sizing candidate — confirm with runtime telemetry)",
    }
    for wtype in ["commitment_mismatch", "idle_resource", "zombie_resource", "unused_commitment", "underutilized_commitment", "idle_compute"]:
        group = [f for f in filtered_findings if f["waste_type"] == wtype]
        if not group:
            continue
        total = sum(f["nec_waste"] if f["nec_waste"] > 0 else f["nec_used"] for f in group)
        label = _TYPE_LABELS.get(wtype, wtype)
        st.markdown(
            f"**{label}** — {len(group)} finding{'s' if len(group) != 1 else ''}  \n"
            f"NEC impact: **\\${total:,.0f}**  \n"
            f"Recommended action: {_action_map.get(wtype, 'Review')}"
        )
        st.markdown("")

# ---------------------------------------------------------------------------
# Cross-cloud inefficiency comparison (Medium #8)
# Shows which cloud is leaking the most *relative to its NEC share* — a small
# cloud can look fine in $ but catastrophic in efficiency terms.
# ---------------------------------------------------------------------------
st.markdown("---")

cloud_nec = scope_df.groupby("cloud_provider")["nec"].sum().rename("nec")
cloud_waste_map = fdf.groupby("cloud_provider")["cost_impact"].sum().rename("waste")
cross = pd.concat([cloud_nec, cloud_waste_map], axis=1).fillna(0).reset_index()
cross["waste_pct"] = (cross["waste"] / cross["nec"].replace(0, float("nan")) * 100).fillna(0).round(1)
cross["cloud_label"] = cross["cloud_provider"].str.upper()
cross["relative_norm"] = cross["waste_pct"] / max(cross["waste_pct"].max(), 1.0)
cross["absolute_norm"] = cross["waste"] / max(cross["waste"].max(), 1.0)
cross["combined_score"] = (0.6 * cross["relative_norm"]) + (0.4 * cross["absolute_norm"])

st.subheader("Cross-cloud inefficiency")
st.caption(
    "Compares absolute waste with waste-as-a-share-of-NEC. A small cloud can still "
    "be the most *inefficient* - this view surfaces that."
)

col_xc1, col_xc2 = st.columns(2)
with col_xc1:
    fig_xc_abs = px.bar(
        cross.sort_values("waste", ascending=True),
        x="waste", y="cloud_label", orientation="h",
        color="cloud_provider",
        color_discrete_map={"aws": "#f97316", "azure": "#2563eb", "gcp": "#22c55e"},
        labels={"waste": "Waste (USD)", "cloud_label": "Cloud"},
        text=cross.sort_values("waste", ascending=True)["waste"].map("${:,.0f}".format),
    )
    fig_xc_abs.update_traces(textposition="outside")
    fig_xc_abs.update_layout(height=200, margin=dict(t=10, b=30, r=100),
                             showlegend=False, yaxis_title=None)
    st.plotly_chart(fig_xc_abs, use_container_width=True)
    st.caption("**Absolute** - dollar leakage.")

with col_xc2:
    fig_xc_rel = px.bar(
        cross.sort_values("waste_pct", ascending=True),
        x="waste_pct", y="cloud_label", orientation="h",
        color="waste_pct",
        color_continuous_scale=[[0, COLOR_OPTIMIZED], [0.5, COLOR_INEFFICIENCY], [1, COLOR_BLOCKER]],
        range_color=[0, max(10.0, cross["waste_pct"].max())],
        labels={"waste_pct": "Waste as % of NEC", "cloud_label": "Cloud"},
        text=cross.sort_values("waste_pct", ascending=True)["waste_pct"].map("{:.1f}%".format),
    )
    fig_xc_rel.update_traces(textposition="outside")
    fig_xc_rel.update_layout(height=200, margin=dict(t=10, b=30, r=80),
                             coloraxis_showscale=False, yaxis_title=None)
    st.plotly_chart(fig_xc_rel, use_container_width=True)
    st.caption("**Relative** - efficiency; a lower bar = healthier cloud.")

# Callout: worst cloud by relative efficiency
if not cross.empty and cross["combined_score"].max() > 0:
    worst = cross.loc[cross["combined_score"].idxmax()]
    if worst["waste_pct"] >= 5:
        st.info(
            f"Highest combined inefficiency score (current filter selection): **{worst['cloud_label']}** — "
            f"60% relative signal intensity + 40% absolute leakage. "
            f"Signal intensity {worst['waste_pct']:.1f}% of NEC — "
            f"\\${worst['waste']:,.0f} raw billing signal, not all directly recoverable. "
            "Use the relative chart for efficiency and the absolute chart for dollar scale."
        )

st.markdown("---")

# Waste by team (stacked bar)
by_team_type = (
    fdf.groupby(["team_label", "waste_type"])["cost_impact"]
    .sum().reset_index()
)
fig_team = px.bar(
    by_team_type, x="team_label", y="cost_impact", color="waste_type",
    color_discrete_map=_TYPE_COLORS,
    labels={"cost_impact": "NEC Impact (USD)", "team_label": "Team", "waste_type": "Waste Type"},
    category_orders={"waste_type": list(_TYPE_COLORS.keys())},
)
fig_team.update_layout(
    height=300, margin=dict(t=10, b=60), xaxis_title=None,
    legend_title_text="Waste Type",
    legend=dict(orientation="h", y=-0.25),
)
st.plotly_chart(fig_team, use_container_width=True)

# Findings table
with st.expander("All waste findings"):
    tbl = fdf.sort_values("cost_impact", ascending=False).reset_index(drop=True)
    disp_tbl = pd.DataFrame({
        "Resource":   tbl["resource_id"].apply(lambda x: ("..." + str(x)[-35:]) if len(str(x)) > 38 else str(x)),
        "Cloud":      tbl["cloud_provider"].str.upper(),
        "Team":       tbl["team_label"],
        "Waste Type": tbl["waste_type"].map(_TYPE_LABELS).fillna(tbl["waste_type"]),
        "NEC Impact": tbl["cost_impact"].map("${:,.0f}".format),
        "Confidence": tbl["confidence"].map("{:.0%}".format),
    })
    st.dataframe(disp_tbl, use_container_width=True, hide_index=True)

st.markdown("---")

# ---------------------------------------------------------------------------
# Step 2 - What actions recover the most
# ---------------------------------------------------------------------------

st.subheader("Step 2 - What actions recover the most")

if not filtered_recs:
    st.info("No recommendations match the current filters.")
else:
    # Enrich every recommendation with Owner / Automation / SLA (Critical #4, Add #4)
    enriched_recs = [enrich_recommendation(r) for r in filtered_recs]
    rdf = pd.DataFrame(enriched_recs)
    rdf["action_label"] = rdf["action"].map(_ACTION_LABELS).fillna(rdf["action"])
    rdf["team_label"]   = (
        rdf["allocated_team"].map(_TEAM_LABELS)
        .fillna(rdf["allocated_team"].str.replace("-", " ").str.title())
    )

    by_action = (
        rdf.groupby(["action", "action_label"])["estimated_savings"]
        .sum().reset_index()
        .sort_values("estimated_savings", ascending=True)
    )
    fig_action = px.bar(
        by_action, x="estimated_savings", y="action_label", orientation="h",
        color="action",
        color_discrete_map=_ACTION_COLORS,
        labels={"estimated_savings": "Estimated Savings (USD)", "action_label": "Action"},
        text=by_action["estimated_savings"].map("${:,.0f}".format),
    )
    fig_action.update_traces(textposition="outside")
    fig_action.update_layout(height=200, margin=dict(t=10, b=40, r=160),
                             showlegend=False, yaxis_title=None)
    st.plotly_chart(fig_action, use_container_width=True)
    st.caption(
        "**Release Commitment** - release or downsize idle RI/SP.  "
        "**Resize Down** - right-size idle compute.  "
        "**Remove Resource** - decommission zombie resources."
    )

    # Signal → Action Mapping reference table — always expanded so it's visible before Step 3
    with st.expander("Signal → Action mapping table (canonical reference)", expanded=True):
        st.caption(
            "This table defines exactly how each signal becomes an action. "
            "Governance signals (tagging_gap, unattributed_cost_gap) are listed separately — "
            "they do not produce direct cost savings and must not be ranked against optimization signals."
        )
        _opt_signals = [m for m in SIGNAL_ACTION_MAP if m["signal_name"] not in (
            "tagging_gap", "unattributed_cost_gap", "shared_cost_concentration",
            "cost_anomaly", "forecasted_month_end_risk",
        )]
        _gov_signals = [m for m in SIGNAL_ACTION_MAP if m["signal_name"] in (
            "tagging_gap", "unattributed_cost_gap", "shared_cost_concentration",
            "cost_anomaly", "forecasted_month_end_risk",
        )]
        st.markdown("**Optimization signals** (direct NEC recovery)")
        st.dataframe(
            pd.DataFrame(_opt_signals).rename(columns={
                "signal_name": "Signal", "trigger_condition": "Trigger",
                "action": "Action", "expected_impact": "Expected Impact", "risk_model": "Risk",
            }),
            use_container_width=True, hide_index=True,
        )
        st.markdown("**Governance signals** (accountability / attribution — no direct NEC reduction)")
        st.dataframe(
            pd.DataFrame(_gov_signals).rename(columns={
                "signal_name": "Signal", "trigger_condition": "Trigger",
                "action": "Action", "expected_impact": "Expected Impact", "risk_model": "Risk",
            }),
            use_container_width=True, hide_index=True,
        )

    st.markdown("---")

    # ---------------------------------------------------------------------------
    # Step 3 - Prioritised action list
    # ---------------------------------------------------------------------------

    st.subheader("Step 3 - Prioritised action list")

    col_f, col_s = st.columns([2, 2])
    with col_f:
        min_priority = st.slider(
            "Minimum priority score", min_value=0.0, max_value=100.0,
            value=0.0, step=5.0, help="Canonical priority score normalized to 0-100.",
        )
    with col_s:
        sort_col = st.selectbox(
            "Sort by",
            ["priority_score (desc)", "estimated_savings (desc)", "savings_pct (desc)", "allocated_team"],
        )
    st.caption(
        "**Optimization priority score** (0–100): "
        "35% normalized savings + 25% confidence + 20% governance severity + 10% urgency + 10% low-risk bonus. "
        "Normalization: `normalized_savings = savings / max_savings_in_scope` (0–1 scale). "
        "Governance severity here reflects signal quality, NOT the tagging-gap penalty — "
        "governance actions (enforce_tags, assign_owner) are intentionally excluded from this ranking table."
    )
    st.caption(
        "This page shows only recoverable optimization actions (commitment waste, idle compute, zombie resources). "
        "Governance gaps (tagging, attribution), anomalies, and forecast risks are surfaced separately in Insights. "
        "Each row represents one canonical signal/action pair for the current billing scope."
    )
    st.caption(
        "ROI is defined as estimated monthly savings divided by mapped effort hours. "
        "Examples: enforce tags = 4h, release commitment = 6h, resize down = 12h, remove resource = 8h."
    )

    _SORT_MAP = {
        "priority_score (desc)":    ("priority_score",    False),
        "estimated_savings (desc)": ("estimated_savings", False),
        "savings_pct (desc)":       ("savings_pct",       False),
        "allocated_team":           ("allocated_team",    True),
    }
    sort_key, asc = _SORT_MAP[sort_col]

    table_df = rdf[rdf["priority_score"] >= min_priority].sort_values(sort_key, ascending=asc).reset_index(drop=True)
    table_df.insert(0, "Rank", range(1, len(table_df) + 1))

    display_df = pd.DataFrame({
        "Rank":          table_df["Rank"],
        "Resource":      table_df["resource_id"].apply(
                             lambda x: ("..." + str(x)[-35:]) if len(str(x)) > 38 else str(x)
                         ),
        "Owner":         table_df["owner"],
        "Action":        table_df["action_label"],
        "Status":        table_df.get("action_status", pd.Series(["recommended"] * len(table_df))).str.replace("_", " ").str.title(),
        "Verification":  table_df.get("verification_status", pd.Series(["pending"] * len(table_df))).str.replace("_", " ").str.title(),
        "Effort":        table_df.get("effort", pd.Series(["-"] * len(table_df))),
        "Time to Savings": table_df.get("time_to_realize", pd.Series(["-"] * len(table_df))),
        "ROI ($/hr)":    table_df.get("roi_score", pd.Series([0.0] * len(table_df))).map("${:,.0f}".format),
        "Savings":       table_df["estimated_savings"].map("${:,.0f}".format),
        "Savings %":     table_df["savings_pct"].map("{:.1f}%".format),
        "Approval":      table_df.get("approval_required", pd.Series([False] * len(table_df))).map(lambda x: "Yes" if x else "No"),
        "Safety":        table_df.get("action_safety", pd.Series(["approval_required"] * len(table_df))).str.replace("_", " ").str.title(),
        "Next Step":     table_df["reasoning"].apply(lambda x: x["next_best_action"]),
        "SLA":           table_df["sla"],
        "Risk":          table_df["risk"],
    })

    def _risk_color(val: str) -> str:
        return {
            "Low":    "background-color:#dcfce7; color:#166534",
            "Medium": "background-color:#fef9c3; color:#854d0e",
            "High":   "background-color:#fee2e2; color:#991b1b",
        }.get(val, "")

    def _sla_color(val: str) -> str:
        return {
            "Immediate":  "background-color:#fee2e2; color:#991b1b; font-weight:600",
            "This week":  "background-color:#fef9c3; color:#854d0e",
            "Next cycle": "background-color:#e0e7ff; color:#3730a3",
        }.get(val, "")

    def _status_color(val: str) -> str:
        return {
            "Recommended": "background-color:#e0e7ff; color:#3730a3",
            "Approved": "background-color:#dbeafe; color:#1d4ed8",
            "Rejected": "background-color:#f3f4f6; color:#374151",
            "Implemented": "background-color:#dcfce7; color:#166534",
            "Verified": "background-color:#bbf7d0; color:#166534; font-weight:600",
        }.get(val, "")

    def _approval_color(val: str) -> str:
        if val == "Yes":
            return "background-color:#fef9c3; color:#854d0e"
        return "background-color:#dcfce7; color:#166534"

    def _safety_color(val: str) -> str:
        return {
            "Auto Safe": "background-color:#dcfce7; color:#166534",
            "Approval Required": "background-color:#fef9c3; color:#854d0e",
            "Manual Review": "background-color:#fee2e2; color:#991b1b",
            "Blocked": "background-color:#111827; color:#ffffff",
        }.get(val, "")

    def _automation_color(val: str) -> str:
        if val.startswith("✔"):
            return "background-color:#dcfce7; color:#166534"
        if "approval" in val.lower():
            return "background-color:#fef9c3; color:#854d0e"
        return "background-color:#f3f4f6; color:#374151"

    def _effort_color(val: str) -> str:
        return {
            "Low":    "background-color:#dcfce7; color:#166534",
            "Medium": "background-color:#fef9c3; color:#854d0e",
            "High":   "background-color:#fee2e2; color:#991b1b",
        }.get(val, "")

    def _time_color(val: str) -> str:
        return {
            "Immediate": "background-color:#dcfce7; color:#166534; font-weight:600",
            "1 week":    "background-color:#fef9c3; color:#854d0e",
            "1 month":   "background-color:#e0e7ff; color:#3730a3",
        }.get(val, "")

    top10_df = display_df.head(10)
    st.dataframe(
        top10_df.style
            .map(_risk_color,   subset=["Risk"])
            .map(_status_color, subset=["Status"])
            .map(_approval_color, subset=["Approval"])
            .map(_safety_color, subset=["Safety"])
            .map(_sla_color,    subset=["SLA"])
            .map(_effort_color, subset=["Effort"])
            .map(_time_color,   subset=["Time to Savings"]),
        use_container_width=True, hide_index=True,
    )

    shown = min(10, len(display_df))
    total = len(table_df)
    if total > shown:
        with st.expander(f"View all {total} recommendations"):
            st.dataframe(
                display_df.style
                    .map(_risk_color,   subset=["Risk"])
                    .map(_status_color, subset=["Status"])
                    .map(_approval_color, subset=["Approval"])
                    .map(_safety_color, subset=["Safety"])
                    .map(_sla_color,    subset=["SLA"])
                    .map(_effort_color, subset=["Effort"])
                    .map(_time_color,   subset=["Time to Savings"]),
                use_container_width=True, hide_index=True,
            )

    st.markdown("**Action lifecycle**")
    st.caption(
        "**Unattributed spend vs unassigned owner:** the 'Action owner' field here is the person accountable "
        "for this specific optimization action — independent of billing attribution. "
        "Assigning an owner to a recommendation does not reduce the Unattributed Spend metric above, "
        "which reflects billing rows with a missing `tag_team` tag."
    )
    st.caption(
        "Confidence calibration activates after the first implemented action is verified. "
        "Until then, scores use canonical signal quality, persistence, corroboration, and anomaly-penalty rules."
    )
    lifecycle_options = {
        f"{row['Rank']}. {row['action_label']} | {row['allocated_team']} | ${row['estimated_savings']:,.0f}/month": idx
        for idx, row in table_df.head(25).iterrows()
    }
    if lifecycle_options:
        selected_label = st.selectbox(
            "Update recommendation state",
            list(lifecycle_options.keys()),
            key="recommendation_lifecycle_select",
        )
        selected_row = table_df.loc[lifecycle_options[selected_label]]
        current_status = str(selected_row.get("action_status", "recommended"))
        allowed_transitions = {
            "recommended": ["recommended", "approved", "rejected"],
            "approved": ["approved", "rejected", "implemented"],
            "implemented": ["implemented", "verified"],
            "verified": ["verified"],
            "rejected": ["rejected"],
        }
        status_options = allowed_transitions.get(
            current_status,
            ["recommended", "approved", "rejected", "implemented", "verified"],
        )
        current_owner = str(selected_row.get("action_owner", selected_row.get("owner_email", "")) or "")
        current_realized = float(selected_row.get("realized_savings", 0.0) or 0.0)
        current_verification = str(selected_row.get("verification_status", "pending") or "pending")
        current_notes = str(selected_row.get("verification_notes", "") or "")
        default_impl_date = (
            pd.to_datetime(selected_row["implementation_date"]).date()
            if pd.notna(selected_row.get("implementation_date"))
            else None
        )

        with st.form("recommendation_lifecycle_form"):
            lifecycle_cols = st.columns(4)
            action_status = lifecycle_cols[0].selectbox(
                "Status",
                status_options,
                index=status_options.index(current_status),
            )
            action_owner = lifecycle_cols[1].text_input("Action owner", value=current_owner)
            realized_savings = lifecycle_cols[2].number_input(
                "Realized savings",
                min_value=0.0,
                value=current_realized,
                step=10.0,
                disabled=action_status not in {"implemented", "verified"},
            )
            implementation_date = lifecycle_cols[3].date_input(
                "Implementation date",
                value=default_impl_date,
                help="Set when status is Implemented or Verified. Leave blank for Recommended or Approved.",
                disabled=action_status not in {"implemented", "verified"},
            )
            verification_cols = st.columns(2)
            verification_status = verification_cols[0].selectbox(
                "Verification status",
                ["pending", "validated", "not_realized"],
                index=["pending", "validated", "not_realized"].index(current_verification),
                disabled=action_status not in {"implemented", "verified"},
            )
            verification_notes = verification_cols[1].text_input(
                "Verification notes",
                value=current_notes,
                disabled=action_status not in {"implemented", "verified"},
            )

            st.caption(
                f"Risk: {selected_row['risk']} ({selected_row.get('risk_score', 0)}/100) | "
                f"Approval required: {'Yes' if selected_row.get('approval_required') else 'No'} | "
                f"Safety: {str(selected_row.get('action_safety', 'approval_required')).replace('_', ' ').title()}"
            )
            reasoning = selected_row.get("reasoning", {})
            if reasoning:
                st.markdown(
                    f"**Root Cause**  \n{reasoning.get('root_cause', '')}\n\n"
                    f"**Evidence**  \n- " + "\n- ".join(reasoning.get("evidence", [])) + "\n\n"
                    f"**Recommended Action**  \n{reasoning.get('recommended_action', '')}\n\n"
                    f"**Why this action**  \n{reasoning.get('action_justification', '')}\n\n"
                    f"**Next Best Action**  \n{reasoning.get('next_best_action', '')}"
                )
            st.caption(
                f"{selected_row.get('risk_reason', '')} "
                f"{selected_row.get('evidence_summary', '')} "
                f"{selected_row.get('confidence_reason', '')}"
            )

            if st.form_submit_button("Save lifecycle update"):
                save_recommendation_action(
                    selected_row["recommendation_id"],
                    {
                        "action_status": action_status,
                        "action_owner": action_owner,
                        "created_date": str(selected_row.get("created_date", date.today().isoformat())),
                        "implementation_date": (implementation_date.isoformat() if implementation_date else None)
                        if action_status in {"implemented", "verified"}
                        else None,
                        "realized_savings": realized_savings,
                        "verification_status": verification_status,
                        "verification_notes": verification_notes,
                    },
                )
                st.success("Recommendation state saved.")
                st.rerun()

    export_cols = st.columns(2)
    export_cols[0].download_button(
        "Download Recommendation CSV",
        recommendation_csv_bytes(table_df.to_dict("records")),
        file_name="finops_recommendations.csv",
        mime="text/csv",
    )
    export_cols[1].download_button(
        "Download Jira Action List",
        jira_action_csv_bytes(table_df.to_dict("records")),
        file_name="finops_jira_actions.csv",
        mime="text/csv",
    )

    st.caption(f"Showing top {shown} of {total} recommendations (priority >= {min_priority:.0f})")

    st.markdown("---")

    # ---------------------------------------------------------------------------
    # Step 4 - Quick wins
    # ---------------------------------------------------------------------------

    st.subheader("Step 4 - Quick wins (Low risk, act now)")

    quick_wins = sorted([r for r in filtered_recs if r["risk"] == "Low"],
                        key=lambda r: r["priority_score"], reverse=True)

    if not quick_wins:
        st.info("No low-risk recommendations in the current filter selection.")
    else:
        # Grouped summary first (executive view)
        qw_by_action: dict[str, list] = {}
        for r in quick_wins:
            qw_by_action.setdefault(r["action"], []).append(r)

        summary_parts = []
        for act, group in sorted(qw_by_action.items(),
                                 key=lambda x: sum(r["estimated_savings"] for r in x[1]),
                                 reverse=True):
            act_lbl = _ACTION_LABELS.get(act, act.replace("_", " ").title())
            group_savings = sum(r["estimated_savings"] for r in group)
            summary_parts.append(
                f"- **{act_lbl}** x {len(group)} — **\\${group_savings:,.0f}/month**"
            )

        total_qw_savings = sum(r["estimated_savings"] for r in quick_wins)
        st.success(
            f"Quick wins: {len(quick_wins)} low-risk actions.\n"
            + "\n".join(summary_parts)
            + f"\n\nTotal projected impact: \\${total_qw_savings:,.0f}/month.\n"
            "No downtime expected. No service interruption or early-exit penalty."
        )
        st.caption("Expand individual actions below for root cause, justification, and alternatives.")

        for i, rec in enumerate(quick_wins[:5], 1):
            team  = _TEAM_LABELS.get(rec["allocated_team"], rec["allocated_team"].replace("-", " ").title())
            act   = _ACTION_LABELS.get(rec["action"], rec["action"])
            short = ("..." + rec["resource_id"][-48:]) if len(rec["resource_id"]) > 50 else rec["resource_id"]
            _qw_is_rs = rec.get("signal_type", rec.get("waste_type", "")) in ("idle_compute", "idle_compute_proxy", "idle_resource")
            _qw_sav_display = f"up to ${rec['estimated_savings']:,.0f} (billing proxy)" if _qw_is_rs else f"${rec['estimated_savings']:,.0f}"
            with st.expander(
                f"{i}. {act} - {short} - {_qw_sav_display} "
                f"({rec['savings_pct']:.1f}% of NEC)"
            ):
                # "Why this recommendation" panel (Task #16 — AI explanation mode).
                # Every quick-win now carries evidence, confidence, data source,
                # priority score, and the annualized cost of ignoring it.
                conf = rec.get("confidence", 0.8)
                conf_label = "high" if conf >= 0.75 else ("medium" if conf >= 0.55 else "low")
                evidence_summary = rec.get("evidence_summary") or "Canonical decision signal triggered this recommendation."
                st.markdown(
                    "Why this recommendation\n"
                    f"- Evidence summary: {evidence_summary}\n"
                    f"- Confidence: {conf:.0%} ({conf_label})\n"
                    f"- Confidence reason: {rec.get('confidence_reason', 'Billing signal')}\n"
                    f"- Risk: {rec['risk']} ({rec.get('risk_score', 0)}/100)\n"
                    f"- Risk reason: {rec.get('risk_reason', 'Review manually.')}\n"
                    f"- Approval required: {'Yes' if rec.get('approval_required') else 'No'}\n"
                    f"- Action safety: {str(rec.get('action_safety', 'approval_required')).replace('_', ' ').title()}\n"
                    f"- Priority score: {rec['priority_score']:.1f} / 100\n"
                    f"- If ignored for 12 months: about \\${rec['estimated_savings'] * 12:,.0f} annualized leakage"
                )
                reasoning = rec.get("reasoning", {})
                if reasoning:
                    st.markdown(
                        f"**Root Cause**  \n{reasoning.get('root_cause', '')}\n\n"
                        f"**Evidence**  \n- " + "\n- ".join(reasoning.get("evidence", [])) + "\n\n"
                        f"**Recommended Action**  \n{reasoning.get('recommended_action', '')}\n\n"
                        f"**Why this action**  \n{reasoning.get('action_justification', '')}\n\n"
                        f"**Next Best Action**  \n{reasoning.get('next_best_action', '')}"
                    )
                col_a, col_b, col_c = st.columns(3)
                col_a.metric("Current NEC",       f"${rec['current_cost']:,.0f}")
                col_b.metric("Projected Impact",  f"${rec['estimated_savings']:,.0f}")
                col_c.metric("Team",              team)

        if len(quick_wins) > 5:
            with st.expander(f"View remaining {len(quick_wins) - 5} quick wins"):
                for i, rec in enumerate(quick_wins[5:], 6):
                    team = _TEAM_LABELS.get(rec["allocated_team"], rec["allocated_team"].replace("-", " ").title())
                    act  = _ACTION_LABELS.get(rec["action"], rec["action"])
                    short = ("..." + rec["resource_id"][-48:]) if len(rec["resource_id"]) > 50 else rec["resource_id"]
                    _rem_is_rs = rec.get("signal_type", rec.get("waste_type", "")) in ("idle_compute", "idle_compute_proxy", "idle_resource")
                    _rem_sav_str = (
                        f"up to \\${rec['estimated_savings']:,.0f}/month (billing proxy)"
                        if _rem_is_rs
                        else f"\\${rec['estimated_savings']:,.0f}/month"
                    )
                    st.markdown(
                        f"**{i}. {act}** — `{short}` — {team} — "
                        f"{_rem_sav_str} — Risk: {rec['risk']}"
                    )

    st.markdown("---")

    # ---------------------------------------------------------------------------
    # Step 5 - Probabilistic impact scenarios (Issue #1, #3, #17)
    # Replaces deterministic "Before vs After" with a 3-scenario model that
    # reflects actual execution uncertainty. Never shows 100% deterministic NEC
    # reduction — savings are always probabilistic.
    # ---------------------------------------------------------------------------

    st.subheader("Step 5 - Probabilistic impact — three scenarios")
    st.caption(
        "Savings are never guaranteed. Each scenario applies a different execution assumption. "
        "The **expected** scenario uses the realization rate derived from the risk profile of active recommendations. "
        "Commitment waste reduction shown is commitment-specific only — it does not represent total waste elimination."
    )

    import plotly.graph_objects as go

    # Compute savings hierarchy with same realization rate as Insights forecast page.
    _fallback_hier = compute_savings_hierarchy(
        filtered_recs,
        realization_rate=_forecast_realization_rate,
    )
    savings_hier = SavingsHierarchy(
        inefficiency_signal=canonical_metrics.waste_signal or _fallback_hier.inefficiency_signal,
        recoverable_opportunity=canonical_metrics.recoverable_savings or _fallback_hier.recoverable_opportunity,
        actionable_savings=canonical_metrics.actionable_savings or _fallback_hier.actionable_savings,
        realized_projection=canonical_metrics.projected_savings or _fallback_hier.realized_projection,
        realization_rate=canonical_metrics.realization_rate or _fallback_hier.realization_rate,
    )
    rr = savings_hier.realization_rate
    confidence_floor = 0.60  # conservative execution floor

    low_savings       = sum(r["estimated_savings"] for r in filtered_recs if r["risk"] == "Low")
    full_savings      = sum(r["estimated_savings"] for r in filtered_recs if r["risk"] in ("Low", "Medium"))
    high_count        = sum(1 for r in filtered_recs if r["risk"] == "High")
    full_count        = sum(1 for r in filtered_recs if r["risk"] in ("Low", "Medium"))
    low_pct_of_nec    = low_savings / total_nec * 100 if total_nec else 0

    # Three scenario NEC outcomes — Expected anchored to canonical forecast for cross-page consistency.
    sc_best_savings     = savings_hier.actionable_savings    # 100% execution, low/med risk
    sc_expected_savings = savings_hier.realized_projection   # realization rate applied
    sc_worst_savings    = savings_hier.realized_projection * confidence_floor  # floor

    sc_best_nec = max(0.0, total_nec - sc_best_savings)
    # Use canonical forecast optimized NEC if available (aligns with Cost Intelligence page).
    sc_expected_nec = (
        _forecast_optimized_nec
        if _forecast_optimized_nec is not None
        else max(0.0, total_nec - sc_expected_savings)
    )
    sc_worst_nec = max(0.0, total_nec - sc_worst_savings)

    sc_best_waste     = max(0.0, total_waste_detected - sc_best_savings)
    sc_expected_waste = max(0.0, total_waste_detected - sc_expected_savings)
    sc_worst_waste    = max(0.0, total_waste_detected - sc_worst_savings)

    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        st.success(
            f"**Best case** — 100% execution ({sum(1 for r in filtered_recs if r['risk'] in ('Low','Medium'))} low/med-risk actions).  \n"
            f"NEC: **\\${sc_best_nec:,.0f}/month** (savings: \\${sc_best_savings:,.0f}/month).  \n"
            f"Annual savings: \\${sc_best_savings * 12:,.0f}.  \n"
            "Requires perfect execution, zero rollbacks, zero delays."
        )
    with sc2:
        st.warning(
            f"**Expected** — {rr:.0%} realization rate applied.  \n"
            f"NEC: **\\${sc_expected_nec:,.0f}/month** (savings: \\${sc_expected_savings:,.0f}/month).  \n"
            f"Annual savings: \\${sc_expected_savings * 12:,.0f}.  \n"
            f"Derived from risk profile: {sum(1 for r in filtered_recs if r['risk']=='Low')} low, "
            f"{sum(1 for r in filtered_recs if r['risk']=='Medium')} medium, "
            f"{high_count} high-risk actions."
        )
    with sc3:
        st.error(
            f"**Conservative** — {rr * confidence_floor:.0%} execution floor applied.  \n"
            f"NEC: **\\${sc_worst_nec:,.0f}/month** (savings: \\${sc_worst_savings:,.0f}/month).  \n"
            f"Annual savings: \\${sc_worst_savings * 12:,.0f}.  \n"
            "Accounts for rollbacks, delays, and partial implementation."
        )

    # 3-scenario bar chart — never deterministic
    scenario_fig = go.Figure(data=[
        go.Bar(
            name="Current (Before)",
            x=["NEC", "Commitment Waste"],
            y=[total_nec, total_waste_detected],
            marker_color=[COLOR_INEFFICIENCY, COLOR_BLOCKER],
            text=[f"${total_nec:,.0f}", f"${total_waste_detected:,.0f}"],
            textposition="outside",
        ),
        go.Bar(
            name=f"Best Case (100% exec)",
            x=["NEC", "Commitment Waste"],
            y=[sc_best_nec, sc_best_waste],
            marker_color=["#86efac", "#bbf7d0"],
            text=[f"${sc_best_nec:,.0f}", f"${sc_best_waste:,.0f}"],
            textposition="outside",
        ),
        go.Bar(
            name=f"Expected ({rr:.0%} realization)",
            x=["NEC", "Commitment Waste"],
            y=[sc_expected_nec, sc_expected_waste],
            marker_color=[COLOR_OPTIMIZED, "#4ade80"],
            text=[f"${sc_expected_nec:,.0f}", f"${sc_expected_waste:,.0f}"],
            textposition="outside",
        ),
        go.Bar(
            name=f"Conservative ({rr * confidence_floor:.0%} floor)",
            x=["NEC", "Commitment Waste"],
            y=[sc_worst_nec, sc_worst_waste],
            marker_color=["#a3e635", "#d9f99d"],
            text=[f"${sc_worst_nec:,.0f}", f"${sc_worst_waste:,.0f}"],
            textposition="outside",
        ),
    ])
    scenario_fig.update_layout(
        barmode="group",
        height=320,
        margin=dict(t=10, b=40),
        yaxis_title="USD / month",
        legend=dict(orientation="h", y=1.12),
    )
    st.plotly_chart(scenario_fig, use_container_width=True)
    st.caption(
        "Commitment waste column shows only commitment-specific (RI/SP/CUD) reduction — "
        "it does not represent total waste elimination. Idle compute and zombie resource "
        "reductions are captured in the NEC column."
    )

    # Summary strip — expected scenario (the authoritative number)
    _exp_pct = sc_expected_savings / total_nec * 100 if total_nec else 0
    _best_pct = sc_best_savings / total_nec * 100 if total_nec else 0
    col_s1, col_s2, col_s3, col_s4 = st.columns(4)
    col_s1.metric(
        "Realization-adj. Reduction",
        f"${sc_expected_savings:,.0f}/month",
        help=f"Best-case actionable (\\${sc_best_savings:,.0f}) x {rr:.0%} realization rate",
    )
    col_s2.metric("Annualized Reduction", f"${sc_expected_savings * 12:,.0f}")
    col_s3.metric(
        "Reduction as % of NEC",
        f"{_exp_pct:.1f}%",
        delta=f"best case: {_best_pct:.1f}%",
        help="Expected scenario reduction as share of current NEC",
    )
    col_s4.metric(
        "Realization Rate",
        f"{rr:.0%}",
        delta=f"floor: {rr * confidence_floor:.0%}",
        delta_color="off",
        help="Probability that modeled savings are actually executed. Derived from the risk profile of active recommendations.",
    )

    # ---------------------------------------------------------------------------
    # Post-action validation loop (Issue #5, #20)
    # Closed-loop intelligence: compares realized vs projected and surfaces
    # calibration gap to improve future realization rate estimates.
    # ---------------------------------------------------------------------------

    st.markdown("---")
    st.subheader("Post-Action Validation Loop")
    st.caption(
        "This is the feedback loop that makes the system adaptive. Compare realized savings "
        "against projected savings to calibrate the realization rate for future recommendations."
    )

    realized_total     = sum(float(r.get("realized_savings", 0.0) or 0.0) for r in filtered_recs)
    implemented_count  = sum(1 for r in filtered_recs if r.get("action_status") in {"implemented", "verified"})
    validated_count    = sum(1 for r in filtered_recs if r.get("verification_status") == "validated")
    not_realized_count = sum(1 for r in filtered_recs if r.get("verification_status") == "not_realized")
    pending_count      = sum(1 for r in filtered_recs if r.get("verification_status", "pending") == "pending")

    fbl1, fbl2, fbl3, fbl4 = st.columns(4)
    fbl1.metric("Actions Implemented", str(implemented_count))
    fbl2.metric("Savings Validated", str(validated_count))
    fbl3.metric("Not Realized", str(not_realized_count))
    fbl4.metric(
        "Realized vs Projected",
        f"${realized_total:,.0f}",
        delta=f"projected: ${sc_expected_savings:,.0f}",
        delta_color="off",
    )

    if implemented_count > 0:
        accuracy_pct = (realized_total / sc_expected_savings * 100) if sc_expected_savings > 0 else 0.0
        calibration_gap = abs(rr * 100 - accuracy_pct)
        if accuracy_pct >= 85:
            st.success(
                f"Validation accuracy: **{accuracy_pct:.0f}%** ({validated_count} verified, "
                f"{implemented_count} implemented).  \n"
                f"Realized **\\${realized_total:,.0f}** vs projected **\\${sc_expected_savings:,.0f}**.  \n"
                f"Realization rate calibration gap: {calibration_gap:.0f}pp. Model is well-calibrated."
            )
        elif accuracy_pct >= 60:
            st.warning(
                f"Validation accuracy: **{accuracy_pct:.0f}%** — realization rate may need adjustment.  \n"
                f"Realized **\\${realized_total:,.0f}** vs projected **\\${sc_expected_savings:,.0f}** "
                f"(calibration gap: {calibration_gap:.0f}pp).  \n"
                "Consider reducing the realization rate assumption for similar risk profiles."
            )
        else:
            st.error(
                f"Validation accuracy: **{accuracy_pct:.0f}%** — significant under-realization detected.  \n"
                f"Realized **\\${realized_total:,.0f}** vs projected **\\${sc_expected_savings:,.0f}**.  \n"
                "Review blocked actions, rollbacks, or missing owner assignments. "
                "Reduce the realization rate until accuracy recovers above 70%."
            )
    else:
        st.info(
            "No actions marked as implemented yet.  \n"
            "Use the **Action Lifecycle** section in Step 3 to track implementation and "
            "record realized savings. Feedback loop activates once first action is marked implemented."
        )
