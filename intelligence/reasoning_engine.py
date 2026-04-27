"""
Explainable reasoning engine for FinOps decisions.

Converts normalized billing and recommendation signals into a single,
deterministic decision object that can be rendered consistently across pages.
"""

from __future__ import annotations

from intelligence import DecisionReasoning, ReasoningInput


def _clamp_score(value: float, *, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, round(value)))


def _safe_pct(value: float | int | None) -> float:
    return float(value or 0.0)


def _risk_defaults(inp: ReasoningInput) -> tuple[int, str, bool]:
    risk_score = int(inp.get("risk_score", 25))
    risk_level = str(inp.get("risk_level", "Low"))
    approval_required = bool(inp.get("approval_required", risk_score >= 60))
    risk_reason = "Low operational risk because the change is non-disruptive."

    environment = str(inp.get("environment", "prod")).lower()
    criticality = str(inp.get("workload_criticality", "medium")).lower()
    support_group = str(inp.get("support_group", "")).strip()

    if risk_score >= 70 or risk_level == "High":
        risk_reason = "High operational risk because the action touches live capacity or deletion paths."
    elif risk_score >= 40 or risk_level == "Medium":
        risk_reason = "Moderate operational risk because the action changes provisioned service behavior."

    if environment == "prod":
        approval_required = True
        risk_reason += " Production scope increases the need for review."
    if criticality in {"high", "mission_critical"}:
        approval_required = True
        risk_reason += f" Workload criticality is {criticality.replace('_', ' ')}."
    if support_group:
        risk_reason += f" {support_group} should review implementation timing."

    return risk_score, risk_reason.strip(), approval_required


def _confidence_defaults(inp: ReasoningInput) -> tuple[float, str]:
    confidence = float(inp.get("confidence_score", 0.75))
    tagging_coverage_pct = _safe_pct(inp.get("tagging_coverage_pct"))
    confidence_reason = "Confidence is based on direct billing and allocation signals."

    if tagging_coverage_pct and tagging_coverage_pct < 70:
        confidence = min(confidence, 0.72)
        confidence_reason = "Confidence is moderated because attribution coverage is incomplete."
    elif tagging_coverage_pct >= 90:
        confidence = max(confidence, 0.88)
        confidence_reason = "High confidence because the signal comes from direct billing, waste, and ownership fields."

    if inp.get("recommendation_type") in {"release_commitment", "enforce_tags"}:
        confidence = max(confidence, 0.85)

    return round(min(confidence, 0.99), 2), confidence_reason


def build_reasoning(inp: ReasoningInput) -> DecisionReasoning:
    nec = float(inp.get("nec", 0.0))
    waste_amount = float(inp.get("waste_amount", 0.0))
    waste_pct = _safe_pct(inp.get("waste_pct"))
    unattributed_spend = float(inp.get("unattributed_spend", 0.0))
    unattributed_pct = _safe_pct(inp.get("unattributed_pct"))
    commitment_waste = float(inp.get("commitment_waste", waste_amount if inp.get("recommendation_type") == "release_commitment" else 0.0))
    commitment_utilization_pct = _safe_pct(inp.get("commitment_utilization_pct"))
    estimated_savings = float(inp.get("estimated_savings", 0.0))
    month_over_month_change_pct = float(inp.get("month_over_month_change_pct", 0.0))
    trend_direction = str(inp.get("trend_direction", "stable"))
    owner_status = str(inp.get("owner_status", "assigned"))
    sla_status = str(inp.get("sla_status", "within_sla"))
    recommendation_type = str(inp.get("recommendation_type", "review"))
    signal_type = str(inp.get("signal_type", inp.get("waste_type", ""))).lower()
    cloud_provider = str(inp.get("cloud_provider", "multi-cloud")).upper()
    team = str(inp.get("team", "unattributed")).replace("-", " ").title()
    application = str(inp.get("application", "unassigned")).replace("-", " ")
    environment = str(inp.get("environment", "prod"))

    confidence_score, confidence_reason = _confidence_defaults(inp)
    risk_score, risk_reason, approval_required = _risk_defaults(inp)

    issue_type = "optimization_opportunity"
    decision_title = "Apply the highest-confidence optimization action"
    root_cause = "The current scope shows recoverable cloud inefficiency."
    evidence = []
    recommended_action = "Review the top recommendation and assign an owner."
    action_justification = "This preserves accountability while moving the highest-value issue first."
    expected_impact = "Reduces avoidable cloud spend."
    next_best_action = "Validate the next highest-priority recommendation."

    if signal_type in {"governance_gap", "tagging_gap", "unattributed_cost_gap"}:
        issue_type = "tagging_governance_gap"
        decision_title = "Fix ownership and tagging gaps before deeper optimization"
        root_cause = (
            f"Spend in {cloud_provider} cannot be allocated cleanly because required owner, team, "
            "cost center, or environment tags are missing."
        )
        evidence = [
            f"Signal `{signal_type}` is active for the selected scope",
            f"${unattributed_spend:,.0f} remains unattributed",
            f"Tagging coverage is {max(0.0, 100 - unattributed_pct):.0f}%",
        ]
        recommended_action = "Enforce required ownership and allocation tags, then assign owners to the highest-cost accounts."
        action_justification = (
            "Governance gaps are blocking accurate attribution and reliable optimization. "
            "Fixing tags and ownership improves chargeback accuracy first."
        )
        confidence_score = max(confidence_score, 0.88)
        risk_score = min(risk_score, 20)
        risk_reason = "Low operational risk because governance fixes do not change runtime workload behavior."
        approval_required = False
        expected_impact = "Improves attribution accuracy and unblocks accountable optimization."
        next_best_action = "Assign owners for the top unattributed accounts and enforce tags at creation."
    elif signal_type in {"commitment_waste", "commitment_mismatch", "unused_commitment", "underutilized_commitment"}:
        issue_type = "commitment_mismatch"
        decision_title = "Re-balance commitments before the next billing cycle"
        root_cause = (
            f"Reserved capacity is underutilized for {team} in {environment}, leaving idle RI/SP/CUD capacity on the books."
        )
        evidence = [
            f"Signal `{signal_type}` is active for the selected scope",
            f"${commitment_waste:,.0f} of commitment waste detected",
            f"Commitment utilization is {commitment_utilization_pct:.1f}%",
        ]
        recommended_action = "Release, reduce, or re-balance commitments for the affected scope."
        action_justification = (
            "The waste signal comes from direct billing commitment fields, so the fastest value comes from matching "
            "coverage to observed demand."
        )
        confidence_score = max(confidence_score, 0.86)
        expected_impact = "Reduces unused commitment cost without waiting for application changes."
        next_best_action = "Review commitment coverage by environment and shift commitments away from low-demand workloads."
    elif signal_type in {"idle_resource", "idle_compute_proxy", "idle_compute"}:
        issue_type = "optimization_opportunity"
        decision_title = "Right-size low-utilization compute"
        root_cause = (
            "A billing-side idle-compute proxy indicates the resource is oversized relative to current spend and demand patterns."
        )
        evidence = [
            f"Signal `{signal_type}` is active for the selected scope",
            f"Estimated monthly savings are ${estimated_savings:,.0f}",
            f"Waste signal is {waste_pct:.1f}% of NEC for this recommendation",
        ]
        recommended_action = "Resize the resource down to a smaller instance class and validate service health after the change."
        action_justification = (
            "The recommendation is based on billing-side inefficiency, not runtime telemetry, so it should be treated as a conservative right-sizing candidate."
        )
        expected_impact = "Reduces provisioned compute cost while preserving workload availability."
        next_best_action = "Validate post-change NEC and continue with the next low-risk right-sizing action."
    elif signal_type in {"zombie_resource"}:
        issue_type = "optimization_opportunity"
        decision_title = "Remove inactive billable resources"
        root_cause = (
            "The resource shows no meaningful usage or only near-zero residual cost, which is consistent with an orphaned or inactive billable artifact."
        )
        evidence = [
            f"Signal `{signal_type}` is active for the selected scope",
            f"Estimated monthly savings are ${estimated_savings:,.0f}",
            "The resource appears inactive from billing evidence",
        ]
        recommended_action = "Review the resource owner, then decommission and remove the inactive asset."
        action_justification = (
            "Zombie-resource actions should remove residual spend only after owner validation, because billing evidence suggests the resource is no longer serving production demand."
        )
        expected_impact = "Eliminates avoidable residual spend tied to inactive resources."
        next_best_action = "Verify the asset is no longer referenced, then delete and track realized savings next month."
    elif unattributed_pct >= 50:
        issue_type = "tagging_governance_gap"
        decision_title = "Fix unattributed spend before deeper optimization"
        root_cause = (
            f"High unattributed NEC is caused by missing required ownership and cost-allocation tags "
            f"for {cloud_provider} services supporting {application}."
        )
        evidence = [
            f"{unattributed_pct:.0f}% of NEC is unattributed",
            f"${unattributed_spend:,.0f} cannot be mapped to a team",
            f"Tagging coverage is {max(0.0, 100 - unattributed_pct):.0f}%",
        ]
        if owner_status != "assigned":
            evidence.append("Owner assignment is incomplete for high-cost scope")
        recommended_action = "Enforce required tags and assign owners to top unattributed accounts."
        action_justification = (
            "Optimization recommendations are less reliable when ownership is missing. "
            "Fixing attribution improves chargeback accuracy and action accountability."
        )
        confidence_score = max(confidence_score, 0.88)
        risk_score = min(risk_score, 20)
        risk_reason = "Low operational risk because tagging and owner assignment do not change runtime workload behavior."
        approval_required = False
        expected_impact = "Improves attribution accuracy and unlocks team-level accountability."
        next_best_action = "Assign owners for the top 5 unattributed accounts and enforce required tags at creation."
    elif commitment_waste > 0 and commitment_utilization_pct and commitment_utilization_pct < 75:
        issue_type = "commitment_mismatch"
        decision_title = "Re-balance commitments before the next billing cycle"
        root_cause = (
            f"Commitment coverage is mismatched to actual demand for {team} in {environment}, "
            f"leaving idle RI/SP capacity on the books."
        )
        evidence = [
            f"${commitment_waste:,.0f} of commitment waste detected",
            f"Commitment utilization is {commitment_utilization_pct:.1f}%",
            f"Waste is {waste_pct:.1f}% of NEC",
        ]
        recommended_action = "Release, reduce, or re-balance commitments for the affected scope."
        action_justification = (
            "The waste signal comes from direct billing fields, so the fastest value comes from matching "
            "commitment coverage to observed demand."
        )
        confidence_score = max(confidence_score, 0.86)
        expected_impact = "Reduces idle commitment cost without waiting for application changes."
        next_best_action = "Review coverage by environment and shift commitments away from low-demand workloads."
    elif waste_pct <= 5 and unattributed_pct >= 20:
        issue_type = "governance_before_optimization"
        decision_title = "Governance is the bottleneck, not raw spend efficiency"
        root_cause = (
            "The estate is relatively cost-efficient, but accountability is weak because a large share of spend "
            "still lacks reliable ownership."
        )
        evidence = [
            f"Waste is only {waste_pct:.1f}% of NEC",
            f"Unattributed spend remains {unattributed_pct:.1f}% of NEC",
            f"${unattributed_spend:,.0f} cannot be assigned confidently",
        ]
        recommended_action = "Fix attribution and owner assignment before expanding optimization automation."
        action_justification = (
            "Improving ownership quality will make later optimization actions more reliable and auditable."
        )
        risk_score = min(risk_score, 25)
        approval_required = False
        expected_impact = "Improves accountability and makes optimization safer to scale."
        next_best_action = "Target the highest-cost unattributed services and enforce missing tags."
    elif owner_status != "assigned" or sla_status == "breached":
        issue_type = "ownership_sla_breach"
        decision_title = "Resolve ownership SLA breaches before implementation"
        root_cause = (
            "Cost ownership is unresolved or overdue, which weakens action accountability and slows safe remediation."
        )
        evidence = [
            f"Owner status is {owner_status}",
            f"SLA status is {sla_status}",
            f"Application scope: {application}",
        ]
        recommended_action = "Escalate to the owning support group and assign an accountable action owner."
        action_justification = "Lifecycle tracking is only useful when there is a clear accountable owner for execution and verification."
        approval_required = False
        risk_score = min(risk_score, 30)
        expected_impact = "Restores accountability and prevents recommendations from stalling in backlog."
        next_best_action = "Escalate to platform governance if ownership is still unresolved after one SLA cycle."

    if estimated_savings > 0 and risk_score >= 70:
        approval_required = True
        next_best_action = "Run a technical review and approve only after workload validation."
        action_justification += " Savings are material, but the operational blast radius is too high for direct execution."
    elif estimated_savings > 0 and risk_score <= 30 and confidence_score >= 0.85:
        issue_type = "quick_win" if issue_type == "optimization_opportunity" else issue_type
        recommended_action = (
            recommended_action
            if issue_type != "quick_win"
            else "Execute the low-risk recommendation now and track realized savings."
        )
        next_best_action = "Queue the next low-risk action once this one is implemented."

    evidence.append(f"Trend direction is {trend_direction} ({month_over_month_change_pct:+.1f}% MoM)")
    if estimated_savings > 0:
        evidence.append(f"Estimated monthly savings are ${estimated_savings:,.0f}")

    priority_score = _clamp_score(
        (unattributed_pct * 0.9)
        + (waste_pct * 1.2)
        + (estimated_savings / max(nec, 1.0) * 100 * 0.8 if nec > 0 else 0.0)
        + (20 if issue_type in {"tagging_governance_gap", "commitment_mismatch", "ownership_sla_breach"} else 0)
        - (risk_score * 0.2)
        + (confidence_score * 20),
    )

    action_safety = (
        "blocked" if risk_score >= 85 else
        "manual_review" if risk_score >= 65 else
        "approval_required" if approval_required else
        "auto_safe"
    )

    return DecisionReasoning(
        issue_type=issue_type,
        decision_title=decision_title,
        root_cause=root_cause,
        evidence=evidence,
        recommended_action=recommended_action,
        action_justification=action_justification,
        confidence_score=confidence_score,
        confidence_reason=confidence_reason,
        risk_score=risk_score,
        risk_reason=risk_reason,
        approval_required=approval_required,
        priority_score=priority_score,
        expected_impact=expected_impact,
        next_best_action=next_best_action,
        action_safety=action_safety,
    )


def from_recommendation(
    recommendation: dict,
    *,
    nec: float,
    waste_amount: float,
    waste_pct: float,
    unattributed_spend: float,
    unattributed_pct: float,
    tagging_coverage_pct: float,
    commitment_utilization_pct: float | None = None,
    commitment_waste: float | None = None,
    owner_status: str = "assigned",
    sla_status: str = "within_sla",
    trend_direction: str = "stable",
    month_over_month_change_pct: float = 0.0,
) -> DecisionReasoning:
    return build_reasoning(
        ReasoningInput(
            nec=float(nec),
            list_cost=float(recommendation.get("current_cost", 0.0)),
            waste_amount=float(waste_amount),
            waste_pct=float(waste_pct),
            unattributed_spend=float(unattributed_spend),
            unattributed_pct=float(unattributed_pct),
            tagging_coverage_pct=float(tagging_coverage_pct),
            commitment_utilization_pct=float(commitment_utilization_pct or 0.0),
            commitment_waste=float(commitment_waste or 0.0),
            cloud_provider=str(recommendation.get("cloud_provider", "multi-cloud")),
            team=str(recommendation.get("allocated_team", "unattributed")),
            application=str(recommendation.get("application", "unassigned")),
            environment=str(recommendation.get("environment", "prod")),
            owner_status=owner_status,
            sla_status=sla_status,
            trend_direction=trend_direction,
            month_over_month_change_pct=float(month_over_month_change_pct),
            recommendation_type=str(recommendation.get("action", "review")),
            signal_type=str(recommendation.get("signal_type", recommendation.get("waste_type", ""))),
            estimated_savings=float(recommendation.get("estimated_savings", 0.0)),
            risk_level=str(recommendation.get("risk", "Low")),
            confidence_score=float(recommendation.get("confidence", 0.75)),
            risk_score=int(recommendation.get("risk_score", 25)),
            support_group=str(recommendation.get("support_group", "")),
            workload_criticality=str(recommendation.get("workload_criticality", "medium")),
            sla_tier=str(recommendation.get("sla_tier", "bronze")),
            approval_required=bool(recommendation.get("approval_required", False)),
        )
    )
