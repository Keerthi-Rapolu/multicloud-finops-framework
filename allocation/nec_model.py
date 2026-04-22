"""
NEC (Net Effective Cost) analysis module.

Reads from the fct_unified_billing DuckDB mart and exposes aggregation
functions used by the Streamlit dashboard and the paper evaluation.

NEC definition per cloud:
  AWS   — reservation_effective_cost (RI) / savings_plan_effective_cost (SP) / unblended_cost (OD)
  Azure — amortized billed_cost; UnusedReservation/SP rows become nec_waste
  GCP   — list_cost + sum(credits)  (CUD/SUD credits are negative amounts)

All formulas are implemented in the dbt intermediate models. This module
only aggregates and reshapes the mart output — it never re-derives NEC.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd

_DEFAULT_DB = Path(__file__).resolve().parents[1] / "finops_dbt.duckdb"
_MART = "marts.fct_unified_billing"


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def _connect(db_path: str | Path) -> duckdb.DuckDBPyConnection:
    path = str(db_path)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"DuckDB not found at {path}. Run `dbt run` first."
        )
    return duckdb.connect(path, read_only=True)


def load_billing_data(
    db_path: str | Path = _DEFAULT_DB,
    billing_month: Optional[str] = None,
    cloud_provider: Optional[str] = None,
) -> pd.DataFrame:
    """
    Load fct_unified_billing into a DataFrame.

    Parameters
    ----------
    billing_month : 'YYYY-MM' string, optional — filter to a single month.
    cloud_provider : 'aws' | 'azure' | 'gcp', optional — filter to one cloud.
    """
    con = _connect(db_path)
    try:
        clauses: list[str] = []
        if billing_month:
            clauses.append(f"billing_month = '{billing_month}'")
        if cloud_provider:
            clauses.append(f"cloud_provider = '{cloud_provider.lower()}'")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        df = con.execute(f"SELECT * FROM {_MART} {where}").df()
    finally:
        con.close()

    return df


# ---------------------------------------------------------------------------
# Core NEC aggregations
# ---------------------------------------------------------------------------

def nec_by_cloud(df: pd.DataFrame) -> pd.DataFrame:
    """Total NEC, list cost, and waste by cloud — used by the Overview page."""
    return (
        df.groupby("cloud_provider", sort=True)
        .agg(
            rows=("nec", "count"),
            list_cost=("list_cost", "sum"),
            nec=("nec", "sum"),
            nec_used=("nec_used", "sum"),
            nec_waste=("nec_waste", "sum"),
        )
        .assign(
            savings=lambda x: x["list_cost"] - x["nec"],
            savings_pct=lambda x: (
                (x["list_cost"] - x["nec"]) / x["list_cost"].replace(0, float("nan")) * 100
            ).round(1),
        )
        .reset_index()
    )


def nec_by_team(df: pd.DataFrame) -> pd.DataFrame:
    """
    Per-team NEC using allocated_nec (which reflects shared-cost spreading
    done in int_azure_nec). AWS and GCP rows use tag_team directly.
    """
    return (
        df.groupby(["allocated_team", "cloud_provider"], sort=True, dropna=False)
        .agg(
            list_cost=("list_cost", "sum"),
            nec=("allocated_nec", "sum"),
            nec_waste=("nec_waste", "sum"),
        )
        .assign(savings=lambda x: x["list_cost"] - x["nec"])
        .reset_index()
        .rename(columns={"allocated_team": "team"})
    )


def nec_by_service_category(df: pd.DataFrame) -> pd.DataFrame:
    """NEC breakdown by service category and cloud — for the Overview page."""
    return (
        df.groupby(["cloud_provider", "service_category"], sort=True)
        .agg(
            list_cost=("list_cost", "sum"),
            nec=("nec", "sum"),
            nec_waste=("nec_waste", "sum"),
            rows=("nec", "count"),
        )
        .reset_index()
    )


def nec_trend(df: pd.DataFrame, freq: str = "D") -> pd.DataFrame:
    """
    Daily (or weekly/monthly) NEC trend across all clouds.

    Parameters
    ----------
    freq : pandas offset alias — 'D' daily, 'W' weekly, 'MS' month-start.
    """
    trend = (
        df.dropna(subset=["usage_date"])
        .assign(period=pd.to_datetime(df["usage_date"]).dt.to_period(freq))
        .groupby(["period", "cloud_provider"])
        .agg(nec=("nec", "sum"), list_cost=("list_cost", "sum"))
        .reset_index()
    )
    trend["period"] = trend["period"].dt.to_timestamp()
    return trend


# ---------------------------------------------------------------------------
# Commitment analysis (RI / SP / CUD)
# ---------------------------------------------------------------------------

def commitment_utilization(df: pd.DataFrame) -> pd.DataFrame:
    """
    Commitment utilization by cloud and discount type.

    utilization_pct = nec_used / (nec_used + nec_waste) * 100
    """
    committed = df[df["discount_type"].isin(["ri", "sp"])].copy()
    result = (
        committed.groupby(["cloud_provider", "discount_type"])
        .agg(
            nec_used=("nec_used", "sum"),
            nec_waste=("nec_waste", "sum"),
            rows=("nec_used", "count"),
        )
        .reset_index()
    )
    total = result["nec_used"] + result["nec_waste"]
    result["utilization_pct"] = (
        (result["nec_used"] / total.replace(0, float("nan")) * 100).round(1)
    )
    return result


def savings_vs_on_demand(df: pd.DataFrame) -> pd.DataFrame:
    """
    Discount savings: (list_cost − nec_used) by cloud and discount_type.
    Shows how much each commitment type saves vs on-demand pricing.
    """
    return (
        df.groupby(["cloud_provider", "discount_type"])
        .agg(
            list_cost=("list_cost", "sum"),
            nec_used=("nec_used", "sum"),
        )
        .assign(
            savings=lambda x: x["list_cost"] - x["nec_used"],
            savings_pct=lambda x: (
                (x["list_cost"] - x["nec_used"])
                / x["list_cost"].replace(0, float("nan"))
                * 100
            ).round(1),
        )
        .reset_index()
    )


def commitment_waste_detail(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rows where is_commitment_waste=True — idle RI/SP/CUD cost.
    Used in the Team Allocation page to surface unused commitment cost.
    """
    waste = df[df["is_commitment_waste"].fillna(False)].copy()
    return waste[
        [
            "cloud_provider",
            "billing_month",
            "account_id",
            "service_name",
            "discount_type",
            "nec_waste",
            "allocated_team",
        ]
    ].sort_values("nec_waste", ascending=False)


# ---------------------------------------------------------------------------
# Effective unit price
# ---------------------------------------------------------------------------

def effective_unit_price_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Average effective unit price vs on-demand unit price by service category.

    effective_unit_price is pre-computed for Azure rows; derived from
    nec_used / usage_amount for AWS and GCP.
    """
    usage = df[(df["nec_used"] > 0) & (df["usage_amount"] > 0)].copy()
    usage["computed_eup"] = usage["effective_unit_price"].fillna(
        usage["nec_used"] / usage["usage_amount"]
    )
    usage["list_eup"] = usage["list_cost"] / usage["usage_amount"]

    return (
        usage.groupby(["cloud_provider", "service_category"])
        .agg(
            avg_effective_unit_price=("computed_eup", "mean"),
            avg_list_unit_price=("list_eup", "mean"),
            total_nec_used=("nec_used", "sum"),
        )
        .assign(
            discount_pct=lambda x: (
                (
                    1
                    - x["avg_effective_unit_price"].astype(float)
                    / x["avg_list_unit_price"].astype(float).replace(0, float("nan"))
                )
                * 100
            ).round(1)
        )
        .reset_index()
    )


# ---------------------------------------------------------------------------
# Full NEC report — convenience wrapper used by the paper evaluation section
# ---------------------------------------------------------------------------

@dataclass
class NECReport:
    """Aggregated NEC report for a single billing month (or all months)."""

    billing_month: Optional[str]
    by_cloud: pd.DataFrame
    by_team: pd.DataFrame
    by_service: pd.DataFrame
    commitment_util: pd.DataFrame
    savings: pd.DataFrame
    waste_rows: pd.DataFrame
    raw: pd.DataFrame = field(repr=False)

    @property
    def total_list_cost(self) -> float:
        return float(self.by_cloud["list_cost"].sum())

    @property
    def total_nec(self) -> float:
        return float(self.by_cloud["nec"].sum())

    @property
    def total_savings(self) -> float:
        return self.total_list_cost - self.total_nec

    @property
    def overall_savings_pct(self) -> float:
        if self.total_list_cost == 0:
            return 0.0
        return round(self.total_savings / self.total_list_cost * 100, 1)

    def summary(self) -> str:
        lines = [
            f"NEC Report — {self.billing_month or 'all months'}",
            f"  List cost : ${self.total_list_cost:>12,.2f}",
            f"  NEC (used): ${self.total_nec:>12,.2f}",
            f"  Savings   : ${self.total_savings:>12,.2f}  ({self.overall_savings_pct}%)",
        ]
        lines.append("\nBy cloud:")
        for _, row in self.by_cloud.iterrows():
            lines.append(
                f"  {row['cloud_provider']:6s}  list=${row['list_cost']:>10,.2f}"
                f"  nec=${row['nec']:>10,.2f}"
                f"  waste=${row['nec_waste']:>8,.2f}"
                f"  savings={row.get('savings_pct', 0):.1f}%"
            )
        return "\n".join(lines)


def build_nec_report(
    db_path: str | Path = _DEFAULT_DB,
    billing_month: Optional[str] = None,
) -> NECReport:
    """
    Load the mart and build a full NECReport for the given billing_month
    (or all months if None).
    """
    df = load_billing_data(db_path, billing_month=billing_month)
    return NECReport(
        billing_month=billing_month,
        by_cloud=nec_by_cloud(df),
        by_team=nec_by_team(df),
        by_service=nec_by_service_category(df),
        commitment_util=commitment_utilization(df),
        savings=savings_vs_on_demand(df),
        waste_rows=commitment_waste_detail(df),
        raw=df,
    )


# ---------------------------------------------------------------------------
# CLI entrypoint — python -m allocation.nec_model
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Print NEC report from DuckDB mart.")
    parser.add_argument("--db", default=str(_DEFAULT_DB), help="Path to finops_dbt.duckdb")
    parser.add_argument("--month", default=None, help="Billing month (YYYY-MM)")
    args = parser.parse_args()

    report = build_nec_report(db_path=args.db, billing_month=args.month)
    print(report.summary())

    print("\nCommitment utilization:")
    print(report.commitment_util.to_string(index=False))

    print("\nSavings vs on-demand:")
    print(report.savings.to_string(index=False))
