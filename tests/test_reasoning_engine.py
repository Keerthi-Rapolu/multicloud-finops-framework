from intelligence.reasoning_engine import build_reasoning, from_recommendation


def test_tagging_governance_gap_reasoning():
    reasoning = build_reasoning(
        {
            "nec": 1000.0,
            "unattributed_spend": 680.0,
            "unattributed_pct": 68.0,
            "tagging_coverage_pct": 32.0,
            "cloud_provider": "azure",
            "application": "core-api",
            "owner_status": "missing",
            "sla_status": "breached",
            "risk_score": 20,
            "risk_level": "Low",
            "confidence_score": 0.9,
        }
    )
    assert reasoning["issue_type"] == "tagging_governance_gap"
    assert reasoning["approval_required"] is False
    assert "unattributed" in reasoning["root_cause"].lower()
    assert reasoning["priority_score"] >= 80


def test_commitment_mismatch_reasoning():
    reasoning = build_reasoning(
        {
            "nec": 5000.0,
            "commitment_waste": 450.0,
            "waste_amount": 450.0,
            "waste_pct": 9.0,
            "commitment_utilization_pct": 58.0,
            "environment": "prod",
            "workload_criticality": "high",
            "risk_score": 55,
            "risk_level": "Medium",
            "estimated_savings": 450.0,
        }
    )
    assert reasoning["issue_type"] == "commitment_mismatch"
    assert reasoning["approval_required"] is True
    assert "commitment" in reasoning["recommended_action"].lower()


def test_high_savings_high_risk_requires_approval():
    reasoning = build_reasoning(
        {
            "nec": 2000.0,
            "waste_amount": 600.0,
            "waste_pct": 30.0,
            "estimated_savings": 600.0,
            "risk_score": 82,
            "risk_level": "High",
            "recommendation_type": "remove_resource",
            "environment": "prod",
            "workload_criticality": "mission_critical",
        }
    )
    assert reasoning["approval_required"] is True
    assert reasoning["action_safety"] in {"manual_review", "blocked"}
    assert "review" in reasoning["next_best_action"].lower()


def test_from_recommendation_produces_quick_win():
    reasoning = from_recommendation(
        {
            "action": "release_commitment",
            "estimated_savings": 120.0,
            "risk": "Low",
            "risk_score": 18,
            "confidence": 0.91,
            "cloud_provider": "aws",
            "allocated_team": "platform",
            "application": "platform-core",
            "environment": "prod",
            "support_group": "platform-operations",
            "workload_criticality": "mission_critical",
            "sla_tier": "platinum",
            "approval_required": False,
        },
        nec=1200.0,
        waste_amount=120.0,
        waste_pct=10.0,
        unattributed_spend=40.0,
        unattributed_pct=3.0,
        tagging_coverage_pct=97.0,
        commitment_utilization_pct=64.0,
        commitment_waste=120.0,
    )
    assert reasoning["priority_score"] > 0
    assert "platform operations" in reasoning["risk_reason"].lower().replace("-", " ")


def test_idle_compute_proxy_does_not_reuse_governance_root_cause():
    reasoning = from_recommendation(
        {
            "action": "resize_down",
            "signal_type": "idle_compute_proxy",
            "estimated_savings": 90.0,
            "risk": "Low",
            "risk_score": 22,
            "confidence": 0.83,
            "cloud_provider": "azure",
            "allocated_team": "backend",
            "application": "orders-api",
            "environment": "prod",
        },
        nec=1800.0,
        waste_amount=90.0,
        waste_pct=5.0,
        unattributed_spend=950.0,
        unattributed_pct=52.0,
        tagging_coverage_pct=48.0,
        commitment_utilization_pct=82.0,
        commitment_waste=0.0,
    )
    assert "idle" in reasoning["root_cause"].lower() or "oversized" in reasoning["root_cause"].lower()
    assert "tag" not in reasoning["root_cause"].lower()
    assert "resize" in reasoning["recommended_action"].lower()


def test_zombie_resource_maps_to_inactive_usage_root_cause():
    reasoning = from_recommendation(
        {
            "action": "remove_resource",
            "signal_type": "zombie_resource",
            "estimated_savings": 25.0,
            "risk": "Medium",
            "risk_score": 45,
            "confidence": 0.77,
            "cloud_provider": "gcp",
            "allocated_team": "ml",
            "application": "feature-store",
            "environment": "nonprod",
        },
        nec=700.0,
        waste_amount=25.0,
        waste_pct=3.6,
        unattributed_spend=10.0,
        unattributed_pct=1.4,
        tagging_coverage_pct=98.6,
        commitment_utilization_pct=100.0,
        commitment_waste=0.0,
    )
    assert "inactive" in reasoning["root_cause"].lower() or "orphaned" in reasoning["root_cause"].lower()
    assert "remove" in reasoning["recommended_action"].lower() or "decommission" in reasoning["recommended_action"].lower()
