"""
GCP Billing Detailed Usage Export ingestor — Layer 1 (Raw ingestion only).

Reads hourly-grain CSVs, validates that required columns exist,
and writes Parquet as-is to data/raw/gcp/YYYY-MM/.
No transformations — all casting, JSON parsing, and derivations happen in dbt staging.
"""
import logging
from pathlib import Path

import pandas as pd

from ingestion.schemas.gcp_billing_schema import REQUIRED_COLUMNS, DATE_PARTITION_COLUMN

logger = logging.getLogger(__name__)

REPO_ROOT  = Path(__file__).parent.parent
SYNTHETIC  = REPO_ROOT / "data" / "synthetic" / "gcp"
RAW_OUTPUT = REPO_ROOT / "data" / "raw" / "gcp"


def _validate(df: pd.DataFrame, source_file: str) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"[{source_file}] Missing required columns: {missing}")
    if df.empty:
        raise ValueError(f"[{source_file}] File is empty")


def _billing_month(df: pd.DataFrame) -> str:
    sample = df[DATE_PARTITION_COLUMN].dropna().iloc[0]
    return str(sample)[:7]  # e.g. "2026-03-01T00:00:00Z" -> "2026-03"


def ingest(source_dir: Path = SYNTHETIC, output_dir: Path = RAW_OUTPUT) -> dict:
    csv_files = sorted(source_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {source_dir}")

    results = {}

    for csv_path in csv_files:
        logger.info("Ingesting %s", csv_path.name)

        df = pd.read_csv(csv_path, dtype=str, low_memory=False)
        logger.info("  Loaded %d rows, %d columns", len(df), len(df.columns))

        _validate(df, csv_path.name)

        month = _billing_month(df)
        out_dir = output_dir / month
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / csv_path.with_suffix(".parquet").name

        df.to_parquet(out_path, index=False, engine="pyarrow")
        logger.info("  Wrote %d rows -> %s", len(df), out_path)
        results[str(out_path)] = len(df)

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    summary = ingest()
    print(f"\nGCP ingestion complete — {sum(summary.values())} rows written.")
