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
    nec_by_cloud,
    nec_by_service_category,
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
# KPI row
# ---------------------------------------------------------------------------

by_cloud = nec_by_cloud(df)
total_list = by_cloud["list_cost"].sum()
total_nec = by_cloud["nec"].sum()
total_waste = by_cloud["nec_waste"].sum()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total List Cost",      f"${total_list:,.2f}")
c2.metric("Net Effective Cost",   f"${total_nec:,.2f}")
c3.metric("Discount Savings",     f"${total_list - total_nec:,.2f}",
          delta=f"{(total_list - total_nec) / total_list * 100:.1f}%")
c4.metric("Commitment Waste",     f"${total_waste:,.2f}")

st.markdown("---")

# ---------------------------------------------------------------------------
# NEC trend
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
    fig_trend.update_layout(height=320, margin=dict(t=10, b=40))
    st.plotly_chart(fig_trend, use_container_width=True)

# ---------------------------------------------------------------------------
# Service category breakdown + per-cloud summary side by side
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
    st.subheader("Savings by discount type")
    savings = savings_vs_on_demand(df)
    fig_sav = px.bar(
        savings, x="discount_type", y="savings", color="cloud_provider",
        barmode="group",
        labels={"discount_type": "Discount type", "savings": "Savings (USD)", "cloud_provider": "Cloud"},
        color_discrete_map={"aws": "#f97316", "azure": "#2563eb", "gcp": "#22c55e"},
    )
    fig_sav.update_layout(height=320, margin=dict(t=10, b=40))
    st.plotly_chart(fig_sav, use_container_width=True)

# ---------------------------------------------------------------------------
# Per-cloud detail table
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("Cloud summary")
display = by_cloud[["cloud_provider", "rows", "list_cost", "nec", "nec_waste", "savings", "savings_pct"]].copy()
display.columns = ["Cloud", "Rows", "List Cost", "NEC", "Waste", "Savings", "Savings %"]
for col in ["List Cost", "NEC", "Waste", "Savings"]:
    display[col] = display[col].map("${:,.2f}".format)
display["Savings %"] = display["Savings %"].map("{:.1f}%".format)
st.dataframe(display, use_container_width=True, hide_index=True)
