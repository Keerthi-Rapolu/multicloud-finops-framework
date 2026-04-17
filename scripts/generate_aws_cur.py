"""
Generate synthetic AWS Cost and Usage Report (CUR) data.
- Hourly grain (one row per resource per hour)
- Realistic line item types: Usage, DiscountedUsage (RI), SavingsPlanCoveredUsage (SP)
- Real EC2/S3/RDS pricing (us-east-1, Linux on-demand)
- Correct RI/SP column semantics: DiscountedUsage has unblended=0, effective cost = amortized
"""
import csv
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from scripts.config import GeneratorConfig, SCENARIOS

random.seed(42)

# ---------------------------------------------------------------------------
# Resource catalog — fixed set of "real" resources in the account
# ---------------------------------------------------------------------------
INSTANCE_TYPES = {
    "t3.micro":   {"od_rate": 0.0104,  "norm": 0.5},
    "t3.small":   {"od_rate": 0.0208,  "norm": 1.0},
    "t3.medium":  {"od_rate": 0.0416,  "norm": 2.0},
    "t3.large":   {"od_rate": 0.0832,  "norm": 4.0},
    "t3.xlarge":  {"od_rate": 0.1664,  "norm": 8.0},
    "m5.large":   {"od_rate": 0.0960,  "norm": 4.0},
    "m5.xlarge":  {"od_rate": 0.1920,  "norm": 8.0},
    "m5.2xlarge": {"od_rate": 0.3840,  "norm": 16.0},
    "c5.large":   {"od_rate": 0.0850,  "norm": 4.0},
    "c5.xlarge":  {"od_rate": 0.1700,  "norm": 8.0},
    "r5.large":   {"od_rate": 0.1260,  "norm": 4.0},
    "r5.xlarge":  {"od_rate": 0.2520,  "norm": 8.0},
}

ACCOUNTS = {
    "112233445566": "platform-prod",
    "223344556677": "data-eng-prod",
    "334455667788": "app-prod",
}

REGIONS_AZ = {
    "us-east-1":      ["us-east-1a", "us-east-1b", "us-east-1c"],
    "us-west-2":      ["us-west-2a", "us-west-2b"],
    "eu-west-1":      ["eu-west-1a", "eu-west-1b"],
}

TEAMS = ["platform", "data-eng", "frontend", "backend", "ml"]
ENVS  = ["prod", "prod", "prod", "staging", "dev"]   # prod-weighted

# Default discount pool — overridden per-run by GeneratorConfig.discount_pool()
_DEFAULT_DISCOUNT_POOL = ["on_demand", "on_demand", "on_demand", "ri", "ri", "sp"]

def _instance_id() -> str:
    return "i-0" + uuid.uuid4().hex[:16]

def _s3_bucket_arn(account: str, name: str) -> str:
    return f"arn:aws:s3:::{name}"

def _rds_arn(account: str, region: str, name: str) -> str:
    return f"arn:aws:rds:{region}:{account}:db:{name}"

def _ri_arn(account: str, region: str) -> str:
    return f"arn:aws:ec2:{region}:{account}:reserved-instances/{uuid.uuid4()}"

def _sp_arn(account: str) -> str:
    return f"arn:aws:savingsplans::{account}:savingsplan/{uuid.uuid4()}"

def _line_item_id() -> str:
    return uuid.uuid4().hex

# ---------------------------------------------------------------------------
# Build a resource registry once — deterministic "fleet"
# ---------------------------------------------------------------------------
def build_resources(cfg: GeneratorConfig) -> list[dict]:
    resources = []
    discount_pool = cfg.discount_pool()

    # EC2 instances (14 total)
    ec2_specs = [
        ("t3.medium", "platform", "prod",    "112233445566", "us-east-1"),
        ("t3.medium", "platform", "prod",    "112233445566", "us-east-1"),
        ("m5.large",  "backend",  "prod",    "334455667788", "us-east-1"),
        ("m5.large",  "backend",  "prod",    "334455667788", "us-east-1"),
        ("m5.xlarge", "backend",  "prod",    "334455667788", "us-east-1"),
        ("c5.large",  "data-eng", "prod",    "223344556677", "us-west-2"),
        ("c5.xlarge", "data-eng", "prod",    "223344556677", "us-west-2"),
        ("r5.large",  "ml",       "prod",    "223344556677", "us-west-2"),
        ("r5.xlarge", "ml",       "prod",    "223344556677", "us-west-2"),
        ("t3.large",  "frontend", "prod",    "334455667788", "eu-west-1"),
        ("t3.large",  "frontend", "prod",    "334455667788", "eu-west-1"),
        ("t3.small",  "platform", "staging", "112233445566", "us-east-1"),
        ("t3.micro",  "frontend", "dev",     "334455667788", "us-east-1"),
        ("m5.2xlarge","data-eng", "prod",    "223344556677", "us-west-2"),
    ]
    for itype, team, env, account, region in ec2_specs:
        discount = random.choice(discount_pool)
        az_list = REGIONS_AZ[region]
        resources.append({
            "type": "ec2",
            "instance_type": itype,
            "resource_id": _instance_id(),
            "account": account,
            "region": region,
            "az": random.choice(az_list),
            "team": team,
            "env": env,
            "discount": discount,
            "ri_arn": _ri_arn(account, region) if discount == "ri" else "",
            "sp_arn": _sp_arn(account) if discount == "sp" else "",
            "od_rate": INSTANCE_TYPES[itype]["od_rate"],
            "norm_factor": INSTANCE_TYPES[itype]["norm"],
        })

    # S3 buckets (daily cost, spread as hourly fraction)
    s3_specs = [
        ("platform-assets-bucket",  "platform", "prod",    "112233445566", "us-east-1", 420.0),
        ("data-lake-raw",           "data-eng", "prod",    "223344556677", "us-west-2", 1850.0),
        ("data-lake-processed",     "data-eng", "prod",    "223344556677", "us-west-2", 940.0),
        ("app-static-assets",       "frontend", "prod",    "334455667788", "us-east-1", 310.0),
        ("ml-model-artifacts",      "ml",       "prod",    "223344556677", "us-west-2", 780.0),
        ("dev-scratch-bucket",      "backend",  "dev",     "334455667788", "us-east-1", 55.0),
    ]
    for name, team, env, account, region, gb in s3_specs:
        resources.append({
            "type": "s3",
            "bucket_name": name,
            "resource_id": _s3_bucket_arn(account, name),
            "account": account,
            "region": region,
            "team": team,
            "env": env,
            "storage_gb": gb,
        })

    # RDS instances
    rds_specs = [
        ("db.t3.medium",  "platform-db",  "platform", "prod",    "112233445566", "us-east-1", 0.068),
        ("db.r5.large",   "analytics-db", "data-eng", "prod",    "223344556677", "us-west-2", 0.240),
        ("db.m5.large",   "app-db",       "backend",  "prod",    "334455667788", "us-east-1", 0.171),
    ]
    for itype, name, team, env, account, region, rate in rds_specs:
        resources.append({
            "type": "rds",
            "instance_type": itype,
            "db_name": name,
            "resource_id": _rds_arn(account, region, name),
            "account": account,
            "region": region,
            "team": team,
            "env": env,
            "od_rate": rate,
        })

    return resources

# ---------------------------------------------------------------------------
# Row generators per resource type
# ---------------------------------------------------------------------------
def _tags(team: str | None, env: str) -> tuple[str, str, str]:
    if team is None:
        return ("", "", "")
    cost_centers = {"platform": "CC100", "data-eng": "CC200", "frontend": "CC300",
                    "backend": "CC400", "ml": "CC500"}
    return (team, env, cost_centers.get(team, "CC999"))


def ec2_row(res: dict, hour_start: datetime, billing_start: str, billing_end: str) -> dict:
    od_rate   = res["od_rate"]
    norm      = res["norm_factor"]
    region    = res["region"]
    account   = res["account"]
    itype     = res["instance_type"]
    discount  = res["discount"]
    team_tag, env_tag, cc_tag = _tags(res.get("team"), res["env"])

    hour_end   = hour_start + timedelta(hours=1)
    interval   = f"{hour_start.strftime('%Y-%m-%dT%H:%M:%SZ')}/{hour_end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    region_pfx = region.replace("-", "").upper()[:4]  # e.g. USE1
    usage_type = f"{region_pfx}-BoxUsage:{itype}"

    base = {
        "identity/LineItemId":              _line_item_id(),
        "identity/TimeInterval":            interval,
        "bill/BillingPeriodStartDate":      billing_start,
        "bill/BillingPeriodEndDate":        billing_end,
        "bill/BillingEntity":               "AWS",
        "lineItem/UsageAccountId":          account,
        "lineItem/LineItemType":            "",
        "lineItem/UsageStartDate":          hour_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lineItem/UsageEndDate":            hour_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lineItem/ProductCode":             "AmazonEC2",
        "lineItem/UsageType":              usage_type,
        "lineItem/Operation":               "RunInstances",
        "lineItem/AvailabilityZone":        res["az"],
        "lineItem/ResourceId":              res["resource_id"],
        "lineItem/UsageAmount":             1.0,
        "lineItem/NormalizationFactor":     norm,
        "lineItem/NormalizedUsageAmount":   norm * 1.0,
        "lineItem/UnblendedRate":           "",
        "lineItem/UnblendedCost":           "",
        "lineItem/BlendedRate":             "",
        "lineItem/BlendedCost":             "",
        "pricing/unit":                     "Hrs",
        "pricing/publicOnDemandRate":       round(od_rate, 6),
        "pricing/publicOnDemandCost":       round(od_rate, 6),
        "product/ProductName":              "Amazon Elastic Compute Cloud",
        "product/instanceType":             itype,
        "product/operatingSystem":          "Linux",
        "product/region":                   region,
        "product/servicecode":              "AmazonEC2",
        "resourceTags/user:Team":           team_tag,
        "resourceTags/user:Environment":    env_tag,
        "resourceTags/user:CostCenter":     cc_tag,
        "reservation/ReservationARN":       "",
        "reservation/EffectiveCost":        "",
        "reservation/RecurringFeeForUsage": "",
        "reservation/AmortizedUpfrontCostForUsage": "",
        "savingsPlan/SavingsPlanARN":       "",
        "savingsPlan/SavingsPlanEffectiveCost": "",
        "savingsPlan/SavingsPlanRate":      "",
        "savingsPlan/UsedCommitment":       "",
    }

    if discount == "on_demand":
        base["lineItem/LineItemType"]  = "Usage"
        base["lineItem/UnblendedRate"] = round(od_rate, 6)
        base["lineItem/UnblendedCost"] = round(od_rate, 6)
        base["lineItem/BlendedRate"]   = round(od_rate * random.uniform(0.95, 1.05), 6)
        base["lineItem/BlendedCost"]   = round(od_rate * random.uniform(0.95, 1.05), 6)

    elif discount == "ri":
        # RI-covered: unblended = 0, effective = amortized (~30-45% of OD)
        amortized = round(od_rate * random.uniform(0.55, 0.70), 6)
        base["lineItem/LineItemType"]                   = "DiscountedUsage"
        base["lineItem/UnblendedRate"]                  = 0.0
        base["lineItem/UnblendedCost"]                  = 0.0
        base["lineItem/BlendedRate"]                    = round(amortized, 6)
        base["lineItem/BlendedCost"]                    = round(amortized, 6)
        base["reservation/ReservationARN"]              = res["ri_arn"]
        base["reservation/EffectiveCost"]               = amortized
        base["reservation/RecurringFeeForUsage"]        = round(amortized * 0.85, 6)
        base["reservation/AmortizedUpfrontCostForUsage"] = round(amortized * 0.15, 6)

    elif discount == "sp":
        # SP-covered: unblended = OD rate, SP effective = discounted (~25-35% off)
        sp_rate = round(od_rate * random.uniform(0.65, 0.75), 6)
        base["lineItem/LineItemType"]                  = "SavingsPlanCoveredUsage"
        base["lineItem/UnblendedRate"]                 = round(od_rate, 6)
        base["lineItem/UnblendedCost"]                 = round(od_rate, 6)
        base["lineItem/BlendedRate"]                   = round(sp_rate, 6)
        base["lineItem/BlendedCost"]                   = round(sp_rate, 6)
        base["savingsPlan/SavingsPlanARN"]             = res["sp_arn"]
        base["savingsPlan/SavingsPlanRate"]            = sp_rate
        base["savingsPlan/SavingsPlanEffectiveCost"]   = sp_rate
        base["savingsPlan/UsedCommitment"]             = round(sp_rate, 6)

    return base


def s3_row(res: dict, hour_start: datetime, billing_start: str, billing_end: str) -> dict:
    gb          = res["storage_gb"]
    # S3 Standard: $0.023/GB-month -> hourly fraction
    monthly_cost = gb * 0.023
    hourly_cost  = round(monthly_cost / (30 * 24) * random.uniform(0.98, 1.02), 8)
    region       = res["region"]
    account      = res["account"]
    team_tag, env_tag, cc_tag = _tags(res.get("team"), res["env"])
    region_pfx   = region.replace("-", "").upper()[:4]
    hour_end     = hour_start + timedelta(hours=1)
    interval     = f"{hour_start.strftime('%Y-%m-%dT%H:%M:%SZ')}/{hour_end.strftime('%Y-%m-%dT%H:%M:%SZ')}"

    return {
        "identity/LineItemId":              _line_item_id(),
        "identity/TimeInterval":            interval,
        "bill/BillingPeriodStartDate":      billing_start,
        "bill/BillingPeriodEndDate":        billing_end,
        "bill/BillingEntity":               "AWS",
        "lineItem/UsageAccountId":          account,
        "lineItem/LineItemType":            "Usage",
        "lineItem/UsageStartDate":          hour_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lineItem/UsageEndDate":            hour_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lineItem/ProductCode":             "AmazonS3",
        "lineItem/UsageType":               f"{region_pfx}-TimedStorage-ByteHrs",
        "lineItem/Operation":               "StandardStorage",
        "lineItem/AvailabilityZone":        "",
        "lineItem/ResourceId":              res["resource_id"],
        "lineItem/UsageAmount":             round(gb * random.uniform(0.999, 1.001), 4),
        "lineItem/NormalizationFactor":     "",
        "lineItem/NormalizedUsageAmount":   "",
        "lineItem/UnblendedRate":           round(0.023 / (30 * 24), 10),
        "lineItem/UnblendedCost":           hourly_cost,
        "lineItem/BlendedRate":             round(0.023 / (30 * 24), 10),
        "lineItem/BlendedCost":             hourly_cost,
        "pricing/unit":                     "GB-Mo",
        "pricing/publicOnDemandRate":       0.023,
        "pricing/publicOnDemandCost":       hourly_cost,
        "product/ProductName":              "Amazon Simple Storage Service",
        "product/instanceType":             "",
        "product/operatingSystem":          "",
        "product/region":                   region,
        "product/servicecode":              "AmazonS3",
        "resourceTags/user:Team":           team_tag,
        "resourceTags/user:Environment":    env_tag,
        "resourceTags/user:CostCenter":     cc_tag,
        "reservation/ReservationARN":       "",
        "reservation/EffectiveCost":        "",
        "reservation/RecurringFeeForUsage": "",
        "reservation/AmortizedUpfrontCostForUsage": "",
        "savingsPlan/SavingsPlanARN":       "",
        "savingsPlan/SavingsPlanEffectiveCost": "",
        "savingsPlan/SavingsPlanRate":      "",
        "savingsPlan/UsedCommitment":       "",
    }


def rds_row(res: dict, hour_start: datetime, billing_start: str, billing_end: str) -> dict:
    od_rate  = res["od_rate"]
    region   = res["region"]
    account  = res["account"]
    itype    = res["instance_type"]
    team_tag, env_tag, cc_tag = _tags(res.get("team"), res["env"])
    region_pfx = region.replace("-", "").upper()[:4]
    hour_end   = hour_start + timedelta(hours=1)
    interval   = f"{hour_start.strftime('%Y-%m-%dT%H:%M:%SZ')}/{hour_end.strftime('%Y-%m-%dT%H:%M:%SZ')}"

    return {
        "identity/LineItemId":              _line_item_id(),
        "identity/TimeInterval":            interval,
        "bill/BillingPeriodStartDate":      billing_start,
        "bill/BillingPeriodEndDate":        billing_end,
        "bill/BillingEntity":               "AWS",
        "lineItem/UsageAccountId":          account,
        "lineItem/LineItemType":            "Usage",
        "lineItem/UsageStartDate":          hour_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lineItem/UsageEndDate":            hour_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lineItem/ProductCode":             "AmazonRDS",
        "lineItem/UsageType":               f"{region_pfx}-InstanceUsage:{itype}",
        "lineItem/Operation":               "CreateDBInstance:0002",
        "lineItem/AvailabilityZone":        "",
        "lineItem/ResourceId":              res["resource_id"],
        "lineItem/UsageAmount":             1.0,
        "lineItem/NormalizationFactor":     "",
        "lineItem/NormalizedUsageAmount":   "",
        "lineItem/UnblendedRate":           round(od_rate, 6),
        "lineItem/UnblendedCost":           round(od_rate * random.uniform(0.999, 1.001), 6),
        "lineItem/BlendedRate":             round(od_rate, 6),
        "lineItem/BlendedCost":             round(od_rate * random.uniform(0.999, 1.001), 6),
        "pricing/unit":                     "Hrs",
        "pricing/publicOnDemandRate":       od_rate,
        "pricing/publicOnDemandCost":       round(od_rate, 6),
        "product/ProductName":              "Amazon Relational Database Service",
        "product/instanceType":             itype,
        "product/operatingSystem":          "",
        "product/region":                   region,
        "product/servicecode":              "AmazonRDS",
        "resourceTags/user:Team":           team_tag,
        "resourceTags/user:Environment":    env_tag,
        "resourceTags/user:CostCenter":     cc_tag,
        "reservation/ReservationARN":       "",
        "reservation/EffectiveCost":        "",
        "reservation/RecurringFeeForUsage": "",
        "reservation/AmortizedUpfrontCostForUsage": "",
        "savingsPlan/SavingsPlanARN":       "",
        "savingsPlan/SavingsPlanEffectiveCost": "",
        "savingsPlan/SavingsPlanRate":      "",
        "savingsPlan/UsedCommitment":       "",
    }


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------
def generate(billing_month: str = "2026-03", cfg: GeneratorConfig | None = None) -> None:
    if cfg is None:
        cfg = GeneratorConfig()

    year, month = map(int, billing_month.split("-"))
    billing_start = f"{year}-{month:02d}-01T00:00:00Z"
    next_month    = datetime(year, month, 1) + timedelta(days=32)
    billing_end   = f"{next_month.year}-{next_month.month:02d}-01T00:00:00Z"

    month_start = datetime(year, month, 1)
    total_hours = 720
    step        = max(1, total_hours // cfg.sample_hours)
    hours       = [month_start + timedelta(hours=h) for h in range(0, total_hours, step)][:cfg.sample_hours]

    resources = build_resources(cfg)

    # Apply untagged_pct — randomly nullify team for that fraction of resources
    rng = random.Random(99)  # separate seed so main data isn't affected
    for res in resources:
        if res.get("team") is not None and rng.random() < cfg.untagged_pct:
            res["team"] = None

    rows = []

    for res in resources:
        for hour in hours:
            # EC2: skip ~2% of hours to simulate brief stops/restarts
            if res["type"] == "ec2":
                if random.random() < 0.02:
                    continue
                rows.append(ec2_row(res, hour, billing_start, billing_end))
            elif res["type"] == "s3":
                rows.append(s3_row(res, hour, billing_start, billing_end))
            elif res["type"] == "rds":
                rows.append(rds_row(res, hour, billing_start, billing_end))

    out_dir  = Path(__file__).parent.parent / "data" / "synthetic" / "aws"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"aws_cur_{billing_month}.csv"

    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    untagged = sum(1 for r in rows if not r.get("resourceTags/user:Team"))
    print(f"Generated {len(rows)} rows -> {out_file}")
    types = {}
    for r in rows:
        t = r["lineItem/LineItemType"]
        types[t] = types.get(t, 0) + 1
    for k, v in types.items():
        print(f"  {k}: {v} rows")
    print(f"  untagged rows: {untagged} ({untagged/len(rows):.0%})")


if __name__ == "__main__":
    generate()
