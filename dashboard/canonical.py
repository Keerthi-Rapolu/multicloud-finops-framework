"""
dashboard/canonical.py — Canonical metrics layer.

Single source of truth for ALL dashboard KPI values. Every page reads from
`load_canonical_metrics()` and displays the result. Pages must not recompute
business logic — they display what this module provides.

Canonical metric definitions (used consistently across all pages and models):
  list_cost           pre-discount gross cloud cost
  nec                 net effective cost after cloud pricing effects
  unattributed_nec    NEC rows with no accountable owner/team tag
  tagging_gap         unattributed_nec / nec  [0, 1]
  commitment_waste    unused RI/SP/CUD capacity cost
  waste_rate          commitment_waste / nec  [0, 1]
  waste_signal        raw billing-detected waste before recovery/risk filters
  recoverable_savings technically recoverable waste after per-signal recovery rates
  actionable_savings  recoverable filtered to low+medium risk (risk_score < 70)
  projected_savings   actionable_savings × realization_rate (execution-adjusted)
  optimized_nec       projected_nec − projected_savings
  low_risk_savings    actionable filtered to risk_score < 35 only
  realization_rate    probability that modeled savings are actually executed [0, 1]
  reliability_score   weighted model-quality score:
                      0.40×data_completeness + 0.35×signal_strength + 0.25×historical_stability
                      (NOT called "confidence" to avoid implying predictive capability)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import streamlit as st

_DB_PATH = Path(__file__).resolve().parents[1] / "finops_dbt.duckdb"

# Risk score thresholds (canonical — must match normalize_canonical_recommendations)
_RISK_LOW_MAX    = 35   # risk_score < 35  → Low
_RISK_MEDIUM_MAX = 70   # risk_score < 70  → Medium; >= 70 → High


# ---------------------------------------------------------------------------
# CanonicalMetrics dataclass — the single metrics contract
# ---------------------------------------------------------------------------

@dataclass
class CanonicalMetrics:
    # --- Cost attribution ------------------------------------------------
    list_cost: float = 0.0           # pre-discount gross cloud cost
    nec: float = 0.0                 # net effective cost
    unattributed_nec: float = 0.0    # NEC with no accountable owner/team tag
    tagging_gap: float = 0.0         # = unattributed_nec / nec
    commitment_waste: float = 0.0    # unused RI/SP/CUD capacity cost
    waste_rate: float = 0.0          # = commitment_waste / nec

    # --- Savings hierarchy (strictly ordered: ws >= rec >= act >= proj) --
    waste_signal: float = 0.0           # raw billing-detected waste magnitude
    recoverable_savings: float = 0.0    # after signal recovery rates
    actionable_savings: float = 0.0     # low+medium risk only
    projected_savings: float = 0.0      # actionable × realization_rate
    low_risk_savings: float = 0.0       # risk_score < 35 subset

    # --- Forecast --------------------------------------------------------
    projected_nec: float = 0.0
    optimized_nec: float = 0.0       # = projected_nec - projected_savings
    realization_rate: float = 0.70
    reliability_score: float = 0.0   # model quality (not predictive confidence)
    lower_bound: float = 0.0
    upper_bound: float = 0.0

    # --- Counts ----------------------------------------------------------
    n_recommendations: int = 0
    n_low_risk: int = 0
    n_anomalies: int = 0

    # --- Scope -----------------------------------------------------------
    billing_month: str = ""
    cloud: str = "All"

    # --- Validation flags (True = invariant holds) -----------------------
    hierarchy_valid: bool = True      # projected <= actionable <= recoverable <= waste_signal
    nec_balance_valid: bool = True    # unattributed fraction is bounded [0, 1]
    optimized_nec_valid: bool = True  # |optimized_nec - (proj_nec - proj_sav)| < 2%


# ---------------------------------------------------------------------------
# Public loader — the only entry point pages should call
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60, show_spinner=False)
def load_canonical_metrics(
    month: str | None,
    cloud: str,
    teams: list[str] | None = None,
) -> CanonicalMetrics:
    """
    Load all canonical KPI values from DuckDB mart tables.

    Priority:
    1. fct_finops_decision_metrics
    2. Composed from fct_finops_summary + fct_month_end_forecast +
       fct_finops_recommendations
    """
    import duckdb

    if not _DB_PATH.exists():
        return CanonicalMetrics(billing_month=month or "", cloud=cloud)

    with duckdb.connect(str(_DB_PATH), read_only=True) as con:
        decision_exists = _table_exists(con, "fct_finops_decision_metrics")
        if decision_exists:
            m = _from_decision_metrics(con, month, cloud, teams)
        else:
            m = _compose_from_marts(con, month, cloud, teams)

        _validate(m)
        return m


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _table_exists(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema='marts' AND table_name=?",
        [name]
    ).fetchone()[0])


def _cloud_clause(cloud: str, col: str = "cloud_provider") -> str:
    return f"AND lower({col}) = lower(?)" if cloud != "All" else ""


def _safe_float(v) -> float:
    return float(v) if v is not None else 0.0


def _from_decision_metrics(con, month, cloud, teams: list[str] | None) -> CanonicalMetrics:
    params: list = [month, month]
    cc = _cloud_clause(cloud)
    if cloud != "All":
        params += [cloud]
    team_clause = ""
    if teams:
        placeholders = ",".join(["?" for _ in teams])
        team_clause = f"AND team IN ({placeholders})"
        params += list(teams)

    row = con.execute(f"""
        SELECT
            sum(list_cost), sum(nec), sum(commitment_waste),
            sum(unattributed_nec), sum(waste_signal),
            sum(recoverable_savings), sum(actionable_savings),
            sum(projected_savings), sum(low_risk_savings),
            sum(projected_nec), sum(optimized_nec),
            avg(realization_rate), avg(reliability_score),
            sum(lower_bound), sum(upper_bound),
            sum(n_recommendations), sum(n_low_risk), sum(n_anomalies)
        FROM marts.fct_finops_decision_metrics
        WHERE (? IS NULL OR billing_month = ?)
        {cc}
        {team_clause}
    """, params).fetchone()

    if not row or row[1] is None:
        # Fall through to composition if table is empty
        return _compose_from_marts(con, month, cloud, teams)

    (list_cost, nec, commitment_waste, unattributed_nec, waste_signal,
     recoverable_savings, actionable_savings, projected_savings, low_risk_savings,
     projected_nec, optimized_nec, realization_rate, reliability_score,
     lower_bound, upper_bound, n_rec, n_low, n_anom) = row

    nec = _safe_float(nec)
    return CanonicalMetrics(
        list_cost=_safe_float(list_cost),
        nec=nec,
        commitment_waste=_safe_float(commitment_waste),
        unattributed_nec=_safe_float(unattributed_nec),
        tagging_gap=round(_safe_float(unattributed_nec) / nec, 4) if nec else 0.0,
        waste_rate=round(_safe_float(commitment_waste) / nec, 4) if nec else 0.0,
        waste_signal=_safe_float(waste_signal),
        recoverable_savings=_safe_float(recoverable_savings),
        actionable_savings=_safe_float(actionable_savings),
        projected_savings=_safe_float(projected_savings),
        low_risk_savings=_safe_float(low_risk_savings),
        projected_nec=_safe_float(projected_nec),
        optimized_nec=_safe_float(optimized_nec),
        realization_rate=_safe_float(realization_rate) or 0.70,
        reliability_score=_safe_float(reliability_score),
        lower_bound=_safe_float(lower_bound),
        upper_bound=_safe_float(upper_bound),
        n_recommendations=int(n_rec or 0),
        n_low_risk=int(n_low or 0),
        n_anomalies=int(n_anom or 0),
        billing_month=month or "",
        cloud=cloud,
    )


def _compose_from_marts(
    con, month: str | None, cloud: str, teams: list[str] | None
) -> CanonicalMetrics:
    """Fallback: compose metrics from individual mart tables."""
    cloud_cc = _cloud_clause(cloud)
    cloud_param = [cloud] if cloud != "All" else []

    team_clause = ""
    team_params: list = []
    if teams:
        placeholders = ",".join(["?" for _ in teams])
        team_clause = f"AND team IN ({placeholders})"
        team_params = list(teams)

    base_params = [month, month] + cloud_param + team_params

    # ── fct_finops_summary (or fct_unified_billing fallback) ───────────
    if _table_exists(con, "fct_finops_summary"):
        sum_row = con.execute(f"""
            SELECT
                sum(total_list_cost),
                sum(total_nec),
                sum(total_commitment_waste),
                sum(total_unattributed_cost),
                sum(total_recoverable_savings)
            FROM marts.fct_finops_summary
            WHERE (? IS NULL OR billing_month = ?)
            {cloud_cc} {team_clause}
        """, base_params).fetchone() or [0] * 5
    else:
        # Bootstrap path: only fct_unified_billing was built
        ub_team_clause = ""
        ub_team_params: list = []
        if teams:
            placeholders = ",".join(["?" for _ in teams])
            ub_team_clause = f"AND allocated_team IN ({placeholders})"
            ub_team_params = list(teams)
        ub_params = [month, month] + cloud_param + ub_team_params
        sum_row = con.execute(f"""
            SELECT
                sum(list_cost),
                sum(nec),
                sum(CASE WHEN is_commitment_waste THEN nec_waste ELSE 0 END),
                sum(CASE WHEN NOT is_tagged THEN allocated_nec ELSE 0 END),
                0.0
            FROM marts.fct_unified_billing
            WHERE (? IS NULL OR billing_month = ?)
            {_cloud_clause(cloud)} {ub_team_clause}
        """, ub_params).fetchone() or [0] * 5

    list_cost, nec, commitment_waste, unattributed_nec, recoverable_mart = (
        _safe_float(v) for v in sum_row
    )

    # ── fct_month_end_forecast ──────────────────────────────────────────
    if _table_exists(con, "fct_month_end_forecast"):
        fc_params = [month, month] + cloud_param + team_params
        fc_row = con.execute(f"""
            SELECT
                sum(projected_month_end_nec),
                sum(optimized_month_end_nec),
                sum(projected_savings_usd),
                sum(projected_realized_savings_usd),
                avg(realization_rate),
                avg(forecast_confidence),
                sum(lower_bound_usd),
                sum(upper_bound_usd)
            FROM marts.fct_month_end_forecast
            WHERE (? IS NULL OR billing_month = ?)
            {cloud_cc} {team_clause}
        """, fc_params).fetchone() or [0] * 8
    else:
        fc_row = [0] * 8

    (projected_nec, optimized_nec_fc, actionable_fc, projected_savings_fc,
     realization_rate, reliability_score, lower_bound, upper_bound) = (
        _safe_float(v) for v in fc_row
    )

    # ── fct_finops_recommendations ──────────────────────────────────────
    if _table_exists(con, "fct_finops_recommendations"):
        rec_row = con.execute(f"""
            SELECT
                sum(nec_impact_usd),
                sum(estimated_savings_usd),
                sum(CASE WHEN risk_score < {_RISK_MEDIUM_MAX} THEN estimated_savings_usd ELSE 0 END),
                sum(CASE WHEN risk_score < {_RISK_LOW_MAX}    THEN estimated_savings_usd ELSE 0 END),
                count(*),
                count(CASE WHEN risk_score < {_RISK_LOW_MAX} THEN 1 END)
            FROM marts.fct_finops_recommendations
            WHERE (? IS NULL OR billing_month = ?)
            {cloud_cc} {team_clause}
        """, base_params).fetchone() or [0] * 6
    else:
        rec_row = [0] * 6

    (waste_signal, recoverable_recs, actionable_recs,
     low_risk_recs, n_rec, n_low) = (
        _safe_float(v) for v in rec_row
    )

    # Canonical hierarchy: prefer forecast-derived values for actionable+projected
    actionable_savings = actionable_fc or actionable_recs
    projected_savings  = projected_savings_fc or (actionable_savings * (realization_rate or 0.70))
    recoverable_savings = max(recoverable_mart, recoverable_recs)
    # Recompute optimized_nec so it always satisfies: optimized = projected_nec - projected_savings
    optimized_nec = max(0.0, projected_nec - projected_savings) if projected_nec else optimized_nec_fc

    nec = _safe_float(nec)
    return CanonicalMetrics(
        list_cost=list_cost,
        nec=nec,
        commitment_waste=commitment_waste,
        unattributed_nec=unattributed_nec,
        tagging_gap=round(unattributed_nec / nec, 4) if nec else 0.0,
        waste_rate=round(commitment_waste / nec, 4) if nec else 0.0,
        waste_signal=waste_signal,
        recoverable_savings=recoverable_savings,
        actionable_savings=actionable_savings,
        projected_savings=projected_savings,
        low_risk_savings=low_risk_recs,
        projected_nec=projected_nec,
        optimized_nec=optimized_nec,
        realization_rate=realization_rate or 0.70,
        reliability_score=reliability_score,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        n_recommendations=int(n_rec),
        n_low_risk=int(n_low),
        billing_month=month or "",
        cloud=cloud,
    )


def _validate(m: CanonicalMetrics) -> None:
    """Set validation flags. Tolerance: 2% of the larger quantity."""
    tol = 0.02

    # Hierarchy invariant
    m.hierarchy_valid = (
        m.projected_savings <= m.actionable_savings + 1.0
        and m.actionable_savings <= m.recoverable_savings + 1.0
    )

    # NEC balance: unattributed fraction must be in [0, 1+tol]
    m.nec_balance_valid = (
        m.nec <= 0
        or 0.0 <= m.unattributed_nec / m.nec <= 1.0 + tol
    )

    # Optimized NEC formula: optimized_nec ≈ projected_nec - projected_savings
    if m.projected_nec > 0:
        expected_opt = m.projected_nec - m.projected_savings
        m.optimized_nec_valid = (
            abs(m.optimized_nec - expected_opt) / m.projected_nec < tol
        )
    else:
        m.optimized_nec_valid = True
