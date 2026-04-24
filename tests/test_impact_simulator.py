"""
Tests for intelligence/impact_simulator.py

All tests use hand-crafted WasteFinding dicts — no DuckDB dependency.
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
):
    return {
        "resource_id":      resource_id,
        "cloud_provider":   cloud_provider,
        "allocated_team":   allocated_team,
        "service_category": service_category,
        "instance_type":    instance_type,
        "waste_type":       waste_type,
        "nec_waste":        nec_waste,
        "nec_used":         nec_used,
        "confidence":       confidence,
        "billing_month":    billing_month,
        "evidence":         {},
    }


# ---------------------------------------------------------------------------
# 9A — action_for_waste_type
# ---------------------------------------------------------------------------

class TestActionMap:
    def test_all_waste_types_covered(self):
        for wtype in ACTION_MAP:
            assert action_for_waste_type(wtype) in ("release_commitment", "resize_down", "remove_resource")

    def test_unused_commitment_action(self):
        assert action_for_waste_type("unused_commitment") == "release_commitment"

    def test_idle_compute_action(self):
        assert action_for_waste_type("idle_compute") == "resize_down"

    def test_zombie_resource_action(self):
        assert action_for_waste_type("zombie_resource") == "remove_resource"

    def test_underutilized_commitment_action(self):
        assert action_for_waste_type("underutilized_commitment") == "release_commitment"

    def test_unknown_type_raises(self):
        with pytest.raises(KeyError):
            action_for_waste_type("nonexistent_type")


# ---------------------------------------------------------------------------
# 9B — estimate_savings
# ---------------------------------------------------------------------------

class TestEstimateSavings:
    def test_savings_unused_commitment(self):
        # 100% recovery rate — $10 waste → $10 savings
        f = _finding(waste_type="unused_commitment", nec_waste=10.0, nec_used=2.0)
        savings, pct = estimate_savings(f)
        assert savings == pytest.approx(10.0)

    def test_savings_idle_compute(self):
        # 80% recovery rate — for idle_compute nec_waste=0, base is nec_used
        f = _finding(waste_type="idle_compute", nec_waste=0.0, nec_used=10.0)
        savings, pct = estimate_savings(f)
        assert savings == pytest.approx(8.0)

    def test_savings_zombie_resource(self):
        # 100% recovery, base = nec_used (nec_waste is 0 for zombie)
        f = _finding(waste_type="zombie_resource", nec_waste=0.0, nec_used=1.5)
        savings, pct = estimate_savings(f)
        assert savings == pytest.approx(1.5)

    def test_savings_underutilized_commitment(self):
        # 60% recovery rate
        f = _finding(waste_type="underutilized_commitment", nec_waste=10.0, nec_used=5.0)
        savings, pct = estimate_savings(f)
        assert savings == pytest.approx(6.0)

    def test_savings_pct_in_range(self):
        for wtype in RECOVERY_RATES:
            f = _finding(waste_type=wtype, nec_waste=5.0, nec_used=5.0)
            _, pct = estimate_savings(f)
            assert 0.0 <= pct <= 100.0, f"savings_pct out of range for {wtype}: {pct}"

    def test_savings_pct_zero_total_cost(self):
        # Both nec_used and nec_waste are 0 — no division by zero
        f = _finding(waste_type="unused_commitment", nec_waste=0.0, nec_used=0.0)
        savings, pct = estimate_savings(f)
        assert pct == 0.0

    def test_savings_pct_correct_for_commitment(self):
        # nec_waste=10, nec_used=2 → total=12, savings=10, pct≈83.3%
        f = _finding(waste_type="unused_commitment", nec_waste=10.0, nec_used=2.0)
        _, pct = estimate_savings(f)
        assert pct == pytest.approx(10.0 / 12.0 * 100, rel=1e-3)

    def test_trivial_savings_filtered_by_run(self):
        # A finding with nec_waste=0.50 (idle_compute base=nec_used=0.50 → savings=0.40 < 1.00)
        f = _finding(waste_type="idle_compute", nec_waste=0.0, nec_used=0.50)
        savings, _ = estimate_savings(f)
        assert savings < 1.00
        recs = run([f])
        assert recs == []


# ---------------------------------------------------------------------------
# 9C — risk_score
# ---------------------------------------------------------------------------

class TestRiskScore:
    def test_risk_map_all_types(self):
        for wtype in RISK_MAP:
            result = risk_score({"waste_type": wtype})
            assert result in ("Low", "Medium", "High"), f"Unexpected risk for {wtype}: {result}"

    def test_unused_commitment_low_risk(self):
        assert risk_score({"waste_type": "unused_commitment"}) == "Low"

    def test_idle_compute_medium_risk(self):
        assert risk_score({"waste_type": "idle_compute"}) == "Medium"

    def test_zombie_resource_low_risk(self):
        assert risk_score({"waste_type": "zombie_resource"}) == "Low"

    def test_underutilized_commitment_high_risk(self):
        assert risk_score({"waste_type": "underutilized_commitment"}) == "High"


# ---------------------------------------------------------------------------
# 9D — build_rationale
# ---------------------------------------------------------------------------

class TestBuildRationale:
    def test_rationale_contains_resource_id(self):
        f = _finding(resource_id="ec2-abc-123")
        r = build_rationale(f, "release_commitment", 5.0)
        assert "ec2-abc-123" in r

    def test_rationale_contains_team(self):
        f = _finding(allocated_team="ml")
        r = build_rationale(f, "resize_down", 3.0)
        assert "ml" in r

    def test_rationale_contains_savings(self):
        f = _finding()
        r = build_rationale(f, "release_commitment", 12.345)
        assert "12.35" in r or "12.34" in r  # formatted to 2dp

    def test_rationale_contains_action(self):
        f = _finding()
        r = build_rationale(f, "remove_resource", 2.0)
        assert "remove resource" in r.lower()

    def test_rationale_is_string(self):
        f = _finding()
        assert isinstance(build_rationale(f, "resize_down", 5.0), str)


# ---------------------------------------------------------------------------
# 9E — run (output schema and sorting)
# ---------------------------------------------------------------------------

class TestRun:
    _REQUIRED_KEYS = {
        "resource_id", "allocated_team", "action",
        "current_cost", "estimated_savings", "savings_pct",
        "risk", "priority_score", "rationale",
    }

    def test_output_schema(self):
        findings = [_finding(waste_type="unused_commitment", nec_waste=10.0, nec_used=2.0)]
        recs = run(findings)
        assert len(recs) == 1
        assert self._REQUIRED_KEYS == set(recs[0].keys())

    def test_priority_sort(self):
        # Low priority (idle_compute, low confidence) + high priority (unused_commitment, high conf)
        findings = [
            _finding(waste_type="idle_compute",       nec_waste=0.0,  nec_used=10.0, confidence=0.75),
            _finding(waste_type="unused_commitment",  nec_waste=10.0, nec_used=2.0,  confidence=0.95),
        ]
        recs = run(findings)
        assert recs[0]["priority_score"] >= recs[1]["priority_score"]

    def test_trivial_findings_excluded(self):
        # nec_waste=0.50, idle_compute: savings=0.40 < $1.00 floor
        findings = [_finding(waste_type="idle_compute", nec_waste=0.0, nec_used=0.50)]
        recs = run(findings)
        assert recs == []

    def test_empty_input(self):
        assert run([]) == []

    def test_current_cost_is_sum_of_nec(self):
        f = _finding(nec_waste=5.0, nec_used=3.0)
        recs = run([f])
        assert recs[0]["current_cost"] == pytest.approx(8.0)

    def test_priority_score_formula(self):
        # priority_score = savings_pct * confidence
        f = _finding(waste_type="unused_commitment", nec_waste=10.0, nec_used=10.0, confidence=0.95)
        recs = run([f])
        assert len(recs) == 1
        expected_pct = 10.0 / 20.0 * 100  # savings=10, total=20 → 50%
        expected_priority = round(expected_pct * 0.95, 4)
        assert recs[0]["priority_score"] == pytest.approx(expected_priority, rel=1e-3)

    def test_multiple_findings_sorted(self):
        findings = [
            _finding(resource_id="r1", waste_type="zombie_resource",    nec_waste=0.0, nec_used=1.5, confidence=0.80),
            _finding(resource_id="r2", waste_type="unused_commitment",   nec_waste=8.0, nec_used=1.0, confidence=0.95),
            _finding(resource_id="r3", waste_type="underutilized_commitment", nec_waste=10.0, nec_used=5.0, confidence=0.85),
        ]
        recs = run(findings)
        scores = [r["priority_score"] for r in recs]
        assert scores == sorted(scores, reverse=True)

    def test_savings_pct_in_range_all_types(self):
        findings = [
            _finding(waste_type="unused_commitment",        nec_waste=5.0,  nec_used=2.0),
            _finding(waste_type="idle_compute",             nec_waste=0.0,  nec_used=5.0),
            _finding(waste_type="zombie_resource",          nec_waste=0.0,  nec_used=1.5),
            _finding(waste_type="underutilized_commitment", nec_waste=5.0,  nec_used=3.0),
        ]
        recs = run(findings)
        for r in recs:
            assert 0.0 <= r["savings_pct"] <= 100.0, f"savings_pct out of range: {r}"