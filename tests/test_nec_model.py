"""
Tests for allocation/nec_model.py.

All tests run against an in-memory DataFrame that mirrors the fct_unified_billing
schema — no DuckDB connection required. The load_billing_data() function is tested
separately via an integration test that skips when the DB is absent.
"""

import math
from pathlib import Path

import pandas as pd
import pytest

from allocation.nec_model import (
    NECReport,
    build_nec_report,
    commitment_utilization,
    commitment_waste_detail,
    effective_unit_price_summary,
    nec_by_cloud,
    nec_by_service_category,
    nec_by_team,
    nec_trend,
    savings_vs_on_demand,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _row(**overrides) -> dict:
    """Return a default fct_unified_billing row, overridable per test."""
    base = dict(
        cloud_provider="aws",
        billing_month="2026-03",
        account_id="123456789012",
        allocated_team="platform",
        service_name="AmazonEC2",
        service_category="Compute",
        discount_type="on_demand",
        usage_date=pd.Timestamp("2026-03-01 00:00:00"),
        usage_amount=100.0,
        list_cost=10.0,
        nec=10.0,
        nec_used=10.0,
        nec_waste=0.0,
        allocated_nec=10.0,
        effective_unit_price=None,
        is_commitment_waste=False,
        is_shared_cost=False,
        is_tagged=True,
        tag_team="platform",
        tag_environment="prod",
        tag_cost_center="eng",
    )
    base.update(overrides)
    return base


@pytest.fixture
def simple_df() -> pd.DataFrame:
    """Three rows: one per cloud, different discount types."""
    rows = [
        _row(cloud_provider="aws",   discount_type="ri",      list_cost=100.0, nec=70.0,  nec_used=70.0,  nec_waste=5.0,  allocated_nec=70.0,  allocated_team="platform", service_category="Compute"),
        _row(cloud_provider="azure", discount_type="sp",      list_cost=200.0, nec=140.0, nec_used=140.0, nec_waste=10.0, allocated_nec=140.0, allocated_team="data-eng", service_category="Storage"),
        _row(cloud_provider="gcp",   discount_type="on_demand", list_cost=50.0, nec=50.0, nec_used=50.0,  nec_waste=0.0,  allocated_nec=50.0,  allocated_team="frontend", service_category="Compute"),
    ]
    return pd.DataFrame(rows)


@pytest.fixture
def commitment_df() -> pd.DataFrame:
    """Rows designed to test commitment utilization and waste."""
    rows = [
        # AWS RI: used
        _row(cloud_provider="aws",   discount_type="ri",  nec_used=80.0,  nec_waste=0.0,  is_commitment_waste=False, list_cost=100.0, nec=80.0, allocated_nec=80.0),
        # AWS RI: waste row
        _row(cloud_provider="aws",   discount_type="ri",  nec_used=0.0,   nec_waste=20.0, is_commitment_waste=True,  list_cost=20.0,  nec=0.0,  allocated_nec=0.0,  service_name="AmazonEC2"),
        # Azure SP: used
        _row(cloud_provider="azure", discount_type="sp",  nec_used=150.0, nec_waste=0.0,  is_commitment_waste=False, list_cost=200.0, nec=150.0, allocated_nec=150.0),
        # Azure SP: waste row
        _row(cloud_provider="azure", discount_type="sp",  nec_used=0.0,   nec_waste=50.0, is_commitment_waste=True,  list_cost=50.0,  nec=0.0,  allocated_nec=0.0),
    ]
    return pd.DataFrame(rows)


@pytest.fixture
def fanout_df() -> pd.DataFrame:
    """
    Azure untagged row fanned out to 3 teams — mirrors what the dbt model emits
    after the fan-out fix (nec_used / retail_cost already divided by n_teams).
    Original: list_cost=90, nec_used=60, nec_waste=30.
    Each of the 3 rows carries 1/3 of each column.
    """
    rows = [
        _row(
            cloud_provider="azure",
            discount_type="sp",
            is_shared_cost=True,
            allocated_team=team,
            list_cost=30.0,       # 90 / 3
            nec=20.0,             # 60 / 3
            nec_used=20.0,
            nec_waste=10.0,       # 30 / 3
            allocated_nec=20.0,
        )
        for team in ["platform", "data-eng", "frontend"]
    ]
    return pd.DataFrame(rows)


@pytest.fixture
def multi_team_df() -> pd.DataFrame:
    """Multiple teams sharing spend — tests nec_by_team grouping."""
    rows = [
        _row(allocated_team="platform",  cloud_provider="aws",   list_cost=100.0, allocated_nec=100.0, nec_waste=0.0),
        _row(allocated_team="platform",  cloud_provider="azure", list_cost=50.0,  allocated_nec=50.0,  nec_waste=5.0),
        _row(allocated_team="data-eng",  cloud_provider="aws",   list_cost=80.0,  allocated_nec=80.0,  nec_waste=0.0),
        _row(allocated_team="frontend",  cloud_provider="gcp",   list_cost=30.0,  allocated_nec=30.0,  nec_waste=0.0),
        _row(allocated_team=None,        cloud_provider="azure", list_cost=20.0,  allocated_nec=20.0,  nec_waste=0.0),
    ]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# nec_by_cloud
# ---------------------------------------------------------------------------

class TestNecByCloud:
    def test_returns_one_row_per_cloud(self, simple_df):
        result = nec_by_cloud(simple_df)
        assert set(result["cloud_provider"]) == {"aws", "azure", "gcp"}

    def test_list_cost_sums_correctly(self, simple_df):
        result = nec_by_cloud(simple_df)
        aws = result[result["cloud_provider"] == "aws"].iloc[0]
        assert math.isclose(aws["list_cost"], 100.0)

    def test_savings_equals_list_minus_nec(self, simple_df):
        result = nec_by_cloud(simple_df)
        for _, row in result.iterrows():
            assert math.isclose(row["savings"], row["list_cost"] - row["nec"], rel_tol=1e-9)

    def test_savings_pct_is_correct(self, simple_df):
        result = nec_by_cloud(simple_df)
        aws = result[result["cloud_provider"] == "aws"].iloc[0]
        expected = round((100.0 - 70.0) / 100.0 * 100, 1)
        assert math.isclose(aws["savings_pct"], expected)

    def test_nec_waste_aggregated(self, simple_df):
        result = nec_by_cloud(simple_df)
        azure = result[result["cloud_provider"] == "azure"].iloc[0]
        assert math.isclose(azure["nec_waste"], 10.0)


# ---------------------------------------------------------------------------
# nec_by_team
# ---------------------------------------------------------------------------

class TestNecByTeam:
    def test_team_column_renamed(self, multi_team_df):
        result = nec_by_team(multi_team_df)
        assert "team" in result.columns
        assert "allocated_team" not in result.columns

    def test_platform_nec_sums_across_clouds(self, multi_team_df):
        result = nec_by_team(multi_team_df)
        platform = result[result["team"] == "platform"]
        total = platform["nec"].sum()
        assert math.isclose(total, 150.0)

    def test_savings_equals_list_minus_nec(self, multi_team_df):
        result = nec_by_team(multi_team_df)
        for _, row in result.iterrows():
            assert math.isclose(row["savings"], row["list_cost"] - row["nec"], rel_tol=1e-9)

    def test_null_team_included(self, multi_team_df):
        result = nec_by_team(multi_team_df)
        null_rows = result[result["team"].isna()]
        assert len(null_rows) == 1


# ---------------------------------------------------------------------------
# nec_by_service_category
# ---------------------------------------------------------------------------

class TestNecByServiceCategory:
    def test_groups_by_cloud_and_category(self, simple_df):
        result = nec_by_service_category(simple_df)
        assert {"cloud_provider", "service_category", "list_cost", "nec", "nec_waste", "rows"}.issubset(result.columns)

    def test_compute_rows_count(self, simple_df):
        result = nec_by_service_category(simple_df)
        compute = result[result["service_category"] == "Compute"]
        # aws=Compute, gcp=Compute → 2 groups
        assert len(compute) == 2


# ---------------------------------------------------------------------------
# nec_trend
# ---------------------------------------------------------------------------

class TestNecTrend:
    def test_daily_trend(self, simple_df):
        result = nec_trend(simple_df, freq="D")
        assert "period" in result.columns
        assert "nec" in result.columns

    def test_period_is_timestamp(self, simple_df):
        result = nec_trend(simple_df, freq="D")
        assert pd.api.types.is_datetime64_any_dtype(result["period"])

    def test_nec_totals_match_original(self, simple_df):
        result = nec_trend(simple_df, freq="D")
        assert math.isclose(result["nec"].sum(), simple_df["nec"].sum(), rel_tol=1e-9)


# ---------------------------------------------------------------------------
# commitment_utilization
# ---------------------------------------------------------------------------

class TestCommitmentUtilization:
    def test_excludes_on_demand(self, commitment_df):
        result = commitment_utilization(commitment_df)
        assert "on_demand" not in result["discount_type"].values

    def test_aws_ri_utilization(self, commitment_df):
        result = commitment_utilization(commitment_df)
        aws_ri = result[(result["cloud_provider"] == "aws") & (result["discount_type"] == "ri")].iloc[0]
        # used=80, waste=20 → 80%
        assert math.isclose(aws_ri["utilization_pct"], 80.0)

    def test_azure_sp_utilization(self, commitment_df):
        result = commitment_utilization(commitment_df)
        az_sp = result[(result["cloud_provider"] == "azure") & (result["discount_type"] == "sp")].iloc[0]
        # used=150, waste=50 → 75%
        assert math.isclose(az_sp["utilization_pct"], 75.0)

    def test_empty_committed_returns_empty(self):
        df = pd.DataFrame([_row(discount_type="on_demand")])
        result = commitment_utilization(df)
        assert result.empty


# ---------------------------------------------------------------------------
# savings_vs_on_demand
# ---------------------------------------------------------------------------

class TestSavingsVsOnDemand:
    def test_savings_positive_when_nec_less_than_list(self, simple_df):
        result = savings_vs_on_demand(simple_df)
        aws_ri = result[(result["cloud_provider"] == "aws") & (result["discount_type"] == "ri")].iloc[0]
        assert aws_ri["savings"] > 0

    def test_on_demand_zero_savings(self):
        df = pd.DataFrame([_row(list_cost=50.0, nec_used=50.0, discount_type="on_demand")])
        result = savings_vs_on_demand(df)
        assert math.isclose(result.iloc[0]["savings"], 0.0, abs_tol=1e-9)

    def test_savings_pct_formula(self, simple_df):
        result = savings_vs_on_demand(simple_df)
        for _, row in result.iterrows():
            if row["list_cost"] > 0:
                expected = round((row["list_cost"] - row["nec_used"]) / row["list_cost"] * 100, 1)
                assert math.isclose(row["savings_pct"], expected, abs_tol=0.01)


# ---------------------------------------------------------------------------
# commitment_waste_detail
# ---------------------------------------------------------------------------

class TestCommitmentWasteDetail:
    def test_only_waste_rows_returned(self, commitment_df):
        result = commitment_waste_detail(commitment_df)
        assert result["nec_waste"].min() >= 0
        assert len(result) == 2  # two is_commitment_waste=True rows in fixture

    def test_sorted_descending(self, commitment_df):
        result = commitment_waste_detail(commitment_df)
        assert result["nec_waste"].is_monotonic_decreasing

    def test_no_waste_rows_returns_empty(self):
        df = pd.DataFrame([_row(is_commitment_waste=False)])
        result = commitment_waste_detail(df)
        assert result.empty


# ---------------------------------------------------------------------------
# effective_unit_price_summary
# ---------------------------------------------------------------------------

class TestEffectiveUnitPriceSummary:
    def test_discount_pct_non_negative_for_discounted_rows(self):
        rows = [
            _row(nec_used=70.0, usage_amount=100.0, list_cost=100.0, effective_unit_price=0.70),
        ]
        df = pd.DataFrame(rows)
        result = effective_unit_price_summary(df)
        assert result.iloc[0]["discount_pct"] >= 0

    def test_filters_zero_usage_amount(self):
        rows = [
            _row(nec_used=10.0, usage_amount=0.0, list_cost=10.0),
        ]
        df = pd.DataFrame(rows)
        result = effective_unit_price_summary(df)
        assert result.empty

    def test_uses_precomputed_eup_for_azure(self):
        rows = [
            _row(cloud_provider="azure", nec_used=0.5, usage_amount=1.0,
                 list_cost=1.0, effective_unit_price=0.5),
        ]
        df = pd.DataFrame(rows)
        result = effective_unit_price_summary(df)
        assert math.isclose(result.iloc[0]["avg_effective_unit_price"], 0.5)


# ---------------------------------------------------------------------------
# NECReport dataclass
# ---------------------------------------------------------------------------

class TestNECReport:
    @pytest.fixture
    def report(self, simple_df):
        return NECReport(
            billing_month="2026-03",
            by_cloud=nec_by_cloud(simple_df),
            by_team=nec_by_team(simple_df),
            by_service=nec_by_service_category(simple_df),
            commitment_util=commitment_utilization(simple_df),
            savings=savings_vs_on_demand(simple_df),
            waste_rows=commitment_waste_detail(simple_df),
            raw=simple_df,
        )

    def test_total_list_cost(self, report, simple_df):
        assert math.isclose(report.total_list_cost, simple_df["list_cost"].sum())

    def test_total_nec(self, report, simple_df):
        assert math.isclose(report.total_nec, simple_df["nec"].sum())

    def test_total_savings(self, report):
        assert math.isclose(report.total_savings, report.total_list_cost - report.total_nec)

    def test_overall_savings_pct(self, report):
        expected = round(report.total_savings / report.total_list_cost * 100, 1)
        assert math.isclose(report.overall_savings_pct, expected, abs_tol=0.01)

    def test_summary_contains_billing_month(self, report):
        assert "2026-03" in report.summary()

    def test_summary_contains_cloud_names(self, report):
        summary = report.summary()
        for cloud in ["aws", "azure", "gcp"]:
            assert cloud in summary


# ---------------------------------------------------------------------------
# Fan-out: Azure shared-cost rows divided across N teams
# ---------------------------------------------------------------------------

class TestFanoutAggregation:
    """
    Verify that cloud-level aggregations are not inflated when Azure untagged rows
    are fanned out to multiple teams (each row already carries 1/N of the cost).
    """

    def test_nec_by_cloud_nec_not_inflated(self, fanout_df):
        result = nec_by_cloud(fanout_df)
        azure = result[result["cloud_provider"] == "azure"].iloc[0]
        # 3 rows × (60/3) must sum to 60, not 180
        assert math.isclose(azure["nec"], 60.0)

    def test_nec_by_cloud_list_cost_not_inflated(self, fanout_df):
        result = nec_by_cloud(fanout_df)
        azure = result[result["cloud_provider"] == "azure"].iloc[0]
        assert math.isclose(azure["list_cost"], 90.0)

    def test_nec_by_cloud_waste_not_inflated(self, fanout_df):
        result = nec_by_cloud(fanout_df)
        azure = result[result["cloud_provider"] == "azure"].iloc[0]
        assert math.isclose(azure["nec_waste"], 30.0)

    def test_nec_by_cloud_savings_pct_correct(self, fanout_df):
        result = nec_by_cloud(fanout_df)
        azure = result[result["cloud_provider"] == "azure"].iloc[0]
        expected = round((90.0 - 60.0) / 90.0 * 100, 1)
        assert math.isclose(azure["savings_pct"], expected, abs_tol=0.01)

    def test_nec_by_team_each_team_gets_correct_share(self, fanout_df):
        result = nec_by_team(fanout_df)
        for _, row in result.iterrows():
            assert math.isclose(row["nec"], 20.0)
            assert math.isclose(row["list_cost"], 30.0)

    def test_nec_by_team_savings_correct_per_team(self, fanout_df):
        result = nec_by_team(fanout_df)
        for _, row in result.iterrows():
            # savings = allocated list_cost − allocated nec = 30 − 20 = 10
            assert math.isclose(row["savings"], 10.0)


# ---------------------------------------------------------------------------
# Integration test — skipped when DuckDB is absent
# ---------------------------------------------------------------------------

_DB_PATH = Path(__file__).resolve().parents[1] / "finops_dbt.duckdb"


@pytest.mark.skipif(not _DB_PATH.exists(), reason="finops_dbt.duckdb not present — run `dbt run` first")
class TestIntegration:
    def test_build_nec_report_returns_report(self):
        report = build_nec_report(db_path=_DB_PATH)
        assert isinstance(report, NECReport)
        assert not report.by_cloud.empty

    def test_by_cloud_has_expected_clouds(self):
        report = build_nec_report(db_path=_DB_PATH)
        clouds = set(report.by_cloud["cloud_provider"])
        assert clouds == {"aws", "azure", "gcp"}

    def test_total_nec_positive(self):
        report = build_nec_report(db_path=_DB_PATH)
        assert report.total_nec > 0

    def test_month_filter_narrows_rows(self):
        from allocation.nec_model import load_billing_data
        df_all = load_billing_data(_DB_PATH)
        df_month = load_billing_data(_DB_PATH, billing_month="2026-03")
        assert len(df_month) <= len(df_all)
        assert (df_month["billing_month"] == "2026-03").all()
