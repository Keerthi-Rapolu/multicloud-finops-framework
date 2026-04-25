"""
Multi-Cloud FinOps Pipeline — single entry point.

Usage:
    python pipeline.py                    # uses current month (YYYY-MM)
    python pipeline.py --month 2026-03    # specific month
    python pipeline.py --month 2026-03 --force   # skip confirmation on re-land

Flow:
    1. Generate synthetic billing data for the requested month
    2. Validate each cloud's CSV (schema, row count, date range, cost integrity)
    3. If ALL validations pass:
         - Delete existing raw Parquet for that month (if any)
         - Ingest CSVs → Parquet in data/raw/{cloud}/YYYY-MM/
    4. If ANY validation fails:
         - Raw data is left untouched
         - Errors printed; exit with code 1
"""

import argparse
import csv
import logging
import shutil
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.config              import GeneratorConfig, SCENARIOS
from scripts.generate_aws_cur    import generate as gen_aws
from scripts.generate_azure_cost import generate as gen_azure
from scripts.generate_gcp_billing import generate as gen_gcp

from ingestion.aws_ingestor   import ingest as ingest_aws,   SYNTHETIC as AWS_SYNTHETIC,   RAW_OUTPUT as AWS_RAW
from ingestion.azure_ingestor import ingest as ingest_azure, SYNTHETIC as AZURE_SYNTHETIC, RAW_OUTPUT as AZURE_RAW
from ingestion.gcp_ingestor   import ingest as ingest_gcp,   SYNTHETIC as GCP_SYNTHETIC,   RAW_OUTPUT as GCP_RAW

from ingestion.schemas.aws_cur_schema      import REQUIRED_COLUMNS as AWS_REQUIRED,   DATE_PARTITION_COLUMN as AWS_DATE
from ingestion.schemas.azure_cost_schema   import REQUIRED_COLUMNS as AZURE_REQUIRED, DATE_PARTITION_COLUMN as AZURE_DATE
from ingestion.schemas.gcp_billing_schema  import REQUIRED_COLUMNS as GCP_REQUIRED,   DATE_PARTITION_COLUMN as GCP_DATE

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _current_month() -> str:
    d = date.today()
    return f"{d.year}-{d.month:02d}"


def _csv_files(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.csv"))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class ValidationError(Exception):
    pass


def _validate_csv(
    csv_path: Path,
    required_cols: list[str],
    date_col: str,
    billing_month: str,
    cloud: str,
) -> list[str]:
    """
    Returns a list of error strings. Empty list = valid.
    Checks:
      1. File exists and is non-empty
      2. All required columns present
      3. Row count > 0
      4. All date values fall within the requested billing_month
      5. Cost column is non-null and numeric for all rows
    """
    errors = []

    # 1. File exists
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        errors.append(f"[{cloud}] File missing or empty: {csv_path.name}")
        return errors  # can't continue further

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        rows    = list(reader)

    # 2. Required columns
    missing_cols = [c for c in required_cols if c not in headers]
    if missing_cols:
        errors.append(f"[{cloud}] Missing required columns: {missing_cols}")

    # 3. Row count
    if len(rows) == 0:
        errors.append(f"[{cloud}] File has no data rows")
        return errors

    logger.info("  %s: %d rows, %d columns", cloud, len(rows), len(headers))

    # 4. Date range — all rows must belong to requested billing_month
    out_of_range = [
        r[date_col][:7]
        for r in rows
        if date_col in r and r[date_col][:7] != billing_month
    ]
    if out_of_range:
        bad_months = set(out_of_range)
        errors.append(
            f"[{cloud}] {len(out_of_range)} rows outside billing month "
            f"'{billing_month}': found {bad_months}"
        )

    # 5. Cost column integrity
    cost_col = {
        "AWS":   "lineItem/UnblendedCost",
        "Azure": "CostInBillingCurrency",
        "GCP":   "cost",
    }[cloud]

    if cost_col in headers:
        bad_cost = 0
        for r in rows:
            val = r.get(cost_col, "").strip()
            if val == "":
                bad_cost += 1
                continue
            try:
                float(val)
            except ValueError:
                bad_cost += 1
        if bad_cost > 0:
            errors.append(f"[{cloud}] {bad_cost} rows with null or non-numeric cost")

    return errors


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

def stage_generate(billing_month: str, cfg: GeneratorConfig) -> None:
    logger.info("=== Stage 1: Generate synthetic data for %s ===", billing_month)
    logger.info("  Config: %s", cfg.summary())
    gen_aws(billing_month=billing_month, cfg=cfg)
    gen_azure(billing_month=billing_month, cfg=cfg)
    gen_gcp(billing_month=billing_month, cfg=cfg)
    sys.stdout.flush()


def stage_validate(billing_month: str) -> dict[str, list[str]]:
    logger.info("=== Stage 2: Validate generated CSVs ===")
    all_errors: dict[str, list[str]] = {}

    checks = [
        ("AWS",   AWS_SYNTHETIC,   AWS_REQUIRED,   AWS_DATE),
        ("Azure", AZURE_SYNTHETIC, AZURE_REQUIRED, AZURE_DATE),
        ("GCP",   GCP_SYNTHETIC,   GCP_REQUIRED,   GCP_DATE),
    ]

    for cloud, syn_dir, required, date_col in checks:
        csv_files = [f for f in _csv_files(syn_dir) if billing_month in f.name]
        if not csv_files:
            all_errors[cloud] = [f"[{cloud}] No CSV files found in {syn_dir} for {billing_month}"]
            continue

        cloud_errors = []
        for csv_path in csv_files:
            cloud_errors.extend(
                _validate_csv(csv_path, required, date_col, billing_month, cloud)
            )
        if cloud_errors:
            all_errors[cloud] = cloud_errors
        else:
            logger.info("  %s: validation passed", cloud)

    return all_errors


def stage_land(billing_month: str) -> dict[str, int]:
    logger.info("=== Stage 3: Land validated data to raw ===")
    row_counts: dict[str, int] = {}

    clouds = [
        ("AWS",   ingest_aws,   AWS_RAW),
        ("Azure", ingest_azure, AZURE_RAW),
        ("GCP",   ingest_gcp,   GCP_RAW),
    ]

    for cloud, ingest_fn, raw_root in clouds:
        month_dir = raw_root / billing_month

        # Remove existing raw files for this month before re-landing.
        # Use per-file deletion so a locked file (e.g. open DuckDB connection)
        # is skipped rather than aborting the whole rmtree.
        if month_dir.exists():
            for f in month_dir.iterdir():
                try:
                    f.unlink()
                except PermissionError:
                    logger.warning("  %s: skipped locked file %s — will be overwritten", cloud, f.name)

        result = ingest_fn(billing_month=billing_month)
        rows   = sum(result.values())
        row_counts[cloud] = rows
        logger.info("  %s: landed %d rows -> %s", cloud, rows, month_dir)

    return row_counts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    billing_month: str | None = None,
    force: bool = False,
    cfg: GeneratorConfig | None = None,
) -> None:
    if billing_month is None:
        billing_month = _current_month()
    if cfg is None:
        cfg = GeneratorConfig()

    logger.info("load_synthetic starting — billing month: %s", billing_month)

    # Stage 1 — Generate
    stage_generate(billing_month, cfg)

    # Stage 2 — Validate
    errors = stage_validate(billing_month)

    if errors:
        logger.error("=== Validation FAILED — raw data not updated ===")
        for cloud, cloud_errors in errors.items():
            for err in cloud_errors:
                logger.error("  %s", err)
        sys.exit(1)

    # Check if raw already exists for this month
    existing = [
        d for d in [AWS_RAW / billing_month, AZURE_RAW / billing_month, GCP_RAW / billing_month]
        if d.exists()
    ]
    if existing and not force:
        print(f"\nRaw data already exists for {billing_month}:")
        for d in existing:
            print(f"  {d}")
        answer = input("\nDelete and re-land? [y/N]: ").strip().lower()
        if answer != "y":
            logger.info("Aborted — raw data unchanged.")
            sys.exit(0)

    # Stage 3 — Land
    row_counts = stage_land(billing_month)

    # Summary
    total = sum(row_counts.values())
    logger.info("=== load_synthetic complete ===")
    logger.info("  Billing month : %s", billing_month)
    for cloud, rows in row_counts.items():
        logger.info("  %-6s        : %d rows", cloud, rows)
    logger.info("  Total         : %d rows landed to raw", total)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-Cloud FinOps synthetic data pipeline")
    parser.add_argument("--month",    type=str,   default=None,  help="Billing month YYYY-MM (default: current month)")
    parser.add_argument("--force",    action="store_true",        help="Skip confirmation when overwriting existing raw data")
    parser.add_argument("--scenario", type=str,   default=None,  help=f"Named scenario: {list(SCENARIOS)}")
    parser.add_argument("--untagged-pct",  type=float, default=None, help="Fraction of rows with no cost-allocation tags (0.0-1.0)")
    parser.add_argument("--ri-pct",        type=float, default=None, help="Fraction of compute covered by RI / CUD (0.0-1.0)")
    parser.add_argument("--sp-pct",        type=float, default=None, help="Fraction of compute covered by Savings Plans / SUD (0.0-1.0)")
    parser.add_argument("--sample-hours",   type=int,   default=None, help="Hours to sample per resource (1-720; 72=dev, 720=full month)")
    parser.add_argument("--cost-multiplier", type=float, default=None, help="Global cost scale factor (1.8=spike, 0.9=reduction)")
    parser.add_argument("--seed",            type=int,   default=None, help="Random seed (default: derived from billing_month for determinism)")
    args = parser.parse_args()

    # Build config: scenario is the base, individual flags override
    if args.scenario:
        if args.scenario not in SCENARIOS:
            parser.error(f"Unknown scenario '{args.scenario}'. Choose from: {list(SCENARIOS)}")
        base = SCENARIOS[args.scenario]
        cfg = GeneratorConfig(
            untagged_pct    = args.untagged_pct    if args.untagged_pct    is not None else base.untagged_pct,
            ri_pct          = args.ri_pct          if args.ri_pct          is not None else base.ri_pct,
            sp_pct          = args.sp_pct          if args.sp_pct          is not None else base.sp_pct,
            sample_hours    = args.sample_hours    if args.sample_hours    is not None else base.sample_hours,
            cost_multiplier = args.cost_multiplier if args.cost_multiplier is not None else base.cost_multiplier,
            seed            = args.seed            if args.seed            is not None else base.seed,
        )
    else:
        cfg = GeneratorConfig(
            **({k: v for k, v in {
                "untagged_pct":    args.untagged_pct,
                "ri_pct":          args.ri_pct,
                "sp_pct":          args.sp_pct,
                "sample_hours":    args.sample_hours,
                "cost_multiplier": args.cost_multiplier,
                "seed":            args.seed,
            }.items() if v is not None})
        )

    run(billing_month=args.month, force=args.force, cfg=cfg)
