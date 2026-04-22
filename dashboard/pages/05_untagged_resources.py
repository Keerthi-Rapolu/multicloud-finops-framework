"""
Page 5 — Untagged Resources

Shows resources with no team tag, broken down by cloud, service, and account.
Surfaces the NEC at risk and which accounts have the worst tagging gaps.
"""

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

st.set_page_config(page_title="Untagged Resources", layout="wide")
st.title("Untagged Resources")
st.caption(
    "Resources without team tags cannot be attributed and require allocation heuristics. "
    ":information_source: Synthetic demo dataset."
)

df = st.session_state.get("df")
if df is None:
    st.warning("Return to the home page first to load data.")
    st.stop()

untagged = df[~df["is_tagged"].fillna(False)].copy()
tagged   = df[df["is_tagged"].fillna(False)]

# ---------------------------------------------------------------------------
# KPIs — Untagged NEC given dominant visual weight (wider column)
# ---------------------------------------------------------------------------

total_nec        = df["nec"].sum()
untagged_nec     = untagged["nec"].sum()
untagged_rows    = len(untagged)
untagged_pct     = untagged_rows / len(df) * 100 if len(df) else 0
untagged_nec_pct = untagged_nec / total_nec * 100 if total_nec else 0

# Wider centre column makes Untagged NEC the visual anchor
c1, c2, c3, c4 = st.columns([1, 2, 1, 1])
c1.metric("Untagged rows",  f"{untagged_rows:,}",
          delta=f"{untagged_pct:.1f}% of total", delta_color="inverse")
c2.metric("Untagged NEC",   f"${untagged_nec:,.2f}",
          delta=f"{untagged_nec_pct:.1f}% of total NEC unattributed", delta_color="inverse")
c3.metric("Untagged NEC %", f"{untagged_nec_pct:.1f}%", delta_color="inverse")
c4.metric("Tagged NEC",     f"${tagged['nec'].sum():,.2f}")

st.markdown("---")

if untagged.empty:
    st.success("No untagged resources in the selected data.")
    st.stop()

# ---------------------------------------------------------------------------
# By cloud
# ---------------------------------------------------------------------------

st.subheader("Untagged NEC by cloud")
st.caption(":information_source: Synthetic dataset — cloud distribution does not reflect real-world proportions.")

by_cloud = (
    untagged.groupby("cloud_provider")
    .agg(untagged_nec=("nec", "sum"), untagged_rows=("nec", "count"))
    .reset_index()
)
by_cloud["pct_of_untagged"] = (by_cloud["untagged_nec"] / untagged_nec * 100).round(1)

col_l, col_r = st.columns(2)

with col_l:
    fig_cloud = px.bar(
        by_cloud, x="cloud_provider", y="untagged_nec",
        color="cloud_provider",
        color_discrete_map={"aws": "#f97316", "azure": "#2563eb", "gcp": "#22c55e"},
        labels={"cloud_provider": "Cloud", "untagged_nec": "Untagged NEC (USD)"},
        text="pct_of_untagged",
    )
    fig_cloud.update_traces(texttemplate="%{text:.1f}% of untagged", textposition="outside")
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
# By service — with % of total untagged NEC
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
by_svc["pct_of_untagged"] = (by_svc["untagged_nec"] / untagged_nec * 100).round(1)

fig_svc = px.bar(
    by_svc, x="untagged_nec", y="service_name", color="cloud_provider",
    orientation="h",
    color_discrete_map={"aws": "#f97316", "azure": "#2563eb", "gcp": "#22c55e"},
    labels={"untagged_nec": "Untagged NEC (USD)", "service_name": "Service", "cloud_provider": "Cloud"},
    text="pct_of_untagged",
)
fig_svc.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
fig_svc.update_layout(height=420, margin=dict(t=10, b=40), yaxis={"categoryorder": "total ascending"})
st.plotly_chart(fig_svc, use_container_width=True)

# ---------------------------------------------------------------------------
# Untagged NEC trend over time
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("Untagged NEC trend over time")
st.caption("Is the tagging gap improving or getting worse?")

if "usage_date" in untagged.columns:
    trend = (
        untagged.assign(date=pd.to_datetime(untagged["usage_date"]).dt.to_period("D"))
        .groupby(["date", "cloud_provider"])
        .agg(untagged_nec=("nec", "sum"))
        .reset_index()
    )
    trend["date"] = trend["date"].dt.to_timestamp()

    if not trend.empty:
        fig_trend = px.line(
            trend, x="date", y="untagged_nec", color="cloud_provider",
            labels={"date": "Date", "untagged_nec": "Untagged NEC (USD)", "cloud_provider": "Cloud"},
            color_discrete_map={"aws": "#f97316", "azure": "#2563eb", "gcp": "#22c55e"},
        )
        fig_trend.update_layout(height=300, margin=dict(t=10, b=40))
        st.plotly_chart(fig_trend, use_container_width=True)
    else:
        st.info("No trend data available.")
else:
    st.info("usage_date column not available for trend.")

# ---------------------------------------------------------------------------
# Worst-offending accounts — with priority signal
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


def _priority(row) -> str:
    if row["untagged_nec"] >= untagged_nec * 0.15 and row["untagged_pct"] >= 30:
        return "High"
    if row["untagged_nec"] >= untagged_nec * 0.05:
        return "Medium"
    return "Low"


by_acct["Priority"] = by_acct.apply(_priority, axis=1)
by_acct["Owner / team"] = "⚠ owner missing"

display = by_acct[[
    "cloud_provider", "account_id", "total_rows", "untagged_rows",
    "untagged_nec", "untagged_pct", "Priority", "Owner / team",
]].copy()
display.columns = ["Cloud", "Account", "Total rows", "Untagged rows",
                   "Untagged NEC", "Untagged %", "Priority", "Owner / team"]
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
    raw["nec"] = raw["nec"].map("${:,.2f}".format)
    raw.columns = ["Cloud", "Account", "Service", "Category", "Resource", "NEC", "Date"]
    st.dataframe(raw, use_container_width=True, hide_index=True)
    st.caption(f"{len(raw):,} untagged rows total.")
