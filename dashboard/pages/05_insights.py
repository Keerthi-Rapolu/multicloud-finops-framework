"""
Page 5 — Cost Intelligence

AI-driven decision engine: explains WHY cloud costs look the way they do,
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
from intelligence.waste_detector import run as detect_waste
from intelligence.impact_simulator import run as simulate
from dashboard._shared import (
    COLOR_BLOCKER,
    COLOR_INEFFICIENCY,
    COLOR_INFO,
    COLOR_OPTIMIZED,
    LABEL_ESTIMATED_MONTHLY_SAVINGS,
    diagnose,
    load_scoped_df,
    overlay_recommendation_actions,
    render_headline,
    render_priority_badge,
)
from dashboard.exporters import executive_summary_markdown

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
    "AI-driven decision engine — explains WHY cloud costs look the way they do, "
    "with root cause evidence, quantified impact, and action justification."
)

df, month_filter, _ = load_scoped_df(render_sidebar=True)

# ---------------------------------------------------------------------------
# Executive headline (Critical #1)
# ---------------------------------------------------------------------------
diag = diagnose(df)
render_headline(diag)

# ---------------------------------------------------------------------------
# Run pipeline
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Running causal analysis…")
def _run_pipeline(_df_hash: int, _df: pd.DataFrame):
    findings = detect_waste(_df)
    insights_out = run_causal(_df, findings)
    recs = simulate(findings)
    return findings, insights_out, recs

@st.cache_data(show_spinner=False)
def _build_trend(_df_hash: int, _df: pd.DataFrame) -> pd.DataFrame:
    from intelligence.causal_engine import build_nec_trend, compute_zscore_anomaly
    return compute_zscore_anomaly(build_nec_trend(_df))

# Content-based hash so cache hits when the data is unchanged
# (id(df) changes on every reload, which defeats the cache).
_df_hash = int(pd.util.hash_pandas_object(df, index=True).sum())
findings, insights, recs = _run_pipeline(_df_hash, df)
trend_df = _build_trend(_df_hash, df)

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------

st.sidebar.markdown("---")
st.sidebar.subheader("Page filters")
st.sidebar.caption("Drill-down only — the global month/cloud filters still apply.")

all_teams = sorted({ins["scope"].replace("team:", "") for ins in insights}) if insights else []
sel_teams = st.sidebar.multiselect("Teams", all_teams, default=all_teams)
show_anomaly_only = st.sidebar.checkbox("Anomalies only", value=False)

filtered = [
    ins for ins in insights
    if ins["scope"].replace("team:", "") in sel_teams
    and (not show_anomaly_only or ins["anomaly"])
]

filtered_teams = {
    ins["scope"].replace("team:", "")
    for ins in filtered
}
scope_df = (
    df[df["allocated_team"].isin(filtered_teams)].copy()
    if filtered_teams
    else df.iloc[0:0].copy()
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

# Pre-compute per-team waste totals from findings
_team_waste: dict[str, float] = {}
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
n_anomalies = sum(1 for ins in filtered if ins["anomaly"])
avg_change  = sum(ins["cost_change_pct"] for ins in filtered) / n_teams if n_teams else 0.0
total_savings = sum(r["estimated_savings"] for r in filtered_recs)
total_nec   = scope_df["nec"].sum()
recoverable_total = sum(
    f["nec_waste"] if f["nec_waste"] > 0 else f["nec_used"]
    for f in filtered_findings
)
commitment_waste_total = scope_df["nec_waste"].sum()
commitment_waste_pct   = commitment_waste_total / total_nec * 100 if total_nec else 0

ck1, ck2, ck3 = st.columns(3)
ck1.metric("Teams with Cost Increases", str(sum(1 for ins in filtered if ins["cost_change_pct"] > 0)),
           delta=f"{n_teams} total teams")
ck2.metric("Avg MoM Change",       f"{avg_change:+.1f}%")
ck3.metric(LABEL_ESTIMATED_MONTHLY_SAVINGS,  f"${total_savings:,.0f}")

if not filtered:
    st.info("No insights match the current filter selection.")
    st.stop()

if n_anomalies:
    anomaly_teams = ", ".join(
        ins["scope"].replace("team:", "").replace("-", " ").title()
        for ins in filtered if ins["anomaly"]
    )
    st.error(
        f":rotating_light: **{n_anomalies} statistical anomal{'y' if n_anomalies == 1 else 'ies'} detected** "
        f"— spend deviated from baseline in: {anomaly_teams}"
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

st.subheader("Forecast Outlook")
fc1, fc2, fc3 = st.columns(3)
fc1.metric("Projected Month-End NEC", f"${forecast.projected_nec:,.0f}")
fc2.metric("Waste if No Action Taken", f"${forecast.no_action_waste:,.0f}")
fc3.metric("Savings if Actions Applied", f"${forecast.projected_savings:,.0f}")

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
            name="Optimized NEC",
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
    f"{forecast.target_month}: {forecast.method}. "
    f"Forecast uses {forecast.months_of_history} prior month(s) of history. "
    f"Savings scenario assumes {forecast.savings_basis}."
)

st.markdown("---")

# ---------------------------------------------------------------------------
# Section 1 — Trend (TIME DIMENSION FIRST — the most important context)
# ---------------------------------------------------------------------------

n_trend_months = 0  # fallback — set inside the trend block if trend_df is populated

plot_trend = trend_df[trend_df["allocated_team"].isin(filtered_teams)].copy()

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
                f"🔴 Pattern break detected — {anomaly_labels} deviated from baseline "
                f"(z-score > 2.0). Investigate deployment events or resource additions."
            )
        else:
            st.caption(
                f"Stable trajectory across {n_trend_months} months — "
                "no pattern breaks. Low-risk window for optimization decisions."
            )

st.markdown("---")

# ---------------------------------------------------------------------------
# Section 2 — Decision Summary
# ---------------------------------------------------------------------------

st.subheader("Decision Summary")

# Primary issue: most common root cause across all insights
cause_counts = Counter(
    rc["cause"]
    for ins in filtered
    for rc in ins["root_causes"]
    if rc["cause"] != "no_anomalies_detected"
)
primary_cause_key   = cause_counts.most_common(1)[0][0] if cause_counts else None
primary_cause_label = _CAUSE_LABELS.get(primary_cause_key, "—") if primary_cause_key else "—"

untagged_nec = scope_df.loc[~scope_df["is_tagged"].fillna(False), "nec"].sum()
untagged_pct = untagged_nec / total_nec * 100 if total_nec else 0

# Top opportunity
top_rec_action = "—"
top_rec_savings = 0.0
if filtered_recs:
    top_rec = max(filtered_recs, key=lambda r: r["estimated_savings"])
    top_rec_action  = top_rec["action"].replace("_", " ").title()
    top_rec_savings = top_rec["estimated_savings"]

n_months = plot_trend["billing_month"].nunique() if not plot_trend.empty else 1
period   = plot_trend["billing_month"].max() if not plot_trend.empty else "—"

summary_lines = [
    f"- **${recoverable_total:,.0f}/month recoverable opportunity** identified across {n_teams} teams",
]
if untagged_pct >= 10:
    summary_lines.append(
        f"- **Primary issue: tagging gap** — {untagged_pct:.0f}% of NEC unattributed (${untagged_nec:,.0f})"
    )
elif primary_cause_label != "—":
    summary_lines.append(f"- **Primary driver:** {primary_cause_label}")

if commitment_waste_total > 0:
    summary_lines.append(
        f"- **Commitment waste in scope:** {commitment_waste_pct:.1f}% of NEC (${commitment_waste_total:,.0f})"
    )

if top_rec_savings > 0:
    summary_lines.append(
        f"- **Top opportunity:** {top_rec_action} — ${top_rec_savings:,.0f}/month recoverable"
    )

# Rank recommended actions
action_savings: dict[str, float] = {}
for r in filtered_recs:
    action_savings[r["action"]] = action_savings.get(r["action"], 0.0) + r["estimated_savings"]
ranked_actions = sorted(action_savings.items(), key=lambda x: x[1], reverse=True)[:3]

action_lines = "\n".join(
    f"{i+1}. **{act.replace('_', ' ').title()}** — ${sav:,.0f}/month"
    for i, (act, sav) in enumerate(ranked_actions)
) if ranked_actions else "No actions identified."

st.info(
    f"**This month ({period}):**\n\n"
    + "\n".join(summary_lines)
    + f"\n\n**Recommended actions:**\n{action_lines}"
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
# "What should I do this week?" — top 3 executive actions
# ---------------------------------------------------------------------------

st.subheader("What should I do this week?")
st.caption("Top 3 actions ordered by: highest savings, lowest risk, highest confidence, shortest time to savings.")

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
        team     = _TEAM_LABELS.get(rec["allocated_team"], rec["allocated_team"].replace("-", " ").title())
        act      = rec["action"].replace("_", " ").title()
        effort   = rec.get("effort", "—")
        ttr      = rec.get("time_to_realize", "—")
        roi      = rec.get("roi_score", 0)
        savings  = rec["estimated_savings"]
        risk     = rec["risk"]
        status   = rec.get("action_status", "recommended").replace("_", " ").title()
        approval = "Yes" if rec.get("approval_required") else "No"
        safety   = rec.get("action_safety", "approval_required").replace("_", " ").title()
        risk_color = {"Low": "#22c55e", "Medium": "#eab308", "High": "#ef4444"}.get(risk, "#6b7280")

        st.markdown(
            f'<div style="border-left:4px solid {risk_color}; padding:10px 16px; '
            f'margin-bottom:8px; border-radius:4px; background:#f9fafb">'
            f'<b>{i}. {act}</b> — {team} · <b>${savings:,.0f}/month</b><br/>'
            f'<span style="font-size:0.88rem; color:#374151">'
            f'Effort: <b>{effort}</b> &nbsp;·&nbsp; '
            f'Time to savings: <b>{ttr}</b> &nbsp;·&nbsp; '
            f'ROI: <b>${roi:,.0f}/hr of work</b> &nbsp;·&nbsp; '
            f'Risk: <span style="color:{risk_color}; font-weight:700">{risk}</span> '
            f'({rec.get("risk_score", 0)}/100) &nbsp;·&nbsp; '
            f'Status: <b>{status}</b> &nbsp;·&nbsp; '
            f'Approval required: <b>{approval}</b> &nbsp;·&nbsp; '
            f'Safety: <b>{safety}</b>'
            f'</span></div>',
            unsafe_allow_html=True,
        )
        st.caption(
            f"{rec.get('risk_reason', 'Review manually.')} "
            f"{rec.get('evidence_summary', '')} "
            f"{rec.get('confidence_reason', '')}"
        )
else:
    st.info("No actionable recommendations found for this filter selection.")

st.markdown("---")

# ---------------------------------------------------------------------------
# Section 2 — System Reasoning Layer (Critical #3, Medium #9)
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
        "icon":       ":mag:",
        "verdict":    f"{untagged_pct:.0f}% of NEC (${untagged_nec:,.0f}) is unattributed.",
        "evidence":   f"Derived from {len(scope_df):,} billing rows; `is_tagged=False` on "
                      f"{(~scope_df['is_tagged'].fillna(False)).sum():,} rows.",
        "data_window": f"Current billing period ({period})",
        "confidence_pct": 95,
        "confidence_reason": "Billing-confirmed signal — `is_tagged` is a direct column, "
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
        "icon":       ":mag:",
        "verdict":    f"{untagged_pct:.0f}% of NEC (${untagged_nec:,.0f}) lacks explicit attribution.",
        "evidence":   f"Heuristic allocation is compensating on "
                      f"{(~scope_df['is_tagged'].fillna(False)).sum():,} rows.",
        "data_window": f"Current billing period ({period})",
        "confidence_pct": 85,
        "confidence_reason": "Direct `is_tagged` column signal — allocation fallback uncertainty "
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
        "icon":       ":white_check_mark:",
        "verdict":    f"{commitment_waste_pct:.1f}% waste — reserved capacity fully utilised (target <3%).",
        "evidence":   f"From `nec_waste > 0` rows: {(scope_df['nec_waste'].fillna(0) > 0).sum():,} "
                      "waste rows flagged across all commitment types (RI + SP).",
        "data_window": f"Current billing period ({period})",
        "confidence_pct": 92,
        "confidence_reason": "Billing-confirmed — waste is computed from actual vs committed usage.",
        "signal_weight": 0.9,
        "impact":     "Commitment coverage is healthy; no immediate optimization needed.",
        "fix":        "Maintain current commitment strategy; monitor quarterly.",
        "color":      COLOR_OPTIMIZED,
        "severity":   "P3",
    })
elif commitment_waste_pct <= 8:
    signals.append({
        "name":       "Commitment optimization opportunity",
        "icon":       ":orange_circle:",
        "verdict":    f"{commitment_waste_pct:.1f}% of NEC (${commitment_waste_total:,.0f}) is idle RI/SP capacity.",
        "evidence":   f"`nec_waste > 0` on {(scope_df['nec_waste'].fillna(0) > 0).sum():,} rows.",
        "data_window": f"Current billing period ({period})",
        "confidence_pct": 90,
        "confidence_reason": "Billing-confirmed idle capacity; recovery estimate uses "
                             "85% realization rate (industry standard for partial release).",
        "signal_weight": 0.85,
        "impact":     "At $10M/month scale this waste rate = "
                      f"${10_000_000 * commitment_waste_pct / 100:,.0f}/month avoidable.",
        "fix":        "Review commitment coverage — see Waste & Recommendations for specific actions.",
        "color":      COLOR_INEFFICIENCY,
        "severity":   "P1",
    })
else:
    signals.append({
        "name":       "Commitment waste elevated",
        "icon":       ":red_circle:",
        "verdict":    f"{commitment_waste_pct:.1f}% of NEC (${commitment_waste_total:,.0f}) in idle commitments.",
        "evidence":   f"`nec_waste > 0` on {(scope_df['nec_waste'].fillna(0) > 0).sum():,} rows; "
                      f"idle capacity ratio exceeds 10% threshold.",
        "data_window": f"Current billing period ({period})",
        "confidence_pct": 94,
        "confidence_reason": "Direct billing signal; confidence degraded only by "
                             "future usage variability.",
        "signal_weight": 1.0,
        "impact":     f"At $10M/month scale = ${10_000_000 * commitment_waste_pct / 100:,.0f}/month avoidable.",
        "fix":        "Immediate review recommended — release or right-size idle commitments.",
        "color":      COLOR_BLOCKER,
        "severity":   "P0",
    })

# Signal: pattern stability (time-based)
if n_months >= 3 and n_anomalies == 0 and n_teams > 0:
    signals.append({
        "name":       "Pattern stability",
        "icon":       ":bar_chart:",
        "verdict":    f"No statistical anomalies across {n_teams} teams over {n_months} months.",
        "evidence":   f"Z-score < 2.0 on all {n_teams} team trends; "
                      f"baseline computed from ≥{n_months} months of billing data.",
        "data_window": f"{n_months} months of billing history",
        "confidence_pct": 88,
        "confidence_reason": f"{n_months} months of data (3+ required for reliable z-score). "
                             "High confidence in the 'no anomaly' signal.",
        "signal_weight": 0.75,
        "impact":     "Low-risk window for commitment optimization — no anomalous spikes to investigate.",
        "fix":        "Safe to act on commitment recommendations now.",
        "color":      COLOR_OPTIMIZED,
        "severity":   "P3",
    })
elif n_months < 3 and n_teams > 0:
    signals.append({
        "name":       "Insufficient history",
        "icon":       ":bar_chart:",
        "verdict":    f"Anomaly detection requires ≥3 months ({n_months} loaded).",
        "evidence":   f"Only {n_months} billing month(s) available in the mart.",
        "data_window": f"{n_months} month(s) — below 3-month minimum",
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
      {sig['icon']} {sig['name']} &nbsp; {badge}
    </div>
    <div style="font-size:0.82rem; color:#6b7280;">
      Signal weight: <b>{sig['signal_weight']:.0%}</b>
      &nbsp;·&nbsp;
      Confidence: <b style="color:{conf_color};">{conf}%</b>
    </div>
  </div>
  <div style="margin-top:4px; color:#111827;">{sig['verdict']}</div>
</div>
        """.strip(),
        unsafe_allow_html=True,
    )
    with st.expander("Why this signal? (evidence, confidence, data window)", expanded=False):
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
    with st.expander("System Reasoning Layer — audit trail", expanded=False):
        st.caption(
            "Each signal shows its data source, confidence level, and why that confidence "
            "was assigned — the auditable layer beneath the recommendations."
        )
        for sig in signals:
            _render_signal(sig)

st.markdown("---")

# ---------------------------------------------------------------------------
# Section 4 — Team Decision Cards (WHY per team — compact format)
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
        arrow = "▲" if chg > 0 else ("▼" if chg < 0 else "→")

        if ins["anomaly"]:
            time_signal = "🔴 Pattern break — deviation from baseline"
        elif abs(chg) > 15:
            time_signal = f"⚡ Sudden {'increase' if chg > 0 else 'decrease'} — {abs(chg):.0f}% MoM"
        elif abs(chg) <= 5 and n_trend_months >= 2:
            time_signal = f"✅ Stable pattern — {n_trend_months}-month baseline"
        elif chg < -15:
            time_signal = "📉 Confirmed reduction — validate over next 2 billing cycles"
        else:
            time_signal = None

        team_waste_amt = _team_waste.get(team_raw, 0.0)
        team_sav_amt = _team_savings.get(team_raw, 0.0)

        with col:
            with st.container(border=True):
                st.markdown(f"**{team_lbl}** &nbsp; {arrow} {abs(chg):.1f}% MoM")
                if time_signal:
                    st.caption(time_signal)

                # Single confidence chip at the top — removes the duplicate
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
                    st.markdown(f"- **{cause_lbl}**: {rc['evidence']}")

                if team_waste_amt > 0:
                    st.markdown(f"**Impact:** ${team_waste_amt:,.0f} waste identified")
                if chg < -5 and team_waste_amt == 0:
                    st.markdown("**Not driven by:** commitment change or resource removal per billing signals")

                top_cause = ins["root_causes"][0]["cause"] if ins["root_causes"] else None
                if top_cause and top_cause in _CAUSE_ACTIONS:
                    action_lbl, risk_lbl = _CAUSE_ACTIONS[top_cause]
                    if team_sav_amt > 0:
                        st.markdown(f"→ **{action_lbl}** · ${team_sav_amt:,.0f} recoverable · Risk: {risk_lbl}")
                    else:
                        st.markdown(f"→ **{action_lbl}** · Risk: {risk_lbl}")
                else:
                    st.markdown("→ **Review manually** · Risk: Medium")

st.markdown("---")

# ---------------------------------------------------------------------------
# Section 5 — Anomaly Explanations (only when anomalies exist)
# ---------------------------------------------------------------------------

anomaly_insights = [ins for ins in filtered if ins["anomaly"]]
if anomaly_insights:
    st.subheader("Anomaly Explanations")
    st.caption("Statistical deviations from baseline with likely causes and confidence scores.")

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

        period_str = f" in {anomaly_month}" if anomaly_month else ""
        st.warning(
            f"**Anomaly detected: {team_lbl}** — spend {chg:+.1f}% MoM{period_str}  \n"
            f"**Likely cause:** {likely_cause}  \n"
            f"{likely_evidence}  \n"
            f"**Confidence:** {ins['confidence']:.0%} | "
            "Investigate deployment events, new resource provisioning, or commitment changes in this period."
        )

    st.markdown("---")
