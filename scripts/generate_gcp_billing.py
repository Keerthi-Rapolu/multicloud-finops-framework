"""
Generate synthetic GCP Cloud Billing — Detailed Usage Export data.
- Hourly grain (usage_start_time / usage_end_time = 1-hour windows)
- Matches GCP Detailed Usage Cost Export to BigQuery schema
- CUD credits applied per-hour per resource (not daily aggregate)
- Labels as list-of-dicts matching real BQ export structure
- Covers Compute Engine, Cloud Storage, BigQuery, Cloud SQL
"""
import csv
import json
import random
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from scripts.config import GeneratorConfig

random.seed(42)

BILLING_ACCOUNT = "ABCDEF-123456-ABCDEF"

PROJECTS = {
    "platform-prod-001": {"name": "Platform Production", "number": "100000000001", "ancestry": "100000000001/222111000/123456789"},
    "data-eng-prod-002": {"name": "Data Eng Production", "number": "100000000002", "ancestry": "100000000002/222111000/123456789"},
    "app-prod-003":      {"name": "App Production",      "number": "100000000003", "ancestry": "100000000003/222111000/123456789"},
    "ml-prod-004":       {"name": "ML Production",       "number": "100000000004", "ancestry": "100000000004/222111000/123456789"},
}

# machine type → (vCPUs, memory_gb) for system_labels
MACHINE_SPECS = {
    "n2-standard-2":  (2,  8),
    "n2-standard-4":  (4,  16),
    "n2-standard-8":  (8,  32),
    "n2-highmem-8":   (8,  64),
    "n2-highmem-16":  (16, 128),
    "e2-standard-2":  (2,  8),
    "e2-standard-4":  (4,  16),
    "e2-micro":       (2,  1),
    "e2-small":       (2,  2),
}

REGIONS = {
    "us-central1":  "US",
    "europe-west1": "EU",
    "asia-east1":   "APAC",
    "us-east1":     "US",
}

# ---------------------------------------------------------------------------
# GCE VM catalog — (project, region, zone_suffix, machine_type, hourly_od_cost, team, env)
# Hourly on-demand prices approximate us-central1 Linux rates
# ---------------------------------------------------------------------------
GCE_VMS = [
    ("platform-prod-001", "us-central1",  "a", "n2-standard-2",  0.1826, "platform", "prod"),
    ("platform-prod-001", "us-central1",  "b", "n2-standard-4",  0.3652, "platform", "prod"),
    ("data-eng-prod-002", "europe-west1", "b", "n2-standard-8",  0.7307, "data-eng", "prod"),
    ("data-eng-prod-002", "europe-west1", "c", "n2-highmem-8",   0.9520, "data-eng", "prod"),
    ("app-prod-003",      "us-central1",  "a", "e2-standard-2",  0.1020, "frontend", "prod"),
    ("app-prod-003",      "us-central1",  "f", "e2-standard-4",  0.2040, "backend",  "prod"),
    ("app-prod-003",      "asia-east1",   "a", "e2-standard-2",  0.1140, "frontend", "prod"),
    ("ml-prod-004",       "us-central1",  "a", "n2-highmem-16",  1.9040, "ml",       "prod"),
    ("ml-prod-004",       "europe-west1", "b", "n2-standard-4",  0.3652, "ml",       "prod"),
    ("platform-prod-001", "us-central1",  "c", "e2-micro",       0.0175, "platform", "staging"),
    ("app-prod-003",      "us-central1",  "b", "e2-small",       0.0253, None,       "dev"),  # untagged
]

# GCS — billed daily even in Detailed export (storage is not hourly metered)
# We emit one row per bucket per day to match real behavior
GCS_BUCKETS = [
    ("platform-prod-001", "us-central1",  "platform-assets-prod",  "platform", "prod",    920.0,  "STANDARD"),
    ("data-eng-prod-002", "us-central1",  "data-lake-raw-prod",     "data-eng", "prod",    18500.0,"STANDARD"),
    ("data-eng-prod-002", "europe-west1", "data-lake-eu-prod",      "data-eng", "prod",    4200.0, "STANDARD"),
    ("data-eng-prod-002", "us-central1",  "data-lake-archive",      "data-eng", "prod",    31000.0,"NEARLINE"),
    ("app-prod-003",      "us-central1",  "app-static-assets",      "frontend", "prod",    380.0,  "STANDARD"),
    ("ml-prod-004",       "us-central1",  "ml-training-data",       "ml",       "prod",    2800.0, "STANDARD"),
    ("ml-prod-004",       "us-central1",  "ml-model-artifacts",     "ml",       "prod",    640.0,  "STANDARD"),
]

# BigQuery — analysis billed per query (sporadic hours), storage daily
BQ_DATASETS = [
    ("data-eng-prod-002", "us", "analytics_warehouse", "data-eng", "prod", 1.8,  12.4),
    ("data-eng-prod-002", "us", "raw_ingestion",        "data-eng", "prod", 0.6,  8.1),
    ("ml-prod-004",       "us", "ml_features",          "ml",       "prod", 2.4,  5.3),
    ("platform-prod-001", "us", "platform_logs",        "platform", "prod", 0.3,  1.2),
]

# Cloud SQL — hourly billing
CLOUD_SQL = [
    ("platform-prod-001", "us-central1",  "platform-db-prod",  "platform", "prod", "db-n1-standard-2", 0.3600),
    ("data-eng-prod-002", "us-central1",  "analytics-db-prod", "data-eng", "prod", "db-n1-highmem-4",  1.0200),
    ("app-prod-003",      "us-central1",  "app-db-prod",       "backend",  "prod", "db-n1-standard-4", 0.6400),
]

_DEFAULT_CUD_DISCOUNT = 0.37
_DEFAULT_SUD_DISCOUNT = 0.20
CUD_DISCOUNT = _DEFAULT_CUD_DISCOUNT  # kept for backward compat in row helpers
SUD_DISCOUNT = _DEFAULT_SUD_DISCOUNT
COST_CENTERS = {"platform": "cc100", "data-eng": "cc200", "frontend": "cc300",
                "backend": "cc400", "ml": "cc500"}

def _labels(team: str | None, env: str) -> str:
    if team is None:
        return "[]"
    return json.dumps([
        {"key": "team",        "value": team},
        {"key": "environment", "value": env},
        {"key": "cost_center", "value": COST_CENTERS.get(team, "cc999")},
    ])

def _cud_credits(cost: float) -> str:
    amount = round(-cost * CUD_DISCOUNT * random.uniform(0.97, 1.03), 8)
    return json.dumps([{
        "name":      "Committed Use Discount",
        "full_name": "Committed Use Discount: 1 Year",
        "id":        "committed-use-discount-1-year",
        "type":      "COMMITTED_USAGE_DISCOUNT",
        "amount":    amount,
    }])

def _sud_credits(cost: float) -> str:
    amount = round(-cost * SUD_DISCOUNT * random.uniform(0.90, 1.10), 8)
    return json.dumps([{
        "name":      "Sustained Use Discount",
        "full_name": "Sustained Use Discount",
        "id":        "sustained-use-discount",
        "type":      "SUSTAINED_USE_DISCOUNT",
        "amount":    amount,
    }])

def _sku_id() -> str:
    return uuid.uuid4().hex[:8].upper() + "-" + uuid.uuid4().hex[:6].upper()

def _base(project: str, service_id: str, service_desc: str,
          sku_id: str, sku_desc: str,
          hour_start: datetime, region: str,
          resource_name: str, resource_global: str,
          cost: float, usage_amount: float, usage_unit: str,
          credits: str, team, env: str,
          system_labels: str = "[]") -> dict:
    hour_end = hour_start + timedelta(hours=1)
    return {
        "billing_account_id":   BILLING_ACCOUNT,
        "service.id":           service_id,
        "service.description":  service_desc,
        "sku.id":               sku_id,
        "sku.description":      sku_desc,
        "usage_start_time":     hour_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "usage_end_time":       hour_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project.id":           project,
        "project.name":         PROJECTS[project]["name"],
        "project.number":       PROJECTS[project]["number"],
        "project.ancestry_numbers": PROJECTS[project]["ancestry"],
        "labels":               _labels(team, env),
        "system_labels":        system_labels,
        "location.region":      region,
        "location.zone":        "",
        "location.country":     REGIONS.get(region, "US"),
        "resource.name":        resource_name,
        "resource.global_name": resource_global,
        "cost":                 cost,
        "cost_at_list":         cost,
        "currency":             "USD",
        "usage.amount":         usage_amount,
        "usage.unit":           usage_unit,
        "usage.pricing_unit":   usage_unit,
        "credits":              credits,
        "invoice.month":        hour_start.strftime("%Y%m"),
        "cost_type":            "regular",
    }


def _gce_system_labels(machine: str) -> str:
    cores, mem_gb = MACHINE_SPECS.get(machine, (0, 0))
    return json.dumps([
        {"key": "compute_cores",            "value": str(cores)},
        {"key": "compute_memory",           "value": str(mem_gb)},
        {"key": "is_unused_reservation",    "value": "false"},
    ])


def gce_row(project: str, region: str, zone_sfx: str, machine: str,
            hourly_od: float, team, env: str,
            hour_start: datetime, credit_type: str | None) -> dict:
    zone = f"{region}-{zone_sfx}"
    cost = round(hourly_od * random.uniform(0.999, 1.001), 8)

    if credit_type == "CUD":
        credits = _cud_credits(cost)
    elif credit_type == "SUD":
        credits = _sud_credits(cost)
    else:
        credits = "[]"

    vm_name = f"vm-{machine.replace('-', '')}-{zone_sfx}"
    return _base(
        project, "6F81-5844-456A", "Compute Engine",
        _sku_id(), f"{machine} running in {region}",
        hour_start, zone,
        f"projects/{project}/zones/{zone}/instances/{vm_name}",
        f"//compute.googleapis.com/projects/{project}/zones/{zone}/instances/{vm_name}",
        cost, 1.0, "hour", credits, team, env,
        system_labels=_gce_system_labels(machine),
    )


def gcs_row(project: str, region: str, bucket: str, team, env: str,
            gb: float, storage_class: str, day_start: datetime) -> dict:
    # GCS storage is billed daily even in Detailed export — emit at midnight
    rate = 0.020 if storage_class == "STANDARD" else 0.010
    daily_cost = round((gb * rate / 30) * random.uniform(0.997, 1.003), 8)
    return _base(
        project, "95FF-2EF5-5EA1", "Cloud Storage",
        _sku_id(), f"{storage_class} Storage {region}",
        day_start, region,
        f"projects/{project}/buckets/{bucket}",
        f"//storage.googleapis.com/{bucket}",
        daily_cost,
        round(gb * random.uniform(0.9998, 1.0002), 4),
        "gibibyte month", "[]", team, env,
    )


def bq_analysis_row(project: str, region: str, dataset: str, team, env: str,
                    tb_scanned: float, hour_start: datetime) -> dict | None:
    # BQ queries happen sporadically — only ~30% of hours have a query
    if random.random() > 0.30:
        return None
    tb_this_hour = round(tb_scanned * random.uniform(0.02, 0.25), 6)
    cost = round(tb_this_hour * 5.0, 8)  # $5/TB on-demand
    return _base(
        project, "95FF-2EF5-5EA1", "BigQuery",
        _sku_id(), "Analysis",
        hour_start, region,
        f"projects/{project}/datasets/{dataset}",
        f"//bigquery.googleapis.com/projects/{project}/datasets/{dataset}",
        cost, tb_this_hour, "tebibyte", "[]", team, env,
    )


def bq_storage_row(project: str, region: str, dataset: str, team, env: str,
                   tb_storage: float, day_start: datetime) -> dict:
    # BQ active storage also billed daily in Detailed export
    daily_cost = round(tb_storage * 1024 * 0.020 / 30 * random.uniform(0.998, 1.002), 8)
    return _base(
        project, "95FF-2EF5-5EA1", "BigQuery",
        _sku_id(), "Active Storage",
        day_start, region,
        f"projects/{project}/datasets/{dataset}",
        f"//bigquery.googleapis.com/projects/{project}/datasets/{dataset}",
        daily_cost,
        round(tb_storage * 1024, 4),
        "gibibyte month", "[]", team, env,
    )


def sql_row(project: str, region: str, instance: str, team, env: str,
            tier: str, hourly_od: float, hour_start: datetime) -> dict:
    cost = round(hourly_od * random.uniform(0.999, 1.001), 8)
    return _base(
        project, "9662-B51E-5089", "Cloud SQL",
        _sku_id(), f"Cloud SQL for PostgreSQL: {tier} in {region}",
        hour_start, region,
        f"projects/{project}/instances/{instance}",
        f"//sqladmin.googleapis.com/projects/{project}/instances/{instance}",
        cost, 1.0, "hour", "[]", team, env,
    )


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------
def generate(billing_month: str = "2026-03", cfg: GeneratorConfig | None = None) -> None:
    if cfg is None:
        cfg = GeneratorConfig()

    year, month = map(int, billing_month.split("-"))
    month_start = datetime(year, month, 1)
    total_hours = 720
    step        = max(1, total_hours // cfg.sample_hours)
    hours       = [month_start + timedelta(hours=h) for h in range(0, total_hours, step)][:cfg.sample_hours]

    start_date = date(year, month, 1)
    next_m     = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
    day_starts = [datetime(year, month, 1) + timedelta(days=d)
                  for d in range((next_m - start_date).days)]

    # Build CUD/SUD pool from config ri_pct/sp_pct
    discount_pool = cfg.discount_pool()
    _credit_map   = {"ri": "CUD", "sp": "SUD", "on_demand": None}
    credit_types  = [_credit_map[random.choice(discount_pool)] for _ in GCE_VMS]

    rows = []

    # --- Compute Engine: hourly ---
    for i, (project, region, zone_sfx, machine, hourly_od, team, env) in enumerate(GCE_VMS):
        for hour in hours:
            if random.random() < 0.005:   # rare brief stop
                continue
            rows.append(gce_row(project, region, zone_sfx, machine, hourly_od,
                                team, env, hour, credit_types[i]))

    # --- Cloud SQL: hourly ---
    for project, region, instance, team, env, tier, hourly_od in CLOUD_SQL:
        for hour in hours:
            rows.append(sql_row(project, region, instance, team, env, tier, hourly_od, hour))

    # --- BigQuery Analysis: hourly (sporadic) ---
    for project, region, dataset, team, env, tb_scan, _ in BQ_DATASETS:
        for hour in hours:
            row = bq_analysis_row(project, region, dataset, team, env, tb_scan, hour)
            if row:
                rows.append(row)

    # --- GCS Storage + BQ Storage: daily ---
    for project, region, bucket, team, env, gb, storage_class in GCS_BUCKETS:
        for day_start in day_starts:
            rows.append(gcs_row(project, region, bucket, team, env, gb, storage_class, day_start))

    for project, region, dataset, team, env, _, tb_store in BQ_DATASETS:
        for day_start in day_starts:
            rows.append(bq_storage_row(project, region, dataset, team, env, tb_store, day_start))

    # Apply untagged_pct: strip labels from a fraction of tagged rows
    rng = random.Random(99)
    untagged_count = 0
    for row in rows:
        labels = json.loads(row["labels"]) if row["labels"] else []
        has_team = any(lbl.get("key") == "team" for lbl in labels)
        if has_team and rng.random() < cfg.untagged_pct:
            row["labels"] = "[]"
            untagged_count += 1

    out_dir  = Path(__file__).parent.parent / "data" / "synthetic" / "gcp"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"gcp_billing_{billing_month}.csv"

    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print(f"Generated {len(rows)} rows -> {out_file}  [config: {cfg.summary()}]")
    print(f"  Untagged rows: {untagged_count} ({untagged_count/len(rows):.1%})")
    services: dict[str, int] = {}
    for r in rows:
        s = r["service.description"]
        services[s] = services.get(s, 0) + 1
    for k, v in services.items():
        print(f"  {k}: {v} rows  ({'hourly' if k in ('Compute Engine','Cloud SQL') else 'hourly+daily'})")


if __name__ == "__main__":
    generate()
