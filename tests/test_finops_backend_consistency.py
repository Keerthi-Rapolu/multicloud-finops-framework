from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from intelligence.decision_engine import DecisionEngine
from dashboard.canonical import load_canonical_metrics


_DB_PATH = Path(__file__).resolve().parents[1] / "finops_dbt.duckdb"


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "billing_month": "2026-01",
                "usage_date": pd.Timestamp("2026-01-01"),
                "cloud_provider": "aws",
                "allocated_team": "platform",
                "account_id": "123456789012",
                "resource_id": "i-prod-001",
                "application": "platform-core",
                "environment": "prod",
                "owner_email": "platform-owner@company.com",
                "support_group": "platform-operations",
                "workload_criticality": "mission_critical",
                "sla_tier": "platinum",
                "service_category": "Compute",
                "discount_type": "sp",
                "is_tagged": False,
                "is_shared_cost": False,
                "is_commitment_waste": True,
                "cost_center": None,
                "nec": 140.0,
                "nec_used": 85.0,
                "nec_waste": 55.0,
                "vcpu": 64,
            },
            {
                "billing_month": "2026-02",
                "usage_date": pd.Timestamp("2026-02-01"),
                "cloud_provider": "aws",
                "allocated_team": "platform",
                "account_id": "123456789012",
                "resource_id": "i-prod-001",
                "application": "platform-core",
                "environment": "prod",
                "owner_email": "platform-owner@company.com",
                "support_group": "platform-operations",
                "workload_criticality": "mission_critical",
                "sla_tier": "platinum",
                "service_category": "Compute",
                "discount_type": "sp",
                "is_tagged": False,
                "is_shared_cost": False,
                "is_commitment_waste": True,
                "cost_center": None,
                "nec": 150.0,
                "nec_used": 90.0,
                "nec_waste": 60.0,
                "vcpu": 64,
            },
            {
                "billing_month": "2026-03",
                "usage_date": pd.Timestamp("2026-03-01"),
                "cloud_provider": "aws",
                "allocated_team": "platform",
                "account_id": "123456789012",
                "resource_id": "i-prod-001",
                "application": "platform-core",
                "environment": "prod",
                "owner_email": "platform-owner@company.com",
                "support_group": "platform-operations",
                "workload_criticality": "mission_critical",
                "sla_tier": "platinum",
                "service_category": "Compute",
                "discount_type": "sp",
                "is_tagged": False,
                "is_shared_cost": False,
                "is_commitment_waste": True,
                "cost_center": None,
                "nec": 160.0,
                "nec_used": 95.0,
                "nec_waste": 65.0,
                "vcpu": 64,
            },
            {
                "billing_month": "2026-04",
                "usage_date": pd.Timestamp("2026-04-15"),
                "cloud_provider": "aws",
                "allocated_team": "platform",
                "account_id": "123456789012",
                "resource_id": "i-prod-001",
                "application": "platform-core",
                "environment": "prod",
                "owner_email": "platform-owner@company.com",
                "support_group": "platform-operations",
                "workload_criticality": "mission_critical",
                "sla_tier": "platinum",
                "service_category": "Compute",
                "discount_type": "sp",
                "is_tagged": False,
                "is_shared_cost": True,
                "is_commitment_waste": True,
                "cost_center": None,
                "nec": 175.0,
                "nec_used": 100.0,
                "nec_waste": 75.0,
                "vcpu": 64,
            },
        ]
    )


def test_recommendation_scoring_is_deterministic():
    engine = DecisionEngine()
    run_one = engine.run(_sample_df())
    run_two = engine.run(_sample_df())
    one = [(rec["recommendation_id"], rec["priority_score"]) for rec in run_one.recommendations]
    two = [(rec["recommendation_id"], rec["priority_score"]) for rec in run_two.recommendations]
    assert one == two


@pytest.mark.skipif(not _DB_PATH.exists(), reason="finops_dbt.duckdb not present — run `dbt run` first")
class TestFinOpsBackendConsistency:
    def test_finops_summary_invariants_hold(self):
        con = duckdb.connect(str(_DB_PATH), read_only=True)
        try:
            table_exists = con.execute(
                """
                select count(*)
                from information_schema.tables
                where table_schema = 'marts'
                  and table_name = 'fct_finops_summary'
                """
            ).fetchone()[0]
            if not table_exists:
                pytest.skip("fct_finops_summary not present — run `dbt run` first")
            mismatches = con.execute(
                """
                select count(*)
                from marts.fct_finops_summary
                where abs(total_nec - (total_nec_used + total_nec_waste)) > 0.01
                   or abs((total_list_cost - total_nec) - (total_list_cost - total_nec)) > 0.01
                   or total_recoverable_savings > total_nec + 0.01
                """
            ).fetchone()[0]
        finally:
            con.close()
        assert mismatches == 0

    def test_nec_totals_match_team_scope(self):
        con = duckdb.connect(str(_DB_PATH), read_only=True)
        try:
            mismatches = con.execute(
                """
                with base as (
                    select
                        billing_month,
                        cloud_provider,
                        coalesce(allocated_team, 'unattributed') as team,
                        round(sum(nec), 2) as nec_total
                    from marts.fct_unified_billing
                    group by 1, 2, 3
                ),
                scoped as (
                    select
                        billing_month,
                        cloud_provider,
                        team,
                        round(sum(nec_usd), 2) as nec_total
                    from intermediate.int_team_monthly_scope
                    group by 1, 2, 3
                )
                select count(*) as mismatch_count
                from base b
                inner join scoped s
                    on b.billing_month = s.billing_month
                   and b.cloud_provider = s.cloud_provider
                   and b.team = s.team
                where abs(b.nec_total - s.nec_total) > 0.01
                """
            ).fetchone()[0]
        finally:
            con.close()
        assert mismatches == 0

    def test_unattributed_nec_matches_team_scope(self):
        con = duckdb.connect(str(_DB_PATH), read_only=True)
        try:
            mismatches = con.execute(
                """
                with base as (
                    select
                        billing_month,
                        cloud_provider,
                        coalesce(allocated_team, 'unattributed') as team,
                        round(sum(case when not coalesce(is_tagged, false) then nec else 0.0 end), 2) as unattributed_nec
                    from marts.fct_unified_billing
                    group by 1, 2, 3
                ),
                scoped as (
                    select
                        billing_month,
                        cloud_provider,
                        team,
                        round(sum(unattributed_spend_usd), 2) as unattributed_nec
                    from intermediate.int_team_monthly_scope
                    group by 1, 2, 3
                )
                select count(*) as mismatch_count
                from base b
                inner join scoped s
                    on b.billing_month = s.billing_month
                   and b.cloud_provider = s.cloud_provider
                   and b.team = s.team
                where abs(b.unattributed_nec - s.unattributed_nec) > 0.01
                """
            ).fetchone()[0]
        finally:
            con.close()
        assert mismatches == 0

    def test_no_negative_nec_in_canonical_billing_mart(self):
        con = duckdb.connect(str(_DB_PATH), read_only=True)
        try:
            negative_rows = con.execute(
                """
                select count(*)
                from marts.fct_unified_billing
                where nec < 0
                """
            ).fetchone()[0]
        finally:
            con.close()
        assert negative_rows == 0

    def test_waste_and_discount_savings_are_not_mixed(self):
        con = duckdb.connect(str(_DB_PATH), read_only=True)
        try:
            table_exists = con.execute(
                """
                select count(*)
                from information_schema.tables
                where table_schema = 'marts'
                  and table_name = 'fct_finops_recommendations'
                """
            ).fetchone()[0]
            if not table_exists:
                pytest.skip("fct_finops_recommendations not present — run `dbt run` first")
            mixed_rows = con.execute(
                """
                select count(*)
                from marts.fct_finops_recommendations
                where root_cause_type in (
                    'missing_owner_team_cost_center_environment_tags',
                    'cannot_allocate_cost_to_accountable_team',
                    'shared_services_concentrated_to_single_team_or_account',
                    'abnormal_nec_movement_from_billing_trend',
                    'month_end_nec_run_rate_exceeds_expected_baseline'
                )
                  and estimated_savings_usd <> 0.0
                """
            ).fetchone()[0]
        finally:
            con.close()
        assert mixed_rows == 0

    def test_finops_summary_unattributed_matches_base_billing(self):
        con = duckdb.connect(str(_DB_PATH), read_only=True)
        try:
            table_exists = con.execute(
                """
                select count(*)
                from information_schema.tables
                where table_schema = 'marts'
                  and table_name = 'fct_finops_summary'
                """
            ).fetchone()[0]
            if not table_exists:
                pytest.skip("fct_finops_summary not present — run `dbt run` first")
            mismatches = con.execute(
                """
                with base as (
                    select
                        billing_month,
                        cloud_provider,
                        coalesce(allocated_team, 'unattributed') as team,
                        round(sum(case when not coalesce(is_tagged, false) then nec else 0.0 end), 2) as unattributed_nec
                    from marts.fct_unified_billing
                    group by 1, 2, 3
                )
                select count(*)
                from marts.fct_finops_summary s
                inner join base b
                    on s.billing_month = b.billing_month
                   and s.cloud_provider = b.cloud_provider
                   and s.team = b.team
                where abs(s.total_unattributed_cost - b.unattributed_nec) > 0.01
                """
            ).fetchone()[0]
        finally:
            con.close()
        assert mismatches == 0

    def test_finops_decision_metrics_invariants_hold(self):
        con = duckdb.connect(str(_DB_PATH), read_only=True)
        try:
            table_exists = con.execute(
                """
                select count(*)
                from information_schema.tables
                where table_schema = 'marts'
                  and table_name = 'fct_finops_decision_metrics'
                """
            ).fetchone()[0]
            if not table_exists:
                pytest.skip("fct_finops_decision_metrics not present - run `dbt run` first")
            mismatches = con.execute(
                """
                select count(*)
                from marts.fct_finops_decision_metrics
                where abs(optimized_nec - (projected_nec - projected_savings)) > 0.02
                   or projected_savings > actionable_savings + 0.01
                   or actionable_savings > recoverable_savings + 0.01
                   or recoverable_savings > waste_signal + 0.01
                   or commitment_waste < 0
                   or unattributed_nec < 0
                """
            ).fetchone()[0]
        finally:
            con.close()
        assert mismatches == 0

    def test_canonical_metrics_loader_matches_decision_metrics(self):
        con = duckdb.connect(str(_DB_PATH), read_only=True)
        try:
            month = con.execute(
                "select max(billing_month) from marts.fct_finops_decision_metrics"
            ).fetchone()[0]
            row = con.execute(
                """
                select
                    round(sum(list_cost), 2),
                    round(sum(nec), 2),
                    round(sum(unattributed_nec), 2),
                    round(sum(commitment_waste), 2),
                    round(sum(recoverable_savings), 2),
                    round(sum(actionable_savings), 2),
                    round(sum(projected_savings), 2),
                    round(sum(optimized_nec), 2)
                from marts.fct_finops_decision_metrics
                where billing_month = ?
                """,
                [month],
            ).fetchone()
        finally:
            con.close()
        metrics = load_canonical_metrics(month, "All")
        assert round(metrics.list_cost, 2) == row[0]
        assert round(metrics.nec, 2) == row[1]
        assert round(metrics.unattributed_nec, 2) == row[2]
        assert round(metrics.commitment_waste, 2) == row[3]
        assert round(metrics.recoverable_savings, 2) == row[4]
        assert round(metrics.actionable_savings, 2) == row[5]
        assert round(metrics.projected_savings, 2) == row[6]
        assert round(metrics.optimized_nec, 2) == row[7]

    def test_forecast_backtest_metrics_are_well_formed(self):
        con = duckdb.connect(str(_DB_PATH), read_only=True)
        try:
            table_exists = con.execute(
                """
                select count(*)
                from information_schema.tables
                where table_schema = 'marts'
                  and table_name = 'fct_forecast_backtest'
                """
            ).fetchone()[0]
            if not table_exists:
                pytest.skip("fct_forecast_backtest not present - run `dbt run` first")
            bad_rows = con.execute(
                """
                select count(*)
                from marts.fct_forecast_backtest
                where absolute_error_usd < 0
                   or absolute_pct_error < 0
                   or accuracy_pct < 0
                   or observed_days < 7
                """
            ).fetchone()[0]
        finally:
            con.close()
        assert bad_rows == 0
