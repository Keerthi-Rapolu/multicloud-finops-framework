"""
Canonical scoring functions for the FinOps decision engine.

All bounded scores are normalized to 0-1 except:
  - risk_score: 0-100
  - effort_score: ordinal 1-5
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Iterable, Mapping
import math


@dataclass(frozen=True)
class PriorityWeights:
    normalized_savings: float = 0.35
    confidence: float = 0.25
    governance_severity: float = 0.20
    urgency: float = 0.10
    low_risk_bonus: float = 0.10


@dataclass(frozen=True)
class ConfidenceWeights:
    data_completeness: float = 0.40
    signal_strength: float = 0.35
    historical_stability: float = 0.25


@dataclass(frozen=True)
class UrgencyWeights:
    waste_growth_rate: float = 0.60
    anomaly_score: float = 0.40


@dataclass(frozen=True)
class ScoringConfig:
    priority: PriorityWeights = field(default_factory=PriorityWeights)
    confidence: ConfidenceWeights = field(default_factory=ConfidenceWeights)
    urgency: UrgencyWeights = field(default_factory=UrgencyWeights)


DEFAULT_SCORING_CONFIG = ScoringConfig()

RISK_CRITICALITY = {
    "low": 15.0,
    "medium": 35.0,
    "high": 65.0,
    "mission_critical": 90.0,
}

RISK_ENVIRONMENT = {
    "sandbox": 5.0,
    "dev": 15.0,
    "test": 25.0,
    "qa": 25.0,
    "nonprod": 30.0,
    "staging": 35.0,
    "prod": 80.0,
}

RISK_SLA = {
    "bronze": 10.0,
    "silver": 35.0,
    "gold": 65.0,
    "platinum": 90.0,
}

RISK_ACTION = {
    "assign_owner": 10.0,
    "enforce_tags": 15.0,
    "release_commitment": 25.0,
    "resize_down": 60.0,
    "remove_resource": 85.0,
    "rebalance_shared_cost": 35.0,
    "investigate_anomaly": 20.0,
    "review_forecast_risk": 25.0,
}

ACTION_EFFORT = {
    "assign_owner": 1.0,
    "enforce_tags": 2.0,
    "release_commitment": 2.0,
    "resize_down": 3.0,
    "remove_resource": 4.0,
    "rebalance_shared_cost": 2.0,
    "investigate_anomaly": 2.0,
    "review_forecast_risk": 2.0,
}

ACTION_TIME_TO_VALUE = {
    "assign_owner": 1,
    "enforce_tags": 3,
    "remove_resource": 3,
    "resize_down": 7,
    "release_commitment": 30,
    "rebalance_shared_cost": 7,
    "investigate_anomaly": 3,
    "review_forecast_risk": 3,
}

ROOT_CAUSE_BY_SIGNAL = {
    "tagging_gap": "missing_owner_team_cost_center_environment_tags",
    "unattributed_cost_gap": "cannot_allocate_cost_to_accountable_team",
    "commitment_waste": "unused_ri_sp_cud_capacity",
    "zombie_resource": "no_activity_or_near_zero_cost",
    "idle_compute_proxy": "billing_side_idle_compute_proxy",
    "shared_cost_concentration": "shared_services_concentrated_to_single_team_or_account",
    "cost_anomaly": "abnormal_nec_movement_from_billing_trend",
    "forecasted_month_end_risk": "month_end_nec_run_rate_exceeds_expected_baseline",
}

RECOVERY_RATE = {
    "tagging_gap": 0.0,
    "unattributed_cost_gap": 0.0,
    "commitment_waste": 0.60,
    "zombie_resource": 1.00,
    "idle_compute_proxy": 0.60,
    "shared_cost_concentration": 0.0,
    "cost_anomaly": 0.0,
    "forecasted_month_end_risk": 0.0,
}

SIGNAL_WEIGHT = {
    "tagging_gap": 0.95,
    "unattributed_cost_gap": 0.95,
    "commitment_waste": 0.90,
    "zombie_resource": 0.75,
    "idle_compute_proxy": 0.70,
    "shared_cost_concentration": 0.85,
    "cost_anomaly": 0.80,
    "forecasted_month_end_risk": 0.80,
}

DEFAULT_CAP = 1.0


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def clamp(value: float, lower: float, upper: float) -> float:
    return max(float(lower), min(float(upper), float(value)))


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if abs(float(denominator)) < 1e-12:
        return default
    return float(numerator) / float(denominator)


def normalize_ratio(numerator: float, denominator: float, cap: float = DEFAULT_CAP) -> float:
    if denominator <= 0 or cap <= 0:
        return 0.0
    return clamp01(safe_div(numerator, denominator) / cap)


def normalize_savings(savings_usd: float, max_savings_in_scope: float) -> float:
    return normalize_ratio(max(float(savings_usd), 0.0), max(float(max_savings_in_scope), 1.0), cap=1.0)


def normalize_growth_rate(growth_rate: float, cap: float = 0.50) -> float:
    return clamp01(max(float(growth_rate), 0.0) / cap)


def normalize_anomaly_score(anomaly_score: float, cap: float = 3.0) -> float:
    return clamp01(abs(float(anomaly_score)) / cap)


def data_completeness_score(available_fields: int, total_fields: int) -> float:
    return clamp01(safe_div(available_fields, total_fields))


def signal_strength_score(metric_value: float, threshold: float, direction: str) -> float:
    if direction == "above":
        if threshold <= 0:
            return clamp01(metric_value)
        return clamp01(safe_div(metric_value - threshold, threshold))
    if direction == "below":
        if threshold <= 0:
            return 0.0
        return clamp01(safe_div(threshold - metric_value, threshold))
    raise ValueError(f"Unsupported direction: {direction}")


def historical_stability_score(values: Iterable[float]) -> float:
    points = [float(v) for v in values]
    if len(points) < 2:
        return 0.50
    mean_value = sum(points) / len(points)
    if abs(mean_value) < 1e-12:
        return 0.50
    variance = sum((v - mean_value) ** 2 for v in points) / len(points)
    cv = math.sqrt(variance) / abs(mean_value)
    return clamp01(1.0 - min(cv, 1.0))


def confidence_score(
    data_completeness: float,
    signal_strength: float,
    historical_stability: float,
    *,
    weights: ConfidenceWeights | None = None,
) -> float:
    weight_set = weights or DEFAULT_SCORING_CONFIG.confidence
    return round(
        clamp01(
            (clamp01(data_completeness) * weight_set.data_completeness)
            + (clamp01(signal_strength) * weight_set.signal_strength)
            + (clamp01(historical_stability) * weight_set.historical_stability)
        ),
        6,
    )


def calibrated_confidence_score(
    base_confidence: float,
    *,
    persistent_periods: int = 1,
    corroborating_signals: int = 1,
    anomaly_score: float = 0.0,
) -> float:
    """
    Apply transparent confidence calibration after the base confidence model.

    Adjustments:
      +0.05 when the signal persists across >= 3 periods
      +0.05 when >= 2 corroborating signals exist in the same scope
      -0.05 when the signal is dominated by an anomaly spike (z >= 2.0)
    """
    adjusted = float(base_confidence)
    if persistent_periods >= 3:
        adjusted += 0.05
    if corroborating_signals >= 2:
        adjusted += 0.05
    if abs(float(anomaly_score)) >= 2.0:
        adjusted -= 0.05
    return round(clamp01(adjusted), 6)


def risk_score(
    workload_criticality: str,
    environment: str,
    sla_tier: str,
    action_type: str,
) -> int:
    criticality_component = RISK_CRITICALITY.get(str(workload_criticality).lower(), 35.0)
    environment_component = RISK_ENVIRONMENT.get(str(environment).lower(), 30.0)
    sla_component = RISK_SLA.get(str(sla_tier).lower(), 35.0)
    action_component = RISK_ACTION.get(str(action_type).lower(), 50.0)
    value = (
        (criticality_component * 0.35)
        + (environment_component * 0.25)
        + (sla_component * 0.20)
        + (action_component * 0.20)
    )
    return int(round(clamp(value, 0.0, 100.0)))


def urgency_score(
    waste_growth_rate: float,
    anomaly_score: float,
    *,
    weights: UrgencyWeights | None = None,
) -> float:
    """Return urgency on a 0-1 scale.

    Formal definition:
      urgency = 0.60 * normalize_growth_rate(waste_growth_rate, cap=0.50)
              + 0.40 * normalize_anomaly_score(anomaly_score, cap=3.0)

    This keeps urgency high only when the signal is either accelerating quickly
    or deviating materially from its historical baseline.
    """
    weight_set = weights or DEFAULT_SCORING_CONFIG.urgency
    normalized_growth = normalize_growth_rate(waste_growth_rate)
    normalized_anomaly = normalize_anomaly_score(anomaly_score)
    return round(
        clamp01(
            (normalized_growth * weight_set.waste_growth_rate)
            + (normalized_anomaly * weight_set.anomaly_score)
        ),
        6,
    )


def effort_score(action_type: str) -> float:
    return ACTION_EFFORT.get(str(action_type).lower(), 3.0)


def time_to_value_days(action_type: str, approval_required: bool = False) -> int:
    days = ACTION_TIME_TO_VALUE.get(str(action_type).lower(), 7)
    if approval_required:
        days += 7
    return days


def savings_estimate_usd(issue_type: str, nec_impact_usd: float) -> float:
    return round(max(0.0, float(nec_impact_usd)) * RECOVERY_RATE.get(issue_type, 0.0), 2)


def governance_severity_score(
    signal_type: str,
    *,
    owner_missing: bool = False,
    sla_breached: bool = False,
) -> float:
    """Return governance severity on a 0-1 scale.

    Baseline severity by FinOps signal class:
      1.00 tagging_gap / unattributed_cost_gap
      0.80 shared_cost_concentration
      0.65 cost_anomaly / forecasted_month_end_risk
      0.35 commitment_waste / unused_commitment / underutilized_commitment
      0.30 idle_compute_proxy / idle_compute / idle_resource / zombie_resource

    Accountability penalties:
      +0.10 if owner is missing
      +0.10 if ownership SLA is breached
    """
    base = {
        "tagging_gap": 1.00,
        "unattributed_cost_gap": 1.00,
        "shared_cost_concentration": 0.80,
        "cost_anomaly": 0.65,
        "forecasted_month_end_risk": 0.65,
        "commitment_waste": 0.35,
        "unused_commitment": 0.35,
        "underutilized_commitment": 0.35,
        "idle_compute_proxy": 0.30,
        "idle_compute": 0.30,
        "idle_resource": 0.30,
        "zombie_resource": 0.30,
    }.get(str(signal_type).lower(), 0.25)
    if owner_missing:
        base += 0.10
    if sla_breached:
        base += 0.10
    return round(clamp01(base), 6)


def low_risk_bonus_score(
    *,
    risk_score_value: float,
    approval_required: bool,
    action_type: str,
) -> float:
    if approval_required:
        return 0.0
    action_bonus = {
        "enforce_tags": 1.00,
        "release_commitment": 0.90,
        "rebalance_shared_cost": 0.80,
        "investigate_anomaly": 0.75,
        "review_forecast_risk": 0.75,
        "resize_down": 0.60,
        "remove_resource": 0.20,
    }.get(str(action_type).lower(), 0.50)
    risk_factor = 1.0 - (clamp(float(risk_score_value), 0.0, 100.0) / 100.0)
    return round(clamp01(action_bonus * max(risk_factor, 0.0)), 6)


def priority_score(
    normalized_savings: float,
    confidence_score_value: float,
    governance_severity_value: float,
    urgency_score_value: float,
    low_risk_bonus_value: float,
    *,
    weights: PriorityWeights | None = None,
) -> float:
    weight_set = weights or DEFAULT_SCORING_CONFIG.priority
    return round(
        clamp01(
            (clamp01(normalized_savings) * weight_set.normalized_savings)
            + (clamp01(confidence_score_value) * weight_set.confidence)
            + (clamp01(governance_severity_value) * weight_set.governance_severity)
            + (clamp01(urgency_score_value) * weight_set.urgency)
            + (clamp01(low_risk_bonus_value) * weight_set.low_risk_bonus)
        ),
        6,
    )


def evidence_strength(signal_weights: Iterable[float]) -> float:
    weights = [clamp01(value) for value in signal_weights]
    if not weights:
        return 0.0
    return round(sum(weights) / len(weights), 6)


def accuracy_pct(expected_savings_usd: float, realized_savings_usd: float) -> float | None:
    expected = float(expected_savings_usd)
    if expected <= 0:
        return None
    realized = max(float(realized_savings_usd), 0.0)
    return round(safe_div(realized, expected) * 100.0, 2)


def confidence_calibration_gap(confidence: float, accuracy_pct_value: float | None) -> float | None:
    if accuracy_pct_value is None:
        return None
    return round(abs((clamp01(confidence) * 100.0) - float(accuracy_pct_value)), 2)


def scoring_config_from_mapping(mapping: Mapping[str, Mapping[str, float]] | None) -> ScoringConfig:
    if not mapping:
        return DEFAULT_SCORING_CONFIG
    priority_raw = mapping.get("priority", {})
    confidence_raw = mapping.get("confidence", {})
    urgency_raw = mapping.get("urgency", {})
    return ScoringConfig(
        priority=PriorityWeights(
            normalized_savings=priority_raw.get("normalized_savings", PriorityWeights().normalized_savings),
            confidence=priority_raw.get("confidence", PriorityWeights().confidence),
            governance_severity=priority_raw.get("governance_severity", PriorityWeights().governance_severity),
            urgency=priority_raw.get("urgency", PriorityWeights().urgency),
            low_risk_bonus=priority_raw.get("low_risk_bonus", PriorityWeights().low_risk_bonus),
        ),
        confidence=ConfidenceWeights(
            data_completeness=confidence_raw.get("data_completeness", ConfidenceWeights().data_completeness),
            signal_strength=confidence_raw.get("signal_strength", ConfidenceWeights().signal_strength),
            historical_stability=confidence_raw.get("historical_stability", ConfidenceWeights().historical_stability),
        ),
        urgency=UrgencyWeights(
            waste_growth_rate=urgency_raw.get("waste_growth_rate", UrgencyWeights().waste_growth_rate),
            anomaly_score=urgency_raw.get("anomaly_score", UrgencyWeights().anomaly_score),
        ),
    )
