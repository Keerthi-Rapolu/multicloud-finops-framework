"""
Page 5 — Untagged Resources

Shows resources with no team tag, broken down by cloud, service, and account.
Surfaces the NEC at risk and which accounts have the worst tagging gaps.
"""

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

st.set_page_config(page_title="Untagged Resources", layout="wide")
st.title("Untagged Resources")
st.caption(
    "Untagged rows have no `tag_team` value. Their NEC cannot be directly "
    "attributed to a team — they fall back to heuristics or shared-cost spreading."
)

df = st.session_state.get("df")
if df is None:
    st.warning("Return to the home page first to load data.")
    st.stop()

untagged = df[~df["is_tagged"].fillna(False)].copy()
tagged   = df[df["is_tagged"].fillna(False)]

# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------

total_nec      = df["nec"].sum()
untagged_nec   = untagged["nec"].sum()
untagged_rows  = len(untagged)
untagged_pct   = untagged_rows / len(df) * 100 if len(df) else 0
untagged_nec_pct = untagged_nec / total_nec * 100 if total_nec else 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("Untagged rows",    f"{untagged_rows:,}", delta=f"{untagged_pct:.1f}% of total", delta_color="inverse")
c2.metric("Untagged NEC",     f"${untagged_nec:,.2f}")
c3.metric("Untagged NEC %",   f"{untagged_nec_pct:.1f}%", delta_color="inverse")
c4.metric("Tagged NEC",       f"${tagged['nec'].sum():,.2f}")

st.markdown("---")

if untagged.empty:
    st.success("No untagged resources in the selected data.")
    st.stop()

# ---------------------------------------------------------------------------
# By cloud
# ---------------------------------------------------------------------------

st.subheader("Untagged NEC by cloud")

by_cloud = (
    untagged.groupby("cloud_provider")
    .agg(untagged_nec=("nec", "sum"), untagged_rows=("nec", "count"))
    .reset_index()
)

col_l, col_r = st.columns(2)

with col_l:
    fig_cloud = px.bar(
        by_cloud, x="cloud_provider", y="untagged_nec",
        color="cloud_provider",
        color_discrete_map={"aws": "#f97316", "azure": "#2563eb", "gcp": "#22c55e"},
        labels={"cloud_provider": "Cloud", "untagged_nec": "Untagged NEC (USD)"},
        text="untagged_nec",
    )
    fig_cloud.update_traces(texttemplate="$%{text:,.2f}", textposition="outside")
    fig_cloud.update_layout(height=300, showlegend=False, margin=dict(t=10, b=40))
    st.plotly_chart(fig_cloud, use_container_width=True)

with col_r:
    fig_rows = px.bar(
        by_cloud, x="cloud_provider", y="untagged_rows",
        color="cloud_provider",
        color_discrete_map={"aws": "#f97316", "azure": "#2563eb", "gcp": "#22c55e"},
        labels={"cloud_provider": "Cloud", "untagged_rows": "Untagged rows"},
        text="untagged_rows",
    )
    fig_rows.update_traces(texttemplate="%{text:,}", textposition="outside")
    fig_rows.update_layout(height=300, showlegend=False, margin=dict(t=10, b=40))
    st.plotly_chart(fig_rows, use_container_width=True)

# ---------------------------------------------------------------------------
# By service — where is the untagged cost hiding?
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("Untagged NEC by service")

by_svc = (
    untagged.groupby(["cloud_provider", "service_name"])
    .agg(untagged_nec=("nec", "sum"), rows=("nec", "count"))
    .reset_index()
    .sort_values("untagged_nec", ascending=False)
    .head(20)
)

fig_svc = px.bar(
    by_svc, x="untagged_nec", y="service_name", color="cloud_provider",
    orientation="h",
    color_discrete_map={"aws": "#f97316", "azure": "#2563eb", "gcp": "#22c55e"},
    labels={"untagged_nec": "Untagged NEC (USD)", "service_name": "Service", "cloud_provider": "Cloud"},
)
fig_svc.update_layout(height=420, margin=dict(t=10, b=40), yaxis={"categoryorder": "total ascending"})
st.plotly_chart(fig_svc, use_container_width=True)

# ---------------------------------------------------------------------------
# By account — which accounts have the worst tagging discipline?
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("Worst-offending accounts")

by_acct = (
    df.groupby(["cloud_provider", "account_id"])
    .apply(lambda g: pd.Series({
        "untagged_nec":  g.loc[~g["is_tagged"].fillna(False), "nec"].sum(),
        "total_nec":     g["nec"].sum(),
        "untagged_rows": (~g["is_tagged"].fillna(False)).sum(),
        "total_rows":    len(g),
    }))
    .reset_index()
)
by_acct["untagged_pct"] = (by_acct["untagged_nec"] / by_acct["total_nec"].replace(0, float("nan")) * 100).round(1)
by_acct = by_acct[by_acct["untagged_nec"] > 0].sort_values("untagged_nec", ascending=False)

display = by_acct[["cloud_provider", "account_id", "total_rows", "untagged_rows", "untagged_nec", "untagged_pct"]].copy()
display.columns = ["Cloud", "Account", "Total rows", "Untagged rows", "Untagged NEC", "Untagged %"]
display["Untagged NEC"] = display["Untagged NEC"].map("${:,.2f}".format)
display["Untagged %"]   = display["Untagged %"].map("{:.1f}%".format)
st.dataframe(display, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Raw untagged rows
# ---------------------------------------------------------------------------

st.markdown("---")
with st.expander("Raw untagged rows"):
    raw = untagged[["cloud_provider", "account_id", "service_name", "service_category",
                     "resource_id", "nec", "usage_date"]].copy()
    raw["nec"] = raw["nec"].map("${:,.4f}".format)
    raw.columns = ["Cloud", "Account", "Service", "Category", "Resource", "NEC", "Date"]
    st.dataframe(raw, use_container_width=True, hide_index=True)
    st.caption(f"{len(raw):,} untagged rows total.")
