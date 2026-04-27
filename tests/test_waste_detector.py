"""
Tests for intelligence/waste_detector.py.

All unit tests run against small, hand-crafted DataFrames that mirror the
fct_unified_billing schema — no DuckDB connection is required. The integration
test class at the bottom is skipped when finops_dbt.duckdb is absent.
"""

import math
from pathlib import Path
import shutil

import pandas as pd
import pytest

from intelligence import WasteFinding
from intelligence.waste_detector import (
    _deduplicate,
    detect_idle_compute,
    detect_underutilized_commitments,
    detect_unused_commitments,
    detect_zombie_resources,
    run,
)

# ---------------------------------------------------------------------------
# Shared fixtures and helpers
# ---------------------------------------------------------------------------

_THRESHOLDS = {
    "min_waste_dollars": 1.00,
    "idle_compute": {"nec_per_vcpu_hour_threshold": 0.005},
    "zombie_resource": {"monthly_nec_threshold": 2.00},
    "underutilized_commitment": {"used_fraction_threshold": 0.70},
    "confidence": {
        "unused_commitment": 0.95,
        "idle_compute": 0.75,
        "zombie_resource": 0.80,
        "underutilized_commitment": 0.85,
    },
}

_WASTE_TYPES = {
    "unused_commitment",
    "idle_compute",
    "zombie_resource",
    "underutilized_commitment",
}

_FINDING_KEYS = {
    "resource_id", "cloud_provider", "allocated_team", "service_category",
    "instance_type", "waste_type", "nec_waste", "nec_used", "confidence",
    "billing_month", "evidence",
}


def _row(**overrides) -> dict:
    """Return a default fct_unified_billing row, overridable per test."""
    base = dict(
        cloud_provider="aws",
        billing_account_id="123456789012",
        billing_month="2026-03",
        account_id="123456789012",
        account_name="test-account",
        usage_date=pd.Timestamp("2026-03-01 00:00:00"),
        resource_id="i-abc123",
        service_name="AmazonEC2",
        product_name="EC2 instance",
        instance_type="t3.medium",
        region="us-east-1",
        usage_amount=100.0,
        usage_unit="Hrs",
        currency="USD",
        list_cost=10.0,
        nec=10.0,
        nec_used=10.0,
        nec_waste=0.0,
        effective_unit_price=0.10,
        discount_type="on_demand",
        vcpu=2,
        memory_gb=4,
        tag_team="platform",
        tag_environment="prod",
        tag_cost_center="eng-01",
        environment="prod",
        cost_center="CC100",
        business_unit="engineering",
        application="platform-core",
        owner_email="platform-owner@company.com",
        workload_criticality="mission_critical",
        sla_tier="gold",
        cpu_util_pct=None,
        memory_util_pct=None,
        disk_util_pct=None,
        idle_hours=None,
        last_activity_at=None,
        is_tagged=True,
        allocated_team="platform",
        allocated_nec=10.0,
        is_shared_cost=False,
        is_commitment_waste=False,
        service_category="Compute",
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# detect_unused_commitments
# ---------------------------------------------------------------------------

class TestDetectUnusedCommitments:
    def test_flags_commitment_waste_row(self):
        df = pd.DataFrame([_row(
            is_commitment_waste=True,
            nec_waste=10.0,
            discount_type="ri",
        )])
        findings = detect_unused_commitments(df, _THRESHOLDS)
        assert len(findings) == 1
        assert findings[0]["waste_type"] == "unused_commitment"

    def test_waste_below_min_is_filtered(self):
        df = pd.DataFrame([_row(
            is_commitment_waste=True,
            nec_waste=0.50,   # below min_waste_dollars=1.00
            discount_type="ri",
        )])
        findings = detect_unused_commitments(df, _THRESHOLDS)
        assert len(findings) == 0

    def test_non_waste_row_not_flagged(self):
        df = pd.DataFrame([_row(is_commitment_waste=False, nec_waste=5.0)])
        findings = detect_unused_commitments(df, _THRESHOLDS)
        assert len(findings) == 0

    def test_nec_waste_value_preserved(self):
        df = pd.DataFrame([_row(is_commitment_waste=True, nec_waste=42.50, discount_type="sp")])
        findings = detect_unused_commitments(df, _THRESHOLDS)
        assert math.isclose(findings[0]["nec_waste"], 42.50)

    def test_confidence_matches_config(self):
        df = pd.DataFrame([_row(is_commitment_waste=True, nec_waste=5.0)])
        findings = detect_unused_commitments(df, _THRESHOLDS)
        assert math.isclose(findings[0]["confidence"], 0.95)

    def test_null_team_becomes_unattributed(self):
        df = pd.DataFrame([_row(
            is_commitment_waste=True, nec_waste=5.0, allocated_team=None
        )])
        findings = detect_unused_commitments(df, _THRESHOLDS)
        assert findings[0]["allocated_team"] == "unattributed"

    def test_multiple_waste_rows_all_returned(self):
        rows = [
            _row(resource_id=f"res-{i}", is_commitment_waste=True, nec_waste=float(i + 2))
            for i in range(5)
        ]
        df = pd.DataFrame(rows)
        findings = detect_unused_commitments(df, _THRESHOLDS)
        assert len(findings) == 5

    def test_evidence_contains_expected_keys(self):
        df = pd.DataFrame([_row(is_commitment_waste=True, nec_waste=5.0, discount_type="ri")])
        findings = detect_unused_commitments(df, _THRESHOLDS)
        ev = findings[0]["evidence"]
        assert "nec_waste" in ev
        assert "discount_type" in ev
        assert "threshold" in ev

    def test_metadata_is_preserved(self):
        df = pd.DataFrame([_row(is_commitment_waste=True, nec_waste=5.0, discount_type="ri")])
        findings = detect_unused_commitments(df, _THRESHOLDS)
        finding = findings[0]
        assert finding["environment"] == "prod"
        assert finding["business_unit"] == "engineering"
        assert finding["application"] == "platform-core"
        assert finding["owner_email"] == "platform-owner@company.com"


# ---------------------------------------------------------------------------
# detect_idle_compute
# ---------------------------------------------------------------------------

class TestDetectIdleCompute:
    def test_flags_idle_compute_row(self):
        # nec_used=1.5 over (4 vcpu * 5000 hours) → cost_per_vcpu_hour=0.000075
        # Monthly aggregate nec_used=1.5 is above min_dollars=1.00
        df = pd.DataFrame([_row(
            service_category="Compute",
            vcpu=4,
            usage_amount=5000.0,
            nec_used=1.5,
        )])
        findings = detect_idle_compute(df, _THRESHOLDS)
        assert len(findings) == 1
        assert findings[0]["waste_type"] == "idle_compute"

    def test_active_compute_not_flagged(self):
        # cost_per_vcpu_hour = 50 / (2 * 100) = 0.25 — well above threshold
        df = pd.DataFrame([_row(
            service_category="Compute",
            vcpu=2,
            usage_amount=100.0,
            nec_used=50.0,
        )])
        findings = detect_idle_compute(df, _THRESHOLDS)
        assert len(findings) == 0

    def test_non_compute_rows_excluded(self):
        df = pd.DataFrame([_row(
            service_category="Storage",
            vcpu=None,
            usage_amount=100.0,
            nec_used=0.001,
        )])
        findings = detect_idle_compute(df, _THRESHOLDS)
        assert len(findings) == 0

    def test_null_vcpu_excluded(self):
        df = pd.DataFrame([_row(
            service_category="Compute",
            vcpu=None,
            nec_used=0.001,
            usage_amount=100.0,
        )])
        findings = detect_idle_compute(df, _THRESHOLDS)
        assert len(findings) == 0

    def test_zero_usage_amount_excluded(self):
        df = pd.DataFrame([_row(
            service_category="Compute",
            vcpu=2,
            usage_amount=0.0,
            nec_used=5.0,
        )])
        findings = detect_idle_compute(df, _THRESHOLDS)
        assert len(findings) == 0

    def test_multiple_hourly_rows_aggregated_per_resource(self):
        # Same resource_id appearing 3 times — should produce 1 finding.
        # Each row: nec_used=0.60; aggregate=1.80 (above min_dollars=1.00)
        # cost_per_vcpu_hour = 0.60 / (4 * 5000) = 0.00003 — below 0.005 threshold
        rows = [
            _row(resource_id="i-idle", service_category="Compute", vcpu=4,
                 usage_amount=5000.0, nec_used=0.60)
            for _ in range(3)
        ]
        df = pd.DataFrame(rows)
        findings = detect_idle_compute(df, _THRESHOLDS)
        assert len(findings) == 1

    def test_confidence_matches_config(self):
        df = pd.DataFrame([_row(
            service_category="Compute", vcpu=4, usage_amount=5000.0, nec_used=1.5
        )])
        findings = detect_idle_compute(df, _THRESHOLDS)
        assert math.isclose(findings[0]["confidence"], 0.75)

    def test_evidence_contains_cost_per_vcpu_hour(self):
        df = pd.DataFrame([_row(
            service_category="Compute", vcpu=4, usage_amount=5000.0, nec_used=1.5
        )])
        findings = detect_idle_compute(df, _THRESHOLDS)
        assert "avg_cost_per_vcpu_hour" in findings[0]["evidence"]
        assert "threshold" in findings[0]["evidence"]

    def test_nec_used_below_min_dollars_excluded(self):
        # nec_used=0.50 is below min_waste_dollars=1.00 — should not be flagged
        df = pd.DataFrame([_row(
            service_category="Compute", vcpu=2, usage_amount=100.0, nec_used=0.50
        )])
        findings = detect_idle_compute(df, _THRESHOLDS)
        assert len(findings) == 0

    def test_telemetry_can_flag_idle_even_when_cost_proxy_is_not_low(self):
        df = pd.DataFrame([_row(
            resource_id="i-telemetry-idle",
            service_category="Compute",
            vcpu=2,
            usage_amount=100.0,
            nec_used=50.0,
            cpu_util_pct=4.0,
            memory_util_pct=8.0,
            disk_util_pct=6.0,
            idle_hours=240.0,
            last_activity_at=pd.Timestamp("2026-02-10 00:00:00"),
        )])
        findings = detect_idle_compute(df, _THRESHOLDS)
        assert len(findings) == 1
        assert findings[0]["evidence"]["signal_source"] == "telemetry+billing"
        assert findings[0]["confidence"] > _THRESHOLDS["confidence"]["idle_compute"]


# ---------------------------------------------------------------------------
# detect_zombie_resources
# ---------------------------------------------------------------------------

class TestDetectZombieResources:
    def test_flags_zombie_resource(self):
        # $1.50 total for the month — above $1 min but below $2 zombie floor
        df = pd.DataFrame([_row(resource_id="res-zombie", nec_used=1.50)])
        findings = detect_zombie_resources(df, _THRESHOLDS)
        assert len(findings) == 1
        assert findings[0]["waste_type"] == "zombie_resource"

    def test_healthy_resource_not_flagged(self):
        # $50/month — clearly above the $2 zombie floor
        df = pd.DataFrame([_row(resource_id="res-healthy", nec_used=50.0)])
        findings = detect_zombie_resources(df, _THRESHOLDS)
        assert len(findings) == 0

    def test_zero_nec_used_excluded(self):
        # Pure RI fee row — nec_used=0 should never be flagged as a zombie
        df = pd.DataFrame([_row(resource_id="res-ri-fee", nec_used=0.0, nec_waste=5.0,
                                is_commitment_waste=True)])
        findings = detect_zombie_resources(df, _THRESHOLDS)
        assert len(findings) == 0

    def test_sub_min_dollars_excluded(self):
        # $0.50 is below min_waste_dollars=1.00 — suppressed as noise
        df = pd.DataFrame([_row(resource_id="res-tiny", nec_used=0.50)])
        findings = detect_zombie_resources(df, _THRESHOLDS)
        assert len(findings) == 0

    def test_rows_aggregated_before_threshold_check(self):
        # 3 rows × $0.60 each = $1.80 total — above $1 min, below $2 floor → zombie
        rows = [_row(resource_id="res-agg", nec_used=0.60) for _ in range(3)]
        df = pd.DataFrame(rows)
        findings = detect_zombie_resources(df, _THRESHOLDS)
        assert len(findings) == 1
        assert math.isclose(findings[0]["nec_used"], 1.80, rel_tol=1e-6)

    def test_cost_only_fallback_reduces_confidence(self):
        df = pd.DataFrame([_row(resource_id="res-z", nec_used=1.50)])
        findings = detect_zombie_resources(df, _THRESHOLDS)
        assert math.isclose(findings[0]["confidence"], 0.72)

    def test_evidence_contains_monthly_nec_used(self):
        df = pd.DataFrame([_row(resource_id="res-z2", nec_used=1.50)])
        findings = detect_zombie_resources(df, _THRESHOLDS)
        assert "monthly_nec_used" in findings[0]["evidence"]
        assert "threshold" in findings[0]["evidence"]

    def test_null_team_becomes_unattributed(self):
        df = pd.DataFrame([_row(resource_id="res-null-team", nec_used=1.50, allocated_team=None)])
        findings = detect_zombie_resources(df, _THRESHOLDS)
        assert findings[0]["allocated_team"] == "unattributed"

    def test_cost_only_zombie_is_suppressed_when_telemetry_shows_recent_activity(self):
        df = pd.DataFrame([_row(
            resource_id="res-active-small",
            nec_used=1.50,
            cpu_util_pct=28.0,
            memory_util_pct=35.0,
            disk_util_pct=32.0,
            idle_hours=4.0,
            last_activity_at=pd.Timestamp("2026-02-28 00:00:00"),
        )])
        findings = detect_zombie_resources(df, _THRESHOLDS)
        assert findings == []

    def test_telemetry_backed_zombie_can_exceed_cost_floor(self):
        df = pd.DataFrame([_row(
            resource_id="res-telemetry-zombie",
            nec_used=5.50,
            cpu_util_pct=1.5,
            memory_util_pct=4.0,
            disk_util_pct=3.0,
            idle_hours=400.0,
            last_activity_at=pd.Timestamp("2026-01-15 00:00:00"),
        )])
        findings = detect_zombie_resources(df, _THRESHOLDS)
        assert len(findings) == 1
        assert findings[0]["evidence"]["signal_source"] == "telemetry"


# ---------------------------------------------------------------------------
# detect_underutilized_commitments
# ---------------------------------------------------------------------------

class TestDetectUnderutilizedCommitments:
    def test_flags_underutilized_ri(self):
        # used=30, waste=70 → used_fraction=0.30 — well below 0.70 threshold
        rows = [
            _row(resource_id="ri-res", discount_type="ri", nec_used=30.0, nec_waste=0.0),
            _row(resource_id="ri-res", discount_type="ri", nec_used=0.0,  nec_waste=70.0,
                 is_commitment_waste=True),
        ]
        df = pd.DataFrame(rows)
        findings = detect_underutilized_commitments(df, _THRESHOLDS)
        assert len(findings) == 1
        assert findings[0]["waste_type"] == "underutilized_commitment"

    def test_well_utilised_commitment_not_flagged(self):
        # used=90, waste=5 → used_fraction=0.947 — above 0.70 threshold
        rows = [
            _row(resource_id="ri-good", discount_type="ri", nec_used=90.0, nec_waste=0.0),
            _row(resource_id="ri-good", discount_type="ri", nec_used=0.0,  nec_waste=5.0),
        ]
        df = pd.DataFrame(rows)
        findings = detect_underutilized_commitments(df, _THRESHOLDS)
        assert len(findings) == 0

    def test_on_demand_rows_excluded(self):
        df = pd.DataFrame([_row(discount_type="on_demand", nec_used=5.0, nec_waste=20.0)])
        findings = detect_underutilized_commitments(df, _THRESHOLDS)
        assert len(findings) == 0

    def test_total_below_min_dollars_excluded(self):
        # Total = used(0.30) + waste(0.40) = 0.70 — below min_waste_dollars=1.00
        rows = [
            _row(resource_id="ri-tiny", discount_type="ri", nec_used=0.30, nec_waste=0.0),
            _row(resource_id="ri-tiny", discount_type="ri", nec_used=0.0,  nec_waste=0.40),
        ]
        df = pd.DataFrame(rows)
        findings = detect_underutilized_commitments(df, _THRESHOLDS)
        assert len(findings) == 0

    def test_savings_plan_also_flagged(self):
        rows = [
            _row(resource_id="sp-res", discount_type="sp", nec_used=20.0, nec_waste=0.0),
            _row(resource_id="sp-res", discount_type="sp", nec_used=0.0,  nec_waste=80.0),
        ]
        df = pd.DataFrame(rows)
        findings = detect_underutilized_commitments(df, _THRESHOLDS)
        assert len(findings) == 1
        assert findings[0]["evidence"]["discount_type"] == "sp"

    def test_used_fraction_in_evidence(self):
        rows = [
            _row(resource_id="ri-ev", discount_type="ri", nec_used=30.0, nec_waste=0.0),
            _row(resource_id="ri-ev", discount_type="ri", nec_used=0.0,  nec_waste=70.0),
        ]
        df = pd.DataFrame(rows)
        findings = detect_underutilized_commitments(df, _THRESHOLDS)
        ev = findings[0]["evidence"]
        assert "used_fraction" in ev
        assert math.isclose(ev["used_fraction"], 0.30, rel_tol=1e-4)

    def test_confidence_matches_config(self):
        rows = [
            _row(resource_id="ri-conf", discount_type="ri", nec_used=20.0, nec_waste=0.0),
            _row(resource_id="ri-conf", discount_type="ri", nec_used=0.0,  nec_waste=80.0),
        ]
        df = pd.DataFrame(rows)
        findings = detect_underutilized_commitments(df, _THRESHOLDS)
        assert math.isclose(findings[0]["confidence"], 0.85)

    def test_empty_dataframe_returns_empty(self):
        df = pd.DataFrame([_row(discount_type="on_demand")])
        findings = detect_underutilized_commitments(df, _THRESHOLDS)
        assert findings == []


# ---------------------------------------------------------------------------
# Output schema and value-range invariants
# ---------------------------------------------------------------------------

class TestOutputSchema:
    def _all_findings(self) -> list[WasteFinding]:
        rows = [
            # unused_commitment
            _row(resource_id="r1", is_commitment_waste=True, nec_waste=5.0, discount_type="ri"),
            # idle_compute
            _row(resource_id="r2", service_category="Compute", vcpu=2,
                 usage_amount=100.0, nec_used=0.001),
            # zombie
            _row(resource_id="r3", nec_used=1.50),
            # underutilized
            _row(resource_id="r4", discount_type="sp", nec_used=20.0, nec_waste=0.0),
            _row(resource_id="r4", discount_type="sp", nec_used=0.0,  nec_waste=80.0),
        ]
        return run(pd.DataFrame(rows))

    def test_all_required_keys_present(self):
        for f in self._all_findings():
            assert _FINDING_KEYS.issubset(f.keys()), f"Missing keys in: {f}"

    def test_waste_type_is_valid(self):
        for f in self._all_findings():
            assert f["waste_type"] in _WASTE_TYPES

    def test_confidence_in_range(self):
        for f in self._all_findings():
            assert 0.0 <= f["confidence"] <= 1.0, f"confidence out of range: {f['confidence']}"

    def test_nec_waste_non_negative(self):
        for f in self._all_findings():
            assert f["nec_waste"] >= 0.0

    def test_nec_used_non_negative(self):
        for f in self._all_findings():
            assert f["nec_used"] >= 0.0

    def test_evidence_is_dict(self):
        for f in self._all_findings():
            assert isinstance(f["evidence"], dict)

    def test_billing_month_format(self):
        for f in self._all_findings():
            assert len(f["billing_month"]) == 7
            assert f["billing_month"][4] == "-"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_same_resource_keeps_highest_confidence(self):
        findings = [
            WasteFinding(resource_id="r1", cloud_provider="aws", allocated_team="platform",
                         service_category="Compute", instance_type=None,
                         waste_type="idle_compute", nec_waste=0.0, nec_used=5.0,
                         confidence=0.75, billing_month="2026-03", evidence={}),
            WasteFinding(resource_id="r1", cloud_provider="aws", allocated_team="platform",
                         service_category="Compute", instance_type=None,
                         waste_type="zombie_resource", nec_waste=0.0, nec_used=5.0,
                         confidence=0.80, billing_month="2026-03", evidence={}),
        ]
        result = _deduplicate(findings)
        assert len(result) == 1
        assert result[0]["waste_type"] == "zombie_resource"  # higher confidence kept
        assert math.isclose(result[0]["confidence"], 0.80)

    def test_different_resources_both_kept(self):
        findings = [
            WasteFinding(resource_id="r1", cloud_provider="aws", allocated_team="a",
                         service_category="Compute", instance_type=None,
                         waste_type="idle_compute", nec_waste=0.0, nec_used=5.0,
                         confidence=0.75, billing_month="2026-03", evidence={}),
            WasteFinding(resource_id="r2", cloud_provider="aws", allocated_team="b",
                         service_category="Storage", instance_type=None,
                         waste_type="zombie_resource", nec_waste=1.5, nec_used=1.5,
                         confidence=0.80, billing_month="2026-03", evidence={}),
        ]
        result = _deduplicate(findings)
        assert len(result) == 2

    def test_different_months_same_resource_both_kept(self):
        base = dict(resource_id="r1", cloud_provider="aws", allocated_team="platform",
                    service_category="Compute", instance_type=None,
                    waste_type="idle_compute", nec_waste=0.0, nec_used=5.0,
                    confidence=0.75, evidence={})
        findings = [
            WasteFinding(**base, billing_month="2026-03"),
            WasteFinding(**base, billing_month="2026-04"),
        ]
        result = _deduplicate(findings)
        assert len(result) == 2

    def test_empty_input_returns_empty(self):
        assert _deduplicate([]) == []


# ---------------------------------------------------------------------------
# run() — integration over all detectors
# ---------------------------------------------------------------------------

class TestRun:
    def test_output_sorted_by_nec_waste_descending(self):
        rows = [
            _row(resource_id="r1", is_commitment_waste=True, nec_waste=5.0, discount_type="ri"),
            _row(resource_id="r2", is_commitment_waste=True, nec_waste=40.0, discount_type="sp"),
            _row(resource_id="r3", is_commitment_waste=True, nec_waste=2.0, discount_type="ri"),
        ]
        df = pd.DataFrame(rows)
        findings = run(df)
        waste_values = [f["nec_waste"] for f in findings]
        assert waste_values == sorted(waste_values, reverse=True)

    def test_empty_dataframe_returns_empty_list(self):
        df = pd.DataFrame([_row(
            is_commitment_waste=False, nec_waste=0.0, nec_used=50.0,
            discount_type="on_demand", vcpu=None, service_category="Storage",
        )])
        findings = run(df)
        assert isinstance(findings, list)

    def test_returns_list_of_dicts(self):
        df = pd.DataFrame([_row(is_commitment_waste=True, nec_waste=5.0)])
        findings = run(df)
        assert isinstance(findings, list)
        for f in findings:
            assert isinstance(f, dict)

    def test_no_duplicates_in_output(self):
        # Row that could trigger both unused_commitment and underutilized_commitment
        rows = [
            _row(resource_id="r1", is_commitment_waste=True, nec_waste=5.0,
                 discount_type="ri", nec_used=20.0),
            _row(resource_id="r1", is_commitment_waste=False, nec_waste=0.0,
                 discount_type="ri", nec_used=20.0),
        ]
        df = pd.DataFrame(rows)
        findings = run(df)
        resource_months = [(f["resource_id"], f["billing_month"]) for f in findings]
        assert len(resource_months) == len(set(resource_months))


# ---------------------------------------------------------------------------
# Integration test — skipped when DuckDB is absent
# ---------------------------------------------------------------------------

_DB_PATH = Path(__file__).resolve().parents[1] / "finops_dbt.duckdb"


@pytest.mark.skipif(
    not _DB_PATH.exists(),
    reason="finops_dbt.duckdb not present — run `dbt run` first",
)
class TestIntegration:
    @pytest.fixture(scope="class")
    def db_copy(self, tmp_path_factory):
        db_dir = tmp_path_factory.mktemp("waste_detector_db")
        db_copy = db_dir / "finops_dbt.duckdb"
        shutil.copy2(_DB_PATH, db_copy)
        return db_copy

    @pytest.fixture(scope="class")
    def df(self, db_copy):
        import duckdb
        con = duckdb.connect(str(db_copy), read_only=True)
        df = con.execute("SELECT * FROM marts.fct_unified_billing").df()
        con.close()
        return df

    @pytest.fixture(scope="class")
    def findings(self, df):
        return run(df)

    def test_finds_unused_commitments(self, findings):
        types = [f["waste_type"] for f in findings]
        assert "unused_commitment" in types

    def test_unused_commitment_total_approx(self, findings):
        # Synthetic data: aws $6.46 (8 rows, 8 distinct resource_ids) +
        # azure $40.27 (61 rows, null resource_ids grouped by account+service+type)
        # = ~$46.73 total. Allow ±$2 for threshold filtering of sub-$1 rows.
        total = sum(f["nec_waste"] for f in findings if f["waste_type"] == "unused_commitment")
        assert total > 44.0, f"Expected ~$46.73 waste, got ${total:.2f}"

    def test_all_findings_have_valid_schema(self, findings):
        for f in findings:
            assert _FINDING_KEYS.issubset(f.keys())
            assert f["waste_type"] in _WASTE_TYPES
            assert 0.0 <= f["confidence"] <= 1.0

    def test_output_sorted_descending(self, findings):
        if len(findings) < 2:
            pytest.skip("Not enough findings to test sort order")
        waste_values = [f["nec_waste"] for f in findings]
        assert waste_values == sorted(waste_values, reverse=True)

    def test_all_clouds_represented(self, findings):
        clouds = {f["cloud_provider"] for f in findings}
        assert len(clouds) >= 1

    def test_no_duplicate_resource_months(self, findings):
        keys = [(f["resource_id"], f["billing_month"]) for f in findings]
        assert len(keys) == len(set(keys)), "Duplicate resource+month pairs found"
