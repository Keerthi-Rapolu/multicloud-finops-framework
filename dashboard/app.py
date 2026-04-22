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

from allocation.nec_model import load_billing_data, nec_by_cloud, nec_by_team

_DB = Path(__file__).resolve().parents[1] / "finops_dbt.duckdb"


@st.cache_data(ttl=30, show_spinner=False)
def _available_months() -> list[str]:
    if not _DB.exists():
        return []
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

if not months:
    st.error(
        "**No data found.** Run `make pipeline` first to generate synthetic data "
        "and build the DuckDB mart, then relaunch the dashboard."
    )
    st.stop()

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

st.title("AI-Ready Multi-Cloud FinOps Cost Attribution & Allocation Framework")
st.caption("Research demo — Keerthi Rapolu & Rishika Naha, April 2026 · Synthetic dataset for demo purposes")

summary = nec_by_cloud(df)
total_list = summary["list_cost"].sum()
total_nec = summary["nec"].sum()
total_waste = summary["nec_waste"].sum()
savings_pct = (1 - total_nec / total_list) * 100 if total_list else 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("List Cost",        f"${total_list:,.0f}")
c2.metric("Net Effective Cost", f"${total_nec:,.0f}")
c3.metric("Savings (vs List Cost)", f"${total_list - total_nec:,.0f}",
          delta=f"{savings_pct:.1f}% off list")
c4.metric("Commitment Waste", f"${total_waste:,.0f}")

st.markdown("---")
st.subheader("Spend by cloud")
st.caption(":information_source: Synthetic dataset — cloud distribution does not reflect real-world proportions.")

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

# ---------------------------------------------------------------------------
# Executive health summary
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader("Overall financial health")

waste_pct      = total_waste / total_nec * 100 if total_nec else 0
is_tagged      = df["is_tagged"].fillna(False)
untagged_nec   = df.loc[~is_tagged, "nec"].sum()
untagged_pct   = untagged_nec / total_nec * 100 if total_nec else 0

# Health signals
signals = []
if waste_pct >= 10:
    signals.append(f":red_circle: **Commitment waste is high** — {waste_pct:.1f}% of NEC is idle RI/SP capacity (>${total_waste:,.0f}). Review Team Allocation for per-account detail.")
elif waste_pct >= 5:
    signals.append(f":orange_circle: **Commitment waste is moderate** — {waste_pct:.1f}% of NEC is unused (>${total_waste:,.0f}). Monitor for increase.")
else:
    signals.append(f":green_circle: **Commitment utilization is healthy** — waste is {waste_pct:.1f}% of NEC.")

if untagged_pct >= 20:
    signals.append(f":red_circle: **Tagging coverage is poor** — {untagged_pct:.1f}% of NEC (${untagged_nec:,.0f}) is unattributed. Enforce tag policies immediately.")
elif untagged_pct >= 10:
    signals.append(f":orange_circle: **Tagging gap requires attention** — {untagged_pct:.1f}% of NEC (${untagged_nec:,.0f}) cannot be directly allocated.")
else:
    signals.append(f":green_circle: **Tagging coverage is acceptable** — {untagged_pct:.1f}% of NEC is unattributed.")

try:
    _team_labels = {"data-eng": "Data Engineering", "platform": "Platform", "frontend": "Frontend", "backend": "Backend", "ml": "Machine Learning"}
    by_team = nec_by_team(df)
    team_totals = by_team.groupby("team")["nec"].sum()
    top_team_key = team_totals.idxmax()
    top_team_label = _team_labels.get(top_team_key, top_team_key.replace("-", " ").title())
    top_pct = team_totals.max() / total_nec * 100
    signals.append(f":blue_circle: **{top_team_label}** is the largest cost centre — {top_pct:.0f}% of total NEC (${team_totals.max():,.0f}).")
except Exception:
    pass

for s in signals:
    st.markdown(s)

st.markdown("---")
st.caption("Navigate the pages in the sidebar to drill into each dimension. Start with **Overview** for trends, then **Tagging Coverage** and **Untagged Resources** to address attribution gaps.")

st.sidebar.markdown("---")
st.sidebar.caption(f"Rows loaded: {len(df):,}")
