"""
Page 1 — Overview

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
    diagnose,
    load_scoped_df,
    render_headline,
)

st.set_page_config(page_title="Overview", layout="wide")
st.title("Overview")
st.caption("What is happening with cloud spend right now?")

df, _, _ = load_scoped_df(render_sidebar=True)

# ---------------------------------------------------------------------------
# Executive headline (Critical #1)
# ---------------------------------------------------------------------------

diag = diagnose(df)
render_headline(diag)

# ---------------------------------------------------------------------------
# KPI row — 5 metrics
# ---------------------------------------------------------------------------

by_cloud = nec_by_cloud(df)
total_list  = by_cloud["list_cost"].sum()
total_nec   = by_cloud["nec"].sum()
total_waste = by_cloud["nec_waste"].sum()
total_savings = total_list - total_nec
savings_pct = total_savings / total_list * 100 if total_list else 0
waste_pct   = total_waste / total_nec * 100 if total_nec else 0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total List Cost",    f"${total_list:,.2f}")
c2.metric(LABEL_NEC,            f"${total_nec:,.2f}")
c3.metric("Savings (vs List Cost)", f"${total_savings:,.2f}",
          delta=f"{savings_pct:.1f}%")
c4.metric("Commitment Waste",   f"${total_waste:,.2f}")
c5.metric(LABEL_WASTE_PCT,      f"{waste_pct:.1f}%", delta_color="inverse",
          delta=f"{waste_pct:.1f}% of NEC wasted")

# Alert if waste is material
if waste_pct >= 5:
    st.warning(
        f":warning: **{waste_pct:.1f}% of committed spend is unused** — "
        f"${total_waste:,.2f} in idle RI / SP capacity. "
        "Review the Team Allocation page for per-account waste detail."
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
            _trend_label = " :red_circle: **Increasing**"
        elif pct_change < -5:
            _trend_label = " :green_circle: **Improving**"
        else:
            _trend_label = " :yellow_circle: **Stable**"

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
        ":mag: **Anomaly markers** (open circles) indicate dates where NEC deviated more than 1.8 standard "
        "deviations from the per-cloud mean — likely caused by burst usage, RI underutilization, or "
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
# Decision Timeline — "what happens if we do nothing?" (Add #1 / Task #14)
# Takes this period's waste + untagged NEC and extrapolates 6 months forward
# assuming no mitigation. Shows the cumulative cost of inaction vs. acting now.
# ---------------------------------------------------------------------------

st.subheader("Decision Timeline — cost of inaction")
st.caption(
    "If current waste patterns persist unchanged, here is the cumulative leakage "
    "over the next 6 months vs. acting now (low-risk recoveries only)."
)

import plotly.graph_objects as _go

_recovery_rate = 0.85   # share of detected waste releasable this quarter
_monthly_waste = float(total_waste)
_monthly_recoverable = _monthly_waste * _recovery_rate
_months = list(range(0, 7))  # months 0..6

do_nothing  = [_monthly_waste * m for m in _months]
act_now     = [min(d, _monthly_waste) if m == 0 else (_monthly_waste - _monthly_recoverable) * m
               for m, d in zip(_months, do_nothing)]

_fig_tl = _go.Figure()
_fig_tl.add_trace(_go.Scatter(
    x=_months, y=do_nothing,
    mode="lines+markers", name="Do nothing — waste accrues",
    line=dict(color=COLOR_BLOCKER, width=3),
    fill="tozeroy", fillcolor="rgba(239, 68, 68, 0.15)",
))
_fig_tl.add_trace(_go.Scatter(
    x=_months, y=act_now,
    mode="lines+markers", name="Act now — recover 85%",
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

# Summary callout — 6-month gap between the two paths
_gap_6m = do_nothing[6] - act_now[6]
if _gap_6m > 0:
    st.info(
        f":hourglass_flowing_sand: **6-month cost of inaction:** "
        f"**${_gap_6m:,.0f}** in avoidable waste (${_gap_6m * 2:,.0f} annualized). "
        f"Low-risk recoveries alone close {_recovery_rate:.0%} of the gap with no downtime."
    )

st.markdown("---")

# Collapsed — dense per-cloud table (available on demand, not dominating the view)
with st.expander("Cloud summary (detailed table)"):
    display = by_cloud[["cloud_provider", "rows", "list_cost", "nec", "nec_waste", "savings", "savings_pct"]].copy()
    display.columns = ["Cloud", "Rows", "List Cost", "NEC", "Waste", "Savings", "Savings %"]
    for col in ["List Cost", "NEC", "Waste", "Savings"]:
        display[col] = display[col].map("${:,.2f}".format)
    display["Savings %"] = display["Savings %"].map("{:.1f}%".format)
    st.dataframe(display, use_container_width=True, hide_index=True)
