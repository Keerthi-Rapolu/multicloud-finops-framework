"""
Waste Detection Engine.

Reads a fct_unified_billing DataFrame and identifies four categories of waste:

  unused_commitment       — is_commitment_waste=True rows; waste is directly
                            recorded in billing data (nec_waste column).
  idle_compute            — Compute rows with very low cost-per-vCPU-hour proxy;
                            a billing-side approximation since real CPU metrics
                            (CloudWatch, Azure Monitor) are not available here.
  zombie_resource         — resources whose total nec_used for the billing month
                            is above zero but below a dollar floor; likely
                            forgotten or decommissioned-but-not-deleted.
  underutilized_commitment— RI/SP rows where the used fraction of the commitment
                            falls below a configurable threshold.

Entry point: run(df) → list[WasteFinding]

All numeric thresholds are read from config/waste_thresholds.yml so they can be
tuned without touching code.
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import yaml

from intelligence import WasteFinding

_DEFAULT_THRESHOLDS = Path(__file__).resolve().parents[1] / "config" / "waste_thresholds.yml"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_thresholds(path: str | Path = _DEFAULT_THRESHOLDS) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _safe_team(value) -> str:
    """Coerce None / NaN allocated_team to 'unattributed'."""
    if value is None:
        return "unattributed"
    if isinstance(value, float) and math.isnan(value):
        return "unattributed"
    return str(value)


def _safe_str(value) -> str | None:
    """Return None for pandas NA / NaN, else str."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return str(value)


def _safe_bool(value) -> bool | None:
    """Return None for pandas NA / NaN, else bool(value)."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return bool(value)


def _safe_float(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _safe_timestamp(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _metric_or_default(value, default: float) -> float:
    metric = _safe_float(value)
    return default if metric is None else metric


_OPTIONAL_METADATA_COLS = [
    "is_tagged",
    "environment",
    "cost_center",
    "business_unit",
    "application",
    "owner_email",
    "workload_criticality",
    "sla_tier",
    "cpu_util_pct",
    "memory_util_pct",
    "disk_util_pct",
    "idle_hours",
    "last_activity_at",
]


def _optional_agg(df: pd.DataFrame) -> dict[str, tuple[str, str]]:
    agg: dict[str, tuple[str, str]] = {}
    for col in _OPTIONAL_METADATA_COLS:
        if col not in df.columns:
            continue
        if col in {"cpu_util_pct", "memory_util_pct", "disk_util_pct"}:
            agg[col] = (col, "mean")
        elif col in {"idle_hours", "last_activity_at"}:
            agg[col] = (col, "max")
        else:
            agg[col] = (col, "first")
    return agg


def _metadata_payload(row: pd.Series | dict) -> dict:
    payload: dict = {}
    for col in _OPTIONAL_METADATA_COLS:
        if col not in row:
            continue
        if col == "is_tagged":
            value = _safe_bool(row[col])
        elif col in {"cpu_util_pct", "memory_util_pct", "disk_util_pct", "idle_hours"}:
            value = _safe_float(row[col])
        elif col == "last_activity_at":
            value = _safe_timestamp(row[col])
        else:
            value = _safe_str(row[col])
        if value is not None:
            payload[col] = value
    return payload


def _stale_days(reference_value, activity_value) -> float | None:
    if reference_value is None or pd.isna(reference_value) or activity_value is None or pd.isna(activity_value):
        return None
    reference_ts = pd.Timestamp(reference_value)
    activity_ts = pd.Timestamp(activity_value)
    delta = reference_ts - activity_ts
    return max(delta.total_seconds() / 86400.0, 0.0)


def _telemetry_present(row: pd.Series | dict) -> bool:
    return any(
        _safe_float(row.get(col)) is not None
        for col in ("cpu_util_pct", "memory_util_pct", "disk_util_pct", "idle_hours")
    ) or _safe_timestamp(row.get("last_activity_at")) is not None


def _telemetry_evidence(row: pd.Series | dict, stale_days: float | None) -> dict:
    evidence: dict[str, float | str] = {}
    for key in ("cpu_util_pct", "memory_util_pct", "disk_util_pct", "idle_hours"):
        value = _safe_float(row.get(key))
        if value is not None:
            evidence[key] = round(value, 2)
    if stale_days is not None:
        evidence["stale_days_since_activity"] = round(stale_days, 2)
    last_activity = _safe_timestamp(row.get("last_activity_at"))
    if last_activity is not None:
        evidence["last_activity_at"] = last_activity
    return evidence


def _required_columns(df: pd.DataFrame, cols: list[str]) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"waste_detector: DataFrame missing columns: {missing}")


# ---------------------------------------------------------------------------
# Detector 1 — unused_commitment
# ---------------------------------------------------------------------------

def detect_unused_commitments(
    df: pd.DataFrame,
    thresholds: dict,
) -> list[WasteFinding]:
    """
    Flag rows where is_commitment_waste=True and nec_waste > min_waste_dollars.

    These rows are directly emitted by the billing provider (AWS RIFee /
    SavingsPlanRecurringFee, Azure UnusedReservation / UnusedSavingsPlan) and
    represent commitment cost paid for capacity that was never consumed.

    On current synthetic data: 69 rows, ~$46.73 waste (aws $6.46, azure $40.27).

    Azure commitment waste rows carry a null resource_id (the billing export does
    not include a resource ARN for reservation-level waste rows). These are grouped
    by (cloud_provider, account_id, service_name, discount_type, billing_month)
    so that all waste for a given commitment type in an account is aggregated into
    one finding rather than creating dozens of near-identical low-dollar entries.
    """
    _required_columns(df, ["is_commitment_waste", "nec_waste", "resource_id",
                            "cloud_provider", "allocated_team", "service_category",
                            "billing_month", "discount_type", "nec_used",
                            "account_id", "service_name"])

    min_dollars = thresholds["min_waste_dollars"]
    confidence = thresholds["confidence"]["unused_commitment"]

    subset = df[
        df["is_commitment_waste"].fillna(False).astype(bool)
        & (df["nec_waste"].fillna(0) > 0)
    ].copy()

    if subset.empty:
        return []

    # Use resource_id when available (AWS), fall back to account_id for null-resource
    # rows (Azure). This ensures each distinct commitment is one finding.
    subset["_group_id"] = subset["resource_id"].fillna(
        subset["account_id"].astype(str)
        + "|"
        + subset["service_name"].astype(str)
        + "|"
        + subset["discount_type"].astype(str)
    )

    agg = (
        subset.groupby(["_group_id", "billing_month"], dropna=False)
        .agg(
            cloud_provider=("cloud_provider", "first"),
            account_id=("account_id", "first"),
            allocated_team=("allocated_team", "first"),
            service_category=("service_category", "first"),
            instance_type=("instance_type", "first"),
            discount_type=("discount_type", "first"),
            nec_waste=("nec_waste", "sum"),
            nec_used=("nec_used", "sum"),
            **_optional_agg(subset),
        )
        .reset_index()
    )

    # Apply min_dollars filter on the aggregated total
    agg = agg[agg["nec_waste"] > min_dollars]

    findings: list[WasteFinding] = []
    for _, row in agg.iterrows():
        findings.append(WasteFinding(
            resource_id=str(row["_group_id"]),
            cloud_provider=str(row["cloud_provider"]),
            allocated_team=_safe_team(row["allocated_team"]),
            service_category=str(row["service_category"]),
            instance_type=_safe_str(row.get("instance_type")),
            waste_type="unused_commitment",
            nec_waste=float(row["nec_waste"]),
            nec_used=float(row["nec_used"]),
            confidence=confidence,
            billing_month=str(row["billing_month"]),
            evidence={
                "nec_waste": float(row["nec_waste"]),
                "discount_type": str(row["discount_type"]),
                "threshold": min_dollars,
            },
            **_metadata_payload(row),
        ))
    return findings


# ---------------------------------------------------------------------------
# Detector 2 — idle_compute
# ---------------------------------------------------------------------------

def detect_idle_compute(
    df: pd.DataFrame,
    thresholds: dict,
) -> list[WasteFinding]:
    """
    Flag Compute rows where cost-per-vCPU-hour is below the idle threshold.

    Proxy metric:
        cost_per_vcpu_hour = nec_used / (vcpu * usage_amount)

    where usage_amount is hours for Compute rows. A very low value means the
    instance is provisioned but barely performing work relative to its size.

    Limitation: this is a billing proxy. Real CPU utilisation requires
    CloudWatch / Azure Monitor data, which is not available here (free tier).
    This is documented in paper section 7.
    """
    _required_columns(df, ["service_category", "vcpu", "nec_used",
                            "usage_amount", "resource_id", "cloud_provider",
                            "allocated_team", "billing_month", "usage_date"])

    threshold = thresholds["idle_compute"]["nec_per_vcpu_hour_threshold"]
    min_dollars = thresholds["min_waste_dollars"]
    base_confidence = thresholds["confidence"]["idle_compute"]

    compute = df[
        (df["service_category"] == "Compute")
        & df["vcpu"].notna()
        & (df["vcpu"] > 0)
        & (df["nec_used"] > 0)       # exclude pure RI-fee rows (nec_used=0)
        & (df["usage_amount"] > 0)
    ].copy()

    if compute.empty:
        return []

    compute["_cost_per_vcpu_hour"] = compute["nec_used"] / (
        compute["vcpu"] * compute["usage_amount"]
    )

    # Aggregate per resource + month — a single resource may have many hourly rows.
    agg = (
        compute.groupby(["resource_id", "billing_month"], dropna=False)
        .agg(
            cloud_provider=("cloud_provider", "first"),
            allocated_team=("allocated_team", "first"),
            service_category=("service_category", "first"),
            instance_type=("instance_type", "first"),
            nec_used=("nec_used", "sum"),
            nec_waste=("nec_waste", "sum"),
            avg_cost_per_vcpu_hour=("_cost_per_vcpu_hour", "mean"),
            latest_usage_date=("usage_date", "max"),
            **_optional_agg(compute),
        )
        .reset_index()
    )

    agg["_stale_days_since_activity"] = agg.apply(
        lambda row: _stale_days(row["latest_usage_date"], row.get("last_activity_at")),
        axis=1,
    )
    agg["_telemetry_backed"] = agg.apply(
        lambda row: (
            _telemetry_present(row)
            and (
                _metric_or_default(row.get("cpu_util_pct"), 101.0) <= 20.0
                or _metric_or_default(row.get("memory_util_pct"), 101.0) <= 25.0
                or _metric_or_default(row.get("disk_util_pct"), 101.0) <= 20.0
            )
            and (
                _metric_or_default(row.get("idle_hours"), 0.0) >= 72.0
                or _metric_or_default(row["_stale_days_since_activity"], 0.0) >= 7.0
            )
        ),
        axis=1,
    )
    agg = agg[
        (agg["avg_cost_per_vcpu_hour"] < threshold) | agg["_telemetry_backed"]
    ]

    # Apply min_dollars floor on the monthly aggregate, not on individual rows.
    # A resource paying $0.001/hr across 1000 hours = $1 total is still meaningful.
    agg = agg[agg["nec_used"] >= min_dollars]

    findings: list[WasteFinding] = []
    for _, row in agg.iterrows():
        confidence = min(
            0.98,
            base_confidence + (0.12 if bool(row["_telemetry_backed"]) else 0.0),
        )
        evidence = {
            "avg_cost_per_vcpu_hour": round(float(row["avg_cost_per_vcpu_hour"]), 6),
            "threshold": threshold,
            "signal_source": "telemetry+billing" if bool(row["_telemetry_backed"]) else "billing_proxy",
        }
        evidence.update(_telemetry_evidence(row, row["_stale_days_since_activity"]))
        findings.append(WasteFinding(
            resource_id=str(row["resource_id"]) if row["resource_id"] else "unknown",
            cloud_provider=str(row["cloud_provider"]),
            allocated_team=_safe_team(row["allocated_team"]),
            service_category=str(row["service_category"]),
            instance_type=_safe_str(row.get("instance_type")),
            waste_type="idle_compute",
            nec_waste=float(row["nec_waste"]),
            nec_used=float(row["nec_used"]),
            confidence=confidence,
            billing_month=str(row["billing_month"]),
            evidence=evidence,
            **_metadata_payload(row),
        ))
    return findings


# ---------------------------------------------------------------------------
# Detector 3 — zombie_resource
# ---------------------------------------------------------------------------

def detect_zombie_resources(
    df: pd.DataFrame,
    thresholds: dict,
) -> list[WasteFinding]:
    """
    Flag resources whose total nec_used for a billing month is above zero
    but below the zombie_monthly_nec_threshold.

    A resource costing less than $2/month is likely a forgotten or
    partially-decommissioned asset still incurring charges (e.g. an
    unattached EBS volume, a stopped-but-not-deleted VM, an empty S3 bucket
    with versioning history).

    Excludes rows with nec_used=0 (e.g. pure RI-fee rows) to avoid
    false-positives on commitment-only records.
    """
    _required_columns(df, ["resource_id", "billing_month", "nec_used", "nec_waste",
                            "cloud_provider", "allocated_team", "service_category",
                            "usage_date"])

    floor = thresholds["zombie_resource"]["monthly_nec_threshold"]
    min_dollars = thresholds["min_waste_dollars"]
    base_confidence = thresholds["confidence"]["zombie_resource"]

    # Exclude rows that are pure commitment-fee records (nec_used=0)
    active = df[df["nec_used"] > 0].copy()

    agg = (
        active.groupby(["resource_id", "billing_month"], dropna=False)
        .agg(
            cloud_provider=("cloud_provider", "first"),
            allocated_team=("allocated_team", "first"),
            service_category=("service_category", "first"),
            instance_type=("instance_type", "first"),
            monthly_nec_used=("nec_used", "sum"),
            nec_waste=("nec_waste", "sum"),
            latest_usage_date=("usage_date", "max"),
            **_optional_agg(active),
        )
        .reset_index()
    )

    agg["_stale_days_since_activity"] = agg.apply(
        lambda row: _stale_days(row["latest_usage_date"], row.get("last_activity_at")),
        axis=1,
    )
    agg["_telemetry_present"] = agg.apply(_telemetry_present, axis=1)
    agg["_telemetry_backed"] = agg.apply(
        lambda row: (
            bool(row["_telemetry_present"])
            and (_metric_or_default(row.get("cpu_util_pct"), 101.0) <= 5.0)
            and (_metric_or_default(row.get("memory_util_pct"), 101.0) <= 12.0)
            and (_metric_or_default(row.get("disk_util_pct"), 101.0) <= 12.0)
            and (
                _metric_or_default(row.get("idle_hours"), 0.0) >= 240.0
                or _metric_or_default(row["_stale_days_since_activity"], 0.0) >= 14.0
            )
        ),
        axis=1,
    )

    # When telemetry exists, require inactivity evidence before recommending deletion.
    # Older datasets without telemetry keep the original low-spend fallback.
    zombies = agg[
        (agg["monthly_nec_used"] > 0)
        & (agg["monthly_nec_used"] >= min_dollars)
        & (
            agg["_telemetry_backed"]
            | (
                ~agg["_telemetry_present"]
                & (agg["monthly_nec_used"] < floor)
            )
        )
    ]

    findings: list[WasteFinding] = []
    for _, row in zombies.iterrows():
        confidence = min(
            0.97,
            base_confidence + (0.12 if bool(row["_telemetry_backed"]) else -0.08),
        )
        evidence = {
            "monthly_nec_used": round(float(row["monthly_nec_used"]), 4),
            "threshold": floor,
            "signal_source": "telemetry" if bool(row["_telemetry_backed"]) else "cost_only_fallback",
        }
        evidence.update(_telemetry_evidence(row, row["_stale_days_since_activity"]))
        findings.append(WasteFinding(
            resource_id=str(row["resource_id"]) if row["resource_id"] else "unknown",
            cloud_provider=str(row["cloud_provider"]),
            allocated_team=_safe_team(row["allocated_team"]),
            service_category=str(row["service_category"]),
            instance_type=_safe_str(row.get("instance_type")),
            waste_type="zombie_resource",
            nec_waste=float(row["nec_waste"]),
            nec_used=float(row["monthly_nec_used"]),
            confidence=confidence,
            billing_month=str(row["billing_month"]),
            evidence=evidence,
            **_metadata_payload(row),
        ))
    return findings


# ---------------------------------------------------------------------------
# Detector 4 — underutilized_commitment
# ---------------------------------------------------------------------------

def detect_underutilized_commitments(
    df: pd.DataFrame,
    thresholds: dict,
) -> list[WasteFinding]:
    """
    Flag RI/SP commitments where the used fraction falls below the threshold.

    used_fraction = SUM(nec_used) / (SUM(nec_used) + SUM(nec_waste))

    A commitment that is <70% utilised is paying for capacity that is mostly
    sitting idle. This is distinct from unused_commitment (which flags billing
    rows where the cloud explicitly marks capacity as unused); this detector
    operates at the resource level across all related rows.
    """
    _required_columns(df, ["discount_type", "resource_id", "billing_month",
                            "nec_used", "nec_waste", "cloud_provider",
                            "allocated_team", "service_category"])

    used_threshold = thresholds["underutilized_commitment"]["used_fraction_threshold"]
    min_dollars = thresholds["min_waste_dollars"]
    confidence = thresholds["confidence"]["underutilized_commitment"]

    committed = df[df["discount_type"].isin(["ri", "sp"])].copy()
    if committed.empty:
        return []

    agg = (
        committed.groupby(["resource_id", "billing_month"], dropna=False)
        .agg(
            cloud_provider=("cloud_provider", "first"),
            allocated_team=("allocated_team", "first"),
            service_category=("service_category", "first"),
            instance_type=("instance_type", "first"),
            discount_type=("discount_type", "first"),
            total_nec_used=("nec_used", "sum"),
            total_nec_waste=("nec_waste", "sum"),
            **_optional_agg(committed),
        )
        .reset_index()
    )

    agg["_total"] = agg["total_nec_used"] + agg["total_nec_waste"]
    # Guard against division by zero
    agg["_used_fraction"] = agg["total_nec_used"] / agg["_total"].replace(0, float("nan"))

    underutil = agg[
        (agg["_used_fraction"] < used_threshold)
        & (agg["_total"] > min_dollars)
        & agg["_used_fraction"].notna()
    ]

    findings: list[WasteFinding] = []
    for _, row in underutil.iterrows():
        findings.append(WasteFinding(
            resource_id=str(row["resource_id"]) if row["resource_id"] else "unknown",
            cloud_provider=str(row["cloud_provider"]),
            allocated_team=_safe_team(row["allocated_team"]),
            service_category=str(row["service_category"]),
            instance_type=_safe_str(row.get("instance_type")),
            waste_type="underutilized_commitment",
            nec_waste=float(row["total_nec_waste"]),
            nec_used=float(row["total_nec_used"]),
            confidence=confidence,
            billing_month=str(row["billing_month"]),
            evidence={
                "used_fraction": round(float(row["_used_fraction"]), 4),
                "threshold": used_threshold,
                "discount_type": str(row["discount_type"]),
            },
            **_metadata_payload(row),
        ))
    return findings


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _deduplicate(findings: list[WasteFinding]) -> list[WasteFinding]:
    """
    When the same resource_id + billing_month appears in multiple detectors,
    keep only the finding with the highest confidence score.

    Rationale: a resource flagged as both 'zombie_resource' and 'idle_compute'
    should surface once with the stronger signal, not twice.
    """
    best: dict[tuple[str, str], WasteFinding] = {}
    for f in findings:
        key = (f["resource_id"], f["billing_month"])
        existing = best.get(key)
        if existing is None or f["confidence"] > existing["confidence"]:
            best[key] = f
    return list(best.values())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(
    df: pd.DataFrame,
    thresholds_path: str | Path = _DEFAULT_THRESHOLDS,
) -> list[WasteFinding]:
    """
    Run all four waste detectors and return a deduplicated list of findings,
    sorted by nec_waste descending.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain all columns from fct_unified_billing (or a compatible schema).
    thresholds_path : path to waste_thresholds.yml

    Returns
    -------
    list[WasteFinding] — empty list if no waste is found.
    """
    thresholds = _load_thresholds(thresholds_path)

    findings: list[WasteFinding] = []
    findings += detect_unused_commitments(df, thresholds)
    findings += detect_idle_compute(df, thresholds)
    findings += detect_zombie_resources(df, thresholds)
    findings += detect_underutilized_commitments(df, thresholds)

    deduped = _deduplicate(findings)
    return sorted(deduped, key=lambda f: f["nec_waste"], reverse=True)


# ---------------------------------------------------------------------------
# CLI — python -m intelligence.waste_detector
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    from pathlib import Path as _Path
    import duckdb

    parser = argparse.ArgumentParser(description="Run waste detection against DuckDB mart.")
    parser.add_argument("--db", default="finops_dbt.duckdb")
    parser.add_argument("--month", default=None)
    args = parser.parse_args()

    db = _Path(args.db)
    if not db.exists():
        raise FileNotFoundError(f"DuckDB not found at {db}. Run `dbt run` first.")

    con = duckdb.connect(str(db), read_only=True)
    query = "SELECT * FROM marts.fct_unified_billing"
    if args.month:
        query += f" WHERE billing_month = '{args.month}'"
    df = con.execute(query).df()
    con.close()

    results = run(df)
    print(f"\nWaste findings: {len(results)}")
    print(f"Total waste:    ${sum(f['nec_waste'] for f in results):.2f}\n")
    for f in results:
        print(
            f"  [{f['waste_type']:28s}]  "
            f"${f['nec_waste']:8.2f}  "
            f"team={f['allocated_team']:12s}  "
            f"cloud={f['cloud_provider']}  "
            f"confidence={f['confidence']:.2f}"
        )
