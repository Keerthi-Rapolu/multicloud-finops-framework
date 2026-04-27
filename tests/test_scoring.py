from intelligence.scoring import (
    ConfidenceWeights,
    accuracy_pct,
    calibrated_confidence_score,
    confidence_calibration_gap,
    confidence_score,
    effort_score,
    governance_severity_score,
    low_risk_bonus_score,
    priority_score,
    risk_score,
    signal_strength_score,
    time_to_value_days,
    urgency_score,
)


def test_signal_strength_above_threshold():
    assert signal_strength_score(0.40, 0.20, "above") == 1.0


def test_confidence_score_weighted_average():
    result = confidence_score(0.8, 0.6, 0.4)
    assert result == 0.63


def test_confidence_weights_are_configurable():
    result = confidence_score(0.8, 0.6, 0.4, weights=ConfidenceWeights(0.5, 0.3, 0.2))
    assert result == 0.66


def test_risk_score_increases_with_environment_and_action():
    low = risk_score("low", "dev", "bronze", "enforce_tags")
    high = risk_score("mission_critical", "prod", "platinum", "remove_resource")
    assert 0 <= low < high <= 100


def test_governance_severity_rewards_accountability_gaps():
    assert governance_severity_score("tagging_gap", owner_missing=True, sla_breached=True) == 1.0
    assert governance_severity_score("commitment_waste") < governance_severity_score("tagging_gap")


def test_low_risk_bonus_prefers_non_disruptive_actions():
    assert low_risk_bonus_score(risk_score_value=15, approval_required=False, action_type="enforce_tags") > 0.8
    assert low_risk_bonus_score(risk_score_value=85, approval_required=True, action_type="remove_resource") == 0.0


def test_urgency_score_is_bounded():
    assert urgency_score(0.8, 5.0) == 1.0


def test_effort_and_time_to_value_are_action_specific():
    assert effort_score("enforce_tags") < effort_score("remove_resource")
    assert time_to_value_days("release_commitment", approval_required=True) == 37


def test_priority_score_matches_finops_formula():
    result = priority_score(
        normalized_savings=0.8,
        confidence_score_value=0.7,
        governance_severity_value=0.9,
        urgency_score_value=0.5,
        low_risk_bonus_value=0.8,
    )
    expected = round((0.8 * 0.35) + (0.7 * 0.25) + (0.9 * 0.20) + (0.5 * 0.10) + (0.8 * 0.10), 6)
    assert result == expected


def test_accuracy_pct_and_calibration_gap():
    assert accuracy_pct(100.0, 80.0) == 80.0
    assert confidence_calibration_gap(0.70, 80.0) == 10.0


def test_calibrated_confidence_score_rewards_persistence_and_corroboration():
    assert calibrated_confidence_score(0.70, persistent_periods=3, corroborating_signals=2, anomaly_score=0.0) == 0.80
