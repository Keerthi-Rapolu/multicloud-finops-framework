"""
Tests for allocation/shared_cost.py.

All tests use in-memory DataFrames and a minimal in-memory YAML config —
no file system or DuckDB dependency.
"""

from __future__ import annotations

import io
import math
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest
import yaml

from allocation.shared_cost import (
    SharedCostDistributor,
    _fanout_row,
    distribute_shared_costs,
)

# ---------------------------------------------------------------------------
# Minimal config used across all tests
# ---------------------------------------------------------------------------

_CONFIG_YAML = """
default_strategy: proportional

teams:
  - platform
  - data-eng
  - frontend

weights:
  platform: 0.50
  data-eng: 0.30
  frontend: 0.20

shared_services:
  - name: networking
    strategy: proportional
    service_names:
      - AmazonVPC
      - Virtual Network

  - name: logging
    strategy: even
    service_names:
      - AWSCloudTrail
      - Azure Monitor

  - name: security
    strategy: weighted
    service_names:
      - AWSSecurityHub
"""

_CONFIG: dict[str, Any] = yaml.safe_load(_CONFIG_YAML)


@pytest.fixture
def dist(tmp_path) -> SharedCostDistributor:
    cfg_file = tmp_path / "cfg.yml"
    cfg_file.write_text(_CONFIG_YAML)
    return SharedCostDistributor(cfg_file)


# ---------------------------------------------------------------------------
# Row factory
# ---------------------------------------------------------------------------

def _row(**overrides) -> dict:
    base = dict(
        cloud_provider="aws",
        billing_month="2026-03",
        account_id="123456789012",
        allocated_team="platform",
        service_name="AmazonEC2",
        service_category="Compute",
        discount_type="on_demand",
        usage_date=pd.Timestamp("2026-03-01"),
        usage_amount=100.0,
        list_cost=50.0,
        nec=50.0,
        nec_used=50.0,
        nec_waste=0.0,
        allocated_nec=50.0,
        effective_unit_price=None,
        is_commitment_waste=False,
        is_shared_cost=False,
        is_tagged=True,
        tag_team="platform",
        tag_environment="prod",
        tag_cost_center="eng",
    )
    base.update(overrides)
    return base


@pytest.fixture
def direct_rows() -> pd.DataFrame:
    """Three tagged direct-spend rows — one per team."""
    return pd.DataFrame([
        _row(allocated_team="platform",  nec=100.0, is_tagged=True),
        _row(allocated_team="data-eng",  nec=50.0,  is_tagged=True),
        _row(allocated_team="frontend",  nec=50.0,  is_tagged=True),
    ])


@pytest.fixture
def shared_vpc_row() -> pd.Series:
    """One untagged VPC row — configured as proportional shared service."""
    return pd.Series(_row(
        service_name="AmazonVPC",
        nec=60.0,
        allocated_nec=60.0,
        allocated_team=None,
        is_tagged=False,
        is_shared_cost=False,
    ))


@pytest.fixture
def shared_logging_row() -> pd.Series:
    """One untagged CloudTrail row — configured as even shared service."""
    return pd.Series(_row(
        service_name="AWSCloudTrail",
        nec=30.0,
        allocated_nec=30.0,
        allocated_team=None,
        is_tagged=False,
        is_shared_cost=False,
    ))


@pytest.fixture
def shared_security_row() -> pd.Series:
    """One untagged SecurityHub row — configured as weighted shared service."""
    return pd.Series(_row(
        service_name="AWSSecurityHub",
        nec=20.0,
        allocated_nec=20.0,
        allocated_team=None,
        is_tagged=False,
        is_shared_cost=False,
    ))


# ---------------------------------------------------------------------------
# _fanout_row
# ---------------------------------------------------------------------------

class TestFanoutRow:
    def test_produces_one_row_per_team(self, shared_vpc_row):
        shares = {"platform": 0.5, "data-eng": 0.3, "frontend": 0.2}
        result = _fanout_row(shared_vpc_row, shares)
        assert len(result) == 3

    def test_allocated_nec_sums_to_original_nec(self, shared_vpc_row):
        shares = {"platform": 0.5, "data-eng": 0.3, "frontend": 0.2}
        result = _fanout_row(shared_vpc_row, shares)
        assert math.isclose(result["allocated_nec"].sum(), shared_vpc_row["nec"])

    def test_is_shared_cost_set_true(self, shared_vpc_row):
        shares = {"platform": 0.5, "data-eng": 0.5}
        result = _fanout_row(shared_vpc_row, shares)
        assert result["is_shared_cost"].all()

    def test_team_names_assigned(self, shared_vpc_row):
        shares = {"platform": 0.6, "data-eng": 0.4}
        result = _fanout_row(shared_vpc_row, shares)
        assert set(result["allocated_team"]) == {"platform", "data-eng"}


# ---------------------------------------------------------------------------
# _compute_shares
# ---------------------------------------------------------------------------

class TestComputeShares:
    def test_even_equal_split(self, dist, direct_rows):
        shares = dist._compute_shares("even", ["platform", "data-eng", "frontend"], direct_rows)
        for v in shares.values():
            assert math.isclose(v, 1 / 3)

    def test_even_sums_to_one(self, dist, direct_rows):
        shares = dist._compute_shares("even", ["platform", "data-eng", "frontend"], direct_rows)
        assert math.isclose(sum(shares.values()), 1.0)

    def test_weighted_uses_config_weights(self, dist, direct_rows):
        shares = dist._compute_shares("weighted", ["platform", "data-eng", "frontend"], direct_rows)
        # weights: 0.5 / 0.3 / 0.2 → already sum to 1.0
        assert math.isclose(shares["platform"], 0.50, rel_tol=1e-6)
        assert math.isclose(shares["data-eng"], 0.30, rel_tol=1e-6)
        assert math.isclose(shares["frontend"], 0.20, rel_tol=1e-6)

    def test_weighted_sums_to_one(self, dist, direct_rows):
        shares = dist._compute_shares("weighted", ["platform", "data-eng", "frontend"], direct_rows)
        assert math.isclose(sum(shares.values()), 1.0)

    def test_proportional_reflects_direct_spend(self, dist, direct_rows):
        # platform=100, data-eng=50, frontend=50 → shares 0.5, 0.25, 0.25
        shares = dist._compute_shares("proportional", ["platform", "data-eng", "frontend"], direct_rows)
        assert math.isclose(shares["platform"], 0.50, rel_tol=1e-6)
        assert math.isclose(shares["data-eng"], 0.25, rel_tol=1e-6)
        assert math.isclose(shares["frontend"], 0.25, rel_tol=1e-6)

    def test_proportional_sums_to_one(self, dist, direct_rows):
        shares = dist._compute_shares("proportional", ["platform", "data-eng", "frontend"], direct_rows)
        assert math.isclose(sum(shares.values()), 1.0)

    def test_proportional_falls_back_to_even_when_no_spend(self, dist):
        empty = pd.DataFrame()
        shares = dist._compute_shares("proportional", ["platform", "data-eng"], empty)
        assert math.isclose(shares["platform"], 0.5)
        assert math.isclose(shares["data-eng"], 0.5)

    def test_weighted_falls_back_to_even_when_no_weights(self, tmp_path):
        cfg = yaml.safe_load(_CONFIG_YAML)
        cfg["weights"] = {}  # no weights
        cfg_file = tmp_path / "cfg.yml"
        cfg_file.write_text(yaml.dump(cfg))
        d = SharedCostDistributor(cfg_file)
        shares = d._compute_shares("weighted", ["platform", "data-eng"], pd.DataFrame())
        assert math.isclose(shares["platform"], 0.5)


# ---------------------------------------------------------------------------
# distribute — even strategy
# ---------------------------------------------------------------------------

class TestDistributeEven:
    @pytest.fixture
    def df(self, direct_rows, shared_logging_row):
        return pd.concat(
            [direct_rows, pd.DataFrame([shared_logging_row.to_dict()])],
            ignore_index=True,
        )

    def test_shared_row_fanned_into_n_rows(self, dist, df):
        result = dist.distribute(df)
        # 3 direct rows stay + 3 fanned rows (one per team)
        assert len(result) == 6

    def test_fanned_nec_sums_to_original(self, dist, df):
        result = dist.distribute(df)
        shared = result[result["is_shared_cost"] & (result["service_name"] == "AWSCloudTrail")]
        assert math.isclose(shared["allocated_nec"].sum(), 30.0)

    def test_each_team_gets_equal_share(self, dist, df):
        result = dist.distribute(df)
        shared = result[result["service_name"] == "AWSCloudTrail"]
        shares = shared["allocated_nec"].values
        assert all(math.isclose(s, 10.0) for s in shares)

    def test_direct_rows_unchanged(self, dist, df):
        result = dist.distribute(df)
        direct = result[result["service_name"] == "AmazonEC2"]
        assert len(direct) == 3
        assert (direct["is_shared_cost"] == False).all()


# ---------------------------------------------------------------------------
# distribute — proportional strategy
# ---------------------------------------------------------------------------

class TestDistributeProportional:
    @pytest.fixture
    def df(self, direct_rows, shared_vpc_row):
        return pd.concat(
            [direct_rows, pd.DataFrame([shared_vpc_row.to_dict()])],
            ignore_index=True,
        )

    def test_fanned_nec_sums_to_original(self, dist, df):
        result = dist.distribute(df)
        shared = result[result["service_name"] == "AmazonVPC"]
        assert math.isclose(shared["allocated_nec"].sum(), 60.0, rel_tol=1e-9)

    def test_platform_gets_largest_share(self, dist, df):
        # platform has 100 NEC direct spend vs 50 each for data-eng and frontend
        result = dist.distribute(df)
        shared = result[result["service_name"] == "AmazonVPC"]
        by_team = shared.set_index("allocated_team")["allocated_nec"]
        assert by_team["platform"] > by_team["data-eng"]
        assert by_team["platform"] > by_team["frontend"]

    def test_proportional_split_correct(self, dist, df):
        # platform=100/200=0.5, data-eng=50/200=0.25, frontend=50/200=0.25
        result = dist.distribute(df)
        shared = result[result["service_name"] == "AmazonVPC"].set_index("allocated_team")
        assert math.isclose(shared.loc["platform", "allocated_nec"], 30.0, rel_tol=1e-6)
        assert math.isclose(shared.loc["data-eng",  "allocated_nec"], 15.0, rel_tol=1e-6)
        assert math.isclose(shared.loc["frontend",  "allocated_nec"], 15.0, rel_tol=1e-6)


# ---------------------------------------------------------------------------
# distribute — weighted strategy
# ---------------------------------------------------------------------------

class TestDistributeWeighted:
    @pytest.fixture
    def df(self, direct_rows, shared_security_row):
        return pd.concat(
            [direct_rows, pd.DataFrame([shared_security_row.to_dict()])],
            ignore_index=True,
        )

    def test_fanned_nec_sums_to_original(self, dist, df):
        result = dist.distribute(df)
        shared = result[result["service_name"] == "AWSSecurityHub"]
        assert math.isclose(shared["allocated_nec"].sum(), 20.0, rel_tol=1e-9)

    def test_weighted_split_uses_config_weights(self, dist, df):
        # weights: platform=0.5, data-eng=0.3, frontend=0.2
        result = dist.distribute(df)
        shared = result[result["service_name"] == "AWSSecurityHub"].set_index("allocated_team")
        assert math.isclose(shared.loc["platform", "allocated_nec"], 10.0, rel_tol=1e-6)
        assert math.isclose(shared.loc["data-eng",  "allocated_nec"], 6.0,  rel_tol=1e-6)
        assert math.isclose(shared.loc["frontend",  "allocated_nec"], 4.0,  rel_tol=1e-6)


# ---------------------------------------------------------------------------
# distribute — strategy_override
# ---------------------------------------------------------------------------

class TestStrategyOverride:
    def test_override_forces_even_on_proportional_service(self, dist, direct_rows, shared_vpc_row):
        df = pd.concat(
            [direct_rows, pd.DataFrame([shared_vpc_row.to_dict()])],
            ignore_index=True,
        )
        result = dist.distribute(df, strategy_override="even")
        shared = result[result["service_name"] == "AmazonVPC"]
        # even: each team gets 60/3 = 20
        for val in shared["allocated_nec"]:
            assert math.isclose(val, 20.0, rel_tol=1e-6)

    def test_invalid_override_raises(self, dist, direct_rows):
        with pytest.raises(ValueError, match="strategy_override"):
            dist.distribute(direct_rows, strategy_override="invalid")


# ---------------------------------------------------------------------------
# distribute — already-fanned rows pass through
# ---------------------------------------------------------------------------

class TestAlreadyFannedRows:
    def test_already_fanned_dbt_rows_not_re_distributed(self, dist):
        """
        Rows where is_shared_cost=True and allocated_team is set (already
        fanned out by the Azure dbt model) must pass through unchanged.
        """
        fanned = pd.DataFrame([
            _row(service_name="AmazonVPC", is_shared_cost=True,
                 allocated_team="platform", is_tagged=False, nec=10.0, allocated_nec=10.0),
            _row(service_name="AmazonVPC", is_shared_cost=True,
                 allocated_team="data-eng", is_tagged=False, nec=10.0, allocated_nec=10.0),
        ])
        result = dist.distribute(fanned)
        assert len(result) == 2  # no additional fan-out
        assert set(result["allocated_team"]) == {"platform", "data-eng"}

    def test_untagged_vpc_without_is_shared_cost_gets_distributed(self, dist):
        """
        An untagged VPC row where is_shared_cost=False is a new shared
        candidate and must be fanned out.
        """
        df = pd.DataFrame([
            _row(service_name="AmazonVPC", is_shared_cost=False,
                 allocated_team=None, is_tagged=False, nec=30.0),
        ])
        result = dist.distribute(df)
        assert len(result) == 3  # one per team


# ---------------------------------------------------------------------------
# distribute — no shared rows
# ---------------------------------------------------------------------------

class TestNoSharedRows:
    def test_returns_copy_when_no_shared_candidates(self, dist, direct_rows):
        result = dist.distribute(direct_rows)
        assert len(result) == len(direct_rows)
        assert (result["is_shared_cost"] == False).all()


# ---------------------------------------------------------------------------
# distribute — teams override
# ---------------------------------------------------------------------------

class TestTeamsOverride:
    def test_custom_teams_used_for_fanout(self, dist, direct_rows, shared_logging_row):
        df = pd.concat(
            [direct_rows, pd.DataFrame([shared_logging_row.to_dict()])],
            ignore_index=True,
        )
        result = dist.distribute(df, teams=["platform", "data-eng"])
        shared = result[result["service_name"] == "AWSCloudTrail"]
        assert len(shared) == 2
        assert set(shared["allocated_team"]) == {"platform", "data-eng"}

    def test_no_teams_raises(self, tmp_path):
        cfg = yaml.safe_load(_CONFIG_YAML)
        cfg["teams"] = []
        cfg_file = tmp_path / "cfg.yml"
        cfg_file.write_text(yaml.dump(cfg))
        d = SharedCostDistributor(cfg_file)
        df = pd.DataFrame([_row(service_name="AWSCloudTrail", is_tagged=False, allocated_team=None)])
        with pytest.raises(ValueError, match="No teams"):
            d.distribute(df)


# ---------------------------------------------------------------------------
# distribute — multiple shared services in one call
# ---------------------------------------------------------------------------

class TestMultipleSharedServices:
    def test_all_shared_services_fanned(self, dist, direct_rows, shared_vpc_row, shared_logging_row):
        df = pd.concat(
            [
                direct_rows,
                pd.DataFrame([shared_vpc_row.to_dict()]),
                pd.DataFrame([shared_logging_row.to_dict()]),
            ],
            ignore_index=True,
        )
        result = dist.distribute(df)
        # 3 direct + 3 fanned VPC + 3 fanned CloudTrail
        assert len(result) == 9

    def test_total_nec_conserved(self, dist, direct_rows, shared_vpc_row, shared_logging_row):
        df = pd.concat(
            [
                direct_rows,
                pd.DataFrame([shared_vpc_row.to_dict()]),
                pd.DataFrame([shared_logging_row.to_dict()]),
            ],
            ignore_index=True,
        )
        original_total = df["nec"].sum()  # 200 direct + 60 VPC + 30 CloudTrail = 290
        result = dist.distribute(df)
        direct_nec = result[~result["is_shared_cost"]]["nec"].sum()
        shared_allocated = result[result["is_shared_cost"]]["allocated_nec"].sum()
        # Shared rows are replaced by fanned rows — total cost is conserved.
        assert math.isclose(direct_nec + shared_allocated, original_total, rel_tol=1e-6)


# ---------------------------------------------------------------------------
# allocation_summary
# ---------------------------------------------------------------------------

class TestAllocationSummary:
    def test_returns_all_three_strategies(self, dist, direct_rows, shared_vpc_row):
        df = pd.concat(
            [direct_rows, pd.DataFrame([shared_vpc_row.to_dict()])],
            ignore_index=True,
        )
        summary = dist.allocation_summary(df)
        assert set(summary["strategy"]) == {"proportional", "even", "weighted"}

    def test_each_strategy_has_team_rows(self, dist, direct_rows, shared_vpc_row):
        df = pd.concat(
            [direct_rows, pd.DataFrame([shared_vpc_row.to_dict()])],
            ignore_index=True,
        )
        summary = dist.allocation_summary(df)
        for strategy in ["proportional", "even", "weighted"]:
            rows = summary[summary["strategy"] == strategy]
            assert len(rows) == 3  # one per team

    def test_even_shares_equal(self, dist, direct_rows, shared_vpc_row):
        df = pd.concat(
            [direct_rows, pd.DataFrame([shared_vpc_row.to_dict()])],
            ignore_index=True,
        )
        summary = dist.allocation_summary(df)
        even_rows = summary[summary["strategy"] == "even"]
        pcts = even_rows["share_pct"].values
        assert all(math.isclose(p, pcts[0], rel_tol=1e-3) for p in pcts)

    def test_returns_empty_when_no_shared_candidates(self, dist, direct_rows):
        summary = dist.allocation_summary(direct_rows)
        assert summary.empty


# ---------------------------------------------------------------------------
# distribute_shared_costs — functional wrapper
# ---------------------------------------------------------------------------

class TestFunctionalWrapper:
    def test_returns_same_result_as_class(self, tmp_path, direct_rows, shared_logging_row):
        cfg_file = tmp_path / "cfg.yml"
        cfg_file.write_text(_CONFIG_YAML)
        df = pd.concat(
            [direct_rows, pd.DataFrame([shared_logging_row.to_dict()])],
            ignore_index=True,
        )
        via_class = SharedCostDistributor(cfg_file).distribute(df)
        via_func = distribute_shared_costs(df, config_path=cfg_file)
        assert len(via_class) == len(via_func)


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------

class TestConfigValidation:
    def test_unknown_strategy_raises(self, tmp_path):
        cfg = yaml.safe_load(_CONFIG_YAML)
        cfg["shared_services"][0]["strategy"] = "magic"
        cfg_file = tmp_path / "cfg.yml"
        cfg_file.write_text(yaml.dump(cfg))
        with pytest.raises(ValueError, match="Unknown strategy"):
            SharedCostDistributor(cfg_file)
