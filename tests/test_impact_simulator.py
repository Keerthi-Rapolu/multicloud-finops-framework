"""
Tests for intelligence/impact_simulator.py.
"""

import pytest

from intelligence.impact_simulator import (
    ACTION_MAP,
    RECOVERY_RATES,
    RISK_MAP,
    action_for_waste_type,
    build_rationale,
    estimate_savings,
    risk_score,
    run,
)


def _finding(
    waste_type="unused_commitment",
    nec_waste=10.0,
    nec_used=2.0,
    confidence=0.95,
    resource_id="res-001",
    allocated_team="backend",
    cloud_provider="aws",
    service_category="Compute",
    billing_month="2026-03",
    instance_type=None,
    environment="prod",
    cost_center="CC400",
    business_unit="product",
    application="core-api",
    owner_email="backend-owner@company.com",
    support_group="api-operations",
    workload_criticality="high",
    sla_tier="silver",
    is_tagged=True,
    evidence=None,
    cpu_util_pct=None,
    memory_util_pct=None,
    disk_util_pct=None,
    idle_hours=None,
    last_activity_at=None,
):
    return {
        "resource_id": resource_id,
        "cloud_provider": cloud_provider,
        "allocated_team": allocated_team,
        "service_category": service_category,
        "instance_type": instance_type,
        "waste_type": waste_type,
        "nec_waste": nec_waste,
        "nec_used": nec_used,
        "confidence": confidence,
        "billing_month": billing_month,
        "evidence": evidence or {},
        "environment": environment,
        "cost_center": cost_center,
        "business_unit": business_unit,
        "application": application,
        "owner_email": owner_email,
        "support_group": support_group,
        "workload_criticality": workload_criticality,
        "sla_tier": sla_tier,
        "cpu_util_pct": cpu_util_pct,
        "memory_util_pct": memory_util_pct,
        "disk_util_pct": disk_util_pct,
        "idle_hours": idle_hours,
        "last_activity_at": last_activity_at,
        "is_tagged": is_tagged,
    }


class TestActionMap:
    def test_all_waste_types_covered(self):
        for waste_type in ACTION_MAP:
            assert action_for_waste_type(waste_type) in {
                "release_commitment",
                "resize_down",
                "remove_resource",
            }

    def test_unknown_type_raises(self):
        with pytest.raises(KeyError):
            action_for_waste_type("nonexistent_type")


class TestEstimateSavings:
    def test_savings_unused_commitment(self):
        finding = _finding(waste_type="unused_commitment", nec_waste=10.0, nec_used=2.0)
        savings, _ = estimate_savings(finding)
        assert savings == pytest.approx(10.0)

    def test_savings_idle_compute(self):
        finding = _finding(waste_type="idle_compute", nec_waste=0.0, nec_used=10.0)
        savings, _ = estimate_savings(finding)
        assert savings == pytest.approx(8.0)

    def test_savings_zombie_resource(self):
        finding = _finding(waste_type="zombie_resource", nec_waste=0.0, nec_used=1.5)
        savings, _ = estimate_savings(finding)
        assert savings == pytest.approx(1.5)

    def test_savings_underutilized_commitment(self):
        finding = _finding(waste_type="underutilized_commitment", nec_waste=10.0, nec_used=5.0)
        savings, _ = estimate_savings(finding)
        assert savings == pytest.approx(6.0)

    def test_savings_pct_in_range(self):
        for waste_type in RECOVERY_RATES:
            finding = _finding(waste_type=waste_type, nec_waste=5.0, nec_used=5.0)
            _, pct = estimate_savings(finding)
            assert 0.0 <= pct <= 100.0

    def test_trivial_savings_filtered_by_run(self):
        finding = _finding(waste_type="idle_compute", nec_waste=0.0, nec_used=0.50)
        savings, _ = estimate_savings(finding)
        assert savings < 1.00
        assert run([finding]) == []


class TestRiskScore:
    def test_risk_map_all_types(self):
        for waste_type in RISK_MAP:
            result = risk_score({"waste_type": waste_type, "environment": "prod", "workload_criticality": "high", "sla_tier": "silver", "service_category": "Compute", "is_tagged": True, "allocated_team": "backend"})
            assert result in {"Low", "Medium", "High"}

    def test_prod_delete_is_higher_risk_than_dev_delete(self):
        prod = run([_finding(waste_type="zombie_resource", environment="prod", workload_criticality="high")])[0]
        dev = run([_finding(waste_type="zombie_resource", environment="dev", workload_criticality="low", sla_tier="bronze")])[0]
        assert prod["risk_score"] > dev["risk_score"]
        assert prod["action_safety"] in {"blocked", "manual_review", "approval_required"}

    def test_mission_critical_resize_blocks_automation(self):
        rec = run([
            _finding(
                waste_type="idle_compute",
                environment="prod",
                workload_criticality="mission_critical",
                sla_tier="gold",
            )
        ])[0]
        assert rec["action_safety"] == "blocked"
        assert rec["approval_required"] is True

    def test_delete_without_telemetry_requires_manual_review(self):
        rec = run([
            _finding(
                waste_type="zombie_resource",
                environment="dev",
                workload_criticality="low",
                sla_tier="bronze",
                evidence={},
            )
        ])[0]
        assert rec["action_safety"] == "manual_review"

    def test_telemetry_backed_delete_reduces_risk(self):
        no_telemetry = run([
            _finding(
                waste_type="zombie_resource",
                environment="dev",
                workload_criticality="low",
                sla_tier="bronze",
                evidence={},
            )
        ])[0]
        telemetry = run([
            _finding(
                waste_type="zombie_resource",
                environment="dev",
                workload_criticality="low",
                sla_tier="bronze",
                evidence={
                    "cpu_util_pct": 1.5,
                    "memory_util_pct": 4.0,
                    "disk_util_pct": 3.0,
                    "idle_hours": 420.0,
                    "stale_days_since_activity": 21.0,
                },
            )
        ])[0]
        assert telemetry["risk_score"] < no_telemetry["risk_score"]


class TestBuildRationale:
    def test_rationale_contains_resource_id(self):
        finding = _finding(resource_id="ec2-abc-123")
        rationale = build_rationale(finding, "release_commitment", 5.0)
        assert "ec2-abc-123" in rationale

    def test_rationale_contains_team(self):
        finding = _finding(allocated_team="ml")
        rationale = build_rationale(finding, "resize_down", 3.0)
        assert "ml" in rationale

    def test_rationale_contains_savings(self):
        finding = _finding()
        rationale = build_rationale(finding, "release_commitment", 12.345)
        assert "12.35" in rationale or "12.34" in rationale


class TestRun:
    _REQUIRED_KEYS = {
        "recommendation_id",
        "resource_id",
        "allocated_team",
        "action",
        "current_cost",
        "estimated_savings",
        "savings_pct",
        "risk",
        "priority_score",
        "rationale",
        "risk_score",
        "risk_reason",
        "approval_required",
        "action_safety",
        "confidence_reason",
        "evidence_summary",
    }

    def test_output_schema(self):
        recs = run([_finding(waste_type="unused_commitment", nec_waste=10.0, nec_used=2.0)])
        assert len(recs) == 1
        assert self._REQUIRED_KEYS.issubset(recs[0].keys())

    def test_source_metadata_passthrough(self):
        rec = run([
            _finding(
                waste_type="unused_commitment",
                cloud_provider="azure",
                billing_month="2026-04",
                confidence=0.91,
                environment="prod",
                business_unit="engineering",
                application="platform-core",
                owner_email="platform-owner@company.com",
                support_group="platform-operations",
                workload_criticality="mission_critical",
                sla_tier="gold",
                cpu_util_pct=4.0,
                memory_util_pct=8.0,
                disk_util_pct=6.0,
                idle_hours=240.0,
                last_activity_at="2026-04-01T00:00:00Z",
            )
        ])[0]
        assert rec["cloud_provider"] == "azure"
        assert rec["waste_type"] == "unused_commitment"
        assert rec["billing_month"] == "2026-04"
        assert rec["confidence"] == pytest.approx(0.91)
        assert rec["environment"] == "prod"
        assert rec["business_unit"] == "engineering"
        assert rec["application"] == "platform-core"
        assert rec["owner_email"] == "platform-owner@company.com"
        assert rec["support_group"] == "platform-operations"
        assert rec["cpu_util_pct"] == pytest.approx(4.0)
        assert rec["idle_hours"] == pytest.approx(240.0)

    def test_recommendation_id_is_stable(self):
        finding = _finding()
        rec_one = run([finding])[0]
        rec_two = run([finding])[0]
        assert rec_one["recommendation_id"] == rec_two["recommendation_id"]

    def test_priority_sort(self):
        findings = [
            _finding(waste_type="idle_compute", nec_waste=0.0, nec_used=10.0, confidence=0.75),
            _finding(waste_type="unused_commitment", nec_waste=10.0, nec_used=2.0, confidence=0.95),
        ]
        recs = run(findings)
        assert recs[0]["priority_score"] >= recs[1]["priority_score"]

    def test_current_cost_is_sum_of_nec(self):
        rec = run([_finding(nec_waste=5.0, nec_used=3.0)])[0]
        assert rec["current_cost"] == pytest.approx(8.0)

    def test_priority_score_formula(self):
        rec = run([_finding(waste_type="unused_commitment", nec_waste=10.0, nec_used=10.0, confidence=0.95)])[0]
        expected_priority = round(
            (
                0.35 * 1.0
                + 0.25 * 0.95
                + 0.20 * 0.35
                + 0.10 * 0.0
                + 0.10 * 0.0
            ) * 100.0,
            2,
        )
        assert rec["priority_score"] == pytest.approx(expected_priority, rel=1e-3)

    def test_action_safety_and_risk_reason_present(self):
        rec = run([_finding(waste_type="idle_compute")])[0]
        assert rec["action_safety"] in {"auto_safe", "approval_required", "manual_review", "blocked"}
        assert rec["risk_reason"]
        assert rec["confidence_reason"]
        assert rec["evidence_summary"]

    def test_multiple_findings_sorted(self):
        findings = [
            _finding(resource_id="r1", waste_type="zombie_resource", nec_waste=0.0, nec_used=1.5, confidence=0.80),
            _finding(resource_id="r2", waste_type="unused_commitment", nec_waste=8.0, nec_used=1.0, confidence=0.95),
            _finding(resource_id="r3", waste_type="underutilized_commitment", nec_waste=10.0, nec_used=5.0, confidence=0.85),
        ]
        recs = run(findings)
        scores = [rec["priority_score"] for rec in recs]
        assert scores == sorted(scores, reverse=True)
