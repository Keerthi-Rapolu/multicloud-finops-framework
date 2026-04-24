"""
Cost Intelligence Layer — shared type contracts.

These TypedDicts are the agreed interface between modules:
  - WasteFinding   : output of waste_detector, input to causal_engine + impact_simulator
  - CausalInsight  : output of causal_engine, consumed by dashboard page 07
  - Recommendation : output of impact_simulator, consumed by dashboard page 08

All three modules must produce / consume exactly these shapes.
"""

from typing import TypedDict, Literal, NotRequired


# ---------------------------------------------------------------------------
# Waste type and action literals
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# WasteFinding
# Output of:  intelligence/waste_detector.py :: run()
# Input to:   intelligence/causal_engine.py  :: run()
#             intelligence/impact_simulator.py :: run()
# ---------------------------------------------------------------------------

class WasteFinding(TypedDict):
    resource_id:      str        # from fct_unified_billing.resource_id
    cloud_provider:   str        # 'aws' | 'azure' | 'gcp'
    allocated_team:   str        # from fct_unified_billing.allocated_team (nullable → 'unattributed')
    service_category: str        # 'Compute' | 'Storage' | 'Database' | 'Analytics' | 'Platform' | 'Other'
    instance_type:    str | None # EC2/GCE instance type — null for non-compute rows
    waste_type:       WasteType
    nec_waste:        float      # dollar amount of identified waste
    nec_used:         float      # actual used cost for context / ratio calculations
    confidence:       float      # 0.0 – 1.0
    billing_month:    str        # 'YYYY-MM'
    evidence:         dict       # supporting data (thresholds hit, ratios computed)


# ---------------------------------------------------------------------------
# RootCause
# Embedded inside CausalInsight.root_causes
# ---------------------------------------------------------------------------

class RootCause(TypedDict):
    cause:    str    # human-readable label, e.g. "commitment_waste_increased"
    evidence: str    # one-sentence supporting detail
    weight:   float  # 0.0 – 1.0, relative contribution to the overall explanation


# ---------------------------------------------------------------------------
# CausalInsight
# Output of:  intelligence/causal_engine.py :: run()
# Input to:   dashboard/pages/07_cost_insights.py
# ---------------------------------------------------------------------------

class CausalInsight(TypedDict):
    scope:            str              # 'team:<name>' | 'cloud:<provider>' | 'service:<category>'
    period:           str              # 'YYYY-MM' of the period being explained
    cost_change_pct:  float            # +18.0 = 18% increase vs prior period; negative = decrease
    root_causes:      list[RootCause]  # ordered by weight DESC, max 3
    confidence:       float            # 0.0 – 1.0, weighted average of root_cause weights
    anomaly:          bool             # True if abs(z_score) > 2.0


# ---------------------------------------------------------------------------
# Recommendation
# Output of:  intelligence/impact_simulator.py :: run()
# Input to:   dashboard/pages/08_recommendations.py
# ---------------------------------------------------------------------------

EffortLevel = Literal["Low", "Medium", "High"]
TimeToRealize = Literal["Immediate", "1 week", "1 month"]


class Recommendation(TypedDict):
    resource_id:        str            # resource the action applies to
    allocated_team:     str            # team responsible
    action:             ActionType
    current_cost:       float          # nec_used + nec_waste for this resource/month
    estimated_savings:  float          # projected monthly savings if action is taken
    savings_pct:        float          # estimated_savings / current_cost * 100
    risk:               RiskLevel
    priority_score:     float          # savings_pct * confidence — used for ranking
    rationale:          str            # structured markdown with action justification
    effort:             EffortLevel    # "Low" = 1-click, "Medium" = needs approval, "High" = migration
    time_to_realize:    TimeToRealize  # when savings start appearing in billing
    roi_score:          float          # annual savings / effort_hours — higher = better bang per effort
    cloud_provider:     NotRequired[str]        # passthrough for drill-down filters
    waste_type:         NotRequired[WasteType]  # maps recommendation back to source finding
    billing_month:      NotRequired[str]        # source billing period
    confidence:         NotRequired[float]      # source finding confidence for UI explanations
