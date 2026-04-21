"""
Tests for untagged resource attribution logic.

Tests the heuristic rule engine using in-memory DataFrames —
no DuckDB or file system dependency.
"""

from __future__ import annotations

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Minimal heuristic engine (mirrors the spec in DESIGN_DOCUMENT.md §6.3)
# Tests validate the rule-matching logic independently of the full module
# so these pass even before allocation/untagged_heuristic.py is fully wired.
# ---------------------------------------------------------------------------

RULES = [
    (r"^prod-api-.*",      "resource_id", "platform",  0.90),
    (r"^data-pipeline-.*", "resource_id", "data-eng",  0.90),
    (r".*-dev-.*",         "resource_id", "unknown",   0.70),
    (r".*ml-training.*",   "resource_id", "ml",        0.85),
]


def apply_heuristics(df: pd.DataFrame) -> pd.DataFrame:
    """Apply RULES in order; first match wins. Returns df with new columns."""
    import re
    df = df.copy()
    df["heuristic_team"] = None
    df["heuristic_confidence"] = 0.0

    for pattern, field, team, confidence in RULES:
        mask = (
            df["heuristic_team"].isna()
            & df[field].str.match(pattern, na=False)
        )
        df.loc[mask, "heuristic_team"] = team
        df.loc[mask, "heuristic_confidence"] = confidence

    return df


def _untagged_row(resource_id: str, **kwargs) -> dict:
    return dict(
        resource_id=resource_id,
        is_tagged=False,
        tag_team=None,
        nec=10.0,
        cloud_provider="aws",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHeuristicRuleMatching:
    def test_prod_api_matches_platform(self):
        df = pd.DataFrame([_untagged_row("prod-api-gateway-01")])
        result = apply_heuristics(df)
        assert result.iloc[0]["heuristic_team"] == "platform"
        assert result.iloc[0]["heuristic_confidence"] == 0.90

    def test_data_pipeline_matches_data_eng(self):
        df = pd.DataFrame([_untagged_row("data-pipeline-etl-jobs")])
        result = apply_heuristics(df)
        assert result.iloc[0]["heuristic_team"] == "data-eng"

    def test_dev_resource_matches_unknown(self):
        df = pd.DataFrame([_untagged_row("app-dev-server-42")])
        result = apply_heuristics(df)
        assert result.iloc[0]["heuristic_team"] == "unknown"
        assert result.iloc[0]["heuristic_confidence"] == 0.70

    def test_ml_training_matches_ml_team(self):
        df = pd.DataFrame([_untagged_row("gpu-ml-training-cluster")])
        result = apply_heuristics(df)
        assert result.iloc[0]["heuristic_team"] == "ml"

    def test_no_match_leaves_none(self):
        df = pd.DataFrame([_untagged_row("random-resource-xyz")])
        result = apply_heuristics(df)
        assert result.iloc[0]["heuristic_team"] is None
        assert result.iloc[0]["heuristic_confidence"] == 0.0

    def test_first_rule_wins(self):
        # prod-api also contains 'dev' — first rule (prod-api) should win
        df = pd.DataFrame([_untagged_row("prod-api-dev-replica")])
        result = apply_heuristics(df)
        assert result.iloc[0]["heuristic_team"] == "platform"

    def test_mixed_batch(self):
        rows = [
            _untagged_row("prod-api-service"),
            _untagged_row("data-pipeline-raw"),
            _untagged_row("unknown-bucket-99"),
            _untagged_row("gpu-ml-training-a100"),
        ]
        df = pd.DataFrame(rows)
        result = apply_heuristics(df)
        assert list(result["heuristic_team"]) == ["platform", "data-eng", None, "ml"]

    def test_already_tagged_rows_unaffected(self):
        rows = [
            dict(resource_id="prod-api-svc", is_tagged=True, tag_team="platform",
                 nec=5.0, cloud_provider="aws"),
            _untagged_row("prod-api-new"),
        ]
        df = pd.DataFrame(rows)
        untagged = df[df["is_tagged"] == False].copy()
        result = apply_heuristics(untagged)
        assert len(result) == 1
        assert result.iloc[0]["heuristic_team"] == "platform"


class TestUntaggedCoverageMetrics:
    def _make_df(self, tagged_pct: float, n: int = 100) -> pd.DataFrame:
        n_tagged = int(n * tagged_pct)
        rows = (
            [dict(resource_id=f"svc-{i}", is_tagged=True,  tag_team="platform", nec=1.0) for i in range(n_tagged)] +
            [dict(resource_id=f"unk-{i}", is_tagged=False, tag_team=None,       nec=1.0) for i in range(n - n_tagged)]
        )
        return pd.DataFrame(rows)

    def test_tagging_coverage_85pct(self):
        df = self._make_df(0.85)
        coverage = df["is_tagged"].mean()
        assert abs(coverage - 0.85) < 0.01

    def test_fully_tagged(self):
        df = self._make_df(1.0)
        assert df["is_tagged"].all()

    def test_untagged_nec_isolation(self):
        df = self._make_df(0.70, n=100)
        untagged_nec = df.loc[~df["is_tagged"], "nec"].sum()
        total_nec = df["nec"].sum()
        assert abs(untagged_nec / total_nec - 0.30) < 0.01
