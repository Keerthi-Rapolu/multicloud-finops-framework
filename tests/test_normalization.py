"""
Tests for ingestion schema validation — ensures required columns are present
and cost/usage fields are numeric in the synthetic CSV files for all three clouds.
"""

from __future__ import annotations

import pandas as pd
import pytest
from pathlib import Path

from ingestion.schemas.aws_cur_schema import REQUIRED_COLUMNS as AWS_REQUIRED
from ingestion.schemas.azure_cost_schema import REQUIRED_COLUMNS as AZURE_REQUIRED
from ingestion.schemas.gcp_billing_schema import REQUIRED_COLUMNS as GCP_REQUIRED

REPO_ROOT = Path(__file__).resolve().parents[1]
AWS_SYNTHETIC   = REPO_ROOT / "data" / "synthetic" / "aws"
AZURE_SYNTHETIC = REPO_ROOT / "data" / "synthetic" / "azure"
GCP_SYNTHETIC   = REPO_ROOT / "data" / "synthetic" / "gcp"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_latest(directory: Path) -> pd.DataFrame:
    csvs = sorted(directory.glob("*.csv"))
    assert csvs, f"No synthetic CSVs found in {directory}"
    return pd.read_csv(csvs[-1], nrows=200)


# ---------------------------------------------------------------------------
# AWS CUR
# ---------------------------------------------------------------------------

class TestAWSNormalization:
    def test_required_columns_present(self):
        df = _load_latest(AWS_SYNTHETIC)
        missing = [c for c in AWS_REQUIRED if c not in df.columns]
        assert not missing, f"AWS CSV missing required columns: {missing}"

    def test_cost_columns_numeric(self):
        df = _load_latest(AWS_SYNTHETIC)
        for col in ["lineItem/UnblendedCost", "pricing/publicOnDemandCost"]:
            assert col in df.columns
            assert pd.to_numeric(df[col], errors="coerce").notna().any(), \
                f"{col} has no valid numeric values"

    def test_line_item_types_valid(self):
        df = _load_latest(AWS_SYNTHETIC)
        valid = {"Usage", "DiscountedUsage", "SavingsPlanCoveredUsage",
                 "RIFee", "SavingsPlanRecurringFee"}
        actual = set(df["lineItem/LineItemType"].dropna().unique())
        assert actual.issubset(valid), f"Unexpected LineItemTypes: {actual - valid}"

    def test_no_negative_on_demand_cost(self):
        df = _load_latest(AWS_SYNTHETIC)
        cost = pd.to_numeric(df["pricing/publicOnDemandCost"], errors="coerce").fillna(0)
        assert (cost >= 0).all(), "Negative on-demand cost found in AWS data"

    def test_usage_dates_parseable(self):
        df = _load_latest(AWS_SYNTHETIC)
        parsed = pd.to_datetime(df["lineItem/UsageStartDate"], errors="coerce")
        assert parsed.notna().all(), "Unparseable UsageStartDate values in AWS data"


# ---------------------------------------------------------------------------
# Azure Cost Management
# ---------------------------------------------------------------------------

class TestAzureNormalization:
    def test_required_columns_present(self):
        df = _load_latest(AZURE_SYNTHETIC)
        missing = [c for c in AZURE_REQUIRED if c not in df.columns]
        assert not missing, f"Azure CSV missing required columns: {missing}"

    def test_cost_column_numeric(self):
        df = _load_latest(AZURE_SYNTHETIC)
        assert "CostInBillingCurrency" in df.columns
        cost = pd.to_numeric(df["CostInBillingCurrency"], errors="coerce")
        assert cost.notna().any(), "CostInBillingCurrency has no valid numeric values"

    def test_charge_types_valid(self):
        df = _load_latest(AZURE_SYNTHETIC)
        valid = {"Usage", "UnusedReservation", "UnusedSavingsPlan"}
        actual = set(df["ChargeType"].dropna().unique())
        assert actual.issubset(valid), f"Unexpected ChargeTypes: {actual - valid}"

    def test_tags_column_present(self):
        df = _load_latest(AZURE_SYNTHETIC)
        assert "Tags" in df.columns, "Tags column missing from Azure data"

    def test_date_column_parseable(self):
        df = _load_latest(AZURE_SYNTHETIC)
        parsed = pd.to_datetime(df["Date"], errors="coerce")
        assert parsed.notna().all(), "Unparseable Date values in Azure data"


# ---------------------------------------------------------------------------
# GCP Billing Export
# ---------------------------------------------------------------------------

class TestGCPNormalization:
    def test_required_columns_present(self):
        df = _load_latest(GCP_SYNTHETIC)
        missing = [c for c in GCP_REQUIRED if c not in df.columns]
        assert not missing, f"GCP CSV missing required columns: {missing}"

    def test_cost_column_numeric(self):
        df = _load_latest(GCP_SYNTHETIC)
        assert "cost" in df.columns
        cost = pd.to_numeric(df["cost"], errors="coerce")
        assert cost.notna().any(), "cost column has no valid numeric values"

    def test_cost_type_regular(self):
        df = _load_latest(GCP_SYNTHETIC)
        assert "cost_type" in df.columns
        assert (df["cost_type"] == "regular").all(), \
            "GCP data contains non-regular cost_type rows (should be filtered at ingest)"

    def test_usage_start_time_parseable(self):
        df = _load_latest(GCP_SYNTHETIC)
        parsed = pd.to_datetime(df["usage_start_time"], errors="coerce")
        assert parsed.notna().all(), "Unparseable usage_start_time values in GCP data"

    def test_billing_account_id_consistent(self):
        df = _load_latest(GCP_SYNTHETIC)
        assert df["billing_account_id"].nunique() == 1, \
            "Multiple billing account IDs in a single GCP export file"
