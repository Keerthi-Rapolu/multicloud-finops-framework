"""
Shared helpers for the Streamlit dashboard.

Provides:
- load_df / month_filter helpers (deep-link safe)
- Executive headline generator (Critical #1)
- Priority badge rendering (Critical #2 / Medium #6)
- Maturity score computation + how-to-improve guidance (Medium #10)
- Visual hierarchy color constants (Medium #6)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from typing import Literal

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Visual hierarchy — priority colors (Medium #6)
# ---------------------------------------------------------------------------

COLOR_BLOCKER      = "#ef4444"   # red     — P0, fix first
COLOR_INEFFICIENCY = "#eab308"   # yellow  — waste / optimization
COLOR_OPTIMIZED    = "#22c55e"   # green   — healthy
COLOR_INFO         = "#2563eb"   # blue    — informational

CLOUD_COLORS = {"aws": "#f97316", "azure": "#2563eb", "gcp": "#22c55e"}

TEAM_LABELS = {
    "data-eng":     "Data Engineering",
    "platform":     "Platform",
    "frontend":     "Frontend",
    "backend":      "Backend",
    "ml":           "Machine Learning",
    "unattributed": "Unattributed",
}

GLOBAL_CLOUD_OPTIONS = ["All", "aws", "azure", "gcp"]

LABEL_NEC = "Net Effective Cost (NEC)"
LABEL_WASTE_PCT = "Waste as % of NEC"
LABEL_ESTIMATED_MONTHLY_SAVINGS = "Estimated Monthly Savings"
LABEL_UNATTRIBUTED_SPEND = "Unattributed Spend"

# ---------------------------------------------------------------------------
# Data loading — deep-link safe
# ---------------------------------------------------------------------------

_DB_PATH = Path(__file__).resolve().parents[1] / "finops_dbt.duckdb"
_RECOMMENDATION_ACTIONS_PATH = Path(__file__).resolve().parents[1] / "data" / "recommendation_actions.json"


@st.cache_data(ttl=30, show_spinner=False)
def available_months() -> list[str]:
    import duckdb

    if not _DB_PATH.exists():
        return []
    with duckdb.connect(str(_DB_PATH), read_only=True) as con:
        rows = con.execute(
            "SELECT DISTINCT billing_month FROM marts.fct_unified_billing ORDER BY 1 DESC"
        ).fetchall()
    return [r[0] for r in rows]


@st.cache_data(show_spinner="Loading billing data…")
def load_df(month: str | None) -> pd.DataFrame:
    from allocation.nec_model import load_billing_data

    return load_billing_data(_DB_PATH, billing_month=month or None)


def _resolve_scope_defaults(months: list[str]) -> tuple[str, str]:
    selected_month = st.session_state.get("billing_month")
    if selected_month not in (["All"] + months):
        legacy_month = st.session_state.get("month")
        selected_month = legacy_month if legacy_month in months else months[0]

    selected_cloud = st.session_state.get("cloud", "All")
    if selected_cloud not in GLOBAL_CLOUD_OPTIONS:
        selected_cloud = "All"

    return selected_month, selected_cloud


def render_global_scope_sidebar(show_title: bool = False) -> tuple[str | None, str]:
    months = available_months()
    if not months:
        st.error(
            "**No data found.** Run `make pipeline` first to generate synthetic data "
            "and build the DuckDB mart, then relaunch the dashboard."
        )
        st.stop()

    selected_month, selected_cloud = _resolve_scope_defaults(months)

    if show_title:
        st.sidebar.title("FinOps Dashboard")
        st.sidebar.markdown("---")

    st.sidebar.markdown("### Global scope")
    st.sidebar.caption(
        "Applies to every page. Page-level filters below narrow this scope."
    )

    month_options = ["All"] + months
    st.session_state.setdefault("billing_month", selected_month)
    st.session_state.setdefault("cloud", selected_cloud)
    selected_month = st.sidebar.selectbox(
        "Billing month",
        month_options,
        index=month_options.index(selected_month),
        key="billing_month",
    )
    selected_cloud = st.sidebar.selectbox(
        "Cloud provider",
        GLOBAL_CLOUD_OPTIONS,
        index=GLOBAL_CLOUD_OPTIONS.index(selected_cloud),
        key="cloud",
    )

    month_filter = None if selected_month == "All" else selected_month
    st.session_state["month"] = month_filter
    return month_filter, selected_cloud


def load_scoped_df(
    *,
    render_sidebar: bool = False,
    show_sidebar_title: bool = False,
) -> tuple[pd.DataFrame, str | None, str]:
    months = available_months()
    if not months:
        st.error(
            "**No data found.** Run `make pipeline` first to generate synthetic data "
            "and build the DuckDB mart, then relaunch the dashboard."
        )
        st.stop()

    if render_sidebar:
        month_filter, selected_cloud = render_global_scope_sidebar(
            show_title=show_sidebar_title
        )
    else:
        selected_month, selected_cloud = _resolve_scope_defaults(months)
        month_filter = None if selected_month == "All" else selected_month
        st.session_state.setdefault("billing_month", selected_month)
        st.session_state["month"] = month_filter
        st.session_state.setdefault("cloud", selected_cloud)

    df_full = load_df(month_filter)
    scoped_df = (
        df_full
        if selected_cloud == "All"
        else df_full[df_full["cloud_provider"] == selected_cloud].copy()
    )
    st.session_state["df"] = scoped_df
    return scoped_df, month_filter, selected_cloud


def content_hash(df: pd.DataFrame) -> int:
    """Stable cache key — unlike id(df) this hits when data is unchanged."""
    return int(pd.util.hash_pandas_object(df, index=True).sum())


def apply_owner_assignments(
    df: pd.DataFrame,
    assigned_map: dict[str, str],
    fallback_by_account: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Fill unattributed rows from saved cloud/account owner assignments."""
    base_team = (
        df["allocated_team"].fillna("unattributed")
        if "allocated_team" in df.columns
        else pd.Series("unattributed", index=df.index)
    ).astype(str)

    if "cloud_provider" not in df.columns or "account_id" not in df.columns:
        return df.assign(effective_team=base_team, is_manually_assigned=False)

    keys = (
        df["cloud_provider"].astype(str).str.lower()
        + "::"
        + df["account_id"].astype(str)
    )
    assigned_team = keys.map(assigned_map)
    if fallback_by_account:
        assigned_team = assigned_team.fillna(df["account_id"].astype(str).map(fallback_by_account))

    manual_mask = base_team.eq("unattributed") & assigned_team.notna()
    effective_team = base_team.mask(manual_mask, assigned_team)
    return df.assign(effective_team=effective_team, is_manually_assigned=manual_mask)


def load_recommendation_actions() -> dict[str, dict]:
    """Load locally persisted recommendation lifecycle state."""
    if not _RECOMMENDATION_ACTIONS_PATH.exists():
        return {}
    with open(_RECOMMENDATION_ACTIONS_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def save_recommendation_action(recommendation_id: str, payload: dict) -> None:
    """Persist lifecycle state for one recommendation."""
    actions = load_recommendation_actions()
    actions[recommendation_id] = payload
    _RECOMMENDATION_ACTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_RECOMMENDATION_ACTIONS_PATH, "w", encoding="utf-8") as handle:
        json.dump(actions, handle, indent=2, sort_keys=True)


def overlay_recommendation_actions(recommendations: list[dict]) -> list[dict]:
    """Merge persisted lifecycle state into recommendations with safe defaults."""
    actions = load_recommendation_actions()
    merged: list[dict] = []
    today = date.today().isoformat()
    for rec in recommendations:
        rid = rec["recommendation_id"]
        saved = actions.get(rid, {})
        merged.append(
            {
                **rec,
                "action_status": saved.get("action_status", "recommended"),
                "created_date": saved.get("created_date", today),
                "implementation_date": saved.get("implementation_date"),
                "realized_savings": float(saved.get("realized_savings", 0.0) or 0.0),
                "action_owner": saved.get(
                    "action_owner",
                    rec.get("owner_email") or TEAM_LABELS.get(rec.get("allocated_team", ""), rec.get("allocated_team", "Unassigned")),
                ),
            }
        )
    return merged


# ---------------------------------------------------------------------------
# Executive headline + priority (Critical #1, #2)
# ---------------------------------------------------------------------------

Priority = Literal["P0", "P1", "P2", "P3"]


@dataclass
class Diagnostic:
    """Summary of the dominant finding + quick-win opportunity."""

    total_nec:       float
    untagged_nec:    float
    untagged_pct:    float
    waste_nec:       float
    waste_pct:       float
    low_risk_savings: float        # commitment waste × recovery rate
    primary_issue:   str           # "tagging" | "commitment_waste" | "healthy"
    priority:        Priority
    headline:        str           # one-line "so what"
    sub_headline:    str           # one-line quick-win
    color:           str           # CSS hex


def diagnose(df: pd.DataFrame, recovery_rate: float = 0.85) -> Diagnostic:
    """Compute the executive diagnostic used at the top of every page.

    ``recovery_rate`` reflects that not 100% of detected idle commitments
    can be released immediately (penalties, partial coverage).
    """
    total_nec    = float(df["nec"].sum())
    waste_nec    = float(df.get("nec_waste", pd.Series(dtype=float)).fillna(0).sum())
    is_tagged    = df["is_tagged"].fillna(False) if "is_tagged" in df.columns else pd.Series(False, index=df.index)
    untagged_nec = float(df.loc[~is_tagged, "nec"].sum())

    untagged_pct = (untagged_nec / total_nec * 100) if total_nec else 0.0
    waste_pct    = (waste_nec    / total_nec * 100) if total_nec else 0.0
    low_risk_savings = waste_nec * recovery_rate

    # Pick the dominant issue — tagging gap generally takes precedence
    # because it blocks accurate attribution (which every other metric depends on).
    if untagged_pct >= 20:
        primary = "tagging"
        priority: Priority = "P0"
        headline = (
            f"You're losing <b>${untagged_nec:,.0f}/month</b> to unoptimizable spend — "
            f"{untagged_pct:.0f}% of cloud cost has no team owner assigned."
        )
        color = COLOR_BLOCKER
    elif waste_pct >= 10:
        primary = "commitment_waste"
        priority = "P0"
        headline = (
            f"You're wasting <b>${waste_nec:,.0f}/month</b> — "
            f"{waste_pct:.0f}% of cloud spend is committed capacity sitting idle."
        )
        color = COLOR_BLOCKER
    elif untagged_pct >= 10:
        primary = "tagging"
        priority = "P1"
        headline = (
            f"<b>${untagged_nec:,.0f}</b> of cloud spend ({untagged_pct:.0f}%) has no owner — "
            "attribution accuracy needs improvement."
        )
        color = COLOR_INEFFICIENCY
    elif waste_pct >= 5:
        primary = "commitment_waste"
        priority = "P1"
        headline = (
            f"<b>${waste_nec:,.0f}</b> of cloud spend ({waste_pct:.0f}%) is idle committed capacity — "
            "optimize before it compounds."
        )
        color = COLOR_INEFFICIENCY
    else:
        primary = "healthy"
        priority = "P3"
        headline = (
            f"Cloud spend is well managed — {waste_pct:.1f}% waste, "
            f"{100-untagged_pct:.1f}% attributed. No immediate action required."
        )
        color = COLOR_OPTIMIZED

    if low_risk_savings > 0 and primary == "commitment_waste":
        sub_headline = (
            f"Do this: release idle commitments "
            f"→ save <b>${low_risk_savings:,.0f}/month</b> · Risk: Low · Time: Immediate · No downtime"
        )
    elif low_risk_savings > 0 and primary == "tagging":
        sub_headline = (
            f"Do this: assign owners in Tagging Coverage "
            f"→ then release idle commitments → save <b>${low_risk_savings:,.0f}/month</b> · Risk: Low"
        )
    elif primary == "tagging":
        sub_headline = (
            "Do this: enforce <code>tag_team</code> at resource creation "
            "→ attribution improves to 95%+ · unlocks full optimization"
        )
    else:
        sub_headline = (
            "Continue monthly monitoring. "
            "Focus on commitment coverage and tagging discipline."
        )

    return Diagnostic(
        total_nec=total_nec,
        untagged_nec=untagged_nec,
        untagged_pct=untagged_pct,
        waste_nec=waste_nec,
        waste_pct=waste_pct,
        low_risk_savings=low_risk_savings,
        primary_issue=primary,
        priority=priority,
        headline=headline,
        sub_headline=sub_headline,
        color=color,
    )


def render_headline(diag: Diagnostic) -> None:
    """Render the executive headline block at the top of a page."""
    badge_bg = {
        "P0": COLOR_BLOCKER,
        "P1": COLOR_INEFFICIENCY,
        "P2": COLOR_INFO,
        "P3": COLOR_OPTIMIZED,
    }[diag.priority]

    st.markdown(
        f"""
<div style="border-left: 6px solid {diag.color};
            background: linear-gradient(90deg, {diag.color}11 0%, transparent 60%);
            padding: 12px 16px 12px 18px; margin-bottom: 8px; border-radius: 4px;">
  <div style="display:flex; align-items:center; gap:10px; margin-bottom:4px;">
    <span style="background:{badge_bg}; color:white; font-weight:700;
                 padding:2px 10px; border-radius:12px; font-size:0.82rem;
                 letter-spacing:0.3px;">{diag.priority}</span>
    <span style="font-size:0.82rem; color:#6b7280; text-transform:uppercase;
                 letter-spacing:0.6px;">Executive Summary</span>
  </div>
  <div style="font-size:1.08rem; font-weight:600; color:#111827; line-height:1.4;">
    {diag.headline}
  </div>
  <div style="font-size:0.95rem; color:#374151; margin-top:4px; line-height:1.4;">
    {diag.sub_headline}
  </div>
</div>
        """.strip(),
        unsafe_allow_html=True,
    )


def render_priority_badge(priority: Priority, label: str | None = None) -> str:
    """Return inline HTML for a priority pill. Use inside st.markdown(..., unsafe_allow_html=True)."""
    bg = {
        "P0": COLOR_BLOCKER,
        "P1": COLOR_INEFFICIENCY,
        "P2": COLOR_INFO,
        "P3": COLOR_OPTIMIZED,
    }[priority]
    text = label or priority
    return (
        f'<span style="background:{bg}; color:white; font-weight:700; '
        f'padding:2px 8px; border-radius:10px; font-size:0.78rem; '
        f'letter-spacing:0.3px;">{text}</span>'
    )


# ---------------------------------------------------------------------------
# Maturity score with improvement guidance (Medium #10)
# ---------------------------------------------------------------------------


@dataclass
class MaturityScore:
    overall:      float
    tagging_score: float
    tagging_level: str
    ownership_score: float
    ownership_level: str
    allocation_score: float
    allocation_level: str
    commitment_score: float
    commitment_level: str
    detect_score: float
    detect_level: str
    forecasting_score: float
    forecasting_level: str
    automation_score: float
    automation_level: str
    guidance:     str   # "To reach 4+/5, do X, Y"


def _score_tagging(pct: float) -> tuple[float, str]:
    if pct <= 5:    return 5.0, "Excellent"
    if pct <= 10:   return 4.0, "Good"
    if pct <= 20:   return 3.0, "Developing"
    if pct <= 40:   return 2.0, "Initiating"
    return 1.0, "Crawl"


def _score_commitment(pct: float) -> tuple[float, str]:
    if pct <= 2:    return 5.0, "Excellent"
    if pct <= 5:    return 4.0, "Good"
    if pct <= 10:   return 3.0, "Developing"
    if pct <= 15:   return 2.0, "Initiating"
    return 1.0, "Crawl"


def _level_from_score(score: float) -> str:
    if score >= 4.0: return "Implemented"
    if score >= 2.0: return "Partial"
    return "Missing"


def compute_maturity(
    df: pd.DataFrame,
    diag: Diagnostic,
    recommendations: list[dict] | None = None,
) -> MaturityScore:
    recommendations = recommendations or []

    tagging_score, tagging_level = _score_tagging(diag.untagged_pct)
    commitment_score, commitment_level = _score_commitment(diag.waste_pct)

    owner_series = df.get("owner_email", pd.Series(dtype=object)).fillna("").astype(str).str.lower()
    owner_coverage = (
        ((owner_series != "") & ~owner_series.str.contains("unassigned")).mean()
        if len(owner_series)
        else 0.0
    )
    ownership_score = round(owner_coverage * 5.0, 1)

    attributed_ratio = (1.0 - diag.untagged_pct / 100.0) if diag.total_nec > 0 else 0.0
    shared_signal = 1.0 if "is_shared_cost" in df.columns and df["is_shared_cost"].notna().any() else 0.5
    allocation_score = round(max(0.0, min(5.0, 5.0 * (0.8 * attributed_ratio + 0.2 * shared_signal))), 1)

    has_commitments = df["discount_type"].isin(["ri", "sp"]).any() if "discount_type" in df.columns else False
    has_waste_signal = (df["nec_waste"].fillna(0) > 0).any() if "nec_waste" in df.columns else False
    has_usage_data = df["nec_used"].notna().any() if "nec_used" in df.columns else False
    has_recommendations = bool(recommendations)
    detect_score = round(
        5.0 * (
            sum([bool(has_commitments), bool(has_waste_signal), bool(has_usage_data), has_recommendations]) / 4
        ),
        1,
    )

    n_months = df["billing_month"].nunique() if "billing_month" in df.columns else 0
    if n_months >= 3:
        forecasting_score = 5.0
    elif n_months == 2:
        forecasting_score = 3.0
    elif n_months == 1:
        forecasting_score = 1.5
    else:
        forecasting_score = 0.0

    if recommendations:
        total = len(recommendations)
        auto_safe = sum(1 for rec in recommendations if rec.get("action_safety") == "auto_safe")
        approval = sum(1 for rec in recommendations if rec.get("action_safety") == "approval_required")
        blocked = sum(1 for rec in recommendations if rec.get("action_safety") == "blocked")
        automation_ratio = (auto_safe + 0.5 * approval) / total if total else 0.0
        automation_penalty = 0.5 if total and blocked / total > 0.3 else 0.0
        automation_score = round(max(0.0, min(5.0, 5.0 * automation_ratio - automation_penalty)), 1)
    else:
        automation_score = 0.0

    dimension_scores = [
        tagging_score,
        ownership_score,
        allocation_score,
        commitment_score,
        detect_score,
        forecasting_score,
        automation_score,
    ]
    overall = round(sum(dimension_scores) / len(dimension_scores), 1) if dimension_scores else 0.0

    gaps: list[str] = []
    if tagging_score < 4.0:
        gaps.append(
            f"reduce unattributed spend from {diag.untagged_pct:.0f}% to below 10% with enforced `tag_team` policy"
        )
    if ownership_score < 4.0:
        gaps.append("close owner coverage gaps for unassigned workloads and action owners")
    if allocation_score < 4.0:
        gaps.append("improve attribution and shared-cost allocation consistency across clouds")
    if commitment_score < 4.0:
        gaps.append(
            f"reduce commitment waste from {diag.waste_pct:.1f}% to below 5% through release/right-sizing"
        )
    if detect_score < 4.0:
        gaps.append("broaden waste-detection signal coverage and keep recommendations flowing from the same mart")
    if forecasting_score < 4.0:
        gaps.append("retain at least 3 months of billing history for stable forecasting")
    if automation_score < 4.0:
        gaps.append("increase the share of auto-safe or pre-approved optimization actions")

    if not gaps:
        guidance = (
            "All seven dimensions are at **Implemented** - maintain current operating discipline "
            "and monitor drift month-over-month."
        )
    else:
        target = 5.0 if overall >= 4.0 else 4.0
        guidance = f"**To reach {target:.1f}/5**, in priority order:\n\n- " + "\n- ".join(gaps)

    return MaturityScore(
        overall=overall,
        tagging_score=tagging_score,
        tagging_level=tagging_level,
        ownership_score=ownership_score,
        ownership_level=_level_from_score(ownership_score),
        allocation_score=allocation_score,
        allocation_level=_level_from_score(allocation_score),
        commitment_score=commitment_score,
        commitment_level=commitment_level,
        detect_score=detect_score,
        detect_level=_level_from_score(detect_score),
        forecasting_score=forecasting_score,
        forecasting_level=_level_from_score(forecasting_score),
        automation_score=automation_score,
        automation_level=_level_from_score(automation_score),
        guidance=guidance,
    )


# ---------------------------------------------------------------------------
# Operational action metadata (Critical #4 + Add #4)
# ---------------------------------------------------------------------------

# Map recommendation action → (owner_role, automation_level, sla)
ACTION_OPS: dict[str, dict[str, str]] = {
    "release_commitment": {
        "owner":      "Cloud Platform / FinOps",
        "automation": "Approval-required",
        "sla":        "This week",
        "automation_badge": "Requires approval",
    },
    "resize_down": {
        "owner":      "Team owning the workload",
        "automation": "Automatable",
        "sla":        "Next cycle",
        "automation_badge": "Auto-safe",
    },
    "remove_resource": {
        "owner":      "Team owning the workload",
        "automation": "Manual verification",
        "sla":        "Immediate",
        "automation_badge": "Manual review",
    },
}


def enrich_recommendation(rec: dict) -> dict:
    """Attach owner, automation, and SLA metadata to a recommendation."""
    ops = ACTION_OPS.get(
        rec.get("action", ""),
        {
            "owner": "Unassigned",
            "automation": "Manual review",
            "sla": "This week",
            "automation_badge": "Manual review",
        },
    )
    team = rec.get("allocated_team", "unattributed")
    team_lbl = TEAM_LABELS.get(team, team.replace("-", " ").title())
    owner = team_lbl if ops["owner"].startswith("Team owning") else ops["owner"]

    action_safety = rec.get("action_safety")
    if action_safety == "blocked":
        automation = "Blocked"
        automation_badge = "Blocked"
    elif action_safety == "manual_review":
        automation = "Manual review"
        automation_badge = "Manual review"
    elif action_safety == "approval_required" or rec.get("approval_required"):
        automation = "Approval-required"
        automation_badge = "Requires approval"
    else:
        automation = ops["automation"]
        automation_badge = ops["automation_badge"]

    sla = ops["sla"]
    if action_safety == "blocked" or rec.get("risk") == "High":
        sla = "Next cycle"
    elif action_safety == "auto_safe" and rec.get("estimated_savings", 0) >= 100:
        sla = "Immediate"

    return {
        **rec,
        "owner": owner,
        "automation": automation,
        "automation_badge": automation_badge,
        "sla": sla,
    }
