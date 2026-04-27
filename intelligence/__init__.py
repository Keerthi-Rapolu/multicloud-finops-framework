"""
Cost Intelligence Layer shared type contracts.

These TypedDicts are the interface between:
  - waste_detector
  - causal_engine
  - impact_simulator
  - dashboard pages that render their outputs
"""

from typing import Literal, NotRequired, TypedDict


WasteType = Literal[
    "unused_commitment",
    "idle_compute",
    "zombie_resource",
    "underutilized_commitment",
]

ActionType = Literal[
    "enforce_tags",
    "release_commitment",
    "resize_down",
    "remove_resource",
    "rebalance_shared_cost",
    "investigate_anomaly",
    "review_forecast_risk",
]

RiskLevel = Literal["Low", "Medium", "High"]
EffortLevel = Literal["Low", "Medium", "High"]
TimeToRealize = Literal["Immediate", "1 week", "1 month"]
ActionSafety = Literal["auto_safe", "approval_required", "manual_review", "blocked"]
LifecycleStatus = Literal["recommended", "approved", "rejected", "implemented", "verified"]
EntityType = Literal["team", "resource", "account"]
SignalDirection = Literal["above", "below"]
SignalType = Literal[
    "tagging_gap",
    "unattributed_cost_gap",
    "commitment_waste",
    "zombie_resource",
    "idle_compute_proxy",
    "shared_cost_concentration",
    "cost_anomaly",
    "forecasted_month_end_risk",
]


class WasteFinding(TypedDict):
    resource_id: str
    cloud_provider: str
    allocated_team: str
    service_category: str
    instance_type: str | None
    waste_type: WasteType
    nec_waste: float
    nec_used: float
    confidence: float
    billing_month: str
    evidence: dict
    is_tagged: NotRequired[bool]
    environment: NotRequired[str]
    cost_center: NotRequired[str]
    business_unit: NotRequired[str]
    application: NotRequired[str]
    owner_email: NotRequired[str]
    support_group: NotRequired[str]
    workload_criticality: NotRequired[str]
    sla_tier: NotRequired[str]
    cpu_util_pct: NotRequired[float]
    memory_util_pct: NotRequired[float]
    disk_util_pct: NotRequired[float]
    idle_hours: NotRequired[float]
    last_activity_at: NotRequired[str]


class RootCause(TypedDict):
    cause: str
    evidence: str
    weight: float


class CausalInsight(TypedDict):
    scope: str
    period: str
    cost_change_pct: float
    root_causes: list[RootCause]
    confidence: float
    anomaly: bool


class Recommendation(TypedDict):
    recommendation_id: str
    resource_id: str
    allocated_team: str
    action: ActionType
    current_cost: float
    estimated_savings: float
    savings_pct: float
    risk: RiskLevel
    priority_score: float
    rationale: str
    effort: EffortLevel
    time_to_realize: TimeToRealize
    roi_score: float
    risk_score: int
    risk_reason: str
    approval_required: bool
    action_safety: ActionSafety
    confidence_reason: str
    evidence_summary: str
    cloud_provider: NotRequired[str]
    waste_type: NotRequired[WasteType]
    billing_month: NotRequired[str]
    confidence: NotRequired[float]
    environment: NotRequired[str]
    cost_center: NotRequired[str]
    business_unit: NotRequired[str]
    application: NotRequired[str]
    owner_email: NotRequired[str]
    support_group: NotRequired[str]
    workload_criticality: NotRequired[str]
    sla_tier: NotRequired[str]
    cpu_util_pct: NotRequired[float]
    memory_util_pct: NotRequired[float]
    disk_util_pct: NotRequired[float]
    idle_hours: NotRequired[float]
    last_activity_at: NotRequired[str]
    action_status: NotRequired[LifecycleStatus]
    owner: NotRequired[str]
    created_date: NotRequired[str]
    implementation_date: NotRequired[str | None]
    realized_savings: NotRequired[float]
    verification_status: NotRequired[Literal["pending", "validated", "not_realized"]]
    verification_notes: NotRequired[str]


class ReasoningInput(TypedDict, total=False):
    nec: float
    list_cost: float
    waste_amount: float
    waste_pct: float
    unattributed_spend: float
    unattributed_pct: float
    tagging_coverage_pct: float
    commitment_utilization_pct: float
    commitment_waste: float
    cloud_provider: str
    team: str
    application: str
    environment: str
    owner_status: str
    sla_status: str
    trend_direction: str
    month_over_month_change_pct: float
    recommendation_type: str
    estimated_savings: float
    risk_level: RiskLevel
    confidence_score: float
    risk_score: int
    support_group: str
    workload_criticality: str
    sla_tier: str
    approval_required: bool


class DecisionReasoning(TypedDict):
    issue_type: str
    decision_title: str
    root_cause: str
    evidence: list[str]
    recommended_action: str
    action_justification: str
    confidence_score: float
    confidence_reason: str
    risk_score: int
    risk_reason: str
    approval_required: bool
    priority_score: int
    expected_impact: str
    next_best_action: str
    action_safety: ActionSafety


class DecisionSignal(TypedDict):
    signal_id: str
    entity_type: EntityType
    entity_id: str
    signal_type: SignalType
    metric_name: str
    metric_value: float
    threshold: float
    direction: SignalDirection
    data_window: str
    signal_weight: float
    confidence: float
    created_at: str


class DecisionExplanation(TypedDict):
    issue_type: str
    root_cause_type: str
    evidence: list[DecisionSignal]
    decision_basis: dict[str, float | int | str | bool]
    rejected_alternatives: list[dict[str, float | int | str | bool]]


class CanonicalRecommendation(TypedDict):
    recommendation_id: str
    entity_id: str
    resource_id: str | None
    team: str
    cloud: str
    action_type: str
    root_cause_type: str
    nec_impact_usd: float
    savings_estimate_usd: float
    priority_score: float
    confidence: float
    risk_score: int
    effort_score: float
    urgency_score: float
    time_to_value_days: int
    evidence_strength: float
    signal_ids: list[str]
    status: LifecycleStatus
    owner: str
    approval_required: bool
    created_at: str
    implemented_at: str | None
    verified_at: str | None
    realized_savings_usd: float
    explanation: DecisionExplanation


class CanonicalDecision(TypedDict):
    decision_id: str
    entity_id: str
    candidate_recommendations: list[str]
    selected_recommendation: str
    decision_score: float
    decision_reason: str
    competing_scores: dict[str, float]
    created_at: str
