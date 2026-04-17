"""Ingestion layer — run all three cloud ingestors."""
import logging
from pathlib import Path

from ingestion.aws_ingestor import ingest as ingest_aws
from ingestion.azure_ingestor import ingest as ingest_azure
from ingestion.gcp_ingestor import ingest as ingest_gcp

logger = logging.getLogger(__name__)


def run_all() -> dict:
    """Run AWS, Azure, and GCP ingestors. Returns combined row counts per output file."""
    results = {}
    for cloud, fn in [("AWS", ingest_aws), ("Azure", ingest_azure), ("GCP", ingest_gcp)]:
        logger.info("=== %s ingestion ===", cloud)
        try:
            cloud_results = fn()
            results.update(cloud_results)
            logger.info("%s complete — %d rows written", cloud, sum(cloud_results.values()))
        except Exception as e:
            logger.error("%s ingestion failed: %s", cloud, e)
            raise
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    summary = run_all()
    total = sum(summary.values())
    print(f"\nAll clouds ingested — {total} total rows written across {len(summary)} Parquet files.")
