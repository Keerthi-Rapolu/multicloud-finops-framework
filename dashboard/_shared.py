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

# ---------------------------------------------------------------------------
# Data loading — deep-link safe
# ---------------------------------------------------------------------------

_DB_PATH = Path(__file__).resolve().parents[1] / "finops_dbt.duckdb"


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


def content_hash(df: pd.DataFrame) -> int:
    """Stable cache key — unlike id(df) this hits when data is unchanged."""
    return int(pd.util.hash_pandas_object(df, index=True).sum())


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
    tag_score:    float
    tag_level:    str
    waste_score:  float
    waste_level:  str
    nec_score:    float
    nec_level:    str
    detect_score: float
    detect_level: str
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


def compute_maturity(df: pd.DataFrame, diag: Diagnostic) -> MaturityScore:
    tag_score,   tag_level   = _score_tagging(diag.untagged_pct)
    waste_score, waste_level = _score_commitment(diag.waste_pct)

    # NEC modeling — data consistency of the NEC equation
    if diag.total_nec > 0:
        nec_used_sum  = df["nec_used"].fillna(0).sum()  if "nec_used"  in df.columns else 0.0
        nec_waste_sum = df["nec_waste"].fillna(0).sum() if "nec_waste" in df.columns else 0.0
        invariant_err = abs(diag.total_nec - (nec_used_sum + nec_waste_sum))
        consistency   = max(0.0, 1.0 - invariant_err / diag.total_nec)
        nec_score     = round(5.0 * consistency, 1)
    else:
        nec_score = 0.0

    # Waste detection — signal coverage
    has_commitments  = df["discount_type"].isin(["ri", "sp"]).any() if "discount_type" in df.columns else False
    has_waste_signal = (df["nec_waste"].fillna(0) > 0).any()        if "nec_waste"     in df.columns else False
    has_usage_data   = df["nec_used"].notna().any()                 if "nec_used"      in df.columns else False
    signals          = sum([bool(has_commitments), bool(has_waste_signal), bool(has_usage_data)])
    detect_score     = round(5.0 * (signals / 3), 1)

    overall = round((tag_score + waste_score + nec_score + detect_score) / 4, 1)

    # Build improvement guidance (Medium #10)
    gaps: list[str] = []
    if tag_score < 4.0:
        gaps.append(
            f"reduce untagged NEC from {diag.untagged_pct:.0f}% → <10% "
            "(enforce `tag_team` at resource creation)"
        )
    if waste_score < 4.0:
        gaps.append(
            f"reduce commitment waste from {diag.waste_pct:.1f}% → <5% "
            "(right-size or release idle RI/SP)"
        )
    if nec_score < 4.0:
        gaps.append("harden NEC equation consistency in the mart layer")
    if detect_score < 4.0:
        gaps.append("add commitment + usage signals to the billing pipeline")

    if not gaps:
        guidance = (
            "All four dimensions are at **Implemented** — maintain current discipline "
            "and monitor drift month-over-month."
        )
    else:
        target = 5.0 if overall >= 4.0 else 4.0
        guidance = (
            f"**To reach {target:.1f}/5**, in priority order:\n\n- "
            + "\n- ".join(gaps)
        )

    return MaturityScore(
        overall=overall,
        tag_score=tag_score,     tag_level=tag_level,
        waste_score=waste_score, waste_level=waste_level,
        nec_score=nec_score,     nec_level=_level_from_score(nec_score),
        detect_score=detect_score, detect_level=_level_from_score(detect_score),
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
        "automation_badge": "⚠ Requires approval",
    },
    "resize_down": {
        "owner":      "Team owning the workload",
        "automation": "Automatable",
        "sla":        "Next cycle",
        "automation_badge": "✔ Fully automatable",
    },
    "remove_resource": {
        "owner":      "Team owning the workload",
        "automation": "Manual verification",
        "sla":        "Immediate",
        "automation_badge": "⚠ Manual verification",
    },
}


def enrich_recommendation(rec: dict) -> dict:
    """Attach Owner / Automation / SLA metadata to a recommendation."""
    ops = ACTION_OPS.get(
        rec.get("action", ""),
        {"owner": "Unassigned", "automation": "Manual",
         "sla": "This week", "automation_badge": "⚠ Manual verification"},
    )
    team = rec.get("allocated_team", "unattributed")
    team_lbl = TEAM_LABELS.get(team, team.replace("-", " ").title())
    # Override owner with the team if the action is team-local
    owner = team_lbl if ops["owner"].startswith("Team owning") else ops["owner"]

    # SLA escalation for very high confidence + high savings
    sla = ops["sla"]
    if rec.get("risk") == "Low" and rec.get("estimated_savings", 0) >= 100:
        sla = "Immediate"
    elif rec.get("risk") == "High":
        sla = "Next cycle"

    return {
        **rec,
        "owner":            owner,
        "automation":       ops["automation"],
        "automation_badge": ops["automation_badge"],
        "sla":              sla,
    }
