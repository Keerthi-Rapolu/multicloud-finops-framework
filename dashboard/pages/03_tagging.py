"""
Page 3 - Tagging & Attribution

Governance control layer: coverage analytics, ownership assignment,
SLA-based escalation tracker, and tag quality scoring.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dashboard._shared import (
    COLOR_BLOCKER,
    COLOR_INEFFICIENCY,
    COLOR_OPTIMIZED,
    LABEL_UNATTRIBUTED_SPEND,
    apply_owner_assignments,
    compute_finops_summary_metrics,
    diagnose,
    load_finops_summary,
    load_scoped_df,
    render_demo_banner,
    render_headline,
)
from dashboard.canonical import load_canonical_metrics

_ASSIGNMENTS_FILE = Path(__file__).resolve().parents[2] / "data" / "team_assignments.json"
_KNOWN_TEAMS = ["data-eng", "platform", "frontend", "backend", "ml"]
_TEAM_LABELS = {
    "data-eng": "Data Engineering",
    "platform": "Platform",
    "frontend": "Frontend",
    "backend": "Backend",
    "ml": "Machine Learning",
}
_TODAY = datetime(2026, 4, 24)  # fixed demo date so SLA buckets are stable


def _assignment_key(cloud_provider: str, account_id: str) -> str:
    return f"{str(cloud_provider).lower()}::{account_id}"


def _load_assignments() -> dict:
    if _ASSIGNMENTS_FILE.exists():
        try:
            return json.loads(_ASSIGNMENTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"assignments": []}


def _save_assignments(data: dict) -> None:
    _ASSIGNMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _ASSIGNMENTS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _lookup_assignment(
    assigned_map: dict[str, str],
    legacy_map: dict[str, str],
    cloud_provider: str,
    account_id: str,
) -> str | None:
    return assigned_map.get(
        _assignment_key(cloud_provider, account_id),
        legacy_map.get(account_id),
    )


st.set_page_config(page_title="Tagging & Attribution", layout="wide")
st.title("Tagging & Attribution")
st.caption(
    "Governance control layer - coverage analytics, ownership assignment, and SLA tracking."
)
render_demo_banner()

df, month_filter, selected_cloud = load_scoped_df(render_sidebar=True)
summary_df = load_finops_summary(month_filter)
summary_metrics = compute_finops_summary_metrics(
    summary_df,
    clouds=selected_cloud,
    fallback_df=df,
)
canonical_metrics = load_canonical_metrics(month_filter, selected_cloud)

diag = diagnose(df, summary=summary_metrics)
render_headline(diag)

notice = st.session_state.pop("tagging_assignment_notice", None)
if notice:
    st.success(notice)

assignments_store = _load_assignments()
_assigned_map: dict[str, str] = {
    _assignment_key(a.get("cloud_provider", "unknown"), a["account_id"]): a["assigned_team"]
    for a in assignments_store.get("assignments", [])
}
_legacy_assigned_map: dict[str, str] = {
    a["account_id"]: a["assigned_team"]
    for a in assignments_store.get("assignments", [])
}

# ---------------------------------------------------------------------------
# View toggle
# ---------------------------------------------------------------------------

view = st.radio(
    "View",
    ["Raw (explicit tags only)", "Adjusted (heuristics + saved owner assignments)"],
    horizontal=True,
    help=(
        "**Raw**: counts only rows with an explicit `tag_team` value.\n\n"
        "**Adjusted**: includes heuristic allocation plus locally saved account-owner "
        "assignments - shows how much of the gap can be closed operationally before "
        "tag policy catches up."
    ),
)
adjusted = "Adjusted" in view

df_assigned = apply_owner_assignments(
    df,
    _assigned_map,
    fallback_by_account=_legacy_assigned_map,
)
is_tagged = df_assigned["is_tagged"].fillna(False)
auto_attr = df_assigned["allocated_team"].fillna("unattributed") != "unattributed"
manual_attr = df_assigned["is_manually_assigned"].fillna(False)
is_attributable = (auto_attr | manual_attr) if adjusted else is_tagged

total_nec = canonical_metrics.nec or summary_metrics.total_nec
unattributed_nec = (
    canonical_metrics.unattributed_nec or summary_metrics.total_unattributed_cost
    if not adjusted else float(df_assigned.loc[~is_attributable, "nec"].sum())
)
attributed_nec = max(0.0, total_nec - unattributed_nec)
attributed_pct = attributed_nec / total_nec * 100 if total_nec else 0.0
unattributed_pct = 100 - attributed_pct

# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------

c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Attributed NEC",
    f"{attributed_pct:.1f}%",
    delta=f"{unattributed_pct:.1f}% unattributed",
    delta_color="inverse",
)
c2.metric("Attributed $", f"${attributed_nec:,.0f}")
c3.metric(LABEL_UNATTRIBUTED_SPEND, f"${unattributed_nec:,.0f}", delta_color="inverse")
c4.metric("Owners Assigned", str(len(_assigned_map)), delta=f"{len(_assigned_map)} accounts mapped")
st.caption(
    "Owner assignments in this synthetic demo are local mappings saved from the dashboard. "
    "No preloaded persisted assignments are included by default. "
    "Assignment improves operational routing, but it does not change billing attribution until the underlying tags are fixed."
)
if not _assigned_map:
    st.info(
        "**Demo state:** No owner assignments are preloaded. "
        "Use the **Assign Owner Now** section below to map accounts to teams — "
        "assignments persist locally and immediately update the Owners Assigned count and the Adjusted attribution view."
    )

if adjusted:
    raw_pct = df_assigned.loc[is_tagged, "nec"].sum() / total_nec * 100 if total_nec else 0.0
    auto_pct = df_assigned.loc[auto_attr, "nec"].sum() / total_nec * 100 if total_nec else 0.0
    auto_gain = auto_pct - raw_pct
    manual_gain = attributed_pct - auto_pct
    gain_parts: list[str] = []
    if auto_gain > 0.1:
        gain_parts.append(f"heuristics +{auto_gain:.1f}%")
    if manual_gain > 0.1:
        gain_parts.append(f"saved owner assignments +{manual_gain:.1f}%")
    if gain_parts:
        st.success(
            f"Adjusted attribution improves coverage - {raw_pct:.1f}% (explicit tags) "
            f"to {attributed_pct:.1f}%. Lift source: {', '.join(gain_parts)}."
        )

if unattributed_pct >= 20:
    st.error(
        f"HIGH — {unattributed_pct:.1f}% of NEC (\\${unattributed_nec:,.0f}) is unattributed. "
        "Use the Assign Owner section below to close the gap. Target: <5% within 60 days."
    )
elif unattributed_pct >= 10:
    st.warning(
        f"MEDIUM — {unattributed_pct:.1f}% of NEC (\\${unattributed_nec:,.0f}) is unattributed. "
        "See the Assign Owner section below."
    )
else:
    st.success(f"Coverage acceptable - {attributed_pct:.1f}% attributed.")

st.markdown("---")

# ---------------------------------------------------------------------------
# Section 1 - Tag policy compliance
# ---------------------------------------------------------------------------

st.subheader("Tag Policy Compliance")
st.caption("Required tags must be present on every billable resource. Optional tags improve analysis depth.")

team_tag_cov = is_tagged.mean() * 100
env_cov_raw = min(team_tag_cov * 0.82, 100)
cc_cov_raw = min(team_tag_cov * 0.55, 100)


def _tag_score(pct: float) -> str:
    if pct >= 95:
        return "Excellent"
    if pct >= 80:
        return "Good"
    if pct >= 50:
        return "Needs work"
    return "Critical"


required_tags = [
    {"Tag": "team", "Type": "Required", "Coverage": f"{team_tag_cov:.0f}%", "Status": _tag_score(team_tag_cov), "Source": "Billing data"},
    {"Tag": "environment", "Type": "Required", "Coverage": f"{env_cov_raw:.0f}%", "Status": _tag_score(env_cov_raw), "Source": "Derived"},
    {"Tag": "cost_center", "Type": "Required", "Coverage": f"{cc_cov_raw:.0f}%", "Status": _tag_score(cc_cov_raw), "Source": "Derived"},
    {"Tag": "project", "Type": "Optional", "Coverage": "-", "Status": "Not tracked", "Source": "Not in pipeline"},
    {"Tag": "owner", "Type": "Optional", "Coverage": "-", "Status": "Not tracked", "Source": "Not in pipeline"},
]
req_df = pd.DataFrame(required_tags)


def _type_color(val: str) -> str:
    return "background-color:#fee2e2; color:#991b1b; font-weight:600" if val == "Required" else ""


st.dataframe(req_df.style.map(_type_color, subset=["Type"]), use_container_width=True, hide_index=True)

req_coverages = [team_tag_cov, env_cov_raw, cc_cov_raw]
quality_score = round(sum(min(c / 20, 5) for c in req_coverages) / len(req_coverages), 1)
quality_color = (
    COLOR_OPTIMIZED
    if quality_score >= 4
    else (COLOR_INEFFICIENCY if quality_score >= 2.5 else COLOR_BLOCKER)
)

col_qs1, col_qs2 = st.columns([1, 3])
with col_qs1:
    st.markdown(
        f"<h2 style='color:{quality_color}; margin:0'>{quality_score} / 5.0</h2>"
        f"<p style='color:#6b7280; margin:0; font-size:0.85rem'>Tag Quality Score</p>",
        unsafe_allow_html=True,
    )
with col_qs2:
    gaps = []
    if team_tag_cov < 95:
        gaps.append(f"enforce `tag_team` at resource creation ({team_tag_cov:.0f}% -> 95%)")
    if env_cov_raw < 80:
        gaps.append("add `environment` tag to provisioning templates")
    if cc_cov_raw < 80:
        gaps.append("add `cost_center` tag to account-level defaults")
    if gaps:
        st.markdown("**To reach 5.0/5:** " + " | ".join(gaps))
    else:
        st.success("All required tags meet coverage targets.")

st.markdown("---")

# ---------------------------------------------------------------------------
# Section 2 - Coverage charts
# ---------------------------------------------------------------------------

st.subheader("Coverage by cloud")
st.caption(
    "All clouds with billing data are shown. A cloud missing from the chart means it has no rows "
    "in the selected billing scope — adjust the global month/cloud filter to include it."
)

df_view = df_assigned.assign(is_attr=is_attributable)
by_cloud = (
    df_view.groupby("cloud_provider")
    .apply(
        lambda g: pd.Series(
            {
                "attributed_pct": (
                    g.loc[g["is_attr"], "nec"].sum() / g["nec"].sum() * 100
                    if g["nec"].sum()
                    else 0.0
                ),
            }
        ),
        include_groups=False,
    )
    .reset_index()
)
fig_cloud = px.bar(
    by_cloud,
    x="cloud_provider",
    y="attributed_pct",
    labels={"cloud_provider": "Cloud", "attributed_pct": "Attributed NEC %"},
    color="cloud_provider",
    color_discrete_map={"aws": "#f97316", "azure": "#2563eb", "gcp": "#22c55e"},
    range_y=[0, 115],
    text="attributed_pct",
)
fig_cloud.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
fig_cloud.add_hline(y=95, line_dash="dot", line_color="#22c55e", annotation_text="95% target", annotation_position="top right")
fig_cloud.update_layout(height=300, showlegend=False, margin=dict(t=10, b=40))
st.plotly_chart(fig_cloud, use_container_width=True)

st.markdown("---")
st.subheader("Coverage by service category")

by_svc = (
    df_view.groupby("service_category")
    .apply(
        lambda g: pd.Series(
            {
                "attributed_pct": (
                    g.loc[g["is_attr"], "nec"].sum() / g["nec"].sum() * 100
                    if g["nec"].sum()
                    else 0.0
                ),
            }
        ),
        include_groups=False,
    )
    .reset_index()
    .sort_values("attributed_pct")
)
fig_svc = px.bar(
    by_svc,
    x="attributed_pct",
    y="service_category",
    orientation="h",
    labels={"attributed_pct": "Attributed NEC %", "service_category": "Service Category"},
    color="attributed_pct",
    color_continuous_scale="RdYlGn",
    range_color=[0, 100],
    text="attributed_pct",
)
fig_svc.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
fig_svc.update_layout(height=300, coloraxis_showscale=False, margin=dict(t=10, b=40), yaxis_title=None)
st.plotly_chart(fig_svc, use_container_width=True)

st.markdown("---")

# ---------------------------------------------------------------------------
# Section 3 - Assign Owner Now
# ---------------------------------------------------------------------------

st.subheader("Assign Owner Now")
st.caption(
    "Assign a team to each unattributed account. Assignments are persisted locally "
    "and counted in the adjusted attribution view."
)

unattr_df = df_view[~df_view["is_attr"]]

if unattr_df.empty:
    st.success("All accounts attributed - no ownership assignments needed.")
else:
    by_acct = (
        df_view.groupby(["cloud_provider", "account_id"])
        .apply(
            lambda g: pd.Series(
                {
                    "unattr_nec": g.loc[~g["is_attr"], "nec"].sum(),
                    "total_nec": g["nec"].sum(),
                    "unattr_rows": int((~g["is_attr"]).sum()),
                }
            ),
            include_groups=False,
        )
        .reset_index()
    )
    by_acct = by_acct[by_acct["unattr_nec"] > 0].sort_values("unattr_nec", ascending=False).reset_index(drop=True)
    by_acct["unattr_pct"] = (by_acct["unattr_nec"] / by_acct["total_nec"].replace(0, float("nan")) * 100).round(1)
    by_acct["pct_of_total"] = (by_acct["unattr_nec"] / unattributed_nec * 100).round(1)

    def _priority(row) -> str:
        if row["unattr_nec"] >= unattributed_nec * 0.15 and row["unattr_pct"] >= 30:
            return "High"
        if row["unattr_nec"] >= unattributed_nec * 0.05:
            return "Medium"
        return "Low"

    by_acct["Priority"] = by_acct.apply(_priority, axis=1)

    if not by_acct.empty and by_acct.iloc[0]["pct_of_total"] >= 15:
        w = by_acct.iloc[0]
        currently_assigned = _lookup_assignment(
            _assigned_map,
            _legacy_assigned_map,
            w["cloud_provider"],
            w["account_id"],
        )
        assign_status = f" (currently -> **{currently_assigned}**)" if currently_assigned else " (unassigned)"
        st.error(
            f"Top gap: `{w['account_id']}` ({w['cloud_provider'].upper()}) — "
            f"\\${w['unattr_nec']:,.0f} ({w['pct_of_total']:.0f}% of all unattributed NEC){assign_status}. "
            "Assigning an owner here closes the largest share of the gap in one action."
        )

    st.markdown("**Assign teams to top unattributed accounts:**")

    top_accounts = by_acct.head(7)
    new_assignments: dict[str, str] = {}

    with st.form("assign_owner_form"):
        for _, row in top_accounts.iterrows():
            acct_id = row["account_id"]
            cloud = row["cloud_provider"].upper()
            priority = row["Priority"]
            current = _lookup_assignment(
                _assigned_map,
                _legacy_assigned_map,
                row["cloud_provider"],
                acct_id,
            ) or ""
            team_opts = ["- unassigned -"] + _KNOWN_TEAMS

            col_info, col_select = st.columns([3, 2])
            with col_info:
                pri_color = {"High": "#ef4444", "Medium": "#eab308", "Low": "#22c55e"}.get(priority, "#6b7280")
                st.markdown(
                    f'<span style="background:{pri_color};color:white;padding:2px 8px;border-radius:10px;'
                    f'font-size:0.78rem;font-weight:700">{priority}</span> '
                    f'**`{acct_id}`** | {cloud} | ${row["unattr_nec"]:,.0f} unattributed '
                    f'({row["pct_of_total"]:.0f}% of gap)',
                    unsafe_allow_html=True,
                )
            with col_select:
                default_idx = (_KNOWN_TEAMS.index(current) + 1) if current in _KNOWN_TEAMS else 0
                chosen = st.selectbox(
                    f"Team for {acct_id}",
                    team_opts,
                    index=default_idx,
                    key=f"assign_{row['cloud_provider']}_{acct_id}",
                    label_visibility="collapsed",
                )
                if chosen != "- unassigned -":
                    new_assignments[_assignment_key(row["cloud_provider"], acct_id)] = chosen

        submitted = st.form_submit_button("Apply Assignments", type="primary")
        if submitted and new_assignments:
            existing = {
                _assignment_key(a.get("cloud_provider", "unknown"), a["account_id"]): a
                for a in assignments_store.get("assignments", [])
            }
            for key, team in new_assignments.items():
                cloud_val, acct_id = key.split("::", 1)
                existing[key] = {
                    "account_id": acct_id,
                    "cloud_provider": cloud_val,
                    "assigned_team": team,
                    "assigned_date": _TODAY.strftime("%Y-%m-%d"),
                }
            assignments_store["assignments"] = list(existing.values())
            _save_assignments(assignments_store)
            st.session_state["tagging_assignment_notice"] = (
                f"Assigned {len(new_assignments)} account(s). Adjusted-view attribution metrics were refreshed."
            )
            st.rerun()

st.markdown("---")

# ---------------------------------------------------------------------------
# Section 4 - SLA tracker
# ---------------------------------------------------------------------------

st.subheader("Tagging SLA Tracker")
st.caption("How long has each unattributed account been visible? Fix-it SLA: 7 days from first detection.")

if unattr_df.empty:
    st.success("No SLA violations - all accounts attributed.")
else:
    unattr_first = (
        unattr_df.groupby(["cloud_provider", "account_id"])["billing_month"]
        .min()
        .reset_index(name="first_seen_month")
    )

    def _days_open(month_str: str) -> int:
        try:
            dt = datetime.strptime(str(month_str) + "-01", "%Y-%m-%d")
            return (_TODAY - dt).days
        except Exception:
            return 0

    unattr_first["days_open"] = unattr_first["first_seen_month"].apply(_days_open)

    def _sla_bucket(days: int) -> str:
        if days <= 3:
            return "New (0-3 days)"
        if days <= 7:
            return "Warning (4-7 days)"
        return "Escalation (>7 days)"

    unattr_first["SLA Status"] = unattr_first["days_open"].apply(_sla_bucket)

    acct_nec = (
        unattr_df.groupby(["cloud_provider", "account_id"])["nec"]
        .sum()
        .reset_index(name="unattr_nec")
    )
    sla_df = unattr_first.merge(acct_nec, on=["cloud_provider", "account_id"], how="left")
    sla_df["Assigned"] = sla_df.apply(
        lambda r: _lookup_assignment(
            _assigned_map,
            _legacy_assigned_map,
            r["cloud_provider"],
            r["account_id"],
        )
        or "Unassigned",
        axis=1,
    )

    bucket_summary = (
        sla_df.groupby("SLA Status")
        .agg(accounts=("account_id", "count"), total_nec=("unattr_nec", "sum"))
        .reset_index()
    )

    col_b1, col_b2, col_b3 = st.columns(3)
    bucket_colors = {
        "New (0-3 days)": (COLOR_OPTIMIZED, col_b1),
        "Warning (4-7 days)": (COLOR_INEFFICIENCY, col_b2),
        "Escalation (>7 days)": (COLOR_BLOCKER, col_b3),
    }
    for _, row in bucket_summary.iterrows():
        bname = row["SLA Status"]
        color, col = bucket_colors.get(bname, ("#6b7280", col_b1))
        with col:
            st.markdown(
                f"<div style='border-left:4px solid {color}; padding:8px 12px; border-radius:4px'>"
                f"<div style='color:{color}; font-weight:700; font-size:1.1rem'>{bname}</div>"
                f"<div style='font-size:0.9rem'><b>{row['accounts']}</b> accounts | "
                f"<b>${row['total_nec']:,.0f}</b> NEC</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

    st.markdown("")

    sla_display = pd.DataFrame(
        {
            "SLA Status": sla_df["SLA Status"],
            "Cloud": sla_df["cloud_provider"].str.upper(),
            "Account": sla_df["account_id"],
            "First Seen": sla_df["first_seen_month"],
            "Days Open": sla_df["days_open"].astype(int),
            "Unattr. NEC": sla_df["unattr_nec"].map("${:,.0f}".format),
            "Assigned To": sla_df["Assigned"],
        }
    ).sort_values(["SLA Status", "Days Open"], ascending=[False, False])

    def _sla_row_color(val: str) -> str:
        return {
            "Escalation (>7 days)": "background-color:#fee2e2; color:#991b1b; font-weight:600",
            "Warning (4-7 days)": "background-color:#fef9c3; color:#854d0e",
            "New (0-3 days)": "background-color:#dcfce7; color:#166534",
        }.get(val, "")

    def _assigned_color(val: str) -> str:
        return "background-color:#dcfce7; color:#166534" if val != "Unassigned" else ""

    st.dataframe(
        sla_display.style.map(_sla_row_color, subset=["SLA Status"]).map(_assigned_color, subset=["Assigned To"]),
        use_container_width=True,
        hide_index=True,
    )

    escalations = sla_df[sla_df["SLA Status"] == "Escalation (>7 days)"]
    if not escalations.empty:
        esc_nec = escalations["unattr_nec"].sum()
        st.error(
            f"{len(escalations)} account(s) are past the 7-day SLA — "
            f"\\${esc_nec:,.0f} NEC has been unattributed for >7 days. "
            "Use the Assign Owner form above to resolve immediately."
        )

st.markdown("---")

# ---------------------------------------------------------------------------
# Section 5 - Ownership gap detail
# ---------------------------------------------------------------------------

st.subheader("Ownership Gap Detail")

if not unattr_df.empty:
    _worst = (
        df_view.groupby(["cloud_provider", "account_id"])
        .apply(lambda g: g.loc[~g["is_attr"], "nec"].sum(), include_groups=False)
        .reset_index(name="unattr_nec")
        .sort_values("unattr_nec", ascending=False)
    )
    if not _worst.empty and _worst.iloc[0]["unattr_nec"] > 0:
        w = _worst.iloc[0]
        w_pct = w["unattr_nec"] / unattributed_nec * 100 if unattributed_nec else 0.0
        currently = _lookup_assignment(
            _assigned_map,
            _legacy_assigned_map,
            w["cloud_provider"],
            w["account_id"],
        )
        status_str = f"Assigned -> **{currently}**" if currently else "**Not yet assigned**"
        if w_pct >= 15:
            st.error(
                f"Single biggest gap: `{w['account_id']}` ({w['cloud_provider'].upper()}) — "
                f"\\${w['unattr_nec']:,.0f} ({w_pct:.0f}% of all unattributed NEC). {status_str}"
            )

if not unattr_df.empty:
    with st.expander("Full unattributed account table"):
        disp = by_acct[["Priority", "cloud_provider", "account_id", "unattr_rows", "unattr_nec", "unattr_pct"]].copy()
        disp.columns = ["Priority", "Cloud", "Account", "Rows", "Unattr. NEC", "Unattr. %"]
        disp["Unattr. NEC"] = disp["Unattr. NEC"].map("${:,.0f}".format)
        disp["Unattr. %"] = disp["Unattr. %"].map("{:.1f}%".format)

        def _risk_color(val: str) -> str:
            return {
                "High": "background-color:#fee2e2; color:#991b1b",
                "Medium": "background-color:#fef9c3; color:#854d0e",
                "Low": "background-color:#dcfce7; color:#166534",
            }.get(val, "")

        st.dataframe(disp.style.map(_risk_color, subset=["Priority"]), use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Section 6 - Secondary detail
# ---------------------------------------------------------------------------

with st.expander("Unattributed NEC by service (top 20)"):
    if not unattr_df.empty:
        by_svc2 = (
            unattr_df.groupby(["cloud_provider", "service_name"])
            .agg(unattr_nec=("nec", "sum"))
            .reset_index()
            .sort_values("unattr_nec", ascending=False)
            .head(20)
        )
        by_svc2["pct"] = (by_svc2["unattr_nec"] / unattributed_nec * 100).round(1)
        fig_s = px.bar(
            by_svc2,
            x="unattr_nec",
            y="service_name",
            color="cloud_provider",
            orientation="h",
            color_discrete_map={"aws": "#f97316", "azure": "#2563eb", "gcp": "#22c55e"},
            labels={"unattr_nec": "Unattributed NEC (USD)", "service_name": "Service", "cloud_provider": "Cloud"},
            text="pct",
        )
        fig_s.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
        fig_s.update_layout(height=420, margin=dict(t=10, b=40), yaxis={"categoryorder": "total ascending"}, yaxis_title=None)
        st.plotly_chart(fig_s, use_container_width=True)
    else:
        st.info("No unattributed rows in this view.")

if "usage_date" in df_assigned.columns:
    with st.expander("Attribution trend over time"):
        trend = (
            df_view.assign(date=pd.to_datetime(df_view["usage_date"]).dt.to_period("D"))
            .groupby(["date", "cloud_provider"])
            .apply(lambda g: pd.Series({"unattr_nec": g.loc[~g["is_attr"], "nec"].sum()}), include_groups=False)
            .reset_index()
        )
        trend["date"] = trend["date"].dt.to_timestamp()
        if not trend.empty:
            fig_t = px.line(
                trend,
                x="date",
                y="unattr_nec",
                color="cloud_provider",
                labels={"date": "Date", "unattr_nec": "Unattributed NEC (USD)", "cloud_provider": "Cloud"},
                color_discrete_map={"aws": "#f97316", "azure": "#2563eb", "gcp": "#22c55e"},
            )
            fig_t.update_layout(height=280, margin=dict(t=10, b=40))
            st.plotly_chart(fig_t, use_container_width=True)
            st.caption("A flat or rising trend confirms tagging policy is not being enforced consistently.")
