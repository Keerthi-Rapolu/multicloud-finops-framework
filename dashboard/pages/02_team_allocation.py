"""
Page 2 — Team Allocation

Per-team NEC breakdown, NEC vs list cost comparison, and commitment utilization.
Uses allocated_nec (which already reflects Azure's shared-cost fan-out from dbt).
"""

import sys
from pathlib import Path

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from allocation.nec_model import (
    commitment_utilization,
    commitment_waste_detail,
    nec_by_team,
)

st.set_page_config(page_title="Team Allocation", layout="wide")
st.title("Team Allocation")

df = st.session_state.get("df")
if df is None:
    st.warning("Return to the home page first to load data.")
    st.stop()

# ---------------------------------------------------------------------------
# Team NEC table
# ---------------------------------------------------------------------------

by_team = nec_by_team(df)
by_team_all = by_team.groupby("team").agg(
    list_cost=("list_cost", "sum"),
    nec=("nec", "sum"),
    nec_waste=("nec_waste", "sum"),
    savings=("savings", "sum"),
).reset_index()
by_team_all["savings_pct"] = (
    (by_team_all["savings"] / by_team_all["list_cost"].replace(0, float("nan"))) * 100
).round(1)

st.subheader("NEC by team (all clouds combined)")

col_bar, col_tbl = st.columns([3, 2])

with col_bar:
    fig = px.bar(
        by_team_all.sort_values("nec", ascending=True),
        x="nec", y="team", orientation="h",
        labels={"nec": "Net Effective Cost (USD)", "team": "Team"},
        color="nec",
        color_continuous_scale="Blues",
    )
    fig.update_layout(height=320, margin=dict(t=10, b=40), coloraxis_showscale=False)
    st.plotly_chart(fig, use_container_width=True)

with col_tbl:
    display = by_team_all[["team", "list_cost", "nec", "nec_waste", "savings_pct"]].copy()
    display.columns = ["Team", "List Cost", "NEC", "Waste", "Savings %"]
    for col in ["List Cost", "NEC", "Waste"]:
        display[col] = display[col].map("${:,.2f}".format)
    display["Savings %"] = display["Savings %"].map(lambda x: f"{x:.1f}%" if x == x else "—")
    st.dataframe(display, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# NEC vs list cost per team × cloud
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("NEC vs list cost by team and cloud")

fig2 = go.Figure()
for cloud, color in [("aws", "#f97316"), ("azure", "#2563eb"), ("gcp", "#22c55e")]:
    sub = by_team[by_team["cloud_provider"] == cloud]
    fig2.add_trace(go.Bar(
        name=f"{cloud} — List",
        x=sub["team"], y=sub["list_cost"],
        marker_color=color, opacity=0.4,
    ))
    fig2.add_trace(go.Bar(
        name=f"{cloud} — NEC",
        x=sub["team"], y=sub["nec"],
        marker_color=color,
    ))
fig2.update_layout(
    barmode="group", xaxis_title="Team", yaxis_title="USD",
    legend=dict(orientation="h", y=1.12), height=360, margin=dict(t=10, b=40),
)
st.plotly_chart(fig2, use_container_width=True)

# ---------------------------------------------------------------------------
# Commitment utilization
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("Commitment utilization (RI / SP)")

util = commitment_utilization(df)
if util.empty:
    st.info("No RI or SP rows in the selected data.")
else:
    col_u1, col_u2 = st.columns(2)

    with col_u1:
        fig_util = px.bar(
            util, x="cloud_provider", y="utilization_pct", color="discount_type",
            barmode="group",
            labels={
                "cloud_provider": "Cloud",
                "utilization_pct": "Utilization %",
                "discount_type": "Type",
            },
            range_y=[0, 110],
            color_discrete_map={"ri": "#7c3aed", "sp": "#0ea5e9"},
        )
        fig_util.add_hline(y=100, line_dash="dash", line_color="gray", opacity=0.5)
        fig_util.update_layout(height=300, margin=dict(t=10, b=40))
        st.plotly_chart(fig_util, use_container_width=True)

    with col_u2:
        util_display = util[["cloud_provider", "discount_type", "nec_used", "nec_waste", "utilization_pct"]].copy()
        util_display.columns = ["Cloud", "Type", "Used ($)", "Waste ($)", "Utilization %"]
        util_display["Used ($)"]  = util_display["Used ($)"].map("${:,.2f}".format)
        util_display["Waste ($)"] = util_display["Waste ($)"].map("${:,.2f}".format)
        util_display["Utilization %"] = util_display["Utilization %"].map("{:.1f}%".format)
        st.dataframe(util_display, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Commitment waste detail
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("Idle commitment rows (waste detail)")

waste = commitment_waste_detail(df)
if waste.empty:
    st.success("No commitment waste rows in the selected data.")
else:
    waste["nec_waste"] = waste["nec_waste"].map("${:,.4f}".format)
    st.dataframe(waste.head(50), use_container_width=True, hide_index=True)
    if len(waste) > 50:
        st.caption(f"Showing top 50 of {len(waste)} waste rows.")
