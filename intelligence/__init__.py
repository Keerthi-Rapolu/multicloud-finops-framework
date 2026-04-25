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
    "release_commitment",
    "resize_down",
    "remove_resource",
]

RiskLevel = Literal["Low", "Medium", "High"]
EffortLevel = Literal["Low", "Medium", "High"]
TimeToRealize = Literal["Immediate", "1 week", "1 month"]
ActionSafety = Literal["auto_safe", "approval_required", "manual_review", "blocked"]
LifecycleStatus = Literal["recommended", "approved", "rejected", "implemented", "verified"]


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
    workload_criticality: NotRequired[str]
    sla_tier: NotRequired[str]
    cpu_util_pct: NotRequired[float]
    memory_util_pct: NotRequired[float]
    disk_util_pct: NotRequired[float]
    idle_hours: NotRequired[float]
    last_activity_at: NotRequired[str]
    action_status: NotRequired[LifecycleStatus]
    created_date: NotRequired[str]
    implementation_date: NotRequired[str | None]
    realized_savings: NotRequired[float]
