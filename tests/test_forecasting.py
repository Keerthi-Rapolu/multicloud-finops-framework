from __future__ import annotations

from datetime import date

import pandas as pd

from intelligence.forecasting import backtest_forecast, build_forecast, monthly_rollup


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
                "is_tagged": True,
            }
        )

    for day in range(1, 25):
        rows.append(
            {
                "billing_month": "2026-04",
                "usage_date": pd.Timestamp(f"2026-04-{day:02d}"),
                "nec": 5.0,
                "nec_waste": 0.5,
                "is_tagged": day % 2 == 0,
            }
        )

    return pd.DataFrame(rows)


def test_monthly_rollup_sums_by_month():
    rolled = monthly_rollup(_rows())
    assert list(rolled["billing_month"]) == ["2026-01", "2026-02", "2026-03", "2026-04"]
    assert rolled.loc[rolled["billing_month"] == "2026-04", "nec"].iloc[0] == 120.0


def test_build_forecast_uses_formal_weighted_formula():
    forecast = build_forecast(
        _rows(),
        recommendations=[],
        target_month="2026-04",
        as_of_date=date(2026, 4, 24),
    )
    expected_mtd = (120.0 / 24.0) * 30.0
    expected_history = (100.0 + 110.0 + 120.0) / 3.0
    expected_projection = round((0.7 * expected_mtd) + (0.3 * expected_history), 2)

    assert forecast.target_month == "2026-04"
    assert forecast.forecast_month_end_nec == round(expected_mtd, 2)
    assert forecast.trailing_3_month_avg_nec == round(expected_history, 2)
    assert forecast.forecast_blended_nec == expected_projection
    assert forecast.projected_nec == expected_projection
    assert forecast.method == "0.7 * current_month_run_rate + 0.3 * trailing_3_month_avg_nec"
    assert forecast.minimum_data_met is True
    assert forecast.lower_bound <= forecast.projected_nec <= forecast.upper_bound
    assert forecast.variance >= 0.0


def test_build_forecast_prefers_approved_savings_basis():
    recs = [
        {"estimated_savings": 50.0, "action_status": "approved", "risk_score": 45},
        {"estimated_savings": 25.0, "action_status": "recommended", "risk_score": 15},
    ]
    forecast = build_forecast(
        _rows(),
        recommendations=recs,
        target_month="2026-04",
        as_of_date=date(2026, 4, 24),
    )
    assert forecast.projected_savings == 50.0
    assert forecast.savings_basis == "approved or implemented actions"
    assert forecast.realization_rate == 0.7
    assert forecast.projected_realized_savings == 35.0
    assert forecast.optimized_nec == forecast.projected_nec - forecast.projected_realized_savings


def test_build_forecast_uses_higher_realization_for_low_risk_actions():
    recs = [
        {"estimated_savings": 80.0, "action_status": "recommended", "risk_score": 20},
        {"estimated_savings": 20.0, "action_status": "recommended", "risk_score": 15},
    ]
    forecast = build_forecast(
        _rows(),
        recommendations=recs,
        target_month="2026-04",
        as_of_date=date(2026, 4, 24),
    )
    assert forecast.projected_savings == 100.0
    assert forecast.realization_rate == 0.8
    assert forecast.projected_realized_savings == 80.0
    assert forecast.optimized_nec == forecast.projected_nec - 80.0


def test_build_forecast_requires_three_months_history():
    sparse = pd.DataFrame(
        [
            {
                "billing_month": "2026-03",
                "usage_date": pd.Timestamp("2026-03-01"),
                "nec": 25.0,
                "nec_waste": 3.0,
                "is_tagged": True,
            },
            {
                "billing_month": "2026-04",
                "usage_date": pd.Timestamp("2026-04-01"),
                "nec": 25.0,
                "nec_waste": 3.0,
                "is_tagged": True,
            },
        ]
    )
    forecast = build_forecast(
        sparse,
        recommendations=[],
        target_month="2026-04",
        as_of_date=date(2026, 4, 1),
    )
    assert forecast.minimum_data_met is False
    assert forecast.confidence == 0.40
    assert forecast.method == "current_month_run_rate"


def test_build_forecast_works_with_single_month_history():
    current_only = pd.DataFrame(
        [
            {
                "billing_month": "2026-04",
                "usage_date": pd.Timestamp("2026-04-01"),
                "nec": 10.0,
                "nec_waste": 1.0,
                "is_tagged": False,
            },
            {
                "billing_month": "2026-04",
                "usage_date": pd.Timestamp("2026-04-02"),
                "nec": 10.0,
                "nec_waste": 1.0,
                "is_tagged": True,
            },
        ]
    )
    forecast = build_forecast(
        current_only,
        recommendations=[],
        target_month="2026-04",
        as_of_date=date(2026, 4, 2),
    )
    assert forecast.minimum_data_met is False
    assert forecast.forecast_month_end_nec == 300.0
    assert forecast.projected_nec == 300.0


def test_backtest_forecast_returns_error_metrics():
    backtest_df, summary = backtest_forecast(_rows())
    assert not backtest_df.empty
    assert summary.evaluations == len(backtest_df)
    assert summary.mae_usd >= 0.0
    assert summary.mape_pct >= 0.0
    assert 0.0 <= summary.within_10pct_rate <= 1.0
    assert "forecast_nec" in backtest_df.columns
