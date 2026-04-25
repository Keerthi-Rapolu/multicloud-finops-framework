"""
Deterministic cost forecasting helpers for the dashboard.

The goal is not to build a sophisticated forecasting model. The goal is to
produce stable, explainable month-end projections from the billing data that is
already present in the mart.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import calendar

import pandas as pd


@dataclass
class ForecastResult:
    target_month: str
    projected_nec: float
    no_action_waste: float
    projected_savings: float
    optimized_nec: float
    months_of_history: int
    method: str
    savings_basis: str
    current_month_actual: float
    days_elapsed: int
    days_in_month: int


def monthly_rollup(df: pd.DataFrame) -> pd.DataFrame:
    """Return NEC and waste totals by billing month."""
    if df.empty:
        return pd.DataFrame(columns=["billing_month", "nec", "nec_waste"])
    rolled = (
        df.groupby("billing_month", dropna=False)[["nec", "nec_waste"]]
        .sum()
        .reset_index()
        .sort_values("billing_month")
        .reset_index(drop=True)
    )
    return rolled


def _history_model(history: pd.DataFrame, target_month: str) -> tuple[float, int]:
    prior = history[history["billing_month"] < target_month].copy()
    if prior.empty:
        target_row = history[history["billing_month"] == target_month]
        if target_row.empty:
            return 0.0, 0
        return float(target_row["nec"].iloc[0]), 0

    if len(prior) >= 3:
        recent = prior.tail(3)
        avg_recent = float(recent["nec"].mean())
        deltas = recent["nec"].diff().dropna()
        trend = float(recent["nec"].iloc[-1] + (deltas.mean() if not deltas.empty else 0.0))
        return max(0.0, 0.6 * avg_recent + 0.4 * trend), len(prior)

    return float(prior["nec"].mean()), len(prior)


def _actionable_savings(recommendations: list[dict]) -> tuple[float, str]:
    approved_statuses = {"approved", "implemented", "verified"}
    approved = sum(
        r["estimated_savings"]
        for r in recommendations
        if r.get("action_status", "recommended") in approved_statuses
    )
    if approved > 0:
        return float(approved), "approved or implemented actions"

    low_risk = sum(
        r["estimated_savings"]
        for r in recommendations
        if r.get("action_status", "recommended") != "rejected"
        and r.get("risk") == "Low"
    )
    return float(low_risk), "low-risk actions"


def build_forecast(
    df: pd.DataFrame,
    recommendations: list[dict],
    *,
    target_month: str | None = None,
    as_of_date: date | None = None,
) -> ForecastResult:
    """
    Build an explainable month-end forecast for the selected scope.

    If the target month is the current month, the forecast blends:
      - month-to-date run rate from usage_date
      - the trailing historical billing trend

    Otherwise the selected month's actual NEC acts as the month-end result.
    """
    history = monthly_rollup(df)
    if history.empty:
        return ForecastResult(
            target_month=target_month or "",
            projected_nec=0.0,
            no_action_waste=0.0,
            projected_savings=0.0,
            optimized_nec=0.0,
            months_of_history=0,
            method="No billing history available",
            savings_basis="none",
            current_month_actual=0.0,
            days_elapsed=0,
            days_in_month=0,
        )

    today = as_of_date or date.today()
    target_month = target_month or str(history["billing_month"].max())
    target_row = history[history["billing_month"] == target_month]
    current_actual = float(target_row["nec"].iloc[0]) if not target_row.empty else 0.0
    current_waste = float(target_row["nec_waste"].iloc[0]) if not target_row.empty else 0.0

    year, month = map(int, target_month.split("-"))
    days_in_month = calendar.monthrange(year, month)[1]
    is_current_month = target_month == f"{today.year:04d}-{today.month:02d}"

    historical_projection, months_of_history = _history_model(history, target_month)
    projected_nec = current_actual
    method = "Actual month total"
    days_elapsed = days_in_month

    if is_current_month and "usage_date" in df.columns:
        usage_dates = pd.to_datetime(df.loc[df["billing_month"] == target_month, "usage_date"], errors="coerce")
        cutoff = pd.Timestamp(today)
        mtd_mask = usage_dates.notna() & (usage_dates.dt.date <= today)
        mtd_nec = float(df.loc[df["billing_month"].eq(target_month) & mtd_mask, "nec"].sum())
        days_elapsed = max(1, min(today.day, days_in_month))
        run_rate_projection = mtd_nec / days_elapsed * days_in_month

        if historical_projection > 0:
            projected_nec = 0.7 * run_rate_projection + 0.3 * historical_projection
            method = "70% month-to-date run rate + 30% trailing 3-month trend"
        else:
            projected_nec = run_rate_projection
            method = "Month-to-date run rate extrapolation"
    elif historical_projection > 0 and current_actual == 0.0:
        projected_nec = historical_projection
        method = "Trailing historical average/trend"

    projected_nec = round(max(0.0, projected_nec), 2)

    waste_rate = current_waste / current_actual if current_actual > 0 else 0.0
    if waste_rate == 0.0 and not history.empty:
        recent = history[history["billing_month"] <= target_month].tail(3)
        denom = float(recent["nec"].sum())
        if denom > 0:
            waste_rate = float(recent["nec_waste"].sum()) / denom

    no_action_waste = round(max(0.0, projected_nec * waste_rate), 2)
    projected_savings, savings_basis = _actionable_savings(recommendations)
    projected_savings = round(projected_savings, 2)
    optimized_nec = round(max(0.0, projected_nec - projected_savings), 2)

    return ForecastResult(
        target_month=target_month,
        projected_nec=projected_nec,
        no_action_waste=no_action_waste,
        projected_savings=projected_savings,
        optimized_nec=optimized_nec,
        months_of_history=months_of_history,
        method=method,
        savings_basis=savings_basis,
        current_month_actual=round(current_actual, 2),
        days_elapsed=days_elapsed,
        days_in_month=days_in_month,
    )
