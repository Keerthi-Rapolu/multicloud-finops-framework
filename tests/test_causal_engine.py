"""
Tests for intelligence/causal_engine.py.

All unit tests use hand-crafted DataFrames — no DuckDB connection required.
The integration class at the bottom is skipped when finops_dbt.duckdb is absent.
"""

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from intelligence import CausalInsight, RootCause
from intelligence.causal_engine import (
    _get_teams,
    build_causal_facts,
    build_nec_trend,
    compute_zscore_anomaly,
    reason,
    run,
)

# ---------------------------------------------------------------------------
# Helpers & fixtures
# ---------------------------------------------------------------------------

_INSIGHT_KEYS = {"scope", "period", "cost_change_pct", "root_causes", "confidence", "anomaly"}
_ROOT_CAUSE_KEYS = {"cause", "evidence", "weight"}


def _row(**overrides) -> dict:
    base = dict(
        cloud_provider="aws",
        billing_month="2026-03",
        account_id="acct-001",
        resource_id="res-001",
        service_name="AmazonEC2",
        service_category="Compute",
        discount_type="on_demand",
        usage_date=pd.Timestamp("2026-03-15"),
        usage_amount=100.0,
        list_cost=10.0,
        nec=10.0,
        nec_used=10.0,
        nec_waste=0.0,
        allocated_nec=10.0,
        allocated_team="platform",
        is_tagged=True,
        is_commitment_waste=False,
        is_shared_cost=False,
        vcpu=2,
        memory_gb=4,
        instance_type="t3.medium",
        region="us-east-1",
        tag_team="platform",
        tag_environment="prod",
        tag_cost_center="eng",
    )
    base.update(overrides)
    return base


def _waste_finding(team="platform", waste_type="unused_commitment",
                   nec_waste=10.0, nec_used=5.0, confidence=0.95) -> dict:
    return dict(
        resource_id="res-001",
        cloud_provider="aws",
        allocated_team=team,
        service_category="Compute",
        instance_type=None,
        waste_type=waste_type,
        nec_waste=nec_waste,
        nec_used=nec_used,
        confidence=confidence,
        billing_month="2026-03",
        evidence={},
    )


# ---------------------------------------------------------------------------
# build_nec_trend
# ---------------------------------------------------------------------------

class TestBuildNecTrend:
    def test_required_columns_present(self):
        df = pd.DataFrame([_row()])
        result = build_nec_trend(df)
        assert {"billing_month", "allocated_team", "period_nec", "pct_change"}.issubset(result.columns)

    def test_single_month_pct_change_is_nan(self):
        df = pd.DataFrame([_row(nec_used=100.0)])
        result = build_nec_trend(df)
        assert result["pct_change"].isna().all()

    def test_two_months_pct_change_computed(self):
        rows = [
            _row(billing_month="2026-03", nec_used=100.0, allocated_team="platform"),
            _row(billing_month="2026-04", nec_used=120.0, allocated_team="platform"),
        ]
        df = pd.DataFrame(rows)
        result = build_nec_trend(df)
        apr = result[result["billing_month"] == "2026-04"].iloc[0]
        assert math.isclose(apr["pct_change"], 20.0, rel_tol=1e-4)

    def test_positive_pct_change_on_increase(self):
        rows = [
            _row(billing_month="2026-03", nec_used=50.0,  allocated_team="backend"),
            _row(billing_month="2026-04", nec_used=100.0, allocated_team="backend"),
        ]
        df = pd.DataFrame(rows)
        result = build_nec_trend(df)
        apr = result[result["billing_month"] == "2026-04"].iloc[0]
        assert apr["pct_change"] > 0

    def test_negative_pct_change_on_decrease(self):
        rows = [
            _row(billing_month="2026-03", nec_used=100.0, allocated_team="ml"),
            _row(billing_month="2026-04", nec_used=80.0,  allocated_team="ml"),
        ]
        df = pd.DataFrame(rows)
        result = build_nec_trend(df)
        apr = result[result["billing_month"] == "2026-04"].iloc[0]
        assert apr["pct_change"] < 0

    def test_multiple_teams_independent_pct_change(self):
        rows = [
            _row(billing_month="2026-03", nec_used=100.0, allocated_team="platform"),
            _row(billing_month="2026-04", nec_used=200.0, allocated_team="platform"),
            _row(billing_month="2026-03", nec_used=50.0,  allocated_team="backend"),
            _row(billing_month="2026-04", nec_used=50.0,  allocated_team="backend"),
        ]
        df = pd.DataFrame(rows)
        result = build_nec_trend(df)
        plt = result[(result["allocated_team"] == "platform") & (result["billing_month"] == "2026-04")].iloc[0]
        bck = result[(result["allocated_team"] == "backend")  & (result["billing_month"] == "2026-04")].iloc[0]
        assert math.isclose(plt["pct_change"], 100.0, rel_tol=1e-4)
        assert math.isclose(bck["pct_change"],   0.0, abs_tol=1e-9)

    def test_aggregates_multiple_rows_per_month(self):
        rows = [
            _row(billing_month="2026-03", nec_used=60.0, allocated_team="platform"),
            _row(billing_month="2026-03", nec_used=40.0, allocated_team="platform"),
        ]
        df = pd.DataFrame(rows)
        result = build_nec_trend(df)
        assert len(result) == 1
        assert math.isclose(result.iloc[0]["period_nec"], 100.0)


# ---------------------------------------------------------------------------
# compute_zscore_anomaly
# ---------------------------------------------------------------------------

class TestComputeZscoreAnomaly:
    def _trend_with_spike(self) -> pd.DataFrame:
        rows = [
            {"billing_month": f"2026-0{i}", "allocated_team": "platform",
             "period_nec": 100.0, "pct_change": 0.0}
            for i in range(1, 6)
        ]
        rows[-1]["period_nec"] = 500.0  # spike in month 5
        return pd.DataFrame(rows)

    def test_adds_anomaly_column(self):
        trend = build_nec_trend(pd.DataFrame([_row()]))
        result = compute_zscore_anomaly(trend)
        assert "anomaly" in result.columns

    def test_spike_flagged_as_anomaly(self):
        result = compute_zscore_anomaly(self._trend_with_spike())
        last_row = result[result["billing_month"] == "2026-05"].iloc[0]
        assert last_row["anomaly"] is True or last_row["anomaly"] == True  # noqa: E712

    def test_stable_series_not_anomaly(self):
        # All values identical — z-score=0 everywhere, no anomaly
        rows = [
            {"billing_month": f"2026-0{i}", "allocated_team": "platform",
             "period_nec": 100.0, "pct_change": 0.0}
            for i in range(1, 6)
        ]
        trend = pd.DataFrame(rows)
        result = compute_zscore_anomaly(trend)
        assert not result["anomaly"].any()

    def test_fewer_than_min_periods_no_anomaly(self):
        rows = [
            {"billing_month": "2026-03", "allocated_team": "platform",
             "period_nec": 100.0, "pct_change": float("nan")},
            {"billing_month": "2026-04", "allocated_team": "platform",
             "period_nec": 999.0, "pct_change": 899.0},
        ]
        trend = pd.DataFrame(rows)
        result = compute_zscore_anomaly(trend, min_periods=3)
        assert not result["anomaly"].any()

    def test_anomaly_column_is_bool(self):
        trend = build_nec_trend(pd.DataFrame([_row()]))
        result = compute_zscore_anomaly(trend)
        assert result["anomaly"].dtype == bool or result["anomaly"].apply(type).eq(bool).all()


# ---------------------------------------------------------------------------
# build_causal_facts
# ---------------------------------------------------------------------------

class TestBuildCausalFacts:
    def test_commitment_waste_fact_generated(self):
        df = pd.DataFrame([_row(allocated_team="platform", nec_used=100.0)])
        findings = [_waste_finding(team="platform", waste_type="unused_commitment",
                                   nec_waste=15.0, nec_used=0.0)]
        facts = build_causal_facts(df, findings)
        types = [f.fact_type for f in facts]
        assert "commitment_waste_identified" in types

    def test_idle_resource_fact_generated(self):
        df = pd.DataFrame([_row(allocated_team="backend", nec_used=50.0)])
        findings = [_waste_finding(team="backend", waste_type="idle_compute",
                                   nec_waste=0.0, nec_used=5.0)]
        facts = build_causal_facts(df, findings)
        types = [f.fact_type for f in facts]
        assert "idle_resources_detected" in types

    def test_untagged_cost_gap_fact_at_threshold(self):
        rows = [
            _row(allocated_team="data-eng", nec_used=100.0, is_tagged=True),
            _row(allocated_team="data-eng", nec_used=20.0,  is_tagged=False),
        ]
        df = pd.DataFrame(rows)
        facts = build_causal_facts(df, [])
        types = [f.fact_type for f in facts]
        # 20/(100+20) = 16.7% → above 10% threshold
        assert "untagged_cost_gap" in types

    def test_untagged_cost_gap_below_threshold_not_generated(self):
        rows = [
            _row(allocated_team="data-eng", nec_used=100.0, is_tagged=True),
            _row(allocated_team="data-eng", nec_used=5.0,   is_tagged=False),
        ]
        df = pd.DataFrame(rows)
        facts = build_causal_facts(df, [])
        types = [f.fact_type for f in facts]
        # 5/105 = 4.8% → below 10% threshold
        assert "untagged_cost_gap" not in types

    def test_service_category_dominance_at_threshold(self):
        rows = [
            _row(allocated_team="ml", nec_used=80.0, service_category="Compute"),
            _row(allocated_team="ml", nec_used=10.0, service_category="Storage"),
        ]
        df = pd.DataFrame(rows)
        facts = build_causal_facts(df, [])
        types = [f.fact_type for f in facts]
        # Compute = 80/90 = 88.9% → above 50% threshold
        assert "service_category_dominance" in types

    def test_service_dominance_below_threshold_not_generated(self):
        rows = [
            _row(allocated_team="frontend", nec_used=40.0, service_category="Compute"),
            _row(allocated_team="frontend", nec_used=35.0, service_category="Storage"),
            _row(allocated_team="frontend", nec_used=25.0, service_category="Database"),
        ]
        df = pd.DataFrame(rows)
        facts = build_causal_facts(df, [])
        types = [f for f in facts if f.scope == "frontend"]
        dom = [f for f in types if f.fact_type == "service_category_dominance"]
        assert len(dom) == 0

    def test_global_waste_fact_generated_when_waste_pct_high(self):
        rows = [
            _row(nec_used=100.0, nec_waste=10.0, is_commitment_waste=True, allocated_team="platform"),
        ]
        df = pd.DataFrame(rows)
        facts = build_causal_facts(df, [])
        global_facts = [f for f in facts if f.scope == "_global"]
        assert len(global_facts) >= 1

    def test_facts_have_weight_in_range(self):
        df = pd.DataFrame([
            _row(allocated_team="platform", nec_used=100.0),
            _row(allocated_team="platform", nec_used=5.0, is_tagged=False),
        ])
        findings = [_waste_finding(team="platform", waste_type="unused_commitment",
                                   nec_waste=10.0, nec_used=0.0)]
        facts = build_causal_facts(df, findings)
        for f in facts:
            assert 0.0 <= f.weight <= 1.0, f"weight out of range: {f.weight}"

    def test_no_facts_for_zero_nec_team(self):
        df = pd.DataFrame([_row(allocated_team="ml", nec_used=0.0)])
        facts = build_causal_facts(df, [])
        ml_facts = [f for f in facts if f.scope == "ml"]
        assert len(ml_facts) == 0


# ---------------------------------------------------------------------------
# reason
# ---------------------------------------------------------------------------

class TestReason:
    def _make_trend(self, team="platform", pct_change=0.0, anomaly=False) -> pd.DataFrame:
        return pd.DataFrame([{
            "billing_month": "2026-03",
            "allocated_team": team,
            "period_nec": 100.0,
            "pct_change": pct_change,
            "anomaly": anomaly,
            "z_score": float("nan"),
        }])

    def test_output_has_all_required_keys(self):
        df = pd.DataFrame([_row(allocated_team="platform")])
        facts = build_causal_facts(df, [])
        trend = self._make_trend()
        insight = reason(facts, trend, "platform")
        assert _INSIGHT_KEYS.issubset(insight.keys())

    def test_root_causes_not_empty(self):
        df = pd.DataFrame([_row(allocated_team="platform", nec_used=100.0)])
        findings = [_waste_finding(team="platform", waste_type="unused_commitment")]
        facts = build_causal_facts(df, findings)
        trend = self._make_trend()
        insight = reason(facts, trend, "platform")
        assert len(insight["root_causes"]) >= 1

    def test_each_root_cause_has_required_keys(self):
        df = pd.DataFrame([_row(allocated_team="platform", nec_used=100.0)])
        facts = build_causal_facts(df, [])
        trend = self._make_trend()
        insight = reason(facts, trend, "platform")
        for rc in insight["root_causes"]:
            assert _ROOT_CAUSE_KEYS.issubset(rc.keys())

    def test_confidence_in_range(self):
        df = pd.DataFrame([_row(allocated_team="platform", nec_used=100.0)])
        facts = build_causal_facts(df, [])
        trend = self._make_trend()
        insight = reason(facts, trend, "platform")
        assert 0.0 <= insight["confidence"] <= 1.0

    def test_anomaly_flag_propagated(self):
        df = pd.DataFrame([_row(allocated_team="platform")])
        facts = build_causal_facts(df, [])
        trend = self._make_trend(anomaly=True)
        insight = reason(facts, trend, "platform")
        assert insight["anomaly"] is True

    def test_spike_adds_cost_spike_cause(self):
        df = pd.DataFrame([_row(allocated_team="platform", nec_used=100.0)])
        facts = build_causal_facts(df, [])
        trend = self._make_trend(pct_change=50.0)  # +50% MoM
        insight = reason(facts, trend, "platform")
        causes = [rc["cause"] for rc in insight["root_causes"]]
        assert "team_cost_spike" in causes

    def test_decrease_adds_cost_decrease_cause(self):
        df = pd.DataFrame([_row(allocated_team="platform", nec_used=100.0)])
        facts = build_causal_facts(df, [])
        trend = self._make_trend(pct_change=-30.0)  # -30% MoM
        insight = reason(facts, trend, "platform")
        causes = [rc["cause"] for rc in insight["root_causes"]]
        assert "team_cost_decrease" in causes

    def test_no_trend_data_gives_zero_change(self):
        df = pd.DataFrame([_row(allocated_team="platform")])
        facts = build_causal_facts(df, [])
        empty_trend = pd.DataFrame(columns=["billing_month", "allocated_team",
                                            "period_nec", "pct_change", "anomaly"])
        insight = reason(facts, empty_trend, "platform")
        assert insight["cost_change_pct"] == 0.0
        assert insight["anomaly"] is False

    def test_scope_format(self):
        df = pd.DataFrame([_row(allocated_team="backend")])
        facts = build_causal_facts(df, [])
        trend = self._make_trend(team="backend")
        insight = reason(facts, trend, "backend")
        assert insight["scope"] == "team:backend"

    def test_root_causes_capped_at_three(self):
        df = pd.DataFrame([
            _row(allocated_team="platform", nec_used=100.0, is_tagged=False),
            _row(allocated_team="platform", nec_used=5.0,   is_tagged=True,
                 service_category="Platform"),
        ])
        findings = [
            _waste_finding(team="platform", waste_type="unused_commitment",
                           nec_waste=10.0, nec_used=0.0),
            _waste_finding(team="platform", waste_type="idle_compute",
                           nec_waste=0.0, nec_used=3.0),
        ]
        facts = build_causal_facts(df, findings)
        trend = self._make_trend(pct_change=25.0)
        insight = reason(facts, trend, "platform")
        assert len(insight["root_causes"]) <= 3

    def test_cost_change_pct_sign_positive(self):
        df = pd.DataFrame([_row(allocated_team="platform")])
        facts = build_causal_facts(df, [])
        trend = self._make_trend(pct_change=20.0)
        insight = reason(facts, trend, "platform")
        assert insight["cost_change_pct"] > 0

    def test_cost_change_pct_sign_negative(self):
        df = pd.DataFrame([_row(allocated_team="platform")])
        facts = build_causal_facts(df, [])
        trend = self._make_trend(pct_change=-20.0)
        insight = reason(facts, trend, "platform")
        assert insight["cost_change_pct"] < 0


# ---------------------------------------------------------------------------
# run  (entry point)
# ---------------------------------------------------------------------------

class TestRun:
    def test_returns_one_insight_per_team(self):
        rows = [
            _row(allocated_team="platform", nec_used=100.0),
            _row(allocated_team="backend",  nec_used=80.0),
            _row(allocated_team="ml",       nec_used=60.0),
        ]
        df = pd.DataFrame(rows)
        insights = run(df, [])
        scopes = {i["scope"] for i in insights}
        assert scopes == {"team:platform", "team:backend", "team:ml"}

    def test_output_sorted_by_abs_cost_change_desc(self):
        rows = [
            _row(billing_month="2026-03", allocated_team="platform", nec_used=100.0),
            _row(billing_month="2026-04", allocated_team="platform", nec_used=150.0),
            _row(billing_month="2026-03", allocated_team="backend",  nec_used=100.0),
            _row(billing_month="2026-04", allocated_team="backend",  nec_used=100.0),
        ]
        df = pd.DataFrame(rows)
        insights = run(df, [])
        changes = [abs(i["cost_change_pct"]) for i in insights]
        assert changes == sorted(changes, reverse=True)

    def test_no_null_team_in_output(self):
        rows = [
            _row(allocated_team="platform",  nec_used=100.0),
            _row(allocated_team=None,         nec_used=50.0),
        ]
        df = pd.DataFrame(rows)
        insights = run(df, [])
        scopes = {i["scope"] for i in insights}
        assert "team:None" not in scopes
        assert "team:nan" not in scopes

    def test_all_insights_have_valid_schema(self):
        df = pd.DataFrame([_row(allocated_team="platform", nec_used=100.0)])
        insights = run(df, [])
        for ins in insights:
            assert _INSIGHT_KEYS.issubset(ins.keys())
            assert 0.0 <= ins["confidence"] <= 1.0
            assert isinstance(ins["root_causes"], list)
            assert len(ins["root_causes"]) >= 1

    def test_empty_waste_findings_still_produces_insights(self):
        df = pd.DataFrame([_row(allocated_team="frontend", nec_used=200.0)])
        insights = run(df, [])
        assert len(insights) == 1
        assert insights[0]["scope"] == "team:frontend"


# ---------------------------------------------------------------------------
# Integration test — skipped when DuckDB is absent
# ---------------------------------------------------------------------------

_DB_PATH = Path(__file__).resolve().parents[1] / "finops_dbt.duckdb"


@pytest.mark.skipif(
    not _DB_PATH.exists(),
    reason="finops_dbt.duckdb not present — run `dbt run` first",
)
class TestIntegration:
    @pytest.fixture(scope="class")
    def df_and_insights(self):
        import duckdb
        from intelligence.waste_detector import run as detect_waste

        con = duckdb.connect(str(_DB_PATH), read_only=True)
        df = con.execute("SELECT * FROM marts.fct_unified_billing").df()
        con.close()

        findings = detect_waste(df)
        insights = run(df, findings)
        return df, insights

    def test_one_insight_per_team(self, df_and_insights):
        df, insights = df_and_insights
        expected_teams = set(_get_teams(df))
        actual_scopes  = {i["scope"].replace("team:", "") for i in insights}
        assert actual_scopes == expected_teams

    def test_all_insights_valid_schema(self, df_and_insights):
        _, insights = df_and_insights
        for ins in insights:
            assert _INSIGHT_KEYS.issubset(ins.keys())
            assert 0.0 <= ins["confidence"] <= 1.0
            assert len(ins["root_causes"]) >= 1

    def test_each_root_cause_has_evidence(self, df_and_insights):
        _, insights = df_and_insights
        for ins in insights:
            for rc in ins["root_causes"]:
                assert rc["evidence"], f"Empty evidence in {ins['scope']}"

    def test_single_month_no_anomaly(self, df_and_insights):
        df, insights = df_and_insights
        if df["billing_month"].nunique() < 3:
            for ins in insights:
                assert ins["anomaly"] is False

    def test_commitment_waste_cause_present(self, df_and_insights):
        _, insights = df_and_insights
        all_causes = {rc["cause"] for i in insights for rc in i["root_causes"]}
        assert "commitment_waste_identified" in all_causes