"""
Tests for the month-scoped synthetic data pipeline orchestration.
"""

from __future__ import annotations

import pandas as pd

import load_synthetic
from ingestion import aws_ingestor


def test_stage_land_passes_billing_month(monkeypatch):
    calls: list[tuple[str, str | None]] = []

    def _stub(name: str):
        def _inner(*, billing_month=None):
            calls.append((name, billing_month))
            return {f"{name}.parquet": 1}
        return _inner

    monkeypatch.setattr(load_synthetic, "ingest_aws", _stub("aws"))
    monkeypatch.setattr(load_synthetic, "ingest_azure", _stub("azure"))
    monkeypatch.setattr(load_synthetic, "ingest_gcp", _stub("gcp"))

    counts = load_synthetic.stage_land("2026-03")

    assert calls == [
        ("aws", "2026-03"),
        ("azure", "2026-03"),
        ("gcp", "2026-03"),
    ]
    assert counts == {"AWS": 1, "Azure": 1, "GCP": 1}


def test_aws_ingest_filters_to_requested_month(tmp_path, monkeypatch):
    source_dir = tmp_path / "synthetic"
    output_dir = tmp_path / "raw"
    source_dir.mkdir()

    pd.DataFrame(
        [{"lineItem/UsageStartDate": "2026-03-01T00:00:00Z"}]
    ).to_csv(source_dir / "aws_cur_2026-03.csv", index=False)
    pd.DataFrame(
        [{"lineItem/UsageStartDate": "2026-04-01T00:00:00Z"}]
    ).to_csv(source_dir / "aws_cur_2026-04.csv", index=False)

    monkeypatch.setattr(aws_ingestor, "_validate", lambda df, source_file: None)

    results = aws_ingestor.ingest(
        source_dir=source_dir,
        output_dir=output_dir,
        billing_month="2026-03",
    )

    assert list(results.values()) == [1]
    assert len(results) == 1
    assert "2026-03" in next(iter(results))
