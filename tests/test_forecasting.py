from __future__ import annotations

from datetime import date

import pandas as pd

from intelligence.forecasting import build_forecast, monthly_rollup


def _rows() -> pd.DataFrame:
    rows: list[dict] = []
    for month, nec, waste in [
        ("2026-01", 100.0, 10.0),
        ("2026-02", 110.0, 11.0),
        ("2026-03", 120.0, 12.0),
    ]:
        rows.append(
            {
                "billing_month": month,
                "usage_date": pd.Timestamp(f"{month}-01"),
                "nec": nec,
                "nec_waste": waste,
            }
        )

    for day in range(1, 25):
        rows.append(
            {
                "billing_month": "2026-04",
                "usage_date": pd.Timestamp(f"2026-04-{day:02d}"),
                "nec": 5.0,
                "nec_waste": 0.5,
            }
        )

    return pd.DataFrame(rows)


def test_monthly_rollup_sums_by_month():
    rolled = monthly_rollup(_rows())
    assert list(rolled["billing_month"]) == ["2026-01", "2026-02", "2026-03", "2026-04"]
    assert rolled.loc[rolled["billing_month"] == "2026-04", "nec"].iloc[0] == 120.0


def test_build_forecast_uses_current_month_run_rate_and_history():
    forecast = build_forecast(
        _rows(),
        recommendations=[],
        target_month="2026-04",
        as_of_date=date(2026, 4, 24),
    )
    assert forecast.target_month == "2026-04"
    assert forecast.projected_nec > 120.0
    assert forecast.no_action_waste > 0.0
    assert "run rate" in forecast.method.lower()


def test_build_forecast_prefers_approved_savings_basis():
    recs = [
        {"estimated_savings": 50.0, "action_status": "approved", "risk": "Medium"},
        {"estimated_savings": 25.0, "action_status": "recommended", "risk": "Low"},
    ]
    forecast = build_forecast(
        _rows(),
        recommendations=recs,
        target_month="2026-04",
        as_of_date=date(2026, 4, 24),
    )
    assert forecast.projected_savings == 50.0
    assert forecast.savings_basis == "approved or implemented actions"
