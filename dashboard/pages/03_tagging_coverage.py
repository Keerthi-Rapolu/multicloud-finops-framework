"""
Page 3 — Tagging Coverage

% of resources tagged with a team label, broken down by cloud, service, and account.
Untagged resources represent attribution risk — they can't be charged to a team.
"""

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

st.set_page_config(page_title="Tagging Coverage", layout="wide")
st.title("Tagging Coverage")
st.caption(
    "Resources without team tags cannot be attributed and require allocation heuristics. "
    "A resource is 'tagged' when `tag_team` is non-null."
)

df = st.session_state.get("df")
if df is None:
    st.warning("Return to the home page first to load data.")
    st.stop()


def _coverage(frame, group_col: str) -> pd.DataFrame:
    agg = (
        frame.assign(is_tagged=frame["is_tagged"].fillna(False))
        .groupby(group_col)
        .apply(
            lambda g: pd.Series({
                "total_rows": len(g),
                "tagged_rows": g["is_tagged"].sum(),
                "tagged_nec": g.loc[g["is_tagged"], "nec"].sum(),
                "total_nec": g["nec"].sum(),
            }),
            include_groups=False,
        )
        .reset_index()
    )
    agg["tagged_row_pct"] = (agg["tagged_rows"] / agg["total_rows"] * 100).round(1)
    agg["tagged_nec_pct"] = (agg["tagged_nec"] / agg["total_nec"].replace(0, float("nan")) * 100).round(1)
    return agg


# ---------------------------------------------------------------------------
# Overall KPIs — Untagged NEC made visually prominent
# ---------------------------------------------------------------------------

is_tagged = df["is_tagged"].fillna(False)
overall_row_pct = is_tagged.mean() * 100
overall_nec_pct = df.loc[is_tagged, "nec"].sum() / df["nec"].sum() * 100 if df["nec"].sum() else 0
untagged_nec = df.loc[~is_tagged, "nec"].sum()
untagged_nec_pct = 100 - overall_nec_pct

c1, c2, c3 = st.columns([1, 1, 1])
c1.metric("Tagged rows",          f"{overall_row_pct:.1f}%")
c2.metric("Tagged NEC",           f"{overall_nec_pct:.1f}%")
c3.metric("Untagged NEC at risk", f"${untagged_nec:,.2f}",
          delta=f"{untagged_nec_pct:.1f}% unattributed", delta_color="inverse")

if untagged_nec_pct >= 10:
    st.warning(
        f":warning: **{untagged_nec_pct:.1f}% of NEC (${untagged_nec:,.0f}) is untagged** — "
        "cannot be directly charged to a team without heuristic allocation."
    )

st.markdown("---")

# ---------------------------------------------------------------------------
# By cloud
# ---------------------------------------------------------------------------

st.subheader("Coverage by cloud")

by_cloud = _coverage(df, "cloud_provider")

col_l, col_r = st.columns(2)
with col_l:
    fig_row = px.bar(
        by_cloud, x="cloud_provider", y="tagged_row_pct",
        labels={"cloud_provider": "Cloud", "tagged_row_pct": "Tagged rows %"},
        color="cloud_provider",
        color_discrete_map={"aws": "#f97316", "azure": "#2563eb", "gcp": "#22c55e"},
        range_y=[0, 110], text="tagged_row_pct",
    )
    fig_row.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
    fig_row.update_layout(height=300, showlegend=False, margin=dict(t=10, b=40))
    st.plotly_chart(fig_row, use_container_width=True)

with col_r:
    fig_nec = px.bar(
        by_cloud, x="cloud_provider", y="tagged_nec_pct",
        labels={"cloud_provider": "Cloud", "tagged_nec_pct": "Tagged NEC %"},
        color="cloud_provider",
        color_discrete_map={"aws": "#f97316", "azure": "#2563eb", "gcp": "#22c55e"},
        range_y=[0, 110], text="tagged_nec_pct",
    )
    fig_nec.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
    fig_nec.update_layout(height=300, showlegend=False, margin=dict(t=10, b=40))
    st.plotly_chart(fig_nec, use_container_width=True)

# ---------------------------------------------------------------------------
# By service category
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("Coverage by service category")

by_svc = _coverage(df, "service_category").sort_values("tagged_nec_pct")
fig_svc = px.bar(
    by_svc, x="tagged_nec_pct", y="service_category", orientation="h",
    labels={"tagged_nec_pct": "Tagged NEC %", "service_category": "Service Category"},
    color="tagged_nec_pct",
    color_continuous_scale="RdYlGn",
    range_color=[0, 100],
    text="tagged_nec_pct",
)
fig_svc.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
fig_svc.update_layout(height=320, coloraxis_showscale=False, margin=dict(t=10, b=40))
st.plotly_chart(fig_svc, use_container_width=True)

# ---------------------------------------------------------------------------
# Top untagged accounts — who needs to act?
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("Top untagged accounts")
st.caption("Accounts with the highest untagged NEC — these owners need to apply team tags.")

untagged_df = df[~df["is_tagged"].fillna(False)]
if untagged_df.empty:
    st.success("No untagged accounts.")
else:
    top_acct = (
        untagged_df.groupby(["cloud_provider", "account_id"])
        .agg(untagged_nec=("nec", "sum"), untagged_rows=("nec", "count"))
        .reset_index()
        .sort_values("untagged_nec", ascending=False)
        .head(10)
    )
    top_acct["untagged_nec_pct"] = (top_acct["untagged_nec"] / untagged_nec * 100).round(1)
    top_acct["Owner / team"] = "⚠ owner missing"

    disp_acct = top_acct[["cloud_provider", "account_id", "untagged_rows",
                            "untagged_nec", "untagged_nec_pct", "Owner / team"]].copy()
    disp_acct.columns = ["Cloud", "Account", "Untagged rows", "Untagged NEC", "% of untagged", "Owner / team"]
    disp_acct["Untagged NEC"] = disp_acct["Untagged NEC"].map("${:,.2f}".format)
    disp_acct["% of untagged"] = disp_acct["% of untagged"].map("{:.1f}%".format)
    st.dataframe(disp_acct, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Top services with missing tags
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("Top services with missing tags")
st.caption("Services that contribute the most to unattributed NEC.")

if not untagged_df.empty:
    top_svc = (
        untagged_df.groupby(["cloud_provider", "service_name"])
        .agg(untagged_nec=("nec", "sum"), untagged_rows=("nec", "count"))
        .reset_index()
        .sort_values("untagged_nec", ascending=False)
        .head(10)
    )
    top_svc["pct_of_untagged"] = (top_svc["untagged_nec"] / untagged_nec * 100).round(1)

    fig_top_svc = px.bar(
        top_svc, x="untagged_nec", y="service_name", color="cloud_provider",
        orientation="h",
        color_discrete_map={"aws": "#f97316", "azure": "#2563eb", "gcp": "#22c55e"},
        labels={
            "untagged_nec": "Untagged NEC (USD)",
            "service_name": "Service",
            "cloud_provider": "Cloud",
        },
        text="pct_of_untagged",
    )
    fig_top_svc.update_traces(texttemplate="%{text:.1f}% of untagged", textposition="outside")
    fig_top_svc.update_layout(
        height=360, margin=dict(t=10, b=40),
        yaxis={"categoryorder": "total ascending"},
    )
    st.plotly_chart(fig_top_svc, use_container_width=True)

# ---------------------------------------------------------------------------
# By account / subscription / project
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("Coverage by account")

by_acct = _coverage(df, "account_id").sort_values("tagged_nec_pct")
by_acct_disp = by_acct[["account_id", "total_rows", "tagged_rows", "tagged_row_pct", "total_nec", "tagged_nec_pct"]].copy()
by_acct_disp.columns = ["Account", "Total rows", "Tagged rows", "Row %", "Total NEC", "NEC %"]
by_acct_disp["Total NEC"] = by_acct_disp["Total NEC"].map("${:,.2f}".format)
by_acct_disp["Row %"]     = by_acct_disp["Row %"].map("{:.1f}%".format)
by_acct_disp["NEC %"]     = by_acct_disp["NEC %"].map("{:.1f}%".format)
st.dataframe(by_acct_disp, use_container_width=True, hide_index=True)
