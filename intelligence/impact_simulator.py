"""
Impact Simulator.

Converts WasteFinding objects into prioritized recommendations with:
  - conservative savings estimates
  - explicit numeric risk scoring
  - approval / action-safety guardrails
  - stable recommendation ids for lifecycle tracking
"""

from __future__ import annotations

import hashlib

from intelligence import Recommendation


ACTION_MAP: dict[str, str] = {
    "unused_commitment": "release_commitment",
    "idle_compute": "resize_down",
    "zombie_resource": "remove_resource",
    "underutilized_commitment": "release_commitment",
}

RECOVERY_RATES: dict[str, float] = {
    "unused_commitment": 1.00,
    "idle_compute": 0.80,
    "zombie_resource": 1.00,
    "underutilized_commitment": 0.60,
}

RISK_MAP: dict[str, str] = {
    "unused_commitment": "Low",
    "idle_compute": "Medium",
    "zombie_resource": "Low",
    "underutilized_commitment": "High",
}

BASE_RISK_SCORES: dict[str, int] = {
    "unused_commitment": 18,
    "idle_compute": 44,
    "zombie_resource": 24,
    "underutilized_commitment": 62,
}

EFFORT_MAP: dict[str, str] = {
    "release_commitment": "Low",
    "resize_down": "Medium",
    "remove_resource": "Low",
}

TIME_MAP: dict[str, str] = {
    "release_commitment": "Immediate",
    "resize_down": "1 week",
    "remove_resource": "Immediate",
}

ENV_RISK_ADJ = {
    "prod": 18,
    "nonprod": 8,
    "staging": 8,
    "test": 8,
    "qa": 8,
    "dev": 0,
    "sandbox": 0,
}

CRITICALITY_RISK_ADJ = {
    "mission_critical": 28,
    "high": 18,
    "medium": 8,
    "low": 0,
}

SLA_RISK_ADJ = {
    "gold": 10,
    "silver": 5,
    "bronze": 0,
}

SERVICE_RISK_ADJ = {
    "Platform": 10,
    "Database": 8,
    "Analytics": 6,
    "Compute": 4,
    "Storage": 2,
    "Other": 0,
}

ACTION_RISK_ADJ = {
    "release_commitment": -6,
    "resize_down": 6,
    "remove_resource": 10,
}

_EFFORT_HOURS: dict[str, float] = {"Low": 1.0, "Medium": 4.0, "High": 16.0}
_MIN_SAVINGS = 1.00

_ACTION_CONTEXT: dict[str, dict[str, list[str] | str]] = {
    "release_commitment": {
        "why_points": [
            "Billing rows show idle RI/SP capacity that can be reduced without resizing a workload",
            "Commitment recovery is immediate because the savings comes from billing structure, not application code changes",
        ],
        "alternative": "keep current commitment coverage and accept the idle spend",
        "chosen_because": "highest savings with the lowest operational impact",
    },
    "resize_down": {
        "why_points": [
            "Billing proxy shows very low cost per vCPU hour relative to the provisioned shape",
            "Right-sizing preserves service while recovering most of the waste",
        ],
        "alternative": "remove the instance entirely after deeper workload validation",
        "chosen_because": "it keeps the workload online while still recovering material savings",
    },
    "remove_resource": {
        "why_points": [
            "The resource has persistent low monthly NEC and fits the orphan / zombie profile",
            "Full removal recovers all spend if the asset is truly unused",
        ],
        "alternative": "keep the resource running and review it again next cycle",
        "chosen_because": "there is no partial optimization path that saves more than deletion",
    },
}


def action_for_waste_type(waste_type: str) -> str:
    return ACTION_MAP[waste_type]


def estimate_savings(finding: dict) -> tuple[float, float]:
    base = finding["nec_waste"] if finding["nec_waste"] > 0 else finding["nec_used"]
    rate = RECOVERY_RATES[finding["waste_type"]]
    estimated_savings = base * rate
    total_cost = finding["nec_used"] + finding["nec_waste"]
    savings_pct = estimated_savings / total_cost * 100 if total_cost > 0 else 0.0
    return estimated_savings, savings_pct


def _risk_level(score: int) -> str:
    if score >= 70:
        return "High"
    if score >= 35:
        return "Medium"
    return "Low"


def _risk_profile(finding: dict, action: str) -> dict[str, int | str | bool]:
    waste_type = finding["waste_type"]
    environment = str(finding.get("environment") or "prod").lower()
    criticality = str(finding.get("workload_criticality") or "medium").lower()
    sla_tier = str(finding.get("sla_tier") or "bronze").lower()
    service_category = str(finding.get("service_category") or "Other")
    is_tagged = bool(finding.get("is_tagged", True))
    evidence = finding.get("evidence") or {}
    telemetry_backed = any(
        key in evidence
        for key in (
            "cpu_util_pct",
            "memory_util_pct",
            "disk_util_pct",
            "idle_hours",
            "stale_days_since_activity",
        )
    )

    score = BASE_RISK_SCORES[waste_type]
    score += ENV_RISK_ADJ.get(environment, 4)
    score += CRITICALITY_RISK_ADJ.get(criticality, 8)
    score += SLA_RISK_ADJ.get(sla_tier, 0)
    score += SERVICE_RISK_ADJ.get(service_category, 0)
    score += ACTION_RISK_ADJ.get(action, 0)
    if not is_tagged or str(finding.get("allocated_team")) == "unattributed":
        score += 6
    if action in {"resize_down", "remove_resource"} and not telemetry_backed:
        score += 12
    elif action in {"resize_down", "remove_resource"} and telemetry_backed:
        score -= 8
    score = max(0, min(100, round(score)))

    risk = _risk_level(score)
    approval_required = (
        score >= 45
        or environment == "prod"
        or criticality in {"high", "mission_critical"}
        or not is_tagged
    )

    if (
        criticality == "mission_critical"
        and action in {"resize_down", "remove_resource"}
    ) or (environment == "prod" and action == "remove_resource") or score >= 85:
        action_safety = "blocked"
    elif action == "remove_resource" and not telemetry_backed:
        action_safety = "manual_review"
    elif score >= 65 or (action == "remove_resource" and environment in {"staging", "nonprod", "test", "qa"}):
        action_safety = "manual_review"
    elif approval_required:
        action_safety = "approval_required"
    else:
        action_safety = "auto_safe"

    reasons: list[str] = [f"{waste_type.replace('_', ' ')} detected from billing data"]
    if environment == "prod":
        reasons.append("workload runs in production")
    if criticality in {"high", "mission_critical"}:
        reasons.append(f"criticality is {criticality.replace('_', ' ')}")
    if sla_tier == "gold":
        reasons.append("gold SLA coverage increases change sensitivity")
    if not is_tagged or str(finding.get("allocated_team")) == "unattributed":
        reasons.append("ownership/tagging is incomplete, so action needs extra validation")
    if action == "remove_resource":
        reasons.append("deletion is harder to reverse than billing-only commitment changes")
    elif action == "resize_down":
        reasons.append("right-sizing changes live capacity and should be validated against workload demand")
    else:
        reasons.append("commitment optimization is primarily a billing action with lower service risk")
    if telemetry_backed:
        reasons.append("telemetry shows persistently low utilization or stale activity")
    elif action in {"resize_down", "remove_resource"}:
        reasons.append("telemetry is missing, so optimization stays conservative")

    return {
        "risk_score": score,
        "risk": risk,
        "risk_reason": "; ".join(reasons[:4]).capitalize(),
        "approval_required": approval_required,
        "action_safety": action_safety,
    }


def risk_score(finding: dict) -> str:
    action = action_for_waste_type(finding["waste_type"])
    return str(_risk_profile(finding, action)["risk"])


def _confidence_reason(finding: dict) -> str:
    waste_type = finding["waste_type"]
    confidence = float(finding.get("confidence", 0.0))
    evidence = finding.get("evidence") or {}
    telemetry_backed = any(
        key in evidence
        for key in (
            "cpu_util_pct",
            "memory_util_pct",
            "disk_util_pct",
            "idle_hours",
            "stale_days_since_activity",
        )
    )
    if waste_type == "unused_commitment":
        reason = "Billing export explicitly marks unused commitment cost, so this is a direct signal."
    elif waste_type == "underutilized_commitment":
        reason = "Confidence comes from the used-vs-wasted commitment ratio computed from billing data."
    elif waste_type == "idle_compute":
        if telemetry_backed:
            reason = "Confidence is higher because low host utilization and inactivity telemetry support the billing signal."
        else:
            reason = "Confidence is moderate because idle compute is inferred from a billing proxy, not host telemetry."
    else:
        if telemetry_backed:
            reason = "Confidence is high because the resource shows stale activity and near-zero utilization."
        else:
            reason = "Confidence is based on persistently low monthly NEC; deletion should be validated before action."

    if not bool(finding.get("is_tagged", True)):
        reason += " Team attribution is weaker because the source row is not explicitly tagged."

    return f"{reason} Current confidence: {confidence:.0%}."


def _evidence_summary(finding: dict) -> str:
    evidence = finding.get("evidence") or {}
    waste_type = finding["waste_type"].replace("_", " ")
    if not evidence:
        return f"{waste_type.title()} was identified from billing structure."

    ordered = []
    for key, value in evidence.items():
        label = key.replace("_", " ")
        if isinstance(value, float):
            if "util" in key or "days" in key:
                ordered.append(f"{label}={value:.2f}")
            elif "threshold" in key or "fraction" in key or "hour" in key:
                ordered.append(f"{label}={value:.4f}")
            else:
                ordered.append(f"{label}=${value:,.2f}")
        else:
            ordered.append(f"{label}={value}")
    return f"{waste_type.title()} evidence: " + ", ".join(ordered[:4])


def build_rationale(finding: dict, action: str, savings: float) -> str:
    resource = finding["resource_id"]
    service = finding["service_category"]
    cloud = finding["cloud_provider"].upper()
    team = finding["allocated_team"]
    waste_type = finding["waste_type"].replace("_", " ")
    action_label = action.replace("_", " ").title()

    ctx = _ACTION_CONTEXT.get(action, {})
    why_lines = "\n".join(f"  - {point}" for point in ctx.get("why_points", []))
    alt = str(ctx.get("alternative", "review manually"))
    chosen = str(ctx.get("chosen_because", "best savings-to-risk ratio"))
    short_id = ("..." + resource[-48:]) if len(resource) > 50 else resource

    return (
        f"**{cloud} | {service} | Team: {team}**  \n"
        f"Resource: `{short_id}`  \n"
        f"Waste detected: {waste_type}  \n\n"
        f"**Why {action_label}:**\n{why_lines}\n"
        f"  - Alternative: {alt}\n\n"
        f"**Chosen because:** {chosen}  \n\n"
        f"**Estimated savings:** ${savings:,.2f}/month"
    )


def _recommendation_id(finding: dict, action: str) -> str:
    raw = "|".join(
        [
            str(finding.get("billing_month", "")),
            str(finding.get("cloud_provider", "")),
            str(finding.get("resource_id", "")),
            str(finding.get("waste_type", "")),
            action,
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def run(waste_findings: list[dict]) -> list[Recommendation]:
    recs: list[Recommendation] = []

    for finding in waste_findings:
        estimated_savings, savings_pct = estimate_savings(finding)
        if estimated_savings < _MIN_SAVINGS:
            continue

        action = action_for_waste_type(finding["waste_type"])
        current_cost = finding["nec_used"] + finding["nec_waste"]
        effort = EFFORT_MAP.get(action, "Medium")
        time_to_realize = TIME_MAP.get(action, "1 week")
        roi_score = round((estimated_savings * 12) / _EFFORT_HOURS[effort], 2)
        profile = _risk_profile(finding, action)

        rec = Recommendation(
            recommendation_id=_recommendation_id(finding, action),
            resource_id=finding["resource_id"],
            allocated_team=finding["allocated_team"],
            action=action,
            current_cost=round(current_cost, 4),
            estimated_savings=round(estimated_savings, 4),
            savings_pct=round(savings_pct, 2),
            risk=str(profile["risk"]),
            priority_score=round(savings_pct * finding["confidence"], 4),
            rationale=build_rationale(finding, action, estimated_savings),
            effort=effort,
            time_to_realize=time_to_realize,
            roi_score=roi_score,
            risk_score=int(profile["risk_score"]),
            risk_reason=str(profile["risk_reason"]),
            approval_required=bool(profile["approval_required"]),
            action_safety=str(profile["action_safety"]),
            confidence_reason=_confidence_reason(finding),
            evidence_summary=_evidence_summary(finding),
            cloud_provider=finding["cloud_provider"],
            waste_type=finding["waste_type"],
            billing_month=finding["billing_month"],
            confidence=round(float(finding.get("confidence", 0.0)), 4),
        )

        for key in (
            "environment",
            "cost_center",
            "business_unit",
            "application",
            "owner_email",
            "workload_criticality",
            "sla_tier",
            "cpu_util_pct",
            "memory_util_pct",
            "disk_util_pct",
            "idle_hours",
            "last_activity_at",
        ):
            value = finding.get(key)
            if value is not None:
                rec[key] = value

        recs.append(rec)

    return sorted(
        recs,
        key=lambda rec: (rec["priority_score"], rec["estimated_savings"]),
        reverse=True,
    )


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    import duckdb

    from intelligence.waste_detector import run as detect_waste

    parser = argparse.ArgumentParser(description="Run impact simulator against DuckDB mart.")
    parser.add_argument("--db", default="finops_dbt.duckdb")
    parser.add_argument("--month", default=None)
    args = parser.parse_args()

    db = Path(args.db)
    if not db.exists():
        raise FileNotFoundError(f"DuckDB not found at {db}. Run `dbt run` first.")

    con = duckdb.connect(str(db), read_only=True)
    query = "SELECT * FROM marts.fct_unified_billing"
    if args.month:
        query += f" WHERE billing_month = '{args.month}'"
    df = con.execute(query).df()
    con.close()

    findings = detect_waste(df)
    recommendations = run(findings)
    total_savings = sum(rec["estimated_savings"] for rec in recommendations)

    print(
        f"\nRecommendations: {len(recommendations)}"
        f"  |  Total estimated savings: ${total_savings:,.2f}\n"
    )
    for index, rec in enumerate(recommendations[:10], 1):
        print(
            f"  {index:2d}. [{rec['risk']:6s}] {rec['action']:20s} "
            f"save ${rec['estimated_savings']:7,.2f} "
            f"({rec['savings_pct']:5.1f}%) "
            f"priority={rec['priority_score']:.1f} "
            f"team={rec['allocated_team']} "
            f"safety={rec['action_safety']}"
        )
    print()
