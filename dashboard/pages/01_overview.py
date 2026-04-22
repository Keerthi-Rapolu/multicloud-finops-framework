"""
Page 1 — Overview

Total spend by cloud, daily NEC trend, and service-category breakdown.
"""

import sys
from pathlib import Path

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from allocation.nec_model import (
    commitment_waste_detail,
    nec_by_cloud,
    nec_by_service_category,
    nec_by_team,
    nec_trend,
    savings_vs_on_demand,
)

st.set_page_config(page_title="Overview", layout="wide")
st.title("Overview")

df = st.session_state.get("df")
if df is None:
    st.warning("Return to the home page first to load data.")
    st.stop()

# ---------------------------------------------------------------------------
# KPI row — 5 metrics
# ---------------------------------------------------------------------------

by_cloud = nec_by_cloud(df)
total_list  = by_cloud["list_cost"].sum()
total_nec   = by_cloud["nec"].sum()
total_waste = by_cloud["nec_waste"].sum()
waste_pct   = total_waste / total_nec * 100 if total_nec else 0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total List Cost",    f"${total_list:,.2f}")
c2.metric("Net Effective Cost", f"${total_nec:,.2f}")
c3.metric("Discount Savings",   f"${total_list - total_nec:,.2f}",
          delta=f"{(total_list - total_nec) / total_list * 100:.1f}%")
c4.metric("Commitment Waste",   f"${total_waste:,.2f}")
c5.metric("Waste %",            f"{waste_pct:.1f}%", delta_color="inverse",
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

st.subheader("Daily NEC trend")

trend = nec_trend(df, freq="D")
if trend.empty:
    st.info("No trend data for the selected filters.")
else:
    fig_trend = px.line(
        trend, x="period", y="nec", color="cloud_provider",
        labels={"period": "Date", "nec": "NEC (USD)", "cloud_provider": "Cloud"},
        color_discrete_map={"aws": "#f97316", "azure": "#2563eb", "gcp": "#22c55e"},
    )

    # Overlay anomaly markers (z-score > 1.8 per cloud)
    anomaly_traces = []
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
# Top waste contributors
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("Top commitment waste contributors")

waste_rows = commitment_waste_detail(df)
if waste_rows.empty:
    st.success("No commitment waste rows in the selected data.")
else:
    top_waste = (
        waste_rows.groupby(["service_name", "cloud_provider"])["nec_waste"]
        .sum()
        .reset_index()
        .sort_values("nec_waste", ascending=False)
        .head(10)
    )
    fig_waste = px.bar(
        top_waste, x="nec_waste", y="service_name", orientation="h",
        color="cloud_provider",
        color_discrete_map={"aws": "#f97316", "azure": "#2563eb", "gcp": "#22c55e"},
        labels={"nec_waste": "Waste (USD)", "service_name": "Service", "cloud_provider": "Cloud"},
    )
    fig_waste.update_layout(
        height=320, margin=dict(t=10, b=40),
        yaxis={"categoryorder": "total ascending"},
    )
    st.plotly_chart(fig_waste, use_container_width=True)

# ---------------------------------------------------------------------------
# Per-cloud detail table
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("Cloud summary")
st.caption(":information_source: Synthetic dataset — cloud distribution does not reflect real-world proportions.")

display = by_cloud[["cloud_provider", "rows", "list_cost", "nec", "nec_waste", "savings", "savings_pct"]].copy()
display.columns = ["Cloud", "Rows", "List Cost", "NEC", "Waste", "Savings", "Savings %"]
for col in ["List Cost", "NEC", "Waste", "Savings"]:
    display[col] = display[col].map("${:,.2f}".format)
display["Savings %"] = display["Savings %"].map("{:.1f}%".format)
st.dataframe(display, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Insight callouts
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("Key insights")

# Cloud dominance
if not by_cloud.empty:
    top_cloud = by_cloud.loc[by_cloud["nec"].idxmax()]
    top_cloud_pct = top_cloud["nec"] / total_nec * 100

    col_i1, col_i2, col_i3 = st.columns(3)

    col_i1.info(
        f"**{top_cloud['cloud_provider'].upper()}** accounts for "
        f"**{top_cloud_pct:.0f}%** of total NEC "
        f"(${top_cloud['nec']:,.0f})."
    )

    # Tagging gap
    untagged_nec = df.loc[~df["is_tagged"].fillna(False), "nec"].sum()
    col_i2.warning(
        f"**Tagging gap** exposes **${untagged_nec:,.0f}** in unallocated NEC "
        "that falls back to heuristics."
    )

    # Top team
    try:
        by_team = nec_by_team(df)
        team_totals = by_team.groupby("team")["nec"].sum()
        if not team_totals.empty:
            top_team = team_totals.idxmax()
            top_team_pct = team_totals.max() / total_nec * 100
            col_i3.info(
                f"**{top_team}** drives **{top_team_pct:.0f}%** of total NEC "
                f"(${team_totals.max():,.0f})."
            )
    except Exception:
        pass
