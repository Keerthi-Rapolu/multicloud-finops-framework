"""
Deterministic cost forecasting helpers for the FinOps decision engine.

Formal model:
    forecast_nec = 0.7 * current_MTD_trend + 0.3 * historical_avg_last_3_months
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
    forecast_month_end_nec: float
    forecast_blended_nec: float
    trailing_3_month_avg_nec: float
    no_action_waste: float
    projected_savings: float
    realization_rate: float
    projected_realized_savings: float
    optimized_nec: float
    next_30_days_nec: float
    projected_unattributed_spend: float
    no_action_savings: float
    months_of_history: int
    method: str
    confidence: float
    reason: str
    savings_basis: str
    current_month_actual: float
    days_elapsed: int
    days_in_month: int
    lower_bound: float
    upper_bound: float
    error_bound_pct: float
    minimum_data_met: bool
    variance: float
    forecast_risk_level: str


@dataclass
class ForecastBacktestSummary:
    evaluations: int
    mae_usd: float
    mape_pct: float
    within_10pct_rate: float
    method: str


def safe_div(numerator: float, denominator: float) -> float:
    if abs(float(denominator)) < 1e-12:
        return 0.0
    return float(numerator) / float(denominator)


def monthly_rollup(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["billing_month", "nec", "nec_waste", "unattributed_nec"])
    tagged = df.get("is_tagged", pd.Series(True, index=df.index)).fillna(False)
    rolled = (
        df.assign(unattributed_nec=df["nec"].where(~tagged, 0.0))
        .groupby("billing_month", dropna=False)[["nec", "nec_waste", "unattributed_nec"]]
        .sum()
        .reset_index()
        .sort_values("billing_month")
        .reset_index(drop=True)
    )
    return rolled


def _current_mtd_trend(
    df: pd.DataFrame,
    *,
    target_month: str,
    today: date,
    days_in_month: int,
) -> tuple[float, int]:
    month_df = df[df["billing_month"].eq(target_month)].copy()
    if month_df.empty:
        return 0.0, 0
    usage_dates = pd.to_datetime(month_df.get("usage_date"), errors="coerce")
    valid = month_df.loc[usage_dates.notna()].copy()
    if valid.empty:
        total_nec = float(month_df["nec"].sum())
        return total_nec, 0

    valid["usage_date"] = pd.to_datetime(valid["usage_date"], errors="coerce")
    valid = valid[valid["usage_date"].dt.date <= today]
    if valid.empty:
        return 0.0, 0

    daily = (
        valid.groupby(valid["usage_date"].dt.day)["nec"]
        .sum()
        .reset_index(name="daily_nec")
        .sort_values("usage_date")
    )
    observed_days = int(daily["usage_date"].nunique())
    if observed_days == 0:
        return 0.0, 0
    run_rate = float(daily["daily_nec"].sum()) / observed_days * days_in_month
    return run_rate, observed_days


def _historical_average(history: pd.DataFrame, target_month: str) -> tuple[float, int, float]:
    prior = history[history["billing_month"] < target_month].copy()
    if prior.empty:
        target_row = history[history["billing_month"] == target_month]
        if target_row.empty:
            return 0.0, 0, 0.0
        return float(target_row["nec"].iloc[0]), 0, 0.0

    recent = prior.tail(3)
    avg_recent = float(recent["nec"].mean())
    variance = float(recent["nec"].var(ddof=0) or 0.0)
    return avg_recent, len(recent), variance


def _weighted_ratio(recent: pd.DataFrame, value_col: str) -> float:
    if recent.empty:
        return 0.0
    recent = recent.sort_values("billing_month", ascending=False).reset_index(drop=True)
    weights = [0.5, 0.3, 0.2][: len(recent)]
    total_weight = sum(weights)
    return sum(
        safe_div(float(recent.loc[idx, value_col]), max(float(recent.loc[idx, "nec"]), 1.0)) * weights[idx]
        for idx in range(len(recent))
    ) / total_weight


def _actionable_savings(recommendations: list[dict]) -> tuple[float, str]:
    approved_statuses = {"approved", "implemented", "verified"}
    approved = sum(
        float(r.get("estimated_savings", r.get("estimated_savings_usd", 0.0)) or 0.0)
        for r in recommendations
        if r.get("action_status", r.get("status", "recommended")) in approved_statuses
    )
    if approved > 0:
        return round(approved, 2), "approved or implemented actions"

    low_risk = sum(
        float(r.get("estimated_savings", r.get("estimated_savings_usd", 0.0)) or 0.0)
        for r in recommendations
        if r.get("action_status", r.get("status", "recommended")) != "rejected"
        and (
            r.get("risk") == "Low"
            or int(r.get("risk_score", 0) or 0) <= 35
        )
    )
    return round(low_risk, 2), "recommended low-risk actions"


def _realization_rate(recommendations: list[dict]) -> float:
    actionable = [r for r in recommendations if r.get("action_status", r.get("status", "recommended")) != "rejected"]
    if not actionable:
        return 0.70
    low_risk = [
        r
        for r in actionable
        if r.get("risk") == "Low" or int(r.get("risk_score", 0) or 0) <= 35
    ]
    if len(low_risk) == len(actionable):
        return 0.80
    if low_risk:
        return 0.70
    return 0.60


def build_forecast(
    df: pd.DataFrame,
    recommendations: list[dict],
    *,
    target_month: str | None = None,
    as_of_date: date | None = None,
) -> ForecastResult:
    history = monthly_rollup(df)
    if history.empty:
        return ForecastResult(
            target_month=target_month or "",
            projected_nec=0.0,
            forecast_month_end_nec=0.0,
            forecast_blended_nec=0.0,
            trailing_3_month_avg_nec=0.0,
            no_action_waste=0.0,
            projected_savings=0.0,
            realization_rate=0.0,
            projected_realized_savings=0.0,
            optimized_nec=0.0,
            next_30_days_nec=0.0,
            projected_unattributed_spend=0.0,
            no_action_savings=0.0,
            months_of_history=0,
            method="insufficient_history",
            confidence=0.0,
            reason="No billing history is available, so the forecast cannot be estimated.",
            savings_basis="none",
            current_month_actual=0.0,
            days_elapsed=0,
            days_in_month=0,
            lower_bound=0.0,
            upper_bound=0.0,
            error_bound_pct=0.0,
            minimum_data_met=False,
            variance=0.0,
            forecast_risk_level="low",
        )

    today = as_of_date or date.today()
    target_month = target_month or str(history["billing_month"].max())
    year, month = map(int, target_month.split("-"))
    days_in_month = calendar.monthrange(year, month)[1]

    target_row = history[history["billing_month"] == target_month]
    current_actual = float(target_row["nec"].iloc[0]) if not target_row.empty else 0.0
    historical_avg, months_of_history, variance = _historical_average(history, target_month)
    mtd_trend, days_elapsed = _current_mtd_trend(
        df,
        target_month=target_month,
        today=today,
        days_in_month=days_in_month,
    )

    minimum_data_met = months_of_history >= 3
    forecast_month_end_nec = max(mtd_trend if mtd_trend > 0.0 else current_actual, 0.0)
    if minimum_data_met and forecast_month_end_nec > 0.0:
        forecast_blended_nec = (0.7 * forecast_month_end_nec) + (0.3 * historical_avg)
        method = "0.7 * current_month_run_rate + 0.3 * trailing_3_month_avg_nec"
    else:
        forecast_blended_nec = forecast_month_end_nec
        method = "current_month_run_rate"

    recent = history[history["billing_month"] <= target_month].tail(3).copy()
    waste_rate = _weighted_ratio(recent, "nec_waste")
    unattributed_rate = _weighted_ratio(recent, "unattributed_nec")

    forecast_month_end_nec = round(forecast_month_end_nec, 2)
    forecast_blended_nec = round(max(forecast_blended_nec, 0.0), 2)
    projected_nec = forecast_blended_nec
    next_30_days_nec = round(max(historical_avg, projected_nec), 2)
    no_action_waste = round(projected_nec * waste_rate, 2)
    projected_unattributed_spend = round(projected_nec * unattributed_rate, 2)
    projected_savings, savings_basis = _actionable_savings(recommendations)
    realization_rate = _realization_rate(recommendations)
    projected_realized_savings = round(projected_savings * realization_rate, 2)
    optimized_nec = round(max(0.0, projected_nec - projected_realized_savings), 2)

    stddev = variance ** 0.5
    error_bound_pct = round(min(1.0, safe_div(stddev, max(projected_nec, 1.0))), 4)
    lower_bound = round(max(0.0, projected_nec - (1.96 * stddev)), 2)
    upper_bound = round(projected_nec + (1.96 * stddev), 2)

    if minimum_data_met and error_bound_pct <= 0.15:
        confidence = 0.85
    elif minimum_data_met:
        confidence = 0.70
    else:
        confidence = 0.40

    if minimum_data_met and historical_avg > 0 and projected_nec / historical_avg >= 1.20:
        forecast_risk_level = "high"
    elif minimum_data_met and historical_avg > 0 and projected_nec / historical_avg >= 1.10:
        forecast_risk_level = "medium"
    elif days_elapsed >= 7 and current_actual > 0 and forecast_month_end_nec / max(current_actual, 1.0) >= 1.15:
        forecast_risk_level = "medium"
    else:
        forecast_risk_level = "low"

    reason = (
        f"Forecast uses a 70/30 blend of current month-to-date NEC run rate and the "
        f"average NEC from the last {months_of_history} full month(s)."
        if minimum_data_met
        else "Forecast uses current month NEC run rate because fewer than 3 full prior months are available."
    )

    return ForecastResult(
        target_month=target_month,
        projected_nec=projected_nec,
        forecast_month_end_nec=forecast_month_end_nec,
        forecast_blended_nec=forecast_blended_nec,
        trailing_3_month_avg_nec=round(historical_avg, 2),
        no_action_waste=no_action_waste,
        projected_savings=projected_savings,
        realization_rate=round(realization_rate, 2),
        projected_realized_savings=projected_realized_savings,
        optimized_nec=optimized_nec,
        next_30_days_nec=next_30_days_nec,
        projected_unattributed_spend=projected_unattributed_spend,
        no_action_savings=0.0,
        months_of_history=months_of_history,
        method=method,
        confidence=confidence,
        reason=reason,
        savings_basis=savings_basis,
        current_month_actual=round(current_actual, 2),
        days_elapsed=days_elapsed,
        days_in_month=days_in_month,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        error_bound_pct=error_bound_pct,
        minimum_data_met=minimum_data_met,
        variance=round(variance, 4),
        forecast_risk_level=forecast_risk_level,
    )


def backtest_forecast(df: pd.DataFrame) -> tuple[pd.DataFrame, ForecastBacktestSummary]:
    """
    Backtest the baseline forecast using the first 15 observed days of each month.

    This is a transparent proxy for month-end projection quality:
      1. use days 1-15 NEC as the current-month run-rate input
      2. blend it with trailing 3 full months when available
      3. compare forecasted month-end NEC with the actual full-month NEC
    """
    history = monthly_rollup(df)
    if history.empty or "usage_date" not in df.columns:
        empty = pd.DataFrame(
            columns=[
                "billing_month",
                "actual_nec",
                "mid_month_run_rate_forecast",
                "trailing_3_month_avg_nec",
                "forecast_nec",
                "history_months",
                "observed_days",
                "absolute_error_usd",
                "absolute_pct_error",
                "accuracy_pct",
                "within_10pct",
            ]
        )
        return empty, ForecastBacktestSummary(0, 0.0, 0.0, 0.0, "first_half_month_backtest")

    base = df.copy()
    base["usage_date"] = pd.to_datetime(base["usage_date"], errors="coerce")
    base = base[base["usage_date"].notna()].copy()
    if base.empty:
        empty = pd.DataFrame()
        return empty, ForecastBacktestSummary(0, 0.0, 0.0, 0.0, "first_half_month_backtest")

    daily = (
        base.assign(day=base["usage_date"].dt.day)
        .groupby(["billing_month", "day"], dropna=False)["nec"]
        .sum()
        .reset_index(name="daily_nec")
    )
    records: list[dict] = []
    months = list(history["billing_month"])
    for idx, month in enumerate(months):
        month_hist = history.iloc[max(0, idx - 3):idx]
        month_daily = daily[daily["billing_month"] == month]
        if month_daily.empty:
            continue
        mid_month = month_daily[month_daily["day"] <= 15]
        observed_days = int(mid_month["day"].nunique())
        if observed_days < 7:
            continue
        year, mm = map(int, str(month).split("-"))
        days_in_month = calendar.monthrange(year, mm)[1]
        actual_nec = float(history.loc[history["billing_month"] == month, "nec"].iloc[0])
        current_run_rate = float(mid_month["daily_nec"].sum()) / observed_days * days_in_month
        trailing_avg = float(month_hist["nec"].mean()) if not month_hist.empty else 0.0
        history_months = len(month_hist)
        forecast_nec = (
            (0.7 * current_run_rate) + (0.3 * trailing_avg)
            if history_months >= 3
            else current_run_rate
        )
        abs_error = abs(actual_nec - forecast_nec)
        abs_pct_error = safe_div(abs_error, actual_nec)
        records.append(
            {
                "billing_month": month,
                "actual_nec": round(actual_nec, 2),
                "mid_month_run_rate_forecast": round(current_run_rate, 2),
                "trailing_3_month_avg_nec": round(trailing_avg, 2),
                "forecast_nec": round(forecast_nec, 2),
                "history_months": history_months,
                "observed_days": observed_days,
                "absolute_error_usd": round(abs_error, 2),
                "absolute_pct_error": round(abs_pct_error, 6),
                "accuracy_pct": round(100.0 - (abs_pct_error * 100.0), 2),
                "within_10pct": abs_pct_error <= 0.10,
            }
        )

    result = pd.DataFrame(records)
    if result.empty:
        return result, ForecastBacktestSummary(0, 0.0, 0.0, 0.0, "first_half_month_backtest")
    summary = ForecastBacktestSummary(
        evaluations=int(len(result)),
        mae_usd=round(float(result["absolute_error_usd"].mean()), 2),
        mape_pct=round(float(result["absolute_pct_error"].mean() * 100.0), 2),
        within_10pct_rate=round(float(result["within_10pct"].mean()), 4),
        method="first_half_month_backtest",
    )
    return result, summary
