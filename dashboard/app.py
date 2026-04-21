"""
Multi-Cloud FinOps Dashboard — Streamlit entrypoint.

Run from repo root:
    streamlit run dashboard/app.py
"""

import sys
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from allocation.nec_model import load_billing_data, nec_by_cloud

_DB = Path(__file__).resolve().parents[1] / "finops_dbt.duckdb"


@st.cache_data(ttl=30, show_spinner=False)
def _available_months() -> list[str]:
    with duckdb.connect(str(_DB), read_only=True) as con:
        rows = con.execute(
            "SELECT DISTINCT billing_month FROM marts.fct_unified_billing ORDER BY 1 DESC"
        ).fetchall()
    return [r[0] for r in rows]

st.set_page_config(
    page_title="Multi-Cloud FinOps",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data(show_spinner="Loading billing data…")
def _load(month: str | None):
    return load_billing_data(_DB, billing_month=month or None)


# ---------------------------------------------------------------------------
# Sidebar — global filters (shared with all pages via session_state)
# ---------------------------------------------------------------------------

st.sidebar.title("☁️ FinOps Dashboard")
st.sidebar.markdown("---")

months = _available_months()
selected_month = st.sidebar.selectbox(
    "Billing month", ["All"] + months, index=1 if months else 0, key="billing_month"
)
month_filter = None if selected_month == "All" else selected_month

selected_cloud = st.sidebar.selectbox(
    "Cloud provider", ["All", "aws", "azure", "gcp"], index=0
)

df_full = _load(month_filter)
df = df_full if selected_cloud == "All" else df_full[df_full["cloud_provider"] == selected_cloud]

st.session_state["df"] = df
st.session_state["month"] = month_filter
st.session_state["cloud"] = selected_cloud

# ---------------------------------------------------------------------------
# Home page
# ---------------------------------------------------------------------------

st.title("Multi-Cloud FinOps Cost Attribution Framework")
st.caption("Research demo — Keerthi Rapolu & Rishika Naha, April 2026")

summary = nec_by_cloud(df)
total_list = summary["list_cost"].sum()
total_nec = summary["nec"].sum()
total_waste = summary["nec_waste"].sum()
savings_pct = (1 - total_nec / total_list) * 100 if total_list else 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("List Cost",        f"${total_list:,.0f}")
c2.metric("Net Effective Cost", f"${total_nec:,.0f}")
c3.metric("Savings",          f"${total_list - total_nec:,.0f}",
          delta=f"{savings_pct:.1f}% off list")
c4.metric("Commitment Waste", f"${total_waste:,.0f}")

st.markdown("---")
st.subheader("Spend by cloud")

fig = go.Figure([
    go.Bar(name="NEC (used)", x=summary["cloud_provider"], y=summary["nec"],       marker_color="#2563eb"),
    go.Bar(name="Waste",      x=summary["cloud_provider"], y=summary["nec_waste"], marker_color="#ef4444"),
    go.Bar(name="Savings",    x=summary["cloud_provider"], y=summary["savings"],   marker_color="#22c55e"),
])
fig.update_layout(
    barmode="stack", xaxis_title="Cloud", yaxis_title="USD",
    legend=dict(orientation="h", y=1.12), height=350, margin=dict(t=10, b=40),
)
st.plotly_chart(fig, use_container_width=True)

st.sidebar.markdown("---")
st.sidebar.caption(f"Rows loaded: {len(df):,}")
