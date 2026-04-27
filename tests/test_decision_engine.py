import pandas as pd

from intelligence.decision_engine import DecisionEngine, example_run


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


def test_decision_engine_generates_expected_signal_types():
    engine = DecisionEngine()
    signals = engine.generate_signals(_sample_df())
    signal_types = {signal["signal_type"] for signal in signals}
    assert "tagging_gap" in signal_types
    assert "unattributed_cost_gap" in signal_types
    assert "idle_compute_proxy" in signal_types
    assert "zombie_resource" not in signal_types
    assert "commitment_waste" in signal_types
    assert "cost_anomaly" in signal_types
    assert "forecasted_month_end_risk" in signal_types


def test_decision_engine_root_cause_mapping_is_strict():
    run = DecisionEngine().run(_sample_df())
    root_causes = {rec["root_cause_type"] for rec in run.recommendations}
    assert "missing_owner_team_cost_center_environment_tags" in root_causes
    assert "cannot_allocate_cost_to_accountable_team" in root_causes
    assert "billing_side_idle_compute_proxy" in root_causes
    assert "unused_ri_sp_cud_capacity" in root_causes


def test_decision_engine_recommendations_are_ranked():
    engine = DecisionEngine()
    run = engine.run(_sample_df())
    assert run.recommendations
    scores = [rec["priority_score"] for rec in run.recommendations]
    assert scores == sorted(scores, reverse=True)


def test_decision_engine_selects_one_decision_per_entity():
    run = DecisionEngine().run(_sample_df())
    assert run.decisions
    for decision in run.decisions:
        assert decision["candidate_recommendations"]
        assert decision["selected_recommendation"] in decision["candidate_recommendations"]


def test_recommendation_explanation_is_structured():
    recommendation = DecisionEngine().run(_sample_df()).recommendations[0]
    assert recommendation["signal_ids"]
    assert recommendation["explanation"]["root_cause_type"]
    assert recommendation["explanation"]["evidence"]


def test_example_run_returns_decision_run():
    run = example_run()
    assert run.signals
    assert run.recommendations
    assert run.decisions
