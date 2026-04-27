"""
Page 5 - Cost Intelligence

Decision intelligence engine: explains why cloud costs look the way they do,
surfaces root causes with quantified impact, and prescribes actions with justification.
"""

import sys
from pathlib import Path
from collections import Counter

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from intelligence.causal_engine import run as run_causal
from intelligence.forecasting import build_forecast
from intelligence.reasoning_engine import build_reasoning, from_recommendation
from intelligence.waste_detector import run as detect_waste
from intelligence.impact_simulator import run as simulate
from dashboard._shared import (
    COLOR_BLOCKER,
    COLOR_INEFFICIENCY,
    COLOR_INFO,
    COLOR_OPTIMIZED,
    LABEL_ACTIONABLE_OPPORTUNITY,
    LABEL_ESTIMATED_MONTHLY_SAVINGS,
    compute_finops_summary_metrics,
    compute_savings_hierarchy,
    diagnose,
    load_canonical_forecast,
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
from dashboard.exporters import executive_summary_markdown
from dashboard.canonical import load_canonical_metrics

_TEAM_LABELS = {
    "data-eng":    "Data Engineering",
    "platform":    "Platform",
    "frontend":    "Frontend",
    "backend":     "Backend",
    "ml":          "Machine Learning",
    "unattributed":"Unattributed",
}
_TEAM_COLORS = ["#f97316", "#2563eb", "#22c55e", "#8b5cf6", "#eab308", "#ef4444"]
_CAUSE_LABELS = {
    "commitment_waste_identified": "Commitment waste",
    "idle_resources_detected":     "Idle resources",
    "untagged_cost_gap":           "Untagged cost gap",
    "service_category_dominance":  "Service dominance",
    "team_cost_spike":             "Cost spike",
    "team_cost_decrease":          "Cost decrease",
    "no_anomalies_detected":       "Stable spend",
}
_CAUSE_ACTIONS = {
    "commitment_waste_identified": ("Release RI/SP commitment",   "Low"),
    "idle_resources_detected":     ("Resize or remove instance",  "Medium"),
    "untagged_cost_gap":           ("Enforce tagging policy",     "Low"),
    "service_category_dominance":  ("Optimise dominant service",  "Medium"),
    "team_cost_spike":             ("Investigate usage surge",    "High"),
    "team_cost_decrease":          ("Validate trend stability",   "Low"),
}

st.set_page_config(page_title="Cost Intelligence", layout="wide")
st.title("Cost Intelligence")
st.caption(
    "Rule-based decision support system with statistical scoring — explains WHY cloud costs look the way they do, "
    "with root cause evidence, quantified impact, and action justification. "
    "Signals are billing-derived; this system does not yet learn from outcomes (post-action feedback loop is in Waste & Recommendations)."
)
render_demo_banner()

df, month_filter, selected_cloud = load_scoped_df(render_sidebar=True)
history_df = load_df(None)
if selected_cloud != "All":
    history_df = history_df[history_df["cloud_provider"] == selected_cloud].copy()
history_months_available = history_df["billing_month"].nunique() if "billing_month" in history_df.columns else 0
summary_df = load_finops_summary(month_filter)

# ---------------------------------------------------------------------------
# Executive headline (Critical #1)
# ---------------------------------------------------------------------------
summary_metrics = compute_finops_summary_metrics(
    summary_df,
    clouds=selected_cloud,
    fallback_df=df,
)
canonical_page_metrics = load_canonical_metrics(month_filter, selected_cloud)
diag = diagnose(df, summary=summary_metrics)
render_headline(diag)

# ---------------------------------------------------------------------------
# Run pipeline
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Running causal analysis...")
def _run_pipeline(_df_hash: int, _df: pd.DataFrame):
    findings = detect_waste(_df)
    insights_out = run_causal(_df, findings)
    recs = simulate(findings)
    return findings, insights_out, recs

@st.cache_data(show_spinner=False)
def _build_trend(_df_hash: int, _df: pd.DataFrame) -> pd.DataFrame:
    from intelligence.causal_engine import build_nec_trend, compute_zscore_anomaly
    return compute_zscore_anomaly(build_nec_trend(_df))


@st.cache_data(show_spinner="Running causal analysis...")
def _run_pipeline_with_history(
    _df_hash: int,
    _df: pd.DataFrame,
    _history_hash: int,
    _history_df: pd.DataFrame,
):
    findings = detect_waste(_df)
    insights_out = run_causal(_history_df, findings)
    recs = simulate(findings)
    return findings, insights_out, recs

# Content-based hash so cache hits when the data is unchanged
# (id(df) changes on every reload, which defeats the cache).
_df_hash = int(pd.util.hash_pandas_object(df, index=True).sum())
_history_hash = int(pd.util.hash_pandas_object(history_df, index=True).sum())
findings, insights, recs = _run_pipeline_with_history(_df_hash, df, _history_hash, history_df)
canonical_recs_df = load_canonical_recommendations(month_filter, selected_cloud)
using_canonical_recommendations = not canonical_recs_df.empty
if not canonical_recs_df.empty:
    recs = normalize_canonical_recommendations(canonical_recs_df)
canonical_forecast_df = load_canonical_forecast(month_filter, selected_cloud)
trend_df = _build_trend(_history_hash, history_df)

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------

st.sidebar.markdown("---")
st.sidebar.subheader("Page filters")
st.sidebar.caption("Drill-down only - the global month/cloud filters still apply.")

team_pool = set()
team_pool.update(ins["scope"].replace("team:", "") for ins in insights)
team_pool.update(df["allocated_team"].fillna("unattributed").astype(str).unique())
team_pool.update(r["allocated_team"] for r in recs)
all_teams = sorted(team_pool)
sel_teams = st.sidebar.multiselect("Teams", all_teams, default=all_teams)
show_anomaly_only = st.sidebar.checkbox("Anomalies only", value=False)

selected_trend = trend_df[trend_df["allocated_team"].isin(sel_teams)].copy()
anomalous_teams = set(
    selected_trend.loc[selected_trend["anomaly"].fillna(False), "allocated_team"].astype(str)
)

filtered = [
    {
        **ins,
        "anomaly": ins["scope"].replace("team:", "") in anomalous_teams,
    }
    for ins in insights
    if ins["scope"].replace("team:", "") in sel_teams
    and (not show_anomaly_only or ins["scope"].replace("team:", "") in anomalous_teams)
]

filtered_teams = set(sel_teams)
plot_trend = trend_df[trend_df["allocated_team"].isin(filtered_teams)].copy()
trend_anomaly_count = int(plot_trend.loc[plot_trend["anomaly"].fillna(False), "allocated_team"].nunique()) if not plot_trend.empty else 0
scope_df = (
    df[df["allocated_team"].isin(filtered_teams)].copy()
    if filtered_teams
    else df.iloc[0:0].copy()
)
scope_summary = compute_finops_summary_metrics(
    summary_df,
    clouds=selected_cloud,
    teams=list(filtered_teams) if filtered_teams else None,
    fallback_df=scope_df,
)
canonical_metrics = load_canonical_metrics(
    month_filter,
    selected_cloud,
    teams=list(filtered_teams) if filtered_teams else None,
)
filtered_findings = [
    f for f in findings
    if f["allocated_team"] in filtered_teams
] if findings else []
filtered_recs = [
    r for r in recs
    if r["allocated_team"] in filtered_teams
] if recs else []
filtered_recs = overlay_recommendation_actions(filtered_recs)

summary_scope_df = summary_df.copy()
if not summary_scope_df.empty:
    if selected_cloud != "All" and "cloud_provider" in summary_scope_df.columns:
        summary_scope_df = summary_scope_df[
            summary_scope_df["cloud_provider"].astype(str).str.lower().eq(selected_cloud.lower())
        ].copy()
    if "team" in summary_scope_df.columns:
        summary_scope_df["team"] = summary_scope_df["team"].fillna("unattributed").astype(str)

team_current_metrics: dict[str, dict[str, float]] = {}
if not summary_scope_df.empty and "team" in summary_scope_df.columns:
    grouped_team_summary = (
        summary_scope_df[summary_scope_df["team"].isin(filtered_teams)]
        .groupby("team", dropna=False)[
            ["total_nec", "total_unattributed_cost", "total_commitment_waste", "total_optimization_opportunity"]
        ]
        .sum()
        .reset_index()
    )
    for _, row in grouped_team_summary.iterrows():
        team_nec = float(row["total_nec"] or 0.0)
        team_unattributed = float(row["total_unattributed_cost"] or 0.0)
        team_current_metrics[str(row["team"])] = {
            "nec": team_nec,
            "unattributed_nec": team_unattributed,
            "unattributed_pct": (team_unattributed / team_nec * 100.0) if team_nec else 0.0,
            "commitment_waste": float(row["total_commitment_waste"] or 0.0),
            "optimization_opportunity": float(row["total_optimization_opportunity"] or 0.0),
        }


def _team_metric(team_raw: str, key: str, fallback: float) -> float:
    return float(team_current_metrics.get(team_raw, {}).get(key, fallback))


def _team_root_cause_text(team_raw: str, rc: dict) -> str:
    if rc["cause"] == "untagged_cost_gap":
        team_nec = _team_metric(team_raw, "nec", 0.0)
        team_unattributed = _team_metric(team_raw, "unattributed_nec", 0.0)
        team_unattributed_pct = _team_metric(team_raw, "unattributed_pct", 0.0)
        if team_nec > 0:
            return (
                f"{team_unattributed_pct:.1f}% of current team NEC "
                f"(${team_unattributed:,.2f}) is unattributed — this is attribution risk, not direct savings."
            )
    return rc["evidence"]

# Pre-compute per-team waste totals.
# Use canonical rec current_cost when available (team-attributed per-rec);
# fall back to local pipeline findings otherwise to avoid portfolio-level aggregation duplicates.
_team_waste: dict[str, float] = {}
if using_canonical_recommendations:
    for r in filtered_recs:
        team = r["allocated_team"]
        _team_waste[team] = _team_waste.get(team, 0.0) + float(r.get("current_cost", 0.0))
else:
    for f in filtered_findings:
        team = f["allocated_team"]
        impact = f["nec_waste"] if f["nec_waste"] > 0 else f["nec_used"]
        _team_waste[team] = _team_waste.get(team, 0.0) + impact

# Per-team recommendation savings
_team_savings: dict[str, float] = {}
for r in filtered_recs:
    team = r["allocated_team"]
    _team_savings[team] = _team_savings.get(team, 0.0) + r["estimated_savings"]

# ---------------------------------------------------------------------------
# KPIs (no zero-anomaly metric)
# ---------------------------------------------------------------------------

n_teams     = len(filtered)
n_anomalies = trend_anomaly_count
avg_change  = sum(ins["cost_change_pct"] for ins in filtered) / n_teams if n_teams else 0.0
total_savings = canonical_metrics.projected_savings or scope_summary.total_recoverable_savings or sum(r["estimated_savings"] for r in filtered_recs)
total_nec   = canonical_metrics.nec or scope_summary.total_nec
recoverable_total = canonical_metrics.waste_signal or sum(
    f["nec_waste"] if f["nec_waste"] > 0 else f["nec_used"]
    for f in filtered_findings
)
commitment_waste_total = canonical_metrics.commitment_waste or scope_summary.total_commitment_waste
commitment_waste_pct   = commitment_waste_total / total_nec * 100 if total_nec else 0

ck1, ck2, ck3 = st.columns(3)
ck1.metric(
    "Teams with Rising Cost",
    str(sum(1 for ins in filtered if ins["cost_change_pct"] > 0)),
    delta=f"of {n_teams} teams in scope",
    delta_color="off",
    help="Count of teams whose NEC increased month-over-month vs. the prior period.",
)
ck2.metric("Avg MoM Change",       f"{avg_change:+.1f}%")
ck3.metric(
    LABEL_ESTIMATED_MONTHLY_SAVINGS,
    f"${total_savings:,.0f}",
    help=(
        "Realization-adjusted projection: actionable savings × execution probability. "
        "See Forecast Outlook below for the full savings pipeline breakdown."
    ),
)
if using_canonical_recommendations:
    st.caption("Actions and scores are sourced from the canonical recommendation table in DuckDB.")

if not filtered:
    st.info("No insights match the current filter selection.")
    st.stop()

if n_anomalies:
    anomaly_teams = ", ".join(
        _TEAM_LABELS.get(team, team.replace("-", " ").title())
        for team in sorted(plot_trend.loc[plot_trend["anomaly"] == True, "allocated_team"].unique())
    )
    st.error(
        f"{n_anomalies} statistical anomal{'y' if n_anomalies == 1 else 'ies'} detected "
        f"(anomaly = z-score deviation from 3-month baseline, not necessarily a large spend change). "
        f"Teams: {anomaly_teams}."
    )

st.markdown("---")

# ---------------------------------------------------------------------------
# Forecast Outlook
# ---------------------------------------------------------------------------

forecast_target_month = month_filter or (
    str(scope_df["billing_month"].max()) if not scope_df.empty else None
)
forecast = build_forecast(
    scope_df,
    filtered_recs,
    target_month=forecast_target_month,
)
forecast_source = "python"
approved_statuses = {"approved", "implemented", "verified"}
immediate_low_risk_savings = sum(
    float(r["estimated_savings"])
    for r in filtered_recs
    if r.get("action_status", "recommended") in approved_statuses
)
if immediate_low_risk_savings <= 0:
    immediate_low_risk_savings = sum(
        float(r["estimated_savings"])
        for r in filtered_recs
        if r.get("action_status", "recommended") != "rejected"
        and r.get("risk") == "Low"
    )
if not canonical_forecast_df.empty:
    scope_forecast_df = canonical_forecast_df[
        canonical_forecast_df["team"].isin(filtered_teams)
    ].copy()
    if not scope_forecast_df.empty:
        forecast.projected_nec = round(float(scope_forecast_df["projected_month_end_nec"].sum()), 2)
        forecast.no_action_waste = round(float(scope_forecast_df["projected_waste_usd"].sum()), 2)
        forecast.projected_unattributed_spend = round(float(scope_forecast_df["projected_unattributed_usd"].sum()), 2)
        forecast.projected_savings = round(float(scope_forecast_df["projected_savings_usd"].sum()), 2)
        forecast.realization_rate = round(float(scope_forecast_df["realization_rate"].mean()), 2)
        forecast.projected_realized_savings = round(float(scope_forecast_df["projected_realized_savings_usd"].sum()), 2)
        forecast.optimized_nec = round(float(scope_forecast_df["optimized_month_end_nec"].sum()), 2)
        forecast.confidence = round(float(scope_forecast_df["forecast_confidence"].mean()), 2)
        forecast.method = str(scope_forecast_df["forecast_method"].mode().iloc[0])
        available_prior_months = max(0, history_months_available - 1)
        forecast.months_of_history = available_prior_months
        forecast.reason = (
            "Canonical forecast table from DuckDB; "
            f"minimum data met for {int(scope_forecast_df['minimum_data_met'].sum())} of {len(scope_forecast_df)} scoped row(s)."
        )
        forecast.lower_bound = round(max(0.0, forecast.projected_nec - float(scope_forecast_df["error_bound_usd"].sum())), 2)
        forecast.upper_bound = round(forecast.projected_nec + float(scope_forecast_df["error_bound_usd"].sum()), 2)
        forecast.error_bound_pct = round(
            float(scope_forecast_df["error_bound_usd"].sum()) / max(forecast.projected_nec, 1.0),
            4,
        )
        forecast.minimum_data_met = bool(scope_forecast_df["minimum_data_met"].all())
        forecast_source = "canonical"

st.subheader("Forecast Outlook")
st.info(
    f"**Current NEC** and **Current unattributed NEC** are billing-period actuals. "
    f"**Forecast NEC** and **Optimized NEC** are model-based month-end projections. "
    f"Forecast method: `{forecast.method}`."
)
current_unattributed_nec = canonical_metrics.unattributed_nec or scope_summary.total_unattributed_cost
fc1, fc2, fc3, fc4, fc5 = st.columns(5)
fc1.metric(
    "Current NEC (actual)",
    f"${total_nec:,.0f}",
    help="Actual current billing-period NEC from the canonical mart.",
)
fc2.metric(
    "Forecast NEC (model-based)",
    f"${forecast.projected_nec:,.0f}",
    delta=f"vs current: {forecast.projected_nec - total_nec:+,.0f}",
    delta_color="off",
    help="Baseline month-end NEC projection before optimization is applied.",
)
fc3.metric(
    "Optimized NEC (expected)",
    f"${forecast.optimized_nec:,.0f}",
    delta=f"-${forecast.projected_realized_savings:,.0f}",
    help="Realization-adjusted month-end NEC after expected savings are applied.",
)
fc4.metric(
    "Current unattributed NEC",
    f"${current_unattributed_nec:,.0f}",
    delta=f"projected: ${forecast.projected_unattributed_spend:,.0f}",
    delta_color="off",
    help="Actual current-period unattributed NEC. Delta shows projected month-end unattributed NEC if the current run rate continues.",
)
fc5.metric(
    LABEL_ESTIMATED_MONTHLY_SAVINGS,
    f"${forecast.projected_realized_savings:,.0f}",
    delta=f"best-case: ${forecast.projected_savings:,.0f}",
    help=(
        f"Realization-adjusted = best-case actionable (\\${forecast.projected_savings:,.0f}) "
        f"x {forecast.realization_rate:.0%} execution rate. "
        "Best-case = low/medium risk only, no execution uncertainty applied."
    ),
)

forecast_fig = go.Figure(
    [
        go.Bar(
            name="Projected NEC",
            x=["Projected Month-End"],
            y=[forecast.projected_nec],
            marker_color=COLOR_INFO,
            text=[f"${forecast.projected_nec:,.0f}"],
            textposition="outside",
        ),
        go.Bar(
            name="No-Action Waste",
            x=["Projected Month-End"],
            y=[forecast.no_action_waste],
            marker_color=COLOR_BLOCKER,
            text=[f"${forecast.no_action_waste:,.0f}"],
            textposition="outside",
        ),
        go.Bar(
            name="Optimized NEC (realization-adjusted)",
            x=["Projected Month-End"],
            y=[forecast.optimized_nec],
            marker_color=COLOR_OPTIMIZED,
            text=[f"${forecast.optimized_nec:,.0f}"],
            textposition="outside",
        ),
    ]
)
forecast_fig.update_layout(
    barmode="group",
    height=280,
    margin=dict(t=10, b=30),
    yaxis_title="USD",
    legend=dict(orientation="h", y=1.1),
)
st.plotly_chart(forecast_fig, use_container_width=True)
st.caption(
    f"**Baseline projection model** (not a predictive model): "
    f"`0.7 * current_month_run_rate + 0.3 * trailing_3_month_avg_NEC`. "
    f"This is a weighted smoothing model - it does not decompose trend, seasonality, or workload correlation. "
    f"Use it as a directional baseline, not a statistical forecast. "
    f"Reliability score: {forecast.confidence:.0%} (0.40 * data_quality + 0.35 * signal_strength + 0.25 * historical_stability). "
    f"{forecast.months_of_history} full prior month(s) of history used. "
    f"Savings scenario: {forecast.savings_basis}. {forecast.reason}"
)
# Compute hierarchy here so both the forecast caption and Decision Summary use the same number.
_fallback_hier = (
    compute_savings_hierarchy(filtered_recs, realization_rate=forecast.realization_rate)
    if filtered_recs else None
)
_insights_hier = _fallback_hier
if _fallback_hier:
    _insights_hier = compute_savings_hierarchy(filtered_recs, realization_rate=forecast.realization_rate)
    _insights_hier.inefficiency_signal = canonical_metrics.waste_signal or _fallback_hier.inefficiency_signal
    _insights_hier.recoverable_opportunity = canonical_metrics.recoverable_savings or _fallback_hier.recoverable_opportunity
    _insights_hier.actionable_savings = canonical_metrics.actionable_savings or _fallback_hier.actionable_savings
    _insights_hier.realized_projection = canonical_metrics.projected_savings or _fallback_hier.realized_projection
    _insights_hier.realization_rate = canonical_metrics.realization_rate or _fallback_hier.realization_rate
_realized_display = _insights_hier.realized_projection if _insights_hier else forecast.projected_realized_savings
st.caption(
    f"Savings pipeline: modeled_opportunity × recovery_rate × actionability_filter × (1 − risk_penalty) "
    f"= best-case actionable (\\${forecast.projected_savings:,.0f}/month). "
    f"Then × {forecast.realization_rate:.0%} execution rate "
    f"= realization-adjusted projection \\${_realized_display:,.0f}/month. "
    f"The realization-adjusted number is used consistently in the Decision Summary below."
)
st.caption(
    f"Projected commitment waste if no action is taken: \\${forecast.no_action_waste:,.0f}/month. "
    f"Projected unattributed NEC at current run rate: \\${forecast.projected_unattributed_spend:,.0f}/month."
)
if forecast_source == "canonical":
    st.caption(
        f"95% CI bounds: \\${forecast.lower_bound:,.0f} – \\${forecast.upper_bound:,.0f} "
        f"(+/- {forecast.error_bound_pct:.1%} error bound, 1.96 sigma). Source: `marts.fct_month_end_forecast`."
    )

if plot_trend.empty:
    st.info("No trend data for the selected teams.")
else:
    plot_trend["team_label"] = (
        plot_trend["allocated_team"].map(_TEAM_LABELS)
        .fillna(plot_trend["allocated_team"].str.replace("-", " ").str.title())
    )
    n_trend_months = plot_trend["billing_month"].nunique()

    if n_trend_months < 2:
        bar_data = (
            plot_trend.groupby("team_label")["period_nec"].sum().reset_index()
            .sort_values("period_nec", ascending=True)
        )
        fig_trend = px.bar(
            bar_data, x="period_nec", y="team_label", orientation="h",
            labels={"period_nec": "Net Effective Cost (USD)", "team_label": "Team"},
            color="team_label", color_discrete_sequence=_TEAM_COLORS,
            text=bar_data["period_nec"].map("${:,.0f}".format),
        )
        fig_trend.update_traces(textposition="outside")
        fig_trend.update_layout(height=260, margin=dict(t=10, b=40, r=100),
                                showlegend=False, yaxis_title=None)
        st.plotly_chart(fig_trend, use_container_width=True)
        st.caption(
            f"Single billing month ({plot_trend['billing_month'].max()}). "
            "Load additional months to enable trend lines and anomaly detection."
        )
    else:
        fig_trend = go.Figure()
        for i, team in enumerate(sorted(plot_trend["allocated_team"].unique())):
            t_data = plot_trend[plot_trend["allocated_team"] == team].sort_values("billing_month")
            color  = _TEAM_COLORS[i % len(_TEAM_COLORS)]
            label  = _TEAM_LABELS.get(team, team.replace("-", " ").title())
            fig_trend.add_trace(go.Scatter(
                x=t_data["billing_month"].astype(str), y=t_data["period_nec"],
                mode="lines+markers", name=label,
                line=dict(color=color, width=2), marker=dict(size=6),
            ))
            anomaly_rows = t_data[t_data["anomaly"] == True]
            if not anomaly_rows.empty:
                fig_trend.add_trace(go.Scatter(
                    x=anomaly_rows["billing_month"].astype(str), y=anomaly_rows["period_nec"],
                    mode="markers", name=f"{label} anomaly",
                    marker=dict(color="#ef4444", size=12, symbol="circle-open",
                                line=dict(width=2)),
                    showlegend=False,
                ))
        fig_trend.update_layout(
            height=340, margin=dict(t=10, b=40),
            xaxis_title="Billing Month", yaxis_title="Net Effective Cost (USD)",
            legend=dict(orientation="h", y=-0.2), hovermode="x unified",
        )
        st.plotly_chart(fig_trend, use_container_width=True)

        anomaly_teams_trend = plot_trend[plot_trend["anomaly"] == True]["allocated_team"].unique()
        if len(anomaly_teams_trend) > 0:
            anomaly_labels = ", ".join(
                _TEAM_LABELS.get(t, t.replace("-", " ").title()) for t in anomaly_teams_trend
            )
            st.caption(
                f"Alert: Pattern break detected - {anomaly_labels} deviated from baseline "
                f"(z-score > 2.0). Investigate deployment events or resource additions."
            )
        else:
            st.caption(
                f"Stable trajectory across {n_trend_months} months - "
                "no pattern breaks. Low-risk window for optimization decisions."
            )

st.markdown("---")

# ---------------------------------------------------------------------------
# Section 2 - Decision Summary
# ---------------------------------------------------------------------------

st.subheader("Decision Summary")
st.caption(
    "Terminology: **unattributed NEC** = missing `tag_team`; **owner assignment gap** = no owner mapping saved; "
    "**optimization-ready** = attribution coverage >= 80% (enough to act with confidence)."
)
st.caption(
    "Savings hierarchy: **Inefficiency signal** (raw billing-side magnitude) "
    "→ **Recoverable opportunity** (after recovery rates) "
    "→ **Best-case actionable** (low/medium risk only) "
    "→ **Realization-adjusted projection** (× execution rate). "
    "Each layer is strictly smaller than the previous — never compare across layers."
)

# Primary issue: most common root cause across all insights
cause_counts = Counter(
    rc["cause"]
    for ins in filtered
    for rc in ins["root_causes"]
    if rc["cause"] != "no_anomalies_detected"
)
primary_cause_key   = cause_counts.most_common(1)[0][0] if cause_counts else None
primary_cause_label = _CAUSE_LABELS.get(primary_cause_key, "-") if primary_cause_key else "-"

untagged_nec = scope_summary.total_unattributed_cost
untagged_pct = scope_summary.unattributed_pct

# Top opportunity
top_rec_action = "-"
top_rec_savings = 0.0
if filtered_recs:
    top_rec = max(filtered_recs, key=lambda r: r["estimated_savings"])
    top_rec_action  = top_rec["action"].replace("_", " ").title()
    top_rec_savings = top_rec["estimated_savings"]
    top_reasoning = from_recommendation(
        top_rec,
        nec=float(total_nec),
        waste_amount=float(recoverable_total),
        waste_pct=(recoverable_total / total_nec * 100) if total_nec else 0.0,
        unattributed_spend=float(untagged_nec),
        unattributed_pct=float(untagged_pct),
        tagging_coverage_pct=max(0.0, 100.0 - float(untagged_pct)),
        commitment_utilization_pct=max(0.0, 100.0 - float(commitment_waste_pct)),
        commitment_waste=float(commitment_waste_total),
        owner_status="assigned" if top_rec.get("owner_email") else "missing",
        sla_status="within_sla" if top_rec.get("owner_email") else "breached",
        trend_direction="up" if avg_change > 0 else "down" if avg_change < 0 else "stable",
        month_over_month_change_pct=float(avg_change),
    )
else:
    top_reasoning = build_reasoning(
        {
            "nec": float(total_nec),
            "waste_amount": float(recoverable_total),
            "waste_pct": float(recoverable_total / total_nec * 100) if total_nec else 0.0,
            "unattributed_spend": float(untagged_nec),
            "unattributed_pct": float(untagged_pct),
            "tagging_coverage_pct": max(0.0, 100.0 - float(untagged_pct)),
            "commitment_utilization_pct": max(0.0, 100.0 - float(commitment_waste_pct)),
            "commitment_waste": float(commitment_waste_total),
            "cloud_provider": "multi-cloud",
            "team": "portfolio",
            "application": "portfolio",
            "environment": "prod",
            "owner_status": "assigned",
            "sla_status": "within_sla",
            "trend_direction": "up" if avg_change > 0 else "down" if avg_change < 0 else "stable",
            "month_over_month_change_pct": float(avg_change),
            "estimated_savings": float(total_savings),
            "risk_level": "Low",
            "confidence_score": 0.82,
            "risk_score": 20,
            "recommendation_type": "portfolio_review",
        }
    )

n_months = plot_trend["billing_month"].nunique() if not plot_trend.empty else 1
period   = plot_trend["billing_month"].max() if not plot_trend.empty else "-"

_low_risk_savings = sum(
    float(r.get("estimated_savings", 0.0)) for r in filtered_recs if r.get("risk") == "Low"
)
_actionable_sav = (
    canonical_metrics.actionable_savings
    or (_insights_hier.actionable_savings if _insights_hier else 0.0)
    or total_savings
)
summary_lines = [
    f"- **Inefficiency signal: \\${recoverable_total:,.0f}/month** (raw billing-side magnitude across {n_teams} teams)",
    f"- **Best-case actionable opportunity: \\${_actionable_sav:,.0f}/month** (low/medium risk, recovery rates applied)",
    f"- **Realization-adjusted projection: \\${total_savings:,.0f}/month** "
    f"(x {canonical_metrics.realization_rate:.0%} execution rate)",
    f"- **Low-risk quick wins: \\${_low_risk_savings:,.0f}/month** (zero-downtime, no approval required)",
]
if untagged_pct >= 10:
    summary_lines.append(
        f"- **Primary issue: tagging gap** — {untagged_pct:.0f}% of NEC unattributed (\\${untagged_nec:,.0f})"
    )
    summary_lines.append(
        f"- **Important:** \\${untagged_nec:,.0f} is **not savings** — it is attribution risk that blocks reliable optimization."
    )
elif primary_cause_label != "-":
    summary_lines.append(f"- **Primary driver:** {primary_cause_label}")

if commitment_waste_total > 0:
    summary_lines.append(
        f"- **Commitment waste in scope:** {commitment_waste_pct:.1f}% of NEC (\\${commitment_waste_total:,.0f})"
    )

if top_rec_savings > 0:
    summary_lines.append(
        f"- **Top single resource opportunity:** {top_rec_action} — \\${top_rec_savings:,.0f}/month (per resource)"
    )

# Rank recommended actions
action_savings: dict[str, float] = {}
for r in filtered_recs:
    action_savings[r["action"]] = action_savings.get(r["action"], 0.0) + r["estimated_savings"]
ranked_actions = sorted(action_savings.items(), key=lambda x: x[1], reverse=True)[:3]

action_lines = "\n".join(
    f"{i+1}. **{act.replace('_', ' ').title()}** — \\${sav:,.0f}/month (aggregated across resources)"
    for i, (act, sav) in enumerate(ranked_actions)
) if ranked_actions else "No actions identified."

st.info(
    f"**This month ({period}):**\n\n"
    + "\n".join(summary_lines)
    + f"\n\n**Recommended actions:**\n{action_lines}"
)
st.markdown(
    f"**Decision Title**  \n{top_reasoning['decision_title']}\n\n"
    f"**Root Cause**  \n{top_reasoning['root_cause']}\n\n"
    f"**Evidence**  \n- " + "\n- ".join(top_reasoning["evidence"]) + "\n\n"
    f"**Recommended Action**  \n{top_reasoning['recommended_action']}\n\n"
    f"**Why this action**  \n{top_reasoning['action_justification']}\n\n"
    f"**Expected Impact**  \n{top_reasoning['expected_impact']}\n\n"
    f"**Next Best Action**  \n{top_reasoning['next_best_action']}\n\n"
    f"**Confidence / Risk**  \n"
    f"Confidence {top_reasoning['confidence_score']:.0%} - {top_reasoning['confidence_reason']}  \n"
    f"Risk {top_reasoning['risk_score']}/100 - {top_reasoning['risk_reason']}  \n"
    f"Approval required: {'Yes' if top_reasoning['approval_required'] else 'No'}"
)

summary_md = executive_summary_markdown(
    title="FinOps Executive Summary",
    total_nec=float(total_nec),
    unattributed_spend=float(untagged_nec),
    waste=float(commitment_waste_total),
    estimated_savings=float(total_savings),
    forecast_month=forecast.target_month,
    forecast_nec=float(forecast.projected_nec),
    forecast_waste=float(forecast.no_action_waste),
    forecast_savings=float(forecast.projected_savings),
    forecast_basis=forecast.savings_basis,
    recommendations=filtered_recs,
)
st.download_button(
    "Download Executive Summary (.md)",
    summary_md.encode("utf-8"),
    file_name="finops_executive_summary.md",
    mime="text/markdown",
)

# ---------------------------------------------------------------------------
# "What should I do this week" - top 3 executive actions
# ---------------------------------------------------------------------------

st.subheader("What should I do this week")
st.caption("Top 3 actions ordered by: highest savings, lowest risk, highest confidence, shortest time to savings.")
st.caption(
    "ROI is defined as estimated monthly savings divided by mapped effort hours. "
    "Confidence combines data quality, signal strength, and historical consistency."
)

_STATUS_PRIORITY = {
    "recommended": 0,
    "approved": 1,
    "implemented": 2,
    "verified": 3,
    "rejected": 4,
}
_TIME_PRIORITY = {"Immediate": 0, "1 week": 1, "1 month": 2}

_weekly_recs = sorted(
    [r for r in filtered_recs if r.get("action_status", "recommended") != "rejected"],
    key=lambda r: (
        -r["estimated_savings"],
        r.get("risk_score", 50),
        -r.get("confidence", 0.0),
        _TIME_PRIORITY.get(r.get("time_to_realize", "1 month"), 99),
        _STATUS_PRIORITY.get(r.get("action_status", "recommended"), 99),
    ),
)[:3]

if not _weekly_recs:
    _weekly_recs = sorted(filtered_recs, key=lambda r: r["estimated_savings"], reverse=True)[:3]

if _weekly_recs:
    for i, rec in enumerate(_weekly_recs, 1):
        reasoning = from_recommendation(
            rec,
            nec=_team_metric(rec["allocated_team"], "nec", float(total_nec)),
            waste_amount=float(recoverable_total),
            waste_pct=(recoverable_total / total_nec * 100) if total_nec else 0.0,
            unattributed_spend=_team_metric(rec["allocated_team"], "unattributed_nec", float(untagged_nec)),
            unattributed_pct=_team_metric(rec["allocated_team"], "unattributed_pct", float(untagged_pct)),
            tagging_coverage_pct=max(0.0, 100.0 - _team_metric(rec["allocated_team"], "unattributed_pct", float(untagged_pct))),
            commitment_utilization_pct=max(0.0, 100.0 - float(commitment_waste_pct)),
            commitment_waste=_team_metric(rec["allocated_team"], "commitment_waste", float(commitment_waste_total)),
            owner_status="assigned" if (rec.get("action_owner") or rec.get("owner_email")) else "missing",
            sla_status="within_sla" if (rec.get("action_owner") or rec.get("owner_email")) else "breached",
            trend_direction="up" if avg_change > 0 else "down" if avg_change < 0 else "stable",
            month_over_month_change_pct=float(avg_change),
        )
        team     = _TEAM_LABELS.get(rec["allocated_team"], rec["allocated_team"].replace("-", " ").title())
        act      = rec["action"].replace("_", " ").title()
        effort   = rec.get("effort", "-")
        ttr      = rec.get("time_to_realize", "-")
        roi      = rec.get("roi_score", 0)
        savings  = rec["estimated_savings"]
        risk     = rec["risk"]
        status   = rec.get("action_status", "recommended").replace("_", " ").title()
        approval = "Yes" if rec.get("approval_required") else "No"
        safety   = rec.get("action_safety", "approval_required").replace("_", " ").title()
        is_billing_proxy = "idle_compute" in rec.get("signal_type", rec.get("waste_type", ""))
        risk_color = {"Low": "#22c55e", "Medium": "#eab308", "High": "#ef4444"}.get(risk, "#6b7280")

        st.markdown(
            f'<div style="border-left:4px solid {risk_color}; padding:10px 16px; '
            f'margin-bottom:8px; border-radius:4px; background:#f9fafb">'
            f'<b>{i}. {act}</b> - {team} | <b>${savings:,.0f}/month</b><br/>'
            f'<span style="font-size:0.88rem; color:#374151">'
            f'Effort: <b>{effort}</b> &nbsp;|&nbsp; '
            f'Time to savings: <b>{ttr}</b> &nbsp;|&nbsp; '
            f'ROI: <b>${roi:,.0f}/hr of work</b> &nbsp;|&nbsp; '
            f'Risk: <span style="color:{risk_color}; font-weight:700">{risk}</span> '
            f'({rec.get("risk_score", 0)}/100) &nbsp;|&nbsp; '
            f'Status: <b>{status}</b> &nbsp;|&nbsp; '
            f'Approval required: <b>{approval}</b> &nbsp;|&nbsp; '
            f'Safety: <b>{safety}</b>'
            f'</span></div>',
            unsafe_allow_html=True,
        )
        st.caption(
            f"{'Estimated savings (billing proxy). ' if is_billing_proxy else ''}"
            f"Root cause: {reasoning['root_cause']} "
            f"Evidence: {'; '.join(reasoning['evidence'][:3])}. "
            f"Why this action: {reasoning['action_justification']} "
            f"Next best action: {reasoning['next_best_action']}"
        )
else:
    st.info("No actionable recommendations found for this filter selection.")

st.markdown("---")

# ---------------------------------------------------------------------------
# Section 2 - System Reasoning Layer (Critical #3, Medium #9)
#
# Each signal carries: verdict, evidence (where it came from), confidence %,
# confidence explanation (why that number), data window used, and signal
# weight. This is what separates "intelligence" from "reporting".
# ---------------------------------------------------------------------------

signals: list[dict] = []

# Signal: tagging governance
if untagged_pct >= 20:
    signals.append({
        "name":       "Governance gap",
        "verdict":    f"{untagged_pct:.0f}% of NEC (${untagged_nec:,.0f}) is unattributed.",
        "evidence":   f"Derived from {len(scope_df):,} billing rows; `is_tagged=False` on "
                      f"{(~scope_df['is_tagged'].fillna(False)).sum():,} rows.",
        "data_window": f"Current billing period ({period})",
        "confidence_pct": 95,
        "confidence_reason": "Billing-confirmed signal - `is_tagged` is a direct column, "
                             "no inference required.",
        "signal_weight": 1.0,
        "impact":     "Every downstream metric (allocation, chargeback, optimization) "
                      "is unreliable until tag coverage improves.",
        "fix":        "Enforce `tag_team` policy at resource creation. "
                      "Expect attribution improvement within 1 billing cycle.",
        "color":      COLOR_BLOCKER,
        "severity":   "P0",
    })
elif untagged_pct >= 10:
    signals.append({
        "name":       "Attribution gap",
        "verdict":    f"{untagged_pct:.0f}% of NEC (${untagged_nec:,.0f}) lacks explicit attribution.",
        "evidence":   f"Heuristic allocation is compensating on "
                      f"{(~scope_df['is_tagged'].fillna(False)).sum():,} rows.",
        "data_window": f"Current billing period ({period})",
        "confidence_pct": 85,
        "confidence_reason": "Direct `is_tagged` column signal - allocation fallback uncertainty "
                             "is the only noise source.",
        "signal_weight": 0.8,
        "impact":     "Chargeback accuracy is degraded; team-level trends have noise.",
        "fix":        "Explicit tagging would eliminate the heuristic fallback.",
        "color":      COLOR_INEFFICIENCY,
        "severity":   "P1",
    })

# Signal: commitment efficiency
if commitment_waste_pct <= 3:
    signals.append({
        "name":       "Commitment efficiency",
        "verdict":    f"{commitment_waste_pct:.1f}% waste - reserved capacity fully utilized (target <3%).",
        "evidence":   f"From `nec_waste > 0` rows: {(scope_df['nec_waste'].fillna(0) > 0).sum():,} "
                      "waste rows flagged across all commitment types (RI + SP).",
        "data_window": f"Current billing period ({period})",
        "confidence_pct": 92,
        "confidence_reason": "Billing-confirmed - waste is computed from actual versus committed usage.",
        "signal_weight": 0.9,
        "impact":     "Commitment coverage is healthy; no immediate optimization needed.",
        "fix":        "Maintain current commitment strategy; monitor quarterly.",
        "color":      COLOR_OPTIMIZED,
        "severity":   "P3",
    })
elif commitment_waste_pct <= 8:
    signals.append({
        "name":       "Commitment optimization opportunity",
        "verdict":    f"{commitment_waste_pct:.1f}% of NEC (${commitment_waste_total:,.0f}) is idle RI/SP capacity.",
        "evidence":   f"`nec_waste > 0` on {(scope_df['nec_waste'].fillna(0) > 0).sum():,} rows.",
        "data_window": f"Current billing period ({period})",
        "confidence_pct": 90,
        "confidence_reason": "Billing-confirmed idle capacity; recovery estimate uses "
                             "85% realization rate (industry standard for partial release).",
        "signal_weight": 0.85,
        "impact":     "This is direct recoverable commitment waste from billing data, "
                      "not a governance gap or a forecast estimate.",
        "fix":        "Review commitment coverage - see Waste & Recommendations for specific actions.",
        "color":      COLOR_INEFFICIENCY,
        "severity":   "P1",
    })
else:
    signals.append({
        "name":       "Commitment waste elevated",
        "verdict":    f"{commitment_waste_pct:.1f}% of NEC (${commitment_waste_total:,.0f}) in idle commitments.",
        "evidence":   f"`nec_waste > 0` on {(scope_df['nec_waste'].fillna(0) > 0).sum():,} rows; "
                      f"idle capacity ratio exceeds 10% threshold.",
        "data_window": f"Current billing period ({period})",
        "confidence_pct": 94,
        "confidence_reason": "Direct billing signal; confidence degraded only by "
                             "future usage variability.",
        "signal_weight": 1.0,
        "impact":     "Commitment waste is elevated in the current scope and should be reviewed before it compounds.",
        "fix":        "Immediate review recommended - release or right-size idle commitments.",
        "color":      COLOR_BLOCKER,
        "severity":   "P0",
    })

# Signal: pattern stability (time-based)
if n_months >= 3 and trend_anomaly_count == 0 and n_teams > 0:
    signals.append({
        "name":       "Pattern stability",
        "verdict":    f"No statistical anomalies across {n_teams} teams over {n_months} months.",
        "evidence":   f"Z-score < 2.0 on all {n_teams} team trends; "
                      f"baseline computed from >={n_months} months of billing data.",
        "data_window": f"{n_months} months of billing history",
        "confidence_pct": 88,
        "confidence_reason": f"{n_months} months of data (3+ required for reliable z-score). "
                             "High confidence in the 'no anomaly' signal.",
        "signal_weight": 0.75,
        "impact":     "Low-risk window for commitment optimization - no anomalous spikes to investigate.",
        "fix":        "Safe to act on commitment recommendations now.",
        "color":      COLOR_OPTIMIZED,
        "severity":   "P3",
    })
elif history_months_available < 3 and n_teams > 0:
    signals.append({
        "name":       "Insufficient history",
        "verdict":    f"Anomaly detection requires >=3 months ({history_months_available} loaded).",
        "evidence":   f"Only {history_months_available} billing month(s) are available in the mart for this cloud scope.",
        "data_window": f"{history_months_available} month(s) - below 3-month minimum",
        "confidence_pct": 50,
        "confidence_reason": "Below statistical minimum for z-score baseline. "
                             "Pattern signals below use billing structure only, not MoM trends.",
        "signal_weight": 0.40,
        "impact":     "Cannot reliably distinguish noise from trend changes.",
        "fix":        "Load additional historical billing periods.",
        "color":      COLOR_INFO,
        "severity":   "P2",
    })


def _render_signal(sig: dict) -> None:
    """Render one signal card with explicit evidence + confidence reasoning."""
    conf = sig["confidence_pct"]
    conf_color = (
        COLOR_OPTIMIZED    if conf >= 85 else
        COLOR_INEFFICIENCY if conf >= 65 else
        COLOR_BLOCKER
    )
    badge = render_priority_badge(sig["severity"], sig["severity"])
    st.markdown(
        f"""
<div style="border-left:4px solid {sig['color']}; background:{sig['color']}0A;
            padding:10px 14px; margin-bottom:10px; border-radius:4px;">
  <div style="display:flex; justify-content:space-between; align-items:center;">
    <div style="font-weight:600; font-size:1.02rem;">
      {sig['name']} &nbsp; {badge}
    </div>
    <div style="font-size:0.82rem; color:#6b7280;">
      Signal weight: <b>{sig['signal_weight']:.0%}</b>
      &nbsp;|&nbsp;
      Confidence: <b style="color:{conf_color};">{conf}%</b>
    </div>
  </div>
  <div style="margin-top:4px; color:#111827;">{sig['verdict']}</div>
</div>
        """.strip(),
        unsafe_allow_html=True,
    )
    with st.expander("Why this signal (evidence, confidence, data window)", expanded=False):
        st.markdown(
            f"- **Evidence:** {sig['evidence']}\n"
            f"- **Data window:** {sig['data_window']}\n"
            f"- **Confidence {conf}%:** {sig['confidence_reason']}\n"
            f"- **Signal weight ({sig['signal_weight']:.0%}):** "
            "relative importance in the overall verdict.\n"
            f"- **Impact:** {sig['impact']}\n"
            f"- **Recommended fix:** {sig['fix']}"
        )


if signals:
    with st.expander("System Reasoning Layer - audit trail", expanded=False):
        st.caption(
            "Each signal shows its data source, confidence level, and why that confidence "
            "was assigned — the auditable layer beneath the recommendations."
        )
        st.caption(
            "Reliability score formula: **0.40 × data_completeness + 0.35 × signal_strength + 0.25 × historical_stability**. "
            "Scale: 0.0–1.0. Thresholds: ≥ 0.85 = high (green), ≥ 0.65 = medium (yellow), < 0.65 = low (red). "
            "Governance signals (tagging gap, attribution gap) are listed separately from "
            "optimization signals (commitment waste, idle compute) — they have different scoring drivers."
        )
        for sig in signals:
            _render_signal(sig)

st.markdown("---")

# ---------------------------------------------------------------------------
# Section 4 - Team Decision Cards (compact team-level why)
# ---------------------------------------------------------------------------

st.subheader("Team Decision Cards")
st.caption("Root cause analysis with evidence, impact quantification, and recommended action.")

# Chunk teams into rows of 3 to avoid awkward column wrapping
per_row = 3
for row_start in range(0, len(filtered), per_row):
    row_slice = filtered[row_start:row_start + per_row]
    cols = st.columns(per_row)
    for col_idx, ins in enumerate(row_slice):
        col = cols[col_idx]
        team_raw = ins["scope"].replace("team:", "")
        team_lbl = _TEAM_LABELS.get(team_raw, team_raw.replace("-", " ").title())
        chg = ins["cost_change_pct"]
        conf = ins["confidence"]
        arrow = "up" if chg > 0 else ("down" if chg < 0 else "flat")

        if ins["anomaly"]:
            if abs(chg) <= 5:
                time_signal = (
                    f"Statistical anomaly: z-score spike despite small MoM change ({chg:+.1f}%) — "
                    "investigate billing composition or commitment structure change"
                )
            else:
                time_signal = f"Pattern break detected — {chg:+.1f}% deviation exceeds z-score threshold (>2.0)"
        elif abs(chg) > 15:
            time_signal = f"Notice: Sudden {'increase' if chg > 0 else 'decrease'} - {abs(chg):.0f}% MoM"
        elif abs(chg) <= 5 and n_trend_months >= 2:
            time_signal = f"OK: Stable pattern - {n_trend_months}-month baseline"
        elif chg < -15:
            time_signal = "Trend: Confirmed reduction - validate over next 2 billing cycles"
        else:
            time_signal = None

        team_waste_amt = _team_waste.get(team_raw, 0.0)
        team_sav_amt = _team_savings.get(team_raw, 0.0)

        with col:
            with st.container(border=True):
                st.markdown(f"**{team_lbl}** &nbsp; {arrow} {abs(chg):.1f}% MoM")
                if time_signal:
                    st.caption(time_signal)

                # Single confidence chip at the top removes the duplicate
                # "(signal weight X%)" on every root cause + caption below.
                conf_label = "high" if conf >= 0.75 else ("medium" if conf >= 0.55 else "low")
                conf_color = (
                    COLOR_OPTIMIZED    if conf >= 0.75 else
                    COLOR_INEFFICIENCY if conf >= 0.55 else
                    COLOR_BLOCKER
                )
                st.markdown(
                    f'<span style="background:{conf_color}22; color:{conf_color}; '
                    f'padding:2px 8px; border-radius:10px; font-size:0.78rem; '
                    f'font-weight:600;">Confidence {conf:.0%} ({conf_label})</span>',
                    unsafe_allow_html=True,
                )

                st.markdown("**Root causes:**")
                for rc in ins["root_causes"]:
                    if rc["cause"] == "no_anomalies_detected":
                        st.markdown(f"- {rc['evidence']}")
                        continue
                    cause_lbl = _CAUSE_LABELS.get(rc["cause"], rc["cause"].replace("_", " ").title())
                    st.markdown(f"- **{cause_lbl}**: {_team_root_cause_text(team_raw, rc)}")

                if team_waste_amt > 0:
                    st.markdown(f"**Inefficiency signal amount:** \\${team_waste_amt:,.0f}")
                if team_sav_amt > 0:
                    st.markdown(f"**Modeled recoverable opportunity:** \\${team_sav_amt:,.0f}")
                if chg < -5 and team_waste_amt == 0:
                    st.markdown("**Not driven by:** commitment change or resource removal per billing signals")

                top_cause = ins["root_causes"][0]["cause"] if ins["root_causes"] else None
                # Show the actual top recommendation for this team if available
                _team_top_recs = sorted(
                    [
                        r for r in filtered_recs
                        if r.get("allocated_team") == team_raw
                        and r.get("action_status", "recommended") != "rejected"
                    ],
                    key=lambda r: -float(r.get("estimated_savings", 0)),
                )
                if _team_top_recs:
                    _tr = _team_top_recs[0]
                    _tr_act = _tr["action"].replace("_", " ").title()
                    _tr_sav = _tr["estimated_savings"]
                    _tr_risk = _tr.get("risk", "Medium")
                    _is_right_sizing = "idle_compute" in _tr.get("signal_type", _tr.get("waste_type", ""))
                    if _is_right_sizing:
                        st.markdown(
                            f"**Top opportunity:** right-sizing candidate — "
                            f"up to **\\${_tr_sav:,.0f}/month** (billing proxy). Risk: {_tr_risk}.  \n"
                            "Confirm with runtime CPU/memory telemetry before acting."
                        )
                    else:
                        st.markdown(f"**Top action:** {_tr_act} — **\\${_tr_sav:,.0f}/month**. Risk: {_tr_risk}.")
                    if len(_team_top_recs) > 1:
                        st.caption(f"+{len(_team_top_recs) - 1} more recommendations in Waste & Recommendations page.")
                elif top_cause and top_cause in _CAUSE_ACTIONS:
                    action_lbl, risk_lbl = _CAUSE_ACTIONS[top_cause]
                    st.markdown(f"**Recommended action:** {action_lbl}. Risk: {risk_lbl}.")
                else:
                    st.markdown("**Recommended action:** Review manually. Risk: Medium.")

st.markdown("---")

# ---------------------------------------------------------------------------
# Section 5 - Anomaly Explanations (only when anomalies exist)
# ---------------------------------------------------------------------------

anomaly_insights = [ins for ins in filtered if ins["anomaly"]]
if anomaly_insights:
    st.subheader("Anomaly Explanations")
    st.caption(
        "Statistical deviations from the full billing history baseline — not limited to the current month filter. "
        "Each anomaly shows the billing period when the deviation was detected (may predate the current filter period)."
    )

    for ins in anomaly_insights:
        team_raw = ins["scope"].replace("team:", "")
        team_lbl = _TEAM_LABELS.get(team_raw, team_raw.replace("-", " ").title())
        chg = ins["cost_change_pct"]

        team_trend = trend_df[trend_df["allocated_team"] == team_raw]
        anomaly_month = None
        if not team_trend.empty:
            anom_rows = team_trend[team_trend["anomaly"]]
            if not anom_rows.empty:
                anomaly_month = anom_rows.sort_values("billing_month").iloc[-1]["billing_month"]

        top_rc = ins["root_causes"][0] if ins["root_causes"] else None
        likely_cause = _CAUSE_LABELS.get(top_rc["cause"], "unknown") if top_rc else "unknown"
        likely_evidence = top_rc["evidence"] if top_rc else ""
        if likely_cause == "Commitment waste":
            likely_cause = "Billing-side inefficiency signals, attribution gaps, and possible resource or provisioning changes"

        period_str = f" in {anomaly_month}" if anomaly_month else ""
        st.warning(
            f"**Anomaly detected: {team_lbl}** - spend {chg:+.1f}% MoM{period_str}  \n"
            f"**Likely cause:** {likely_cause}  \n"
            f"{likely_evidence}  \n"
            f"**Confidence:** {ins['confidence']:.0%} | "
            "Investigate deployment events, new resource provisioning, or commitment changes in this period."
        )

    st.markdown("---")
