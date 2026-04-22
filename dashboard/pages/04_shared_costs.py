"""
Page 4 — Shared Costs

Shows shared-infrastructure cost distribution using all three strategies
(proportional, even, weighted) side-by-side. Lets you pick a strategy and
see how each team's allocation changes.
"""

import sys
from pathlib import Path

import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from allocation.shared_cost import SharedCostDistributor

_CONFIG = Path(__file__).resolve().parents[2] / "config" / "shared_cost_weights.yml"

st.set_page_config(page_title="Shared Costs", layout="wide")
st.title("Shared Cost Distribution")
st.caption(
    "Shared infrastructure rows (untagged VPC, logging, security services) are "
    "spread across teams using the selected strategy."
)

df = st.session_state.get("df")
if df is None:
    st.warning("Return to the home page first to load data.")
    st.stop()

dist = SharedCostDistributor(_CONFIG)

# ---------------------------------------------------------------------------
# Strategy selector
# ---------------------------------------------------------------------------

col_ctrl1, col_ctrl2 = st.columns([2, 3])
with col_ctrl1:
    strategy = st.selectbox(
        "Distribution strategy",
        ["proportional", "even", "weighted"],
        index=0,
        help=(
            "**proportional** — teams that spend more absorb more shared cost\n\n"
            "**even** — equal split regardless of size\n\n"
            "**weighted** — fixed % shares by business unit, defined in `config/shared_cost_weights.yml`: "
            "Platform 30%, Data Engineering 25%, Frontend 20%, Backend 15%, ML 10%. "
            "Use this when cost ownership is governed by headcount, SLA contract, or negotiated budget."
        ),
    )

with col_ctrl1:
    strategy_notes = {
        "proportional": "Each team's share scales with its total NEC — bigger spenders absorb more shared infrastructure cost.",
        "even":         "Shared cost is split equally across all teams regardless of size or consumption.",
        "weighted":     "Shares are fixed by business unit weight in `config/shared_cost_weights.yml` "
                        "(Platform 30%, Data Engineering 25%, Frontend 20%, Backend 15%, ML 10%). "
                        "Appropriate when cost ownership is governed by headcount or negotiated SLA.",
    }
    st.caption(f":bulb: {strategy_notes[strategy]}")

_STRATEGY_RECS = {
    "proportional": "**Recommendation:** Adopt proportional allocation for production environments — it creates natural cost accountability by tying shared-infra charges to each team's actual consumption.",
    "even":         "**Recommendation:** Even split is appropriate for small, similarly-sized teams. If team size diverges, switch to proportional to avoid over-charging smaller teams.",
    "weighted":     "**Recommendation:** Review `config/shared_cost_weights.yml` quarterly to keep weights aligned with actual headcount and budget agreements.",
}
st.info(_STRATEGY_RECS[strategy])

# ---------------------------------------------------------------------------
# Run distribution
# ---------------------------------------------------------------------------

allocated_df = dist.distribute(df, strategy_override=strategy)
shared_mask  = allocated_df["is_shared_cost"]

candidate_mask   = dist._shared_candidate_mask(df)
n_shared_rows    = candidate_mask.sum()
total_shared_nec = df.loc[candidate_mask, "nec"].sum()

with col_ctrl2:
    cs1, cs2 = st.columns(2)
    cs1.metric("Shared-cost rows identified", f"{n_shared_rows:,}")
    cs2.metric("Total shared NEC",            f"${total_shared_nec:,.2f}")

st.markdown("---")

# ---------------------------------------------------------------------------
# Strategy comparison — all three side-by-side
# ---------------------------------------------------------------------------

st.subheader("Strategy comparison — team shares")

summary = dist.allocation_summary(df)
if summary.empty:
    st.info("No shared-cost candidates found in the selected data.")
    st.stop()

fig_cmp = px.bar(
    summary, x="team", y="share_pct", color="strategy", barmode="group",
    labels={"team": "Team", "share_pct": "Share %", "strategy": "Strategy"},
    color_discrete_map={
        "proportional": "#2563eb",
        "even":         "#22c55e",
        "weighted":     "#f97316",
    },
    text="share_pct",
)
fig_cmp.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
fig_cmp.update_layout(height=360, margin=dict(t=10, b=40), yaxis_range=[0, 70])
st.plotly_chart(fig_cmp, use_container_width=True)

# ---------------------------------------------------------------------------
# Allocated NEC under chosen strategy
# ---------------------------------------------------------------------------

st.markdown("---")
st.subheader(f"Allocated NEC under '{strategy}' strategy")

shared_out = allocated_df[shared_mask].copy()
if shared_out.empty:
    st.info("No shared-cost rows to display for the current selection.")
else:
    team_alloc = (
        shared_out.groupby("allocated_team")
        .agg(allocated_nec=("allocated_nec", "sum"))
        .reset_index()
        .rename(columns={"allocated_team": "team"})
        .sort_values("allocated_nec", ascending=False)
    )

    col_pie, col_tbl = st.columns([2, 2])

    with col_pie:
        fig_pie = px.pie(
            team_alloc, names="team", values="allocated_nec",
            hole=0.4,
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig_pie.update_layout(height=320, margin=dict(t=10, b=10))
        st.plotly_chart(fig_pie, use_container_width=True)

    with col_tbl:
        team_alloc["allocated_nec"] = team_alloc["allocated_nec"].map("${:,.2f}".format)
        team_alloc.columns = ["Team", "Allocated NEC"]
        st.dataframe(team_alloc, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Shared rows detail
# ---------------------------------------------------------------------------

st.markdown("---")
with st.expander("Shared-cost rows detail"):
    raw_shared = df[candidate_mask][
        ["cloud_provider", "service_name", "account_id", "nec", "usage_date"]
    ].copy()
    raw_shared["nec"] = raw_shared["nec"].map("${:,.2f}".format)
    raw_shared.columns = ["Cloud", "Service", "Account", "NEC", "Date"]
    st.dataframe(raw_shared, use_container_width=True, hide_index=True)
