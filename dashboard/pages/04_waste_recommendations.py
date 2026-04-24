"""
Page 4 — Waste & Recommendations

Full waste-to-action pipeline: detects cost waste, explains root causes,
and surfaces prioritised recommendations with savings estimates and risk scores.
Flow: Problem → Root Cause → Action → Savings → Risk
"""

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from intelligence.impact_simulator import run as simulate
from intelligence.waste_detector import run as detect_waste
from dashboard._shared import (
    ACTION_OPS,
    COLOR_BLOCKER,
    COLOR_INEFFICIENCY,
    COLOR_OPTIMIZED,
    diagnose,
    enrich_recommendation,
    render_headline,
    render_priority_badge,
)

_TYPE_COLORS = {
    "unused_commitment":        "#ef4444",
    "idle_compute":             "#f97316",
    "zombie_resource":          "#8b5cf6",
    "underutilized_commitment": "#eab308",
}
_TYPE_LABELS = {
    "unused_commitment":        "Unused Commitment",
    "idle_compute":             "Idle Compute",
    "zombie_resource":          "Zombie Resource",
    "underutilized_commitment": "Underutilised Commitment",
}
_ACTION_COLORS = {
    "release_commitment": "#2563eb",
    "resize_down":        "#f97316",
    "remove_resource":    "#8b5cf6",
}
_ACTION_LABELS = {
    "release_commitment": "Release Commitment",
    "resize_down":        "Resize Down",
    "remove_resource":    "Remove Resource",
}
_TEAM_LABELS = {
    "data-eng":    "Data Engineering",
    "platform":    "Platform",
    "frontend":    "Frontend",
    "backend":     "Backend",
    "ml":          "Machine Learning",
    "unattributed":"Unattributed",
}

st.set_page_config(page_title="Waste & Recommendations", layout="wide")
st.title("Waste & Recommendations")
st.caption("Where is cost leaking, and what should you do about it?")

df = st.session_state.get("df")
if df is None:
    st.warning("Return to the home page first to load data.")
    st.stop()

# Executive headline (Critical #1)
diag = diagnose(df)
render_headline(diag)

# ---------------------------------------------------------------------------
# Run pipeline (cached per DataFrame identity)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Scanning for waste and simulating impact…")
def _run_pipeline(df_hash: int, _df: pd.DataFrame):
    findings = detect_waste(_df)
    recs = simulate(findings)
    return findings, recs

# Content-based hash so cache hits when the data is unchanged
# (id(df) changes on every reload, which defeats the cache).
_df_hash = int(pd.util.hash_pandas_object(df, index=True).sum())
findings, recs = _run_pipeline(_df_hash, df)

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------

st.sidebar.markdown("---")
st.sidebar.subheader("Page filters")
st.sidebar.caption("Drill-down only — the global month/cloud filters still apply.")

all_types  = sorted({f["waste_type"]     for f in findings}) if findings else []
all_teams  = sorted({f["allocated_team"] for f in findings}) if findings else []
all_clouds = sorted({f["cloud_provider"] for f in findings}) if findings else []

sel_types  = st.sidebar.multiselect("Waste type", all_types,  default=all_types)
sel_teams  = st.sidebar.multiselect("Team",        all_teams,  default=all_teams)
sel_clouds = st.sidebar.multiselect("Cloud",       all_clouds, default=all_clouds)
sel_risks  = st.sidebar.multiselect("Risk level",  ["Low", "Medium", "High"], default=["Low", "Medium", "High"])

filtered_findings = [
    f for f in findings
    if f["waste_type"]     in sel_types
    and f["allocated_team"] in sel_teams
    and f["cloud_provider"] in sel_clouds
] if findings else []

scope_df = df[
    df["allocated_team"].isin(sel_teams)
    & df["cloud_provider"].isin(sel_clouds)
].copy()

filtered_recs = [
    r for r in recs
    if r["allocated_team"]      in sel_teams
    and r.get("cloud_provider") in sel_clouds
    and r.get("waste_type")     in sel_types
    and r["risk"]               in sel_risks
] if recs else []

# ---------------------------------------------------------------------------
# KPI row
# ---------------------------------------------------------------------------

total_waste_detected = sum(
    f["nec_waste"] if f["nec_waste"] > 0 else f["nec_used"] for f in filtered_findings
) if filtered_findings else 0.0

total_nec = scope_df["nec"].sum()
waste_pct = total_waste_detected / total_nec * 100 if total_nec else 0
total_savings  = sum(r["estimated_savings"] for r in filtered_recs)
n_quick_wins   = sum(1 for r in filtered_recs if r["risk"] == "Low")

ck1, ck2, ck3, ck4 = st.columns(4)
ck1.metric("Waste Detected",      f"${total_waste_detected:,.0f}",
           delta=f"{waste_pct:.1f}% of NEC", delta_color="inverse")
ck2.metric("Savings Opportunity", f"${total_savings:,.0f}")
ck3.metric("Recommendations",     str(len(filtered_recs)))
ck4.metric("Low-Risk Quick Wins", str(n_quick_wins))

# Enterprise scale projection — makes small numbers meaningful
if total_nec > 0 and waste_pct > 0:
    enterprise_monthly  = 10_000_000
    enterprise_savings  = enterprise_monthly * (waste_pct / 100) * 0.85
    st.info(
        f":scales: **Enterprise scale projection** — at $10M/month cloud spend, "
        f"this {waste_pct:.1f}% waste rate = **${enterprise_savings:,.0f}/month** recoverable. "
        f"This environment: **${total_savings:,.0f}/month** identified opportunity."
    )

if not filtered_findings:
    st.success(
        "No waste detected in the selected filters. "
        "Try loading more months or broadening the sidebar filters."
    )
    st.stop()

st.markdown("---")

# ---------------------------------------------------------------------------
# Step 1 — Where is the waste?
# ---------------------------------------------------------------------------

st.subheader("Step 1 — Where is the waste?")

fdf = pd.DataFrame(filtered_findings)
fdf["cost_impact"] = fdf.apply(
    lambda r: r["nec_waste"] if r["nec_waste"] > 0 else r["nec_used"], axis=1
)
fdf["team_label"] = (
    fdf["allocated_team"].map(_TEAM_LABELS)
    .fillna(fdf["allocated_team"].str.replace("-", " ").str.title())
)

by_type = (
    fdf.groupby("waste_type")["cost_impact"]
    .sum().reset_index()
    .sort_values("cost_impact", ascending=True)
)
by_type["label"] = by_type["waste_type"].map(_TYPE_LABELS).fillna(by_type["waste_type"])

col_chart, col_actions = st.columns([3, 2])

with col_chart:
    fig_type = px.bar(
        by_type, x="cost_impact", y="label", orientation="h",
        color="waste_type",
        color_discrete_map=_TYPE_COLORS,
        labels={"cost_impact": "NEC Impact (USD)", "label": "Waste Type"},
        text=by_type["cost_impact"].map("${:,.0f}".format),
    )
    fig_type.update_traces(textposition="outside")
    fig_type.update_layout(height=240, margin=dict(t=10, b=40, r=120),
                           showlegend=False, yaxis_title=None)
    st.plotly_chart(fig_type, use_container_width=True)
    st.caption(
        "**Unused Commitment** — billing-confirmed idle RI/SP (highest confidence).  "
        "**Idle Compute** — very low cost-per-vCPU-hour proxy.  "
        "**Zombie Resource** — <$2/month total spend.  "
        "**Underutilised** — <70% RI/SP utilisation ratio."
    )

with col_actions:
    _action_map = {
        "unused_commitment":        "Release / downsize the commitment",
        "underutilized_commitment": "Partially release commitment",
        "idle_compute":             "Right-size or suspend instance",
        "zombie_resource":          "Decommission and delete",
    }
    for wtype in ["unused_commitment", "underutilized_commitment", "idle_compute", "zombie_resource"]:
        group = [f for f in filtered_findings if f["waste_type"] == wtype]
        if not group:
            continue
        total = sum(f["nec_waste"] if f["nec_waste"] > 0 else f["nec_used"] for f in group)
        label = _TYPE_LABELS.get(wtype, wtype)
        st.markdown(
            f"**{label}** — {len(group)} finding{'s' if len(group) != 1 else ''}  \n"
            f"NEC impact: **${total:,.0f}**  \n"
            f":wrench: {_action_map.get(wtype, 'Review')}"
        )
        st.markdown("")

# ---------------------------------------------------------------------------
# Cross-cloud inefficiency comparison (Medium #8)
# Shows which cloud is leaking the most *relative to its NEC share* — a small
# cloud can look fine in $ but catastrophic in efficiency terms.
# ---------------------------------------------------------------------------
st.markdown("---")

cloud_nec = scope_df.groupby("cloud_provider")["nec"].sum().rename("nec")
cloud_waste_map = fdf.groupby("cloud_provider")["cost_impact"].sum().rename("waste")
cross = pd.concat([cloud_nec, cloud_waste_map], axis=1).fillna(0).reset_index()
cross["waste_pct"] = (cross["waste"] / cross["nec"].replace(0, float("nan")) * 100).fillna(0).round(1)
cross["cloud_label"] = cross["cloud_provider"].str.upper()

st.subheader("Cross-cloud inefficiency")
st.caption(
    "Compares absolute waste with waste-as-a-share-of-NEC. A small cloud can still "
    "be the most *inefficient* — this view surfaces that."
)

col_xc1, col_xc2 = st.columns(2)
with col_xc1:
    fig_xc_abs = px.bar(
        cross.sort_values("waste", ascending=True),
        x="waste", y="cloud_label", orientation="h",
        color="cloud_provider",
        color_discrete_map={"aws": "#f97316", "azure": "#2563eb", "gcp": "#22c55e"},
        labels={"waste": "Waste (USD)", "cloud_label": "Cloud"},
        text=cross.sort_values("waste", ascending=True)["waste"].map("${:,.0f}".format),
    )
    fig_xc_abs.update_traces(textposition="outside")
    fig_xc_abs.update_layout(height=200, margin=dict(t=10, b=30, r=100),
                             showlegend=False, yaxis_title=None)
    st.plotly_chart(fig_xc_abs, use_container_width=True)
    st.caption("**Absolute** — dollar leakage.")

with col_xc2:
    fig_xc_rel = px.bar(
        cross.sort_values("waste_pct", ascending=True),
        x="waste_pct", y="cloud_label", orientation="h",
        color="waste_pct",
        color_continuous_scale=[[0, COLOR_OPTIMIZED], [0.5, COLOR_INEFFICIENCY], [1, COLOR_BLOCKER]],
        range_color=[0, max(10.0, cross["waste_pct"].max())],
        labels={"waste_pct": "Waste % of NEC", "cloud_label": "Cloud"},
        text=cross.sort_values("waste_pct", ascending=True)["waste_pct"].map("{:.1f}%".format),
    )
    fig_xc_rel.update_traces(textposition="outside")
    fig_xc_rel.update_layout(height=200, margin=dict(t=10, b=30, r=80),
                             coloraxis_showscale=False, yaxis_title=None)
    st.plotly_chart(fig_xc_rel, use_container_width=True)
    st.caption("**Relative** — efficiency; a lower bar = healthier cloud.")

# Callout: worst cloud by relative efficiency
if not cross.empty and cross["waste_pct"].max() > 0:
    worst = cross.loc[cross["waste_pct"].idxmax()]
    if worst["waste_pct"] >= 5:
        st.info(
            f":mag: **Least efficient cloud: {worst['cloud_label']}** — "
            f"{worst['waste_pct']:.1f}% of NEC is waste (${worst['waste']:,.0f}). "
            "Prioritise commitment review here even if it isn't the largest in $ terms."
        )

st.markdown("---")

# Waste by team (stacked bar)
by_team_type = (
    fdf.groupby(["team_label", "waste_type"])["cost_impact"]
    .sum().reset_index()
)
fig_team = px.bar(
    by_team_type, x="team_label", y="cost_impact", color="waste_type",
    color_discrete_map=_TYPE_COLORS,
    labels={"cost_impact": "NEC Impact (USD)", "team_label": "Team", "waste_type": "Waste Type"},
    category_orders={"waste_type": list(_TYPE_COLORS.keys())},
)
fig_team.update_layout(
    height=300, margin=dict(t=10, b=60), xaxis_title=None,
    legend_title_text="Waste Type",
    legend=dict(orientation="h", y=-0.25),
)
st.plotly_chart(fig_team, use_container_width=True)

# Findings table
with st.expander("All waste findings"):
    tbl = fdf.sort_values("cost_impact", ascending=False).reset_index(drop=True)
    disp_tbl = pd.DataFrame({
        "Resource":   tbl["resource_id"].apply(lambda x: ("…" + str(x)[-35:]) if len(str(x)) > 38 else str(x)),
        "Cloud":      tbl["cloud_provider"].str.upper(),
        "Team":       tbl["team_label"],
        "Waste Type": tbl["waste_type"].map(_TYPE_LABELS).fillna(tbl["waste_type"]),
        "NEC Impact": tbl["cost_impact"].map("${:,.0f}".format),
        "Confidence": tbl["confidence"].map("{:.0%}".format),
    })
    st.dataframe(disp_tbl, use_container_width=True, hide_index=True)

st.markdown("---")

# ---------------------------------------------------------------------------
# Step 2 — What actions recover the most?
# ---------------------------------------------------------------------------

st.subheader("Step 2 — What actions recover the most?")

if not filtered_recs:
    st.info("No recommendations match the current filters.")
else:
    # Enrich every recommendation with Owner / Automation / SLA (Critical #4, Add #4)
    enriched_recs = [enrich_recommendation(r) for r in filtered_recs]
    rdf = pd.DataFrame(enriched_recs)
    rdf["action_label"] = rdf["action"].map(_ACTION_LABELS).fillna(rdf["action"])
    rdf["team_label"]   = (
        rdf["allocated_team"].map(_TEAM_LABELS)
        .fillna(rdf["allocated_team"].str.replace("-", " ").str.title())
    )

    by_action = (
        rdf.groupby(["action", "action_label"])["estimated_savings"]
        .sum().reset_index()
        .sort_values("estimated_savings", ascending=True)
    )
    fig_action = px.bar(
        by_action, x="estimated_savings", y="action_label", orientation="h",
        color="action",
        color_discrete_map=_ACTION_COLORS,
        labels={"estimated_savings": "Estimated Savings (USD)", "action_label": "Action"},
        text=by_action["estimated_savings"].map("${:,.0f}".format),
    )
    fig_action.update_traces(textposition="outside")
    fig_action.update_layout(height=200, margin=dict(t=10, b=40, r=120),
                             showlegend=False, yaxis_title=None)
    st.plotly_chart(fig_action, use_container_width=True)
    st.caption(
        "**Release Commitment** — release or downsize idle RI/SP.  "
        "**Resize Down** — right-size idle compute.  "
        "**Remove Resource** — decommission zombie resources."
    )

    st.markdown("---")

    # ---------------------------------------------------------------------------
    # Step 3 — Prioritised action list
    # ---------------------------------------------------------------------------

    st.subheader("Step 3 — Prioritised action list")

    col_f, col_s = st.columns([2, 2])
    with col_f:
        min_priority = st.slider(
            "Minimum priority score", min_value=0.0, max_value=100.0,
            value=0.0, step=5.0, help="priority_score = savings_pct × confidence",
        )
    with col_s:
        sort_col = st.selectbox(
            "Sort by",
            ["priority_score (desc)", "estimated_savings (desc)", "savings_pct (desc)", "allocated_team"],
        )

    _SORT_MAP = {
        "priority_score (desc)":    ("priority_score",    False),
        "estimated_savings (desc)": ("estimated_savings", False),
        "savings_pct (desc)":       ("savings_pct",       False),
        "allocated_team":           ("allocated_team",    True),
    }
    sort_key, asc = _SORT_MAP[sort_col]

    table_df = rdf[rdf["priority_score"] >= min_priority].sort_values(sort_key, ascending=asc).reset_index(drop=True)
    table_df.insert(0, "Rank", range(1, len(table_df) + 1))

    display_df = pd.DataFrame({
        "Rank":          table_df["Rank"],
        "Resource":      table_df["resource_id"].apply(
                             lambda x: ("…" + str(x)[-35:]) if len(str(x)) > 38 else str(x)
                         ),
        "Owner":         table_df["owner"],
        "Action":        table_df["action_label"],
        "Effort":        table_df.get("effort", pd.Series(["—"] * len(table_df))),
        "Time to $ Save": table_df.get("time_to_realize", pd.Series(["—"] * len(table_df))),
        "ROI ($/hr)":    table_df.get("roi_score", pd.Series([0.0] * len(table_df))).map("${:,.0f}".format),
        "Savings":       table_df["estimated_savings"].map("${:,.0f}".format),
        "Savings %":     table_df["savings_pct"].map("{:.1f}%".format),
        "SLA":           table_df["sla"],
        "Risk":          table_df["risk"],
    })

    def _risk_color(val: str) -> str:
        return {
            "Low":    "background-color:#dcfce7; color:#166534",
            "Medium": "background-color:#fef9c3; color:#854d0e",
            "High":   "background-color:#fee2e2; color:#991b1b",
        }.get(val, "")

    def _sla_color(val: str) -> str:
        return {
            "Immediate":  "background-color:#fee2e2; color:#991b1b; font-weight:600",
            "This week":  "background-color:#fef9c3; color:#854d0e",
            "Next cycle": "background-color:#e0e7ff; color:#3730a3",
        }.get(val, "")

    def _automation_color(val: str) -> str:
        if val.startswith("✔"):
            return "background-color:#dcfce7; color:#166534"
        if "approval" in val.lower():
            return "background-color:#fef9c3; color:#854d0e"
        return "background-color:#f3f4f6; color:#374151"

    def _effort_color(val: str) -> str:
        return {
            "Low":    "background-color:#dcfce7; color:#166534",
            "Medium": "background-color:#fef9c3; color:#854d0e",
            "High":   "background-color:#fee2e2; color:#991b1b",
        }.get(val, "")

    def _time_color(val: str) -> str:
        return {
            "Immediate": "background-color:#dcfce7; color:#166534; font-weight:600",
            "1 week":    "background-color:#fef9c3; color:#854d0e",
            "1 month":   "background-color:#e0e7ff; color:#3730a3",
        }.get(val, "")

    top10_df = display_df.head(10)
    st.dataframe(
        top10_df.style
            .map(_risk_color,   subset=["Risk"])
            .map(_sla_color,    subset=["SLA"])
            .map(_effort_color, subset=["Effort"])
            .map(_time_color,   subset=["Time to $ Save"]),
        use_container_width=True, hide_index=True,
    )

    shown = min(10, len(display_df))
    total = len(table_df)
    if total > shown:
        with st.expander(f"View all {total} recommendations"):
            st.dataframe(
                display_df.style
                    .map(_risk_color,   subset=["Risk"])
                    .map(_sla_color,    subset=["SLA"])
                    .map(_effort_color, subset=["Effort"])
                    .map(_time_color,   subset=["Time to $ Save"]),
                use_container_width=True, hide_index=True,
            )

    # CSV export (addressing a feature gap I flagged earlier)
    csv_bytes = display_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Download as CSV (paste into tickets/Jira)",
        csv_bytes,
        file_name="finops_recommendations.csv",
        mime="text/csv",
    )

    st.caption(f"Showing top {shown} of {total} recommendations (priority ≥ {min_priority:.0f})")

    st.markdown("---")

    # ---------------------------------------------------------------------------
    # Step 4 — Quick wins
    # ---------------------------------------------------------------------------

    st.subheader("Step 4 — Quick wins (Low risk, act now)")

    quick_wins = sorted([r for r in filtered_recs if r["risk"] == "Low"],
                        key=lambda r: r["priority_score"], reverse=True)

    if not quick_wins:
        st.info("No low-risk recommendations in the current filter selection.")
    else:
        # Grouped summary first (executive view)
        qw_by_action: dict[str, list] = {}
        for r in quick_wins:
            qw_by_action.setdefault(r["action"], []).append(r)

        summary_parts = []
        for act, group in sorted(qw_by_action.items(),
                                 key=lambda x: sum(r["estimated_savings"] for r in x[1]),
                                 reverse=True):
            act_lbl = _ACTION_LABELS.get(act, act.replace("_", " ").title())
            group_savings = sum(r["estimated_savings"] for r in group)
            summary_parts.append(
                f"- **{act_lbl}** × {len(group)} — **${group_savings:,.0f}/month**"
            )

        total_qw_savings = sum(r["estimated_savings"] for r in quick_wins)
        st.success(
            f"**Quick wins (low risk, {len(quick_wins)} actions):**\n"
            + "\n".join(summary_parts)
            + f"\n\n**Total: ${total_qw_savings:,.0f}/month**  \n"
            "No downtime expected — no service interruption, no early-exit penalty."
        )
        st.caption("Expand individual actions below for root cause, justification, and alternatives.")

        for i, rec in enumerate(quick_wins[:5], 1):
            team  = _TEAM_LABELS.get(rec["allocated_team"], rec["allocated_team"].replace("-", " ").title())
            act   = _ACTION_LABELS.get(rec["action"], rec["action"])
            short = ("…" + rec["resource_id"][-48:]) if len(rec["resource_id"]) > 50 else rec["resource_id"]
            with st.expander(
                f"{i}. **{act}** — `{short}` · **${rec['estimated_savings']:,.0f}** "
                f"({rec['savings_pct']:.1f}% of current NEC)"
            ):
                # "Why this recommendation?" panel (Task #16 — AI explanation mode).
                # Every quick-win now carries evidence, confidence, data source,
                # priority score, and the annualized cost of ignoring it.
                conf = rec.get("confidence", 0.8)
                conf_label = "high" if conf >= 0.75 else ("medium" if conf >= 0.55 else "low")
                st.markdown(
                    "**Why this recommendation?**  \n"
                    "- **Detected by:** `waste_detector` (billing-confirmed signal)  \n"
                    f"- **Evidence:** {rec['rationale']}  \n"
                    f"- **Confidence:** {conf:.0%} ({conf_label})  \n"
                    f"- **Priority score:** {rec['priority_score']:.1f} / 100 "
                    "(savings_pct × confidence)  \n"
                    f"- **If ignored for 12 months:** ~${rec['estimated_savings'] * 12:,.0f} "
                    "annualised leakage"
                )
                col_a, col_b, col_c = st.columns(3)
                col_a.metric("Current NEC",       f"${rec['current_cost']:,.0f}")
                col_b.metric("Estimated Savings", f"${rec['estimated_savings']:,.0f}")
                col_c.metric("Team",              team)

        if len(quick_wins) > 5:
            with st.expander(f"View remaining {len(quick_wins) - 5} quick wins"):
                for i, rec in enumerate(quick_wins[5:], 6):
                    team = _TEAM_LABELS.get(rec["allocated_team"], rec["allocated_team"].replace("-", " ").title())
                    act  = _ACTION_LABELS.get(rec["action"], rec["action"])
                    short = ("…" + rec["resource_id"][-48:]) if len(rec["resource_id"]) > 50 else rec["resource_id"]
                    st.markdown(
                        f"**{i}. {act}** — `{short}` · {team} · "
                        f"${rec['estimated_savings']:,.0f}/month · Risk: {rec['risk']}"
                    )

    st.markdown("---")

    # ---------------------------------------------------------------------------
    # Step 5 — Projected impact + Before vs After
    # ---------------------------------------------------------------------------

    st.subheader("Step 5 — Projected impact if actions applied")

    low_savings        = sum(r["estimated_savings"] for r in filtered_recs if r["risk"] == "Low")
    savings_pct_of_nec = total_savings / total_nec * 100 if total_nec else 0
    low_pct_of_nec     = low_savings / total_nec * 100 if total_nec else 0
    high_count         = sum(1 for r in filtered_recs if r["risk"] == "High")

    col_low, col_all = st.columns(2)
    with col_low:
        st.success(
            f":white_check_mark: **Low-risk only** — {n_quick_wins} action{'s' if n_quick_wins != 1 else ''}  \n"
            f"**${low_savings:,.0f}/month** ({low_pct_of_nec:.1f}% of NEC)  \n"
            f"No service interruption · no early-exit penalty"
        )
    with col_all:
        st.warning(
            f":scales: **All recommendations** — {len(filtered_recs)} action{'s' if len(filtered_recs) != 1 else ''}  \n"
            f"**${total_savings:,.0f}/month** ({savings_pct_of_nec:.1f}% of NEC)  \n"
            f"Includes {high_count} high-risk action(s) — review before proceeding"
        )

    # ---------------------------------------------------------------------------
    # Scenario Comparison
    # ---------------------------------------------------------------------------
    st.markdown("---")
    st.subheader("Scenario Comparison")
    st.caption("How much can you recover, and at what risk level?")

    qw_savings   = sum(r["estimated_savings"] for r in filtered_recs if r["risk"] == "Low")
    full_savings  = sum(r["estimated_savings"] for r in filtered_recs if r["risk"] in ("Low", "Medium"))
    aggr_savings  = total_savings  # all including High

    qw_count   = sum(1 for r in filtered_recs if r["risk"] == "Low")
    full_count  = sum(1 for r in filtered_recs if r["risk"] in ("Low", "Medium"))
    aggr_count  = len(filtered_recs)

    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        st.success(
            f"**Quick Wins Only**  \n"
            f"Low-risk actions · {qw_count} recommendations  \n"
            f"**${qw_savings:,.0f}/month** · **${qw_savings*12:,.0f}/year**  \n"
            f"No downtime · no approval required  \n"
            f"Time to realize: **Immediate**"
        )
    with sc2:
        st.warning(
            f"**Full Optimization**  \n"
            f"Low + Medium risk · {full_count} recommendations  \n"
            f"**${full_savings:,.0f}/month** · **${full_savings*12:,.0f}/year**  \n"
            f"Some actions need team approval  \n"
            f"Time to realize: **1–7 days**"
        )
    with sc3:
        high_count_sc = aggr_count - full_count
        st.error(
            f"**Aggressive**  \n"
            f"All risk levels · {aggr_count} recommendations  \n"
            f"**${aggr_savings:,.0f}/month** · **${aggr_savings*12:,.0f}/year**  \n"
            f"Includes {high_count_sc} high-risk action(s) — review before acting  \n"
            f"Time to realize: **up to 1 month**"
        )

    # Before vs After summary
    st.markdown("---")
    st.subheader("Before vs After — if all actions applied")

    waste_after     = max(0, total_waste_detected - total_savings)
    waste_pct_after = waste_after / total_nec * 100 if total_nec else 0
    nec_after       = max(0, total_nec - total_savings)
    waste_improvement_pct = (
        (total_waste_detected - waste_after) / total_waste_detected * 100
        if total_waste_detected > 0 else 0
    )
    annual_savings  = total_savings * 12
    annual_low_sav  = low_savings * 12

    col_b, col_a = st.columns(2)
    with col_b:
        st.markdown("**Current state**")
        st.markdown(f"- NEC: **${total_nec:,.0f}/month**")
        st.markdown(f"- Waste: **${total_waste_detected:,.0f}** ({waste_pct:.1f}% of NEC)")
        st.markdown(f"- Recoverable: **${total_savings:,.0f}/month**")
        st.markdown(f"- Quick wins available: **{n_quick_wins}** low-risk actions")
    with col_a:
        st.markdown("**After all recommendations applied**")
        st.markdown(f"- NEC: **${nec_after:,.0f}/month** (−${total_savings:,.0f})")
        st.markdown(f"- Waste: **${waste_after:,.0f}** ({waste_pct_after:.1f}% of NEC)")
        st.markdown(f"- **↓ Waste reduced by {waste_improvement_pct:.0f}%** "
                    f"({waste_pct:.1f}% → {waste_pct_after:.1f}%)")
        st.markdown(f"- **Annual savings potential: ${annual_savings:,.0f}**")

    # --- Before vs After bar visual (Medium #7) -----------------------------
    import plotly.graph_objects as go
    ba_fig = go.Figure(data=[
        go.Bar(name="Before", x=["NEC", "Waste"],
               y=[total_nec, total_waste_detected],
               marker_color=[COLOR_INEFFICIENCY, COLOR_BLOCKER],
               text=[f"${total_nec:,.0f}", f"${total_waste_detected:,.0f}"],
               textposition="outside"),
        go.Bar(name="After",  x=["NEC", "Waste"],
               y=[nec_after, waste_after],
               marker_color=[COLOR_OPTIMIZED, COLOR_INEFFICIENCY],
               text=[f"${nec_after:,.0f}", f"${waste_after:,.0f}"],
               textposition="outside"),
    ])
    ba_fig.update_layout(
        barmode="group", height=260, margin=dict(t=10, b=40),
        yaxis_title="USD / month",
        legend=dict(orientation="h", y=1.12),
    )
    st.plotly_chart(ba_fig, use_container_width=True)

    # Enhanced summary strip — monthly, annual, % of NEC avoided (Task #7)
    _nec_pct_avoided = total_savings / total_nec * 100 if total_nec else 0
    col_s1, col_s2, col_s3, col_s4 = st.columns(4)
    col_s1.metric("Monthly avoidance",  f"${total_savings:,.0f}")
    col_s2.metric("Annualised",         f"${annual_savings:,.0f}")
    col_s3.metric("% of NEC avoided",   f"{_nec_pct_avoided:.1f}%")
    col_s4.metric("Waste reduction",    f"{waste_improvement_pct:.0f}%",
                  delta=f"{waste_pct:.1f}% → {waste_pct_after:.1f}%", delta_color="inverse")

    # Business impact callout
    col_low_imp, col_all_imp = st.columns(2)
    with col_low_imp:
        st.info(
            f":white_check_mark: **Low-risk actions only**  \n"
            f"${low_savings:,.0f}/month · **${annual_low_sav:,.0f}/year**  \n"
            f"No downtime · no early-exit penalty"
        )
    with col_all_imp:
        if waste_pct > 0:
            enterprise_before = 10_000_000 * (waste_pct / 100)
            enterprise_after  = 10_000_000 * (waste_pct_after / 100)
            st.warning(
                f":scales: **At $10M/month scale**  \n"
                f"Waste: ${enterprise_before:,.0f} → ${enterprise_after:,.0f}/month  \n"
                f"Savings: **${enterprise_before - enterprise_after:,.0f}/month**"
            )
