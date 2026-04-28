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
LABEL_ESTIMATED_MONTHLY_SAVINGS = "Realization-adj. Savings"
LABEL_ACTIONABLE_OPPORTUNITY = "Best-case Actionable Opportunity"
LABEL_UNATTRIBUTED_SPEND = "Unattributed Spend"
LABEL_UNASSIGNED_OWNER = "Unassigned Owner"

ROOT_CAUSE_SIGNAL_FALLBACK = {
    "missing_owner_team_cost_center_environment_tags": "tagging_gap",
    "cannot_allocate_cost_to_accountable_team": "unattributed_cost_gap",
    "unused_ri_sp_cud_capacity": "commitment_waste",
    "no_activity_or_near_zero_cost": "zombie_resource",
    "billing_side_idle_compute_proxy": "idle_compute_proxy",
    "shared_services_concentrated_to_single_team_or_account": "shared_cost_concentration",
    "abnormal_nec_movement_from_billing_trend": "cost_anomaly",
    "month_end_nec_run_rate_exceeds_expected_baseline": "forecasted_month_end_risk",
}

ACTION_SIGNAL_FALLBACK = {
    "enforce_tags": "tagging_gap",
    "release_commitment": "commitment_waste",
    "resize_down": "idle_compute_proxy",
    "remove_resource": "zombie_resource",
    "rebalance_shared_cost": "shared_cost_concentration",
    "investigate_anomaly": "cost_anomaly",
    "review_forecast_risk": "forecasted_month_end_risk",
}

DEFAULT_METRIC_NAME_BY_SIGNAL = {
    "tagging_gap": "missing_required_tag_pct",
    "unattributed_cost_gap": "unattributed_nec_pct",
    "commitment_waste": "commitment_utilization_pct",
    "commitment_mismatch": "commitment_utilization_pct",
    "unused_commitment": "unused_commitment_cost",
    "underutilized_commitment": "commitment_utilization_pct",
    "idle_compute_proxy": "nec_per_vcpu_proxy",
    "idle_resource": "nec_per_vcpu_proxy",
    "idle_compute": "nec_per_vcpu_proxy",
    "zombie_resource": "nec_impact_usd",
    "shared_cost_concentration": "shared_cost_share_pct",
    "cost_anomaly": "anomaly_score",
    "forecasted_month_end_risk": "forecast_growth_pct",
}

DEFAULT_THRESHOLD_BY_SIGNAL = {
    "tagging_gap": 0.10,
    "unattributed_cost_gap": 0.10,
    "commitment_waste": 0.75,
    "commitment_mismatch": 0.75,
    "unused_commitment": 0.0,
    "underutilized_commitment": 0.75,
    "idle_compute_proxy": 5.0,
    "idle_resource": 5.0,
    "idle_compute": 5.0,
    "zombie_resource": 2.0,
    "shared_cost_concentration": 0.40,
    "cost_anomaly": 2.0,
    "forecasted_month_end_risk": 0.10,
}

DEFAULT_DIRECTION_BY_SIGNAL = {
    "commitment_waste": "below",
    "commitment_mismatch": "below",
    "underutilized_commitment": "below",
    "idle_compute_proxy": "below",
    "idle_resource": "below",
    "idle_compute": "below",
    "zombie_resource": "below",
}

# ---------------------------------------------------------------------------
# Savings noise filter
# ---------------------------------------------------------------------------

SAVINGS_NOISE_THRESHOLD_USD: float = 10.0
"""Recommendations below this USD threshold are filtered from priority lists to avoid small-signal noise."""

# ---------------------------------------------------------------------------
# Canonical signal → action mapping (explicit, not narrative)
# ---------------------------------------------------------------------------

SIGNAL_ACTION_MAP: list[dict] = [
    {
        "signal_name":       "unused_commitment",
        "trigger_condition": "RI/SP utilisation < 75% of purchased capacity for the billing period",
        "action":            "release_commitment",
        "expected_impact":   "Eliminate idle reservation cost — recovery rate 100% of unused portion",
        "risk_model":        "Low — no service impact; early-exit fee applies for 1-year+ RIs",
    },
    {
        "signal_name":       "underutilized_commitment",
        "trigger_condition": "RI/SP utilisation < 75% (partial underuse, not fully idle)",
        "action":            "release_commitment",
        "expected_impact":   "Recover 60% of excess committed capacity cost",
        "risk_model":        "High — partial release may expose demand spikes; model future usage first",
    },
    {
        "signal_name":       "idle_compute_proxy",
        "trigger_condition": "NEC/vCPU proxy < $5/month (billing-side indicator only, not runtime telemetry)",
        "action":            "resize_down",
        "expected_impact":   "60% cost reduction on the right-sized instance",
        "risk_model":        "Medium — billing proxy only; runtime CPU/mem telemetry confirmation required before acting",
    },
    {
        "signal_name":       "zombie_resource",
        "trigger_condition": "Resource NEC < $2/month (near-zero activity — effectively dormant)",
        "action":            "remove_resource",
        "expected_impact":   "100% elimination of orphan spend",
        "risk_model":        "Low — verify no silent dependency or scheduled wake-up before deletion",
    },
    {
        "signal_name":       "tagging_gap",
        "trigger_condition": "Required tag (team, environment, cost_center) missing on ≥ 10% of NEC",
        "action":            "enforce_tags",
        "expected_impact":   "Governance only — no direct NEC reduction; enables all downstream optimization",
        "risk_model":        "None — metadata operation with no infrastructure impact",
    },
    {
        "signal_name":       "unattributed_cost_gap",
        "trigger_condition": "Untagged NEC ≥ 10% of total NEC for the billing period",
        "action":            "assign_owner",
        "expected_impact":   "Accountability improvement — unlocks reliable team-level chargeback",
        "risk_model":        "None — owner assignment is an accounting action",
    },
    {
        "signal_name":       "shared_cost_concentration",
        "trigger_condition": "> 40% of shared infrastructure NEC attributed to one team in the period",
        "action":            "rebalance_shared_cost",
        "expected_impact":   "More accurate chargeback — no direct NEC reduction",
        "risk_model":        "Low — accounting rebalance only; may affect team budget allocations",
    },
    {
        "signal_name":       "cost_anomaly",
        "trigger_condition": "NEC z-score > 2.0 versus trailing 3-month per-team baseline",
        "action":            "investigate_anomaly",
        "expected_impact":   "Root cause identification — actual savings depend on findings",
        "risk_model":        "Low — investigation only; no infrastructure change required",
    },
    {
        "signal_name":       "forecasted_month_end_risk",
        "trigger_condition": "Month-end NEC projection ≥ 10% above trailing 3-month average",
        "action":            "review_forecast_risk",
        "expected_impact":   "Early warning — prevents unbudgeted overspend",
        "risk_model":        "None — forecast review is informational",
    },
]

# ---------------------------------------------------------------------------
# Data loading — deep-link safe
# ---------------------------------------------------------------------------

_DB_PATH = Path(__file__).resolve().parents[1] / "finops_dbt.duckdb"
_RECOMMENDATION_ACTIONS_PATH = Path(__file__).resolve().parents[1] / "data" / "recommendation_actions.json"
_RECOMMENDATION_ACTIONS_FLAT_PATH = Path(__file__).resolve().parents[1] / "data" / "recommendation_actions_flat.csv"


@dataclass
class FinopsSummaryMetrics:
    total_list_cost: float
    total_nec_used: float
    total_nec_waste: float
    total_nec: float
    total_commitment_waste: float
    total_unattributed_cost: float
    total_recoverable_savings: float

    @property
    def total_savings(self) -> float:
        return self.total_list_cost - self.total_nec

    @property
    def savings_pct(self) -> float:
        return (self.total_savings / self.total_list_cost * 100.0) if self.total_list_cost else 0.0

    @property
    def commitment_waste_pct(self) -> float:
        return (self.total_commitment_waste / self.total_nec * 100.0) if self.total_nec else 0.0

    @property
    def unattributed_pct(self) -> float:
        return (self.total_unattributed_cost / self.total_nec * 100.0) if self.total_nec else 0.0

    @property
    def recoverable_savings_pct(self) -> float:
        return (self.total_recoverable_savings / self.total_nec * 100.0) if self.total_nec else 0.0

    @property
    def total_governance_gap(self) -> float:
        return self.total_unattributed_cost

    @property
    def total_optimization_opportunity(self) -> float:
        return self.total_recoverable_savings


# ---------------------------------------------------------------------------
# Savings hierarchy — strict 4-layer model (enforced globally across all pages)
# ---------------------------------------------------------------------------


@dataclass
class SavingsHierarchy:
    """
    Strict 4-layer savings hierarchy. All pages must use this model — mixing layers is a
    hard credibility failure (deterministic page + probabilistic page = broken system).

    Layer 1 — inefficiency_signal    : raw billing-side signal magnitude (the problem, not the solution).
    Layer 2 — recoverable_opportunity: after applying per-signal recovery rates.
    Layer 3 — actionable_savings     : recoverable filtered to low/medium risk only.
    Layer 4 — realized_projection    : actionable × realization_rate (execution probability).
    """

    inefficiency_signal: float      # Layer 1: raw cost of the signal
    recoverable_opportunity: float  # Layer 2: post recovery-rate
    actionable_savings: float       # Layer 3: low/medium risk only
    realized_projection: float      # Layer 4: actionable × realization_rate
    realization_rate: float         # e.g. 0.62 — from forecast engine or risk profile

    def layer_label(self) -> str:
        """Plain-text pipeline string safe for st.markdown / st.info.
        $ is escaped as \\$ so Streamlit does not interpret pairs as LaTeX delimiters."""
        return (
            f"Savings pipeline: "
            f"**Signal** \\${self.inefficiency_signal:,.0f}/month"
            f" → **Recoverable** \\${self.recoverable_opportunity:,.0f}/month (recovery rates applied)"
            f" → **Best-case actionable** \\${self.actionable_savings:,.0f}/month (low/med risk only)"
            f" → **Realization-adjusted** \\${self.realized_projection:,.0f}/month"
            f" ({self.realization_rate:.0%} execution rate)"
        )

    def layer_label_html(self) -> str:
        """HTML version for use with unsafe_allow_html=True — preserves dollar signs cleanly."""
        def _fmt(v: float) -> str:
            return f"${v:,.0f}/month"
        return (
            f"<b>Savings pipeline:</b> "
            f"<b>Signal</b> {_fmt(self.inefficiency_signal)}"
            f" &rarr; <b>Recoverable</b> {_fmt(self.recoverable_opportunity)}"
            f" &rarr; <b>Best-case actionable</b> {_fmt(self.actionable_savings)} <em>(low/med risk)</em>"
            f" &rarr; <b>Realization-adjusted</b> {_fmt(self.realized_projection)}"
            f" <em>(&times; {self.realization_rate:.0%} execution rate)</em>"
        )


def compute_savings_hierarchy(
    recommendations: list[dict],
    *,
    realization_rate: float | None = None,
    noise_threshold_usd: float = 0.0,
) -> SavingsHierarchy:
    """
    Compute the strict 4-layer savings hierarchy from a recommendation list.

    noise_threshold_usd filters out small-signal noise (zombie/idle < $10) before aggregation.
    realization_rate is auto-derived from the risk profile when None.
    """
    recs = [
        r for r in recommendations
        if float(r.get("estimated_savings", 0.0) or 0.0) >= noise_threshold_usd
    ]

    # Layer 1: raw signal magnitude (cost of the underlying problem)
    inefficiency_signal = sum(
        float(r.get("current_cost", 0.0) or r.get("nec_impact_usd", 0.0) or 0.0)
        for r in recs
    )

    # Layer 2: recoverable opportunity (after signal-specific recovery rates)
    recoverable_opportunity = sum(float(r.get("estimated_savings", 0.0) or 0.0) for r in recs)

    # Layer 3: actionable savings (low/medium risk only — high risk excluded)
    actionable_savings = sum(
        float(r.get("estimated_savings", 0.0) or 0.0)
        for r in recs
        if r.get("risk", "High") in ("Low", "Medium")
    )

    # Layer 4: realized projection (execution probability applied)
    if realization_rate is None:
        low_ct  = sum(1 for r in recs if r.get("risk") == "Low")
        high_ct = sum(1 for r in recs if r.get("risk") == "High")
        if not recs:
            realization_rate = 0.70
        elif high_ct == 0 and low_ct > 0:
            realization_rate = 0.80  # all low-risk: higher execution confidence
        elif high_ct == 0:
            realization_rate = 0.70  # mixed low/medium
        else:
            realization_rate = 0.62  # includes high-risk actions

    realized_projection = actionable_savings * realization_rate
    return SavingsHierarchy(
        inefficiency_signal=inefficiency_signal,
        recoverable_opportunity=recoverable_opportunity,
        actionable_savings=actionable_savings,
        realized_projection=realized_projection,
        realization_rate=realization_rate,
    )


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


@st.cache_data(show_spinner="Loading billing data...")
def load_df(month: str | None) -> pd.DataFrame:
    from allocation.nec_model import load_billing_data

    return load_billing_data(_DB_PATH, billing_month=month or None)


@st.cache_data(show_spinner=False)
def load_finops_summary(month: str | None) -> pd.DataFrame:
    import duckdb

    if not _DB_PATH.exists():
        return pd.DataFrame()

    with duckdb.connect(str(_DB_PATH), read_only=True) as con:
        exists = bool(
            con.execute(
                """
                select count(*)
                from information_schema.tables
                where table_schema = 'marts'
                  and table_name = 'fct_finops_summary'
                """
            ).fetchone()[0]
        )
        if not exists:
            return pd.DataFrame()
        return con.execute(
            """
            select *
            from marts.fct_finops_summary
            where (? is null or billing_month = ?)
            """,
            [month, month],
        ).fetchdf()


def _summary_from_df(df: pd.DataFrame) -> FinopsSummaryMetrics:
    total_list_cost = float(df.get("list_cost", pd.Series(dtype=float)).fillna(0.0).sum())
    total_nec_used = float(df.get("nec_used", pd.Series(dtype=float)).fillna(0.0).sum())
    total_nec_waste = float(df.get("nec_waste", pd.Series(dtype=float)).fillna(0.0).sum())
    total_nec = total_nec_used + total_nec_waste
    if not df.empty and {"is_commitment_waste", "nec_waste"}.issubset(df.columns):
        total_commitment_waste = float(
            df.loc[df["is_commitment_waste"].fillna(False), "nec_waste"].sum()
        )
    else:
        total_commitment_waste = total_nec_waste
    if not df.empty and {"is_tagged", "nec"}.issubset(df.columns):
        total_unattributed_cost = float(
            df.loc[~df["is_tagged"].fillna(False), "nec"].sum()
        )
    else:
        total_unattributed_cost = 0.0

    return FinopsSummaryMetrics(
        total_list_cost=total_list_cost,
        total_nec_used=total_nec_used,
        total_nec_waste=total_nec_waste,
        total_nec=total_nec,
        total_commitment_waste=total_commitment_waste,
        total_unattributed_cost=total_unattributed_cost,
        total_recoverable_savings=0.0,
    )


def compute_finops_summary_metrics(
    summary_df: pd.DataFrame,
    *,
    clouds: str | list[str] | None = None,
    teams: list[str] | None = None,
    fallback_df: pd.DataFrame | None = None,
) -> FinopsSummaryMetrics:
    if summary_df.empty:
        if fallback_df is not None:
            return _summary_from_df(fallback_df)
        return FinopsSummaryMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    scoped = summary_df.copy()
    if clouds:
        cloud_values = [clouds] if isinstance(clouds, str) else list(clouds)
        cloud_values = [c for c in cloud_values if c != "All"]
        if cloud_values:
            scoped = scoped[scoped["cloud_provider"].isin(cloud_values)]
    if teams:
        scoped = scoped[scoped["team"].isin(teams)]

    if scoped.empty:
        return FinopsSummaryMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    return FinopsSummaryMetrics(
        total_list_cost=float(scoped["total_list_cost"].sum()),
        total_nec_used=float(scoped.get("total_nec_used", pd.Series(dtype=float)).sum()),
        total_nec_waste=float(scoped.get("total_nec_waste", pd.Series(dtype=float)).sum()),
        total_nec=float(scoped["total_nec"].sum()),
        total_commitment_waste=float(scoped["total_commitment_waste"].sum()),
        total_unattributed_cost=float(scoped["total_unattributed_cost"].sum()),
        total_recoverable_savings=float(scoped["total_recoverable_savings"].sum()),
    )


@st.cache_data(show_spinner=False)
def load_canonical_signals(month: str | None, cloud: str) -> pd.DataFrame:
    import duckdb

    if not _DB_PATH.exists():
        return pd.DataFrame()

    with duckdb.connect(str(_DB_PATH), read_only=True) as con:
        def _table_exists(name: str) -> bool:
            return bool(con.execute(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema='marts' AND table_name=?", [name]
            ).fetchone()[0])

        if _table_exists("fct_finops_signals"):
            query = """
                select *
                from marts.fct_finops_signals
                where (? is null or billing_month = ?)
                  and (? = 'All' or lower(cloud_provider) = lower(?))
            """
        elif _table_exists("fct_signals"):
            query = """
                select *
                from marts.fct_signals
                where (? is null or billing_month = ?)
                  and (? = 'All' or lower(cloud) = lower(?))
            """
        else:
            return pd.DataFrame()
        return con.execute(query, [month, month, cloud, cloud]).fetchdf()


@st.cache_data(show_spinner=False)
def load_canonical_recommendations(month: str | None, cloud: str) -> pd.DataFrame:
    import duckdb

    if not _DB_PATH.exists():
        return pd.DataFrame()

    with duckdb.connect(str(_DB_PATH), read_only=True) as con:
        def _table_exists(name: str) -> bool:
            return bool(con.execute(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema='marts' AND table_name=?", [name]
            ).fetchone()[0])

        if _table_exists("fct_finops_recommendations"):
            query = """
                select *
                from marts.fct_finops_recommendations
                where (? is null or billing_month = ?)
                  and (? = 'All' or lower(cloud_provider) = lower(?))
            """
        elif _table_exists("fct_recommendations"):
            query = """
                select *
                from marts.fct_recommendations
                where (? is null or billing_month = ?)
                  and (? = 'All' or lower(cloud) = lower(?))
            """
        else:
            return pd.DataFrame()
        return con.execute(query, [month, month, cloud, cloud]).fetchdf()


@st.cache_data(show_spinner=False)
def load_canonical_forecast(month: str | None, cloud: str) -> pd.DataFrame:
    import duckdb

    if not _DB_PATH.exists():
        return pd.DataFrame()

    with duckdb.connect(str(_DB_PATH), read_only=True) as con:
        exists = con.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema='marts' AND table_name='fct_month_end_forecast'"
        ).fetchone()[0]
        if not exists:
            return pd.DataFrame()
        query = """
            select *
            from marts.fct_month_end_forecast
            where (? is null or target_month = ?)
              and (? = 'All' or lower(cloud) = lower(?))
        """
        return con.execute(query, [month, month, cloud, cloud]).fetchdf()


def normalize_canonical_recommendations(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []

    recs = df.copy()
    if "cloud" not in recs.columns and "cloud_provider" in recs.columns:
        recs["cloud"] = recs["cloud_provider"]
    if "owner" not in recs.columns and "owner_email" in recs.columns:
        recs["owner"] = recs["owner_email"]
    if "estimated_savings_usd" not in recs.columns and "savings_estimate_usd" in recs.columns:
        recs["estimated_savings_usd"] = recs["savings_estimate_usd"]
    if "confidence_score" not in recs.columns and "confidence" in recs.columns:
        recs["confidence_score"] = recs["confidence"]
    if "threshold" not in recs.columns:
        recs["threshold"] = recs.get("signal_type", pd.Series(dtype=str)).map(DEFAULT_THRESHOLD_BY_SIGNAL)
    if "metric_value" not in recs.columns:
        recs["metric_value"] = 0.0
    recs["team"] = recs["team"].fillna("unattributed").astype(str)
    recs["cloud"] = recs["cloud"].fillna("unknown").astype(str)
    recs["owner"] = (
        recs["owner"]
        .fillna("unassigned@example.com")
        .astype(str)
        .str.replace("@company.com", "@example.com", regex=False)
    )
    recs["application"] = recs["application"].fillna("unassigned").astype(str)
    recs["environment"] = recs["environment"].fillna("nonprod").astype(str)
    recs["workload_criticality"] = recs["workload_criticality"].fillna("medium").astype(str)
    recs["sla_tier"] = recs["sla_tier"].fillna("silver").astype(str)
    if "signal_type" not in recs.columns:
        if "root_cause_type" in recs.columns:
            recs["signal_type"] = recs["root_cause_type"].map(ROOT_CAUSE_SIGNAL_FALLBACK)
        else:
            recs["signal_type"] = None
    if recs["signal_type"].isna().any() and "action_type" in recs.columns:
        recs["signal_type"] = recs["signal_type"].fillna(recs["action_type"].map(ACTION_SIGNAL_FALLBACK))
    recs["signal_type"] = recs["signal_type"].fillna("unclassified_issue").astype(str)
    if "metric_name" not in recs.columns:
        recs["metric_name"] = recs["signal_type"].map(DEFAULT_METRIC_NAME_BY_SIGNAL)
    recs["metric_name"] = (
        recs["metric_name"]
        .fillna(recs["signal_type"].map(DEFAULT_METRIC_NAME_BY_SIGNAL))
        .fillna("normalized_cost_signal")
        .astype(str)
    )
    if "direction" not in recs.columns:
        recs["direction"] = recs["signal_type"].map(DEFAULT_DIRECTION_BY_SIGNAL)
    recs["direction"] = recs["direction"].fillna(
        recs["signal_type"].map(DEFAULT_DIRECTION_BY_SIGNAL)
    ).fillna("above").astype(str)
    recs["threshold"] = recs["threshold"].fillna(
        recs["signal_type"].map(DEFAULT_THRESHOLD_BY_SIGNAL)
    ).fillna(0.0).astype(float)
    recs["metric_value"] = recs["metric_value"].fillna(0.0).astype(float)
    if "time_to_value_days" not in recs.columns:
        if "action_type" in recs.columns:
            recs["time_to_value_days"] = recs["action_type"].map(
                {
                    "enforce_tags": 3,
                    "release_commitment": 7,
                    "resize_down": 7,
                    "remove_resource": 3,
                    "rebalance_shared_cost": 14,
                    "investigate_anomaly": 7,
                    "review_forecast_risk": 7,
                }
            ).fillna(7)
        else:
            recs["time_to_value_days"] = 7
    recs["resource_id"] = recs["resource_id"].fillna("").astype(str)
    recs["allocated_team"] = recs["team"]
    recs["cloud_provider"] = recs["cloud"]
    recs["action"] = recs["action_type"]
    recs["current_cost"] = recs["nec_impact_usd"].astype(float)
    recs["estimated_savings"] = recs["estimated_savings_usd"].astype(float)
    recs["priority_score"] = recs["priority_score"].astype(float) * 100.0
    recs["confidence"] = recs["confidence_score"].astype(float)
    risk_max = float(recs["risk_score"].astype(float).max()) if len(recs) else 0.0
    if risk_max <= 1.0:
        recs["risk_score"] = (recs["risk_score"].astype(float) * 100.0).round().astype(int)
    else:
        recs["risk_score"] = recs["risk_score"].astype(float).round().astype(int)
    recs["effort"] = recs["effort_score"].map(
        lambda v: "Low" if float(v) <= 2 else "Medium" if float(v) <= 3 else "High"
    )
    recs["time_to_realize"] = recs["time_to_value_days"].map(
        lambda v: "Immediate" if int(v) <= 3 else "1 week" if int(v) <= 14 else "1 month"
    )
    recs["roi_score"] = (
        (recs["estimated_savings"].astype(float) * 12.0) / recs["effort_score"].astype(float).clip(lower=1.0)
    ).round(2)
    recs["owner_email"] = recs["owner"]
    recs["waste_type"] = recs["signal_type"]
    recs["risk"] = recs["risk_score"].map(
        lambda v: "High" if int(v) >= 70 else "Medium" if int(v) >= 35 else "Low"
    )
    recs["action_safety"] = recs.apply(
        lambda row: (
            "blocked" if row["risk_score"] >= 85 else
            "manual_review" if row["risk_score"] >= 65 else
            "approval_required" if bool(row["approval_required"]) else
            "auto_safe"
        ),
        axis=1,
    )
    recs["confidence_reason"] = recs.apply(
        lambda row: (
            f"Confidence {row['confidence']:.0%} from canonical signal '{row['signal_type']}' "
            f"using {row['metric_name']} against threshold {row['threshold']}."
        ),
        axis=1,
    )
    recs["risk_reason"] = recs.apply(
        lambda row: (
            f"Risk is driven by {row['environment']} environment, "
            f"{row['workload_criticality']} criticality, {row['sla_tier']} SLA, "
            f"and `{row['action']}` action type."
        ),
        axis=1,
    )
    recs["evidence_summary"] = recs.apply(
        lambda row: (
            f"Signal '{row['signal_type']}' fired because {row['metric_name']} was "
            f"{float(row['metric_value']):.3f} versus threshold {float(row['threshold']):.3f} "
            f"with '{row['direction']}' threshold logic."
        ),
        axis=1,
    )
    recs["savings_pct"] = recs.apply(
        lambda row: (float(row["estimated_savings"]) / max(float(row["current_cost"]), 1.0) * 100.0),
        axis=1,
    )
    return recs.to_dict("records")


def normalize_canonical_signals(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    signals = df.copy()
    if "cloud" not in signals.columns and "cloud_provider" in signals.columns:
        signals["cloud"] = signals["cloud_provider"]
    if "confidence_score" not in signals.columns and "confidence" in signals.columns:
        signals["confidence_score"] = signals["confidence"]
    signals["team"] = signals["team"].fillna("unattributed").astype(str)
    signals["cloud"] = signals["cloud"].fillna("unknown").astype(str)
    signals["resource_id"] = signals["resource_id"].fillna(signals["entity_id"]).astype(str)
    signals["signal_type"] = signals["signal_type"].fillna("unclassified_issue").astype(str)
    signals["allocated_team"] = signals["team"]
    signals["cloud_provider"] = signals["cloud"]
    signals["waste_type"] = signals["signal_type"]
    signals["nec_waste"] = 0.0
    signals["nec_used"] = signals["metric_value"].astype(float)
    signals["confidence"] = signals["confidence_score"].astype(float)
    return signals.to_dict("records")


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
        actions = json.load(handle)
    _sync_recommendation_actions_flat(actions)
    return actions


def _sync_recommendation_actions_flat(actions: dict[str, dict]) -> None:
    """Mirror recommendation action state into a flat CSV for dbt/DuckDB models."""
    _RECOMMENDATION_ACTIONS_FLAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "recommendation_id",
        "action_status",
        "created_date",
        "approved_at",
        "implementation_date",
        "verified_at",
        "action_owner",
        "expected_savings",
        "realized_savings",
        "verification_status",
        "verification_notes",
        "realization_rate",
    ]
    rows = []
    for recommendation_id, payload in sorted(actions.items()):
        expected = float(payload.get("expected_savings", 0.0) or 0.0)
        realized = float(payload.get("realized_savings", 0.0) or 0.0)
        realization_rate = (realized / expected) if expected > 0 else 0.0
        rows.append(
            {
                "recommendation_id": recommendation_id,
                "action_status": payload.get("action_status", "recommended"),
                "created_date": payload.get("created_date", ""),
                "approved_at": payload.get("approved_at", ""),
                "implementation_date": payload.get("implementation_date", ""),
                "verified_at": payload.get("verified_at", ""),
                "action_owner": payload.get("action_owner", ""),
                "expected_savings": expected,
                "realized_savings": realized,
                "verification_status": payload.get("verification_status", "pending"),
                "verification_notes": payload.get("verification_notes", ""),
                "realization_rate": round(realization_rate, 4),
            }
        )
    pd.DataFrame(rows, columns=columns).to_csv(_RECOMMENDATION_ACTIONS_FLAT_PATH, index=False)


def save_recommendation_action(recommendation_id: str, payload: dict) -> None:
    """Persist lifecycle state for one recommendation."""
    actions = load_recommendation_actions()
    actions[recommendation_id] = payload
    _RECOMMENDATION_ACTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_RECOMMENDATION_ACTIONS_PATH, "w", encoding="utf-8") as handle:
        json.dump(actions, handle, indent=2, sort_keys=True)
    _sync_recommendation_actions_flat(actions)


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
                "verification_status": saved.get("verification_status", "pending"),
                "verification_notes": saved.get("verification_notes", ""),
                "action_owner": saved.get(
                    "action_owner",
                    rec.get("owner_email") or TEAM_LABELS.get(rec.get("allocated_team", ""), rec.get("allocated_team", "Unassigned")),
                ),
                "owner": saved.get(
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
    low_risk_savings: float        # low-risk optimization savings
    optimization_opportunity: float
    primary_issue:   str           # "tagging" | "commitment_waste" | "healthy"
    priority:        Priority
    headline:        str           # one-line "so what"
    sub_headline:    str           # one-line quick-win
    color:           str           # CSS hex


def diagnose(
    df: pd.DataFrame,
    recovery_rate: float = 0.85,
    summary: FinopsSummaryMetrics | None = None,
) -> Diagnostic:
    """Compute the executive diagnostic used at the top of every page."""
    if summary is None:
        summary = _summary_from_df(df)

    total_nec = summary.total_nec
    waste_nec = summary.total_commitment_waste
    untagged_nec = summary.total_unattributed_cost
    optimization_opportunity = summary.total_optimization_opportunity

    untagged_pct = (untagged_nec / total_nec * 100.0) if total_nec else 0.0
    waste_pct = (waste_nec / total_nec * 100.0) if total_nec else 0.0
    low_risk_savings = (
        min(summary.total_optimization_opportunity, total_nec)
        if summary.total_optimization_opportunity > 0
        else waste_nec * recovery_rate
    )

    if untagged_pct >= 20:
        primary = "tagging"
        priority: Priority = "P0"
        headline = (
            f"<b>Governance gap:</b> <b>${untagged_nec:,.0f}/month</b> is unattributed because `tag_team` is missing - "
            f"{untagged_pct:.1f}% of NEC cannot be tied to an accountable team."
        )
        color = COLOR_BLOCKER
    elif waste_pct >= 10:
        primary = "commitment_waste"
        priority = "P0"
        headline = (
            f"You're carrying <b>${waste_nec:,.0f}/month</b> of commitment waste - "
            f"{waste_pct:.0f}% of cloud spend is committed capacity sitting idle."
        )
        color = COLOR_BLOCKER
    elif untagged_pct >= 10:
        primary = "tagging"
        priority = "P1"
        headline = (
            f"<b>${untagged_nec:,.0f}</b> of NEC ({untagged_pct:.1f}%) is unattributed - "
            "team-level accountability needs improvement."
        )
        color = COLOR_INEFFICIENCY
    elif waste_pct >= 5:
        primary = "commitment_waste"
        priority = "P1"
        headline = (
            f"<b>${waste_nec:,.0f}</b> of cloud spend ({waste_pct:.0f}%) is idle committed capacity - "
            "optimize before it compounds."
        )
        color = COLOR_INEFFICIENCY
    else:
        primary = "healthy"
        priority = "P3"
        headline = (
            f"Cloud spend is well managed - {waste_pct:.1f}% commitment waste, "
            f"{100 - untagged_pct:.1f}% attributed. No immediate action required."
        )
        color = COLOR_OPTIMIZED

    if low_risk_savings > 0 and primary == "commitment_waste":
        sub_headline = (
            f"Do this: right-size idle compute and remove zombie resources. Save <b>${low_risk_savings:,.0f}/month</b>. "
            "Risk: Low. Time to value: Immediate. No downtime expected."
        )
    elif low_risk_savings > 0 and primary == "tagging":
        sub_headline = (
            f"<b>Important:</b> <b>${untagged_nec:,.0f}</b> is <b>not savings</b> - it is attribution risk. "
            f"Current optimization opportunity is separate. "
            f"<b>Best-case actionable opportunity:</b> up to <b>${optimization_opportunity:,.0f}/month</b> in recoverable compute signals once attribution is trustworthy. "
            "Do this: assign owners in Tagging Coverage, then right-size idle compute and remove zombie resources."
        )
    elif primary == "tagging":
        sub_headline = (
            "Do this: enforce <code>tag_team</code> at resource creation -> "
            "attribution improves to 95%+ and unlocks reliable optimization."
        )
    else:
        sub_headline = "Continue monthly monitoring. Focus on commitment coverage and tagging discipline."

    return Diagnostic(
        total_nec=total_nec,
        untagged_nec=untagged_nec,
        untagged_pct=untagged_pct,
        waste_nec=waste_nec,
        waste_pct=waste_pct,
        low_risk_savings=low_risk_savings,
        optimization_opportunity=optimization_opportunity,
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
    history_months: int | None = None,
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

    n_months = history_months if history_months is not None else (df["billing_month"].nunique() if "billing_month" in df.columns else 0)
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
            f"reduce unattributed NEC from {diag.untagged_pct:.0f}% to below 10% with enforced `tag_team` policy"
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
    "enforce_tags": {
        "owner":      "FinOps Governance",
        "automation": "Approval-required",
        "sla":        "This week",
        "automation_badge": "Requires approval",
    },
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


# ---------------------------------------------------------------------------
# Synthetic demo banner — rendered at the top of every page
# ---------------------------------------------------------------------------

def render_demo_banner() -> None:
    """Render a non-intrusive synthetic-data disclaimer."""
    st.markdown(
        '<div style="background:#fef3c7; border-left:3px solid #d97706; '
        'padding:4px 12px; border-radius:3px; font-size:0.80rem; color:#92400e; '
        'margin-bottom:8px;">'
        '<b>Synthetic demo (not production data)</b>'
        '</div>',
        unsafe_allow_html=True,
    )
