"""
Page 2 — Cost Allocation

Per-team NEC breakdown, commitment utilization, and shared-cost distribution.
Merges the former Team Allocation and Shared Costs pages into one cohesive view.
"""

import sys
from pathlib import Path

import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from allocation.nec_model import (
    commitment_utilization,
    commitment_waste_detail,
    nec_by_team,
)
from allocation.shared_cost import SharedCostDistributor
from dashboard._shared import load_scoped_df
from dashboard._shared import compute_finops_summary_metrics, load_finops_summary, render_demo_banner
from dashboard.canonical import load_canonical_metrics

_CONFIG = Path(__file__).resolve().parents[2] / "config" / "shared_cost_weights.yml"

_TEAM_LABELS = {
    "data-eng":    "Data Engineering",
    "platform":    "Platform",
    "frontend":    "Frontend",
    "backend":     "Backend",
    "ml":          "Machine Learning",
    "unattributed":"Unattributed",
}
# Short forms for metric display (Streamlit metric values truncate at ~12 chars in narrow columns)
_TEAM_LABELS_SHORT = {
    "data-eng":    "Data Eng",
    "platform":    "Platform",
    "frontend":    "Frontend",
    "backend":     "Backend",
    "ml":          "ML",
    "unattributed":"Unattributed",
}

st.set_page_config(page_title="Cost Allocation", layout="wide")
st.title("Cost Allocation")
st.caption("Who is spending what, and how is shared infrastructure charged back to teams?")
st.caption(
    "This page uses the same canonical NEC baseline as Overview and Insights. "
    "Differences come from shared-cost distribution and team-level allocation views, not from a different source table."
)
render_demo_banner()

df, month_filter, selected_cloud = load_scoped_df(render_sidebar=True)
summary_df = load_finops_summary(month_filter)
canonical_metrics = load_canonical_metrics(month_filter, selected_cloud)

# ---------------------------------------------------------------------------
# Team NEC summary
# ---------------------------------------------------------------------------

by_team = nec_by_team(df)
by_team_all = by_team.groupby("team").agg(
    list_cost=("list_cost", "sum"),
    nec=("nec", "sum"),
    nec_waste=("nec_waste", "sum"),
    savings=("savings", "sum"),
).reset_index()
if not summary_df.empty:
    by_team_all = (
        summary_df[
            summary_df["cloud_provider"].isin([selected_cloud]) if selected_cloud != "All" else [True] * len(summary_df)
        ]
        .groupby("team", dropna=False)[
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
    by_team_all["savings"] = by_team_all["list_cost"] - by_team_all["nec"]
by_team_all["savings_pct"] = (
    (by_team_all["savings"] / by_team_all["list_cost"].replace(0, float("nan"))) * 100
).round(1)

total_nec = canonical_metrics.nec or by_team_all["nec"].sum()
top_row   = by_team_all.loc[by_team_all["nec"].idxmax()]
top_label = _TEAM_LABELS.get(top_row["team"], top_row["team"].replace("-", " ").title())
top_pct   = top_row["nec"] / total_nec * 100 if total_nec else 0

_top_label_short = _TEAM_LABELS_SHORT.get(top_row["team"], top_label[:8])
ck1, ck2, ck3 = st.columns(3)
ck1.metric("Teams tracked",          str(len(by_team_all)))
ck2.metric(
    "Largest cost centre",
    _top_label_short,
    delta=f"{top_pct:.0f}% of NEC — ${top_row['nec']:,.0f}",
    delta_color="off",
    help=f"Full name: {top_label}",
)
ck3.metric(
    "Total commitment waste",
    f"${(canonical_metrics.commitment_waste or by_team_all['nec_waste'].sum()):,.0f}",
    delta_color="inverse",
    help="Idle RI/SP/CUD capacity cost — committed but not consumed.",
)

st.markdown("---")
st.subheader("NEC by team")

col_bar, col_tbl = st.columns([3, 2])

_sorted = by_team_all.sort_values("nec", ascending=True).copy()
_sorted["team_label"] = _sorted["team"].map(_TEAM_LABELS).fillna(
    _sorted["team"].str.replace("-", " ").str.title()
)

with col_bar:
    fig = px.bar(
        _sorted,
        x="nec", y="team_label", orientation="h",
        labels={"nec": "NEC (USD)", "team_label": "Team"},
        color="nec",
        color_continuous_scale="Blues",
        text=_sorted["nec"].map("${:,.0f}".format),
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(height=320, margin=dict(t=10, b=40, r=110), coloraxis_showscale=False, yaxis_title=None)
    st.plotly_chart(fig, use_container_width=True)

with col_tbl:
    # Expandable — keep primary view visually simple, table on demand
    with st.expander("Per-team table (NEC, Waste, Savings %)", expanded=False):
        disp = by_team_all[["team", "list_cost", "nec", "nec_waste", "savings_pct"]].copy()
        disp["team"] = disp["team"].map(lambda t: _TEAM_LABELS.get(t, t.replace("-", " ").title()))
        disp.columns = ["Team", "List Cost", "NEC", "Waste", "Savings %"]
        for c in ["List Cost", "NEC", "Waste"]:
            disp[c] = disp[c].map("${:,.0f}".format)
        disp["Savings %"] = disp["Savings %"].map(lambda x: f"{x:.1f}%" if x == x else "—")
        st.dataframe(disp, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Commitment utilization
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("Commitment utilization (RI / SP)")
st.caption(
    "Synthetic dataset tuned to demonstrate near-optimal commitment usage behavior; real environments "
    "typically show noisier commitment waste."
)

util = commitment_utilization(df)
if util.empty:
    st.info("No RI or SP rows in the selected data.")
else:
    col_u1, col_u2 = st.columns(2)
    with col_u1:
        fig_util = px.bar(
            util, x="cloud_provider", y="utilization_pct", color="discount_type",
            barmode="group",
            labels={"cloud_provider": "Cloud", "utilization_pct": "Utilization %", "discount_type": "Type"},
            range_y=[0, 110],
            color_discrete_map={"ri": "#7c3aed", "sp": "#0ea5e9"},
        )
        fig_util.add_hline(y=100, line_dash="dash", line_color="gray", opacity=0.5)
        fig_util.update_layout(height=300, margin=dict(t=10, b=40))
        st.plotly_chart(fig_util, use_container_width=True)
    with col_u2:
        u_disp = util[["cloud_provider", "discount_type", "nec_used", "nec_waste", "utilization_pct"]].copy()
        u_disp.columns = ["Cloud", "Type", "NEC Used", "NEC Waste", "Utilization %"]
        u_disp["NEC Used"]  = u_disp["NEC Used"].map("${:,.0f}".format)
        u_disp["NEC Waste"] = u_disp["NEC Waste"].map("${:,.0f}".format)
        u_disp["Utilization %"] = u_disp["Utilization %"].map("{:.1f}%".format)
        st.dataframe(u_disp, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Shared cost allocation
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("Shared cost allocation")
st.caption(
    "Untagged shared infrastructure (VPC, logging, security) is distributed "
    "across teams using the selected strategy."
)

dist = SharedCostDistributor(_CONFIG)

col_ctrl, _ = st.columns([2, 3])
with col_ctrl:
    strategy = st.selectbox(
        "Distribution strategy",
        ["proportional", "even", "weighted"],
        index=0,
        help=(
            "**proportional** — teams that spend more absorb more shared cost\n\n"
            "**even** — equal split regardless of size\n\n"
            "**weighted** — fixed % shares (Platform 30%, Data Eng 25%, Frontend 20%, Backend 15%, ML 10%)"
        ),
    )

candidate_mask   = dist._shared_candidate_mask(df)
n_shared_rows    = candidate_mask.sum()
total_shared_nec = df.loc[candidate_mask, "nec"].sum()

c_s1, c_s2 = st.columns(2)
c_s1.metric("Shared-cost rows", f"{n_shared_rows:,}")
c_s2.metric("Shared NEC",       f"${total_shared_nec:,.0f}")

allocated_df = dist.distribute(df, strategy_override=strategy)
shared_out   = allocated_df[allocated_df["is_shared_cost"]].copy()

if not shared_out.empty:
    team_alloc = (
        shared_out.groupby("allocated_team")
        .agg(allocated_nec=("allocated_nec", "sum"))
        .reset_index()
        .sort_values("allocated_nec", ascending=False)
    )
    team_alloc["team_label"] = team_alloc["allocated_team"].map(_TEAM_LABELS).fillna(
        team_alloc["allocated_team"].str.replace("-", " ").str.title()
    )

    col_pie, col_tbl2 = st.columns([2, 2])
    with col_pie:
        fig_pie = px.pie(
            team_alloc, names="team_label", values="allocated_nec",
            hole=0.4,
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig_pie.update_layout(height=300, margin=dict(t=10, b=10))
        st.plotly_chart(fig_pie, use_container_width=True)
    with col_tbl2:
        ta_disp = team_alloc[["team_label", "allocated_nec"]].copy()
        ta_disp.columns = ["Team", "Allocated NEC"]
        ta_disp["Allocated NEC"] = ta_disp["Allocated NEC"].map("${:,.0f}".format)
        st.dataframe(ta_disp, use_container_width=True, hide_index=True)

    with st.expander("Compare all three strategies"):
        summary = dist.allocation_summary(df)
        if not summary.empty:
            fig_cmp = px.bar(
                summary, x="team", y="share_pct", color="strategy", barmode="group",
                labels={"team": "Team", "share_pct": "Share %", "strategy": "Strategy"},
                color_discrete_map={"proportional": "#2563eb", "even": "#22c55e", "weighted": "#f97316"},
                text="share_pct",
            )
            fig_cmp.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
            fig_cmp.update_layout(height=340, margin=dict(t=10, b=40), yaxis_range=[0, 70])
            st.plotly_chart(fig_cmp, use_container_width=True)

# ---------------------------------------------------------------------------
# Commitment waste detail
# ---------------------------------------------------------------------------

st.markdown("---")
with st.expander("Commitment waste detail (idle RI/SP rows)"):
    waste = commitment_waste_detail(df)
    if waste.empty:
        st.success("No commitment waste rows in the selected data.")
    else:
        waste["nec_waste"] = waste["nec_waste"].map("${:,.4f}".format)
        st.dataframe(waste.head(50), use_container_width=True, hide_index=True)
        if len(waste) > 50:
            st.caption(f"Showing top 50 of {len(waste)} waste rows.")
