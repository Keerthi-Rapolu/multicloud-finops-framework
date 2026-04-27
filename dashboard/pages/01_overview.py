"""
Page 1 - Overview

Total spend by cloud, daily NEC trend, and service-category breakdown.
"""

import sys
from pathlib import Path

import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from allocation.nec_model import (
    nec_by_cloud,
    nec_by_service_category,
    nec_trend,
    savings_vs_on_demand,
)
from dashboard._shared import (
    CLOUD_COLORS,
    COLOR_BLOCKER,
    COLOR_OPTIMIZED,
    LABEL_NEC,
    LABEL_WASTE_PCT,
    compute_finops_summary_metrics,
    compute_savings_hierarchy,
    diagnose,
    load_canonical_forecast,
    load_canonical_recommendations,
    load_finops_summary,
    load_scoped_df,
    normalize_canonical_recommendations,
    overlay_recommendation_actions,
    render_demo_banner,
    render_headline,
)
from dashboard.canonical import load_canonical_metrics

st.set_page_config(page_title="Overview", layout="wide")
st.title("Overview")
st.caption("What is happening with cloud spend right now")
render_demo_banner()

df, month_filter, selected_cloud = load_scoped_df(render_sidebar=True)
summary_df = load_finops_summary(month_filter)
summary_metrics = compute_finops_summary_metrics(
    summary_df,
    clouds=selected_cloud,
    fallback_df=df,
)
canonical_metrics = load_canonical_metrics(month_filter, selected_cloud)
canonical_recs_df = load_canonical_recommendations(month_filter, selected_cloud)
canonical_recs = (
    overlay_recommendation_actions(normalize_canonical_recommendations(canonical_recs_df))
    if not canonical_recs_df.empty
    else []
)
low_risk_recs = [
    r for r in canonical_recs
    if r.get("risk") == "Low" and r.get("action_status", "recommended") != "rejected"
]

# ---------------------------------------------------------------------------
# Executive headline (Critical #1)
# ---------------------------------------------------------------------------

diag = diagnose(df, summary=summary_metrics)
render_headline(diag)

# ---------------------------------------------------------------------------
# KPI row - 5 metrics
# ---------------------------------------------------------------------------

by_cloud = nec_by_cloud(df)
if not summary_df.empty:
    by_cloud = (
        summary_df.groupby("cloud_provider", dropna=False)[
            ["total_list_cost", "total_nec", "total_commitment_waste"]
        ]
        .sum()
        .reset_index()
        .rename(
            columns={
                "total_list_cost": "list_cost",
                "total_nec": "nec",
                "total_commitment_waste": "nec_waste",
            }
        )
    )
    if selected_cloud != "All":
        by_cloud = by_cloud[by_cloud["cloud_provider"] == selected_cloud].copy()
    by_cloud["savings"] = by_cloud["list_cost"] - by_cloud["nec"]
    by_cloud["savings_pct"] = (
        by_cloud["savings"] / by_cloud["list_cost"].replace(0, float("nan")) * 100
    ).round(1)
    by_cloud["rows"] = (
        df.groupby("cloud_provider", dropna=False)
        .size()
        .reindex(by_cloud["cloud_provider"])
        .fillna(0)
        .astype(int)
        .values
    )
total_list  = canonical_metrics.list_cost or summary_metrics.total_list_cost
total_nec   = canonical_metrics.nec or summary_metrics.total_nec
total_waste = canonical_metrics.commitment_waste or summary_metrics.total_commitment_waste
total_savings = total_list - total_nec
savings_pct = ((total_savings / total_list) * 100) if total_list else 0.0
waste_pct   = (canonical_metrics.waste_rate * 100.0) if canonical_metrics.nec else summary_metrics.commitment_waste_pct

# Optimized NEC — use canonical forecast's optimized_month_end_nec so all pages agree.
canonical_forecast_df = load_canonical_forecast(month_filter, selected_cloud)
if canonical_metrics.optimized_nec > 0:
    _optimized_nec = canonical_metrics.optimized_nec
    _forecast_realized = canonical_metrics.projected_savings
    _forecast_base_nec = canonical_metrics.projected_nec or total_nec
    _forecast_rr = canonical_metrics.realization_rate
    _nec_delta_pct = (_forecast_realized / _forecast_base_nec * 100) if _forecast_base_nec else 0.0
elif not canonical_forecast_df.empty and "optimized_month_end_nec" in canonical_forecast_df.columns:
    _optimized_nec = float(canonical_forecast_df["optimized_month_end_nec"].sum())
    _forecast_realized = float(canonical_forecast_df["projected_realized_savings_usd"].sum()) if "projected_realized_savings_usd" in canonical_forecast_df.columns else 0.0
    _forecast_base_nec = float(canonical_forecast_df["projected_month_end_nec"].sum()) if "projected_month_end_nec" in canonical_forecast_df.columns else total_nec
    _forecast_rr = float(canonical_forecast_df["realization_rate"].mean()) if "realization_rate" in canonical_forecast_df.columns else 0.70
    _nec_delta_pct = (_forecast_realized / _forecast_base_nec * 100) if _forecast_base_nec else 0.0
else:
    _hier = compute_savings_hierarchy(canonical_recs)
    _optimized_nec = max(0.0, total_nec - _hier.realized_projection)
    _forecast_realized = _hier.realized_projection
    _forecast_rr = _hier.realization_rate
    _nec_delta_pct = (_forecast_realized / total_nec * 100) if total_nec else 0.0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric(
    "Total List Cost",
    f"${total_list:,.0f}",
    help="Gross pre-discount cloud cost (list price before any RI/SP/CUD savings).",
)
c2.metric(
    "Net Effective Cost",
    f"${total_nec:,.0f}",
    help="Current billing period actual NEC (from canonical mart). NEC = nec_used + nec_waste. This is the billing-period actuals — not a forecast. See 'Optimized NEC' for the projected value.",
)
c3.metric(
    "Optimized NEC",
    f"${_optimized_nec:,.0f}",
    delta=f"−{_nec_delta_pct:.1f}% ({_forecast_rr:.0%} realization)",
    delta_color="inverse",
    help=f"Projected month-end NEC after realization-adjusted savings (${_forecast_realized:,.0f}/month) from canonical forecast.",
)
c4.metric("Commitment Waste",   f"${total_waste:,.0f}")
c5.metric(LABEL_WASTE_PCT,      f"{waste_pct:.1f}%", delta_color="inverse",
          delta=f"{waste_pct:.1f}% of NEC wasted")

st.caption(
    "**NEC definition:** Net Effective Cost = nec\\_used + nec\\_waste. "
    "nec\\_used is billed capacity actually consumed. "
    "nec\\_waste is the idle RI/SP commitment cost (committed but not consumed). "
    "Optimization reduces the nec\\_waste component. "
    "savings = list\\_cost − NEC (the RI/SP discount delivered)."
)

# Alert if waste is material
if waste_pct >= 5:
    st.warning(
        f"{waste_pct:.1f}% of committed spend is unused. "
        f"\\${total_waste:,.0f}/month is sitting in idle RI/SP capacity. "
        "Review the Cost Allocation page for per-account waste detail."
    )

st.markdown("---")

# ---------------------------------------------------------------------------
# NEC trend with anomaly highlight
# ---------------------------------------------------------------------------

trend = nec_trend(df, freq="D")

# Trend direction label
_trend_label = ""
if not trend.empty:
    total_by_period = trend.groupby("period")["nec"].sum().sort_index()
    if len(total_by_period) >= 4:
        n = len(total_by_period)
        first_avg = total_by_period.iloc[:n // 3].mean()
        last_avg  = total_by_period.iloc[-n // 3:].mean()
        pct_change = (last_avg - first_avg) / first_avg * 100 if first_avg else 0
        if pct_change > 5:
            _trend_label = " - Increasing"
        elif pct_change < -5:
            _trend_label = " - Improving"
        else:
            _trend_label = " - Stable"

st.subheader(f"Daily NEC trend{_trend_label}")

if trend.empty:
    st.info("No trend data for the selected filters.")
else:
    fig_trend = px.line(
        trend, x="period", y="nec", color="cloud_provider",
        labels={"period": "Date", "nec": "NEC (USD)", "cloud_provider": "Cloud"},
        color_discrete_map={"aws": "#f97316", "azure": "#2563eb", "gcp": "#22c55e"},
    )

    # Overlay anomaly markers (z-score > 1.8 per cloud)
    for cloud, grp in trend.groupby("cloud_provider"):
        if len(grp) < 5:
            continue
        mean, std = grp["nec"].mean(), grp["nec"].std()
        if std == 0:
            continue
        outliers = grp[((grp["nec"] - mean).abs() / std) > 1.8]
        if not outliers.empty:
            color_map = {"aws": "#f97316", "azure": "#2563eb", "gcp": "#22c55e"}
            fig_trend.add_scatter(
                x=outliers["period"],
                y=outliers["nec"],
                mode="markers",
                marker=dict(size=10, symbol="circle-open", line=dict(width=2),
                            color=color_map.get(cloud, "#888")),
                name=f"{cloud} anomaly",
                showlegend=True,
            )

    fig_trend.update_layout(height=320, margin=dict(t=10, b=40))
    st.plotly_chart(fig_trend, use_container_width=True)
    st.caption(
        "Anomaly markers (open circles) indicate dates where NEC deviated more than 1.8 standard "
        "deviations from the per-cloud mean. Likely drivers are burst usage, RI underutilization, or "
        "synthetic data variability in this demo."
    )

# ---------------------------------------------------------------------------
# Service category breakdown + pricing-model savings side by side
# ---------------------------------------------------------------------------

col_left, col_right = st.columns(2)

with col_left:
    st.subheader("NEC by service category")
    by_svc = nec_by_service_category(df)
    svc_total = by_svc.groupby("service_category")["nec"].sum().reset_index()
    fig_svc = px.pie(
        svc_total, names="service_category", values="nec",
        hole=0.4,
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    fig_svc.update_layout(height=320, margin=dict(t=10, b=10))
    st.plotly_chart(fig_svc, use_container_width=True)

with col_right:
    st.subheader("Savings by pricing model")
    st.caption(
        "**on_demand** = baseline pricing (no discount). "
        "**ri** = Reserved Instance savings. **sp** = Savings Plan savings."
    )
    savings = savings_vs_on_demand(df)
    fig_sav = px.bar(
        savings, x="discount_type", y="savings", color="cloud_provider",
        barmode="group",
        labels={
            "discount_type": "Pricing model",
            "savings":       "Savings vs on-demand (USD)",
            "cloud_provider": "Cloud",
        },
        color_discrete_map={"aws": "#f97316", "azure": "#2563eb", "gcp": "#22c55e"},
    )
    fig_sav.update_layout(height=320, margin=dict(t=10, b=40))
    st.plotly_chart(fig_sav, use_container_width=True)

# ---------------------------------------------------------------------------
# Per-cloud detail table
# ---------------------------------------------------------------------------

st.markdown("---")

# ---------------------------------------------------------------------------
# Decision Timeline - "what happens if we do nothing" (Add #1 / Task #14)
# Takes this period's waste + untagged NEC and extrapolates 6 months forward
# assuming no mitigation. Shows the cumulative cost of inaction vs. acting now.
# ---------------------------------------------------------------------------

st.subheader("Decision Timeline - cost of inaction")
st.caption(
    "If current waste patterns persist unchanged, here is the cumulative leakage "
    "over the next 6 months vs. acting now (low-risk recoveries only)."
)

import plotly.graph_objects as _go

_monthly_waste = float(canonical_metrics.low_risk_savings or sum(r["estimated_savings"] for r in low_risk_recs))
_months = list(range(0, 7))  # months 0..6

do_nothing  = [_monthly_waste * m for m in _months]
act_now     = [0.0 for _ in _months]

_fig_tl = _go.Figure()
_fig_tl.add_trace(_go.Scatter(
    x=_months, y=do_nothing,
    mode="lines+markers", name="Do nothing - waste accrues",
    line=dict(color=COLOR_BLOCKER, width=3),
    fill="tozeroy", fillcolor="rgba(239, 68, 68, 0.15)",
))
_fig_tl.add_trace(_go.Scatter(
    x=_months, y=act_now,
    mode="lines+markers", name="Act now - remove current low-risk leak",
    line=dict(color=COLOR_OPTIMIZED, width=3),
))
_fig_tl.update_layout(
    height=240, margin=dict(t=10, b=40),
    xaxis=dict(title="Months from now", tickmode="linear", dtick=1),
    yaxis=dict(title="Cumulative waste (USD)", tickformat="$,.0f"),
    legend=dict(orientation="h", y=1.12),
    hovermode="x unified",
)
st.plotly_chart(_fig_tl, use_container_width=True)

# Summary callout - 6-month gap between the two paths
_gap_6m = do_nothing[6] - act_now[6]
if _gap_6m > 0:
    st.info(
        f"6-month cost of inaction: **\\${_gap_6m:,.0f}** (low-risk only)  \n"
        f"Annualized: **\\${_gap_6m * 2:,.0f}/year**  \n"
        "Low-risk quick wins only — does not include medium/high-risk savings opportunity."
    )
st.caption(
    "Two savings numbers in this dashboard — different things: "
    "**Realization-adjusted projection** (Optimized NEC card) = all actionable savings × execution probability. "
    "**Low-risk quick wins** (chart above) = zero-downtime, no-approval subset only. "
    "Low-risk is always smaller — not a contradiction."
)

st.markdown("---")

# Collapsed - dense per-cloud table (available on demand, not dominating the view)
with st.expander("Cloud summary (detailed table)"):
    display = by_cloud[["cloud_provider", "rows", "list_cost", "nec", "nec_waste", "savings", "savings_pct"]].copy()
    display.columns = ["Cloud", "Rows", "List Cost", "NEC", "Waste", "Savings", "Savings %"]
    for col in ["List Cost", "NEC", "Waste", "Savings"]:
        display[col] = display[col].map("${:,.2f}".format)
    display["Savings %"] = display["Savings %"].map("{:.1f}%".format)
    st.dataframe(display, use_container_width=True, hide_index=True)
