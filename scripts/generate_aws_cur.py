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

# ---------------------------------------------------------------------------
# Resource catalog — fixed set of "real" resources in the account
# ---------------------------------------------------------------------------
INSTANCE_TYPES = {
    #              od_rate   norm  vcpu  memory
    "t3.micro":   {"od_rate": 0.0104,  "norm": 0.5,  "vcpu": 2,  "memory": "1 GiB"},
    "t3.small":   {"od_rate": 0.0208,  "norm": 1.0,  "vcpu": 2,  "memory": "2 GiB"},
    "t3.medium":  {"od_rate": 0.0416,  "norm": 2.0,  "vcpu": 2,  "memory": "4 GiB"},
    "t3.large":   {"od_rate": 0.0832,  "norm": 4.0,  "vcpu": 2,  "memory": "8 GiB"},
    "t3.xlarge":  {"od_rate": 0.1664,  "norm": 8.0,  "vcpu": 4,  "memory": "16 GiB"},
    "m5.large":   {"od_rate": 0.0960,  "norm": 4.0,  "vcpu": 2,  "memory": "8 GiB"},
    "m5.xlarge":  {"od_rate": 0.1920,  "norm": 8.0,  "vcpu": 4,  "memory": "16 GiB"},
    "m5.2xlarge": {"od_rate": 0.3840,  "norm": 16.0, "vcpu": 8,  "memory": "32 GiB"},
    "c5.large":   {"od_rate": 0.0850,  "norm": 4.0,  "vcpu": 2,  "memory": "4 GiB"},
    "c5.xlarge":  {"od_rate": 0.1700,  "norm": 8.0,  "vcpu": 4,  "memory": "8 GiB"},
    "r5.large":   {"od_rate": 0.1260,  "norm": 4.0,  "vcpu": 2,  "memory": "16 GiB"},
    "r5.xlarge":  {"od_rate": 0.2520,  "norm": 8.0,  "vcpu": 4,  "memory": "32 GiB"},
}

# Payer account for all member accounts (simulates AWS Org consolidated billing)
PAYER_ACCOUNT = "112233445566"

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
def build_resources(cfg: GeneratorConfig, cost_multiplier: float = 1.0) -> list[dict]:
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
            "od_rate": INSTANCE_TYPES[itype]["od_rate"] * cost_multiplier,
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
            "cost_rate": 0.023 * cost_multiplier,
        })

    # Shared infra — always untagged (no team owner); picked up by shared_cost.py
    resources.append({
        "type": "vpc_nat",
        "resource_id": f"arn:aws:ec2:us-east-1:{PAYER_ACCOUNT}:natgateway/nat-" + uuid.uuid4().hex[:17],
        "account": PAYER_ACCOUNT,
        "region": "us-east-1",
        "team": None,
        "env": "prod",
        "od_rate": 0.045 * cost_multiplier,
    })
    resources.append({
        "type": "vpc_vpn",
        "resource_id": f"arn:aws:ec2:us-east-1:{PAYER_ACCOUNT}:vpn-connection/vpn-" + uuid.uuid4().hex[:8],
        "account": PAYER_ACCOUNT,
        "region": "us-east-1",
        "team": None,
        "env": "prod",
        "od_rate": 0.05 * cost_multiplier,
    })
    resources.append({
        "type": "cloudtrail",
        "resource_id": f"arn:aws:cloudtrail:us-east-1:{PAYER_ACCOUNT}:trail/org-trail",
        "account": PAYER_ACCOUNT,
        "region": "us-east-1",
        "team": None,
        "env": "prod",
        "od_rate": 0.10 * cost_multiplier,
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
            "od_rate": rate * cost_multiplier,
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

    specs = INSTANCE_TYPES[itype]
    base = {
        "identity/LineItemId":              _line_item_id(),
        "identity/TimeInterval":            interval,
        "bill/PayerAccountId":              PAYER_ACCOUNT,
        "bill/BillingPeriodStartDate":      billing_start,
        "bill/BillingPeriodEndDate":        billing_end,
        "bill/BillingEntity":               "AWS",
        "lineItem/UsageAccountId":          account,
        "lineItem/LineItemType":            "",
        "lineItem/UsageStartDate":          hour_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lineItem/UsageEndDate":            hour_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lineItem/ProductCode":             "AmazonEC2",
        "lineItem/UsageType":               usage_type,
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
        "product/vcpu":                     specs["vcpu"],
        "product/memory":                   specs["memory"],
        "product/operatingSystem":          "Linux",
        "product/region":                   region,
        "product/servicecode":              "AmazonEC2",
        "resourceTags/user:Team":           team_tag,
        "resourceTags/user:Environment":    env_tag,
        "resourceTags/user:CostCenter":     cc_tag,
        "reservation/ReservationARN":                        "",
        "reservation/EffectiveCost":                         "",
        "reservation/RecurringFeeForUsage":                  "",
        "reservation/AmortizedUpfrontCostForUsage":          "",
        "reservation/UnusedQuantity":                        "",
        "reservation/UnusedAmortizedUpfrontFeeForBillingPeriod": "",
        "reservation/UnusedRecurringFee":                    "",
        "savingsPlan/SavingsPlanARN":                        "",
        "savingsPlan/SavingsPlanEffectiveCost":              "",
        "savingsPlan/SavingsPlanRate":                       "",
        "savingsPlan/UsedCommitment":                        "",
        "savingsPlan/TotalCommitmentToDate":                 "",
        "savingsPlan/RecurringCommitmentForBillingPeriod":   "",
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
    rate         = res.get("cost_rate", 0.023)
    monthly_cost = gb * rate
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
        "bill/PayerAccountId":              PAYER_ACCOUNT,
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
        "lineItem/UnblendedRate":           round(rate / (30 * 24), 10),
        "lineItem/UnblendedCost":           hourly_cost,
        "lineItem/BlendedRate":             round(rate / (30 * 24), 10),
        "lineItem/BlendedCost":             hourly_cost,
        "pricing/unit":                     "GB-Mo",
        "pricing/publicOnDemandRate":       rate,
        "pricing/publicOnDemandCost":       hourly_cost,
        "product/ProductName":              "Amazon Simple Storage Service",
        "product/instanceType":             "",
        "product/vcpu":                     "",
        "product/memory":                   "",
        "product/operatingSystem":          "",
        "product/region":                   region,
        "product/servicecode":              "AmazonS3",
        "resourceTags/user:Team":           team_tag,
        "resourceTags/user:Environment":    env_tag,
        "resourceTags/user:CostCenter":     cc_tag,
        "reservation/ReservationARN":                        "",
        "reservation/EffectiveCost":                         "",
        "reservation/RecurringFeeForUsage":                  "",
        "reservation/AmortizedUpfrontCostForUsage":          "",
        "reservation/UnusedQuantity":                        "",
        "reservation/UnusedAmortizedUpfrontFeeForBillingPeriod": "",
        "reservation/UnusedRecurringFee":                    "",
        "savingsPlan/SavingsPlanARN":                        "",
        "savingsPlan/SavingsPlanEffectiveCost":              "",
        "savingsPlan/SavingsPlanRate":                       "",
        "savingsPlan/UsedCommitment":                        "",
        "savingsPlan/TotalCommitmentToDate":                 "",
        "savingsPlan/RecurringCommitmentForBillingPeriod":   "",
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
        "bill/PayerAccountId":              PAYER_ACCOUNT,
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
        "product/vcpu":                     "",
        "product/memory":                   "",
        "product/operatingSystem":          "",
        "product/region":                   region,
        "product/servicecode":              "AmazonRDS",
        "resourceTags/user:Team":           team_tag,
        "resourceTags/user:Environment":    env_tag,
        "resourceTags/user:CostCenter":     cc_tag,
        "reservation/ReservationARN":                        "",
        "reservation/EffectiveCost":                         "",
        "reservation/RecurringFeeForUsage":                  "",
        "reservation/AmortizedUpfrontCostForUsage":          "",
        "reservation/UnusedQuantity":                        "",
        "reservation/UnusedAmortizedUpfrontFeeForBillingPeriod": "",
        "reservation/UnusedRecurringFee":                    "",
        "savingsPlan/SavingsPlanARN":                        "",
        "savingsPlan/SavingsPlanEffectiveCost":              "",
        "savingsPlan/SavingsPlanRate":                       "",
        "savingsPlan/UsedCommitment":                        "",
        "savingsPlan/TotalCommitmentToDate":                 "",
        "savingsPlan/RecurringCommitmentForBillingPeriod":   "",
    }


def ri_fee_row(res: dict, billing_start: str, billing_end: str,
               amortized_rate: float, total_hours: int) -> dict:
    """
    Monthly RIFee row — one per RI-covered resource per billing period.
    Carries unused RI capacity: hours reserved but never consumed.
    unused_qty ~ 10–25% of total reserved hours (realistic underutilisation).
    """
    rng_local   = random.Random(hash(res["resource_id"]) & 0xFFFFFFFF)
    unused_frac = rng_local.uniform(0.10, 0.25)
    unused_qty  = round(total_hours * unused_frac, 2)
    upfront_per_hr  = amortized_rate * 0.15   # 15% of amortized = upfront portion
    recurring_per_hr = amortized_rate * 0.85  # 85% = recurring portion
    itype   = res["instance_type"]
    account = res["account"]
    region  = res["region"]
    team_tag, env_tag, cc_tag = _tags(res.get("team"), res["env"])
    region_pfx = region.replace("-", "").upper()[:4]
    specs   = INSTANCE_TYPES[itype]

    return {
        "identity/LineItemId":              _line_item_id(),
        "identity/TimeInterval":            f"{billing_start}/{billing_end}",
        "bill/PayerAccountId":              PAYER_ACCOUNT,
        "bill/BillingPeriodStartDate":      billing_start,
        "bill/BillingPeriodEndDate":        billing_end,
        "bill/BillingEntity":               "AWS",
        "lineItem/UsageAccountId":          account,
        "lineItem/LineItemType":            "RIFee",
        "lineItem/UsageStartDate":          billing_start,
        "lineItem/UsageEndDate":            billing_end,
        "lineItem/ProductCode":             "AmazonEC2",
        "lineItem/UsageType":               f"{region_pfx}-HeavyUsage:{itype}",
        "lineItem/Operation":               "RunInstances",
        "lineItem/AvailabilityZone":        res.get("az", ""),
        "lineItem/ResourceId":              res["resource_id"],
        "lineItem/UsageAmount":             float(total_hours),
        "lineItem/NormalizationFactor":     specs["norm"],
        "lineItem/NormalizedUsageAmount":   specs["norm"] * total_hours,
        "lineItem/UnblendedRate":           0.0,
        "lineItem/UnblendedCost":           0.0,
        "lineItem/BlendedRate":             round(amortized_rate, 6),
        "lineItem/BlendedCost":             round(amortized_rate * total_hours, 6),
        "pricing/unit":                     "Hrs",
        "pricing/publicOnDemandRate":       round(res["od_rate"], 6),
        "pricing/publicOnDemandCost":       round(res["od_rate"] * total_hours, 6),
        "product/ProductName":              "Amazon Elastic Compute Cloud",
        "product/instanceType":             itype,
        "product/vcpu":                     specs["vcpu"],
        "product/memory":                   specs["memory"],
        "product/operatingSystem":          "Linux",
        "product/region":                   region,
        "product/servicecode":              "AmazonEC2",
        "resourceTags/user:Team":           team_tag,
        "resourceTags/user:Environment":    env_tag,
        "resourceTags/user:CostCenter":     cc_tag,
        "reservation/ReservationARN":                        res["ri_arn"],
        "reservation/EffectiveCost":                         round(amortized_rate * total_hours, 6),
        "reservation/RecurringFeeForUsage":                  round(recurring_per_hr * total_hours, 6),
        "reservation/AmortizedUpfrontCostForUsage":          round(upfront_per_hr * total_hours, 6),
        "reservation/UnusedQuantity":                        unused_qty,
        "reservation/UnusedAmortizedUpfrontFeeForBillingPeriod": round(upfront_per_hr * unused_qty, 6),
        "reservation/UnusedRecurringFee":                    round(recurring_per_hr * unused_qty, 6),
        "savingsPlan/SavingsPlanARN":                        "",
        "savingsPlan/SavingsPlanEffectiveCost":              "",
        "savingsPlan/SavingsPlanRate":                       "",
        "savingsPlan/UsedCommitment":                        "",
        "savingsPlan/TotalCommitmentToDate":                 "",
        "savingsPlan/RecurringCommitmentForBillingPeriod":   "",
    }


def sp_recurring_fee_row(res: dict, billing_start: str, billing_end: str,
                         sp_rate: float, used_hours: int, total_hours: int) -> dict:
    """
    Monthly SavingsPlanRecurringFee row — one per SP-covered resource per billing period.
    Carries SP commitment utilisation: how much of the monthly commitment was consumed.
    """
    monthly_commitment = round(sp_rate * total_hours, 6)
    used_commitment    = round(sp_rate * used_hours, 6)
    account = res["account"]
    region  = res["region"]
    itype   = res["instance_type"]
    team_tag, env_tag, cc_tag = _tags(res.get("team"), res["env"])
    region_pfx = region.replace("-", "").upper()[:4]
    specs   = INSTANCE_TYPES[itype]

    return {
        "identity/LineItemId":              _line_item_id(),
        "identity/TimeInterval":            f"{billing_start}/{billing_end}",
        "bill/PayerAccountId":              PAYER_ACCOUNT,
        "bill/BillingPeriodStartDate":      billing_start,
        "bill/BillingPeriodEndDate":        billing_end,
        "bill/BillingEntity":               "AWS",
        "lineItem/UsageAccountId":          account,
        "lineItem/LineItemType":            "SavingsPlanRecurringFee",
        "lineItem/UsageStartDate":          billing_start,
        "lineItem/UsageEndDate":            billing_end,
        "lineItem/ProductCode":             "AmazonEC2",
        "lineItem/UsageType":               f"{region_pfx}-BoxUsage:{itype}",
        "lineItem/Operation":               "RunInstances",
        "lineItem/AvailabilityZone":        res.get("az", ""),
        "lineItem/ResourceId":              res["resource_id"],
        "lineItem/UsageAmount":             float(total_hours),
        "lineItem/NormalizationFactor":     specs["norm"],
        "lineItem/NormalizedUsageAmount":   specs["norm"] * total_hours,
        "lineItem/UnblendedRate":           round(res["od_rate"], 6),
        "lineItem/UnblendedCost":           round(res["od_rate"] * total_hours, 6),
        "lineItem/BlendedRate":             round(sp_rate, 6),
        "lineItem/BlendedCost":             round(sp_rate * total_hours, 6),
        "pricing/unit":                     "Hrs",
        "pricing/publicOnDemandRate":       round(res["od_rate"], 6),
        "pricing/publicOnDemandCost":       round(res["od_rate"] * total_hours, 6),
        "product/ProductName":              "Amazon Elastic Compute Cloud",
        "product/instanceType":             itype,
        "product/vcpu":                     specs["vcpu"],
        "product/memory":                   specs["memory"],
        "product/operatingSystem":          "Linux",
        "product/region":                   region,
        "product/servicecode":              "AmazonEC2",
        "resourceTags/user:Team":           team_tag,
        "resourceTags/user:Environment":    env_tag,
        "resourceTags/user:CostCenter":     cc_tag,
        "reservation/ReservationARN":                        "",
        "reservation/EffectiveCost":                         "",
        "reservation/RecurringFeeForUsage":                  "",
        "reservation/AmortizedUpfrontCostForUsage":          "",
        "reservation/UnusedQuantity":                        "",
        "reservation/UnusedAmortizedUpfrontFeeForBillingPeriod": "",
        "reservation/UnusedRecurringFee":                    "",
        "savingsPlan/SavingsPlanARN":                        res["sp_arn"],
        "savingsPlan/SavingsPlanEffectiveCost":              round(sp_rate, 6),
        "savingsPlan/SavingsPlanRate":                       round(sp_rate, 6),
        "savingsPlan/UsedCommitment":                        used_commitment,
        "savingsPlan/TotalCommitmentToDate":                 monthly_commitment,
        "savingsPlan/RecurringCommitmentForBillingPeriod":   monthly_commitment,
    }


def _shared_infra_row(res: dict, product_code: str, usage_type: str, operation: str,
                      product_name: str, hour_start: datetime,
                      billing_start: str, billing_end: str) -> dict:
    """Generic row for untagged shared-infra services (VPC, CloudTrail)."""
    hour_end = hour_start + timedelta(hours=1)
    interval = f"{hour_start.strftime('%Y-%m-%dT%H:%M:%SZ')}/{hour_end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    cost = round(res["od_rate"] * random.uniform(0.98, 1.02), 6)
    return {
        "identity/LineItemId":              _line_item_id(),
        "identity/TimeInterval":            interval,
        "bill/PayerAccountId":              PAYER_ACCOUNT,
        "bill/BillingPeriodStartDate":      billing_start,
        "bill/BillingPeriodEndDate":        billing_end,
        "bill/BillingEntity":               "AWS",
        "lineItem/UsageAccountId":          res["account"],
        "lineItem/LineItemType":            "Usage",
        "lineItem/UsageStartDate":          hour_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lineItem/UsageEndDate":            hour_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lineItem/ProductCode":             product_code,
        "lineItem/UsageType":               usage_type,
        "lineItem/Operation":               operation,
        "lineItem/AvailabilityZone":        "",
        "lineItem/ResourceId":              res["resource_id"],
        "lineItem/UsageAmount":             1.0,
        "lineItem/NormalizationFactor":     "",
        "lineItem/NormalizedUsageAmount":   "",
        "lineItem/UnblendedRate":           round(res["od_rate"], 6),
        "lineItem/UnblendedCost":           cost,
        "lineItem/BlendedRate":             round(res["od_rate"], 6),
        "lineItem/BlendedCost":             cost,
        "pricing/unit":                     "Hrs",
        "pricing/publicOnDemandRate":       round(res["od_rate"], 6),
        "pricing/publicOnDemandCost":       cost,
        "product/ProductName":              product_name,
        "product/instanceType":             "",
        "product/vcpu":                     "",
        "product/memory":                   "",
        "product/operatingSystem":          "",
        "product/region":                   res["region"],
        "product/servicecode":              product_code,
        # No team tags — these are shared infra, deliberately untagged
        "resourceTags/user:Team":           "",
        "resourceTags/user:Environment":    "",
        "resourceTags/user:CostCenter":     "",
        "reservation/ReservationARN":                        "",
        "reservation/EffectiveCost":                         "",
        "reservation/RecurringFeeForUsage":                  "",
        "reservation/AmortizedUpfrontCostForUsage":          "",
        "reservation/UnusedQuantity":                        "",
        "reservation/UnusedAmortizedUpfrontFeeForBillingPeriod": "",
        "reservation/UnusedRecurringFee":                    "",
        "savingsPlan/SavingsPlanARN":                        "",
        "savingsPlan/SavingsPlanEffectiveCost":              "",
        "savingsPlan/SavingsPlanRate":                       "",
        "savingsPlan/UsedCommitment":                        "",
        "savingsPlan/TotalCommitmentToDate":                 "",
        "savingsPlan/RecurringCommitmentForBillingPeriod":   "",
    }


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------
def generate(billing_month: str = "2026-03", cfg: GeneratorConfig | None = None) -> None:
    if cfg is None:
        cfg = GeneratorConfig()

    _seed = cfg.seed if cfg.seed is not None else (hash(billing_month) & 0xFFFF_FFFF)
    random.seed(_seed)

    year, month = map(int, billing_month.split("-"))
    billing_start = f"{year}-{month:02d}-01T00:00:00Z"
    next_month    = datetime(year, month, 1) + timedelta(days=32)
    billing_end   = f"{next_month.year}-{next_month.month:02d}-01T00:00:00Z"

    month_start  = datetime(year, month, 1)
    next_m_start = datetime(next_month.year, next_month.month, 1)
    total_hours  = int((next_m_start - month_start).total_seconds() // 3600)
    step         = max(1, total_hours // cfg.sample_hours)
    hours        = [month_start + timedelta(hours=h) for h in range(0, total_hours, step)][:cfg.sample_hours]

    resources = build_resources(cfg, cost_multiplier=cfg.cost_multiplier)

    # Guarantee exactly round(n * untagged_pct) resources are untagged.
    # Probabilistic per-resource check can produce 0 untagged with certain seeds.
    rng = random.Random(99)
    tagged = [r for r in resources if r.get("team") is not None]
    n_untagged = round(len(tagged) * cfg.untagged_pct)
    for res in rng.sample(tagged, n_untagged):
        res["team"] = None

    rows = []
    # Track per-EC2-resource stats for monthly fee rows
    ec2_hour_counts: dict[str, dict] = {}   # resource_id → {used, discount, amortized, sp_rate}

    for res in resources:
        for hour in hours:
            if res["type"] == "ec2":
                if random.random() < 0.02:
                    continue
                row = ec2_row(res, hour, billing_start, billing_end)
                rows.append(row)
                rid = res["resource_id"]
                if rid not in ec2_hour_counts:
                    ec2_hour_counts[rid] = {
                        "res": res, "used": 0,
                        "amortized": float(row.get("reservation/EffectiveCost") or 0),
                        "sp_rate":   float(row.get("savingsPlan/SavingsPlanRate") or 0),
                    }
                ec2_hour_counts[rid]["used"] += 1
            elif res["type"] == "s3":
                rows.append(s3_row(res, hour, billing_start, billing_end))
            elif res["type"] == "rds":
                rows.append(rds_row(res, hour, billing_start, billing_end))
            elif res["type"] == "vpc_nat":
                rows.append(_shared_infra_row(
                    res, "AmazonVPC", "USE1-NatGateway-Hours", "NatGateway",
                    "Amazon Virtual Private Cloud", hour, billing_start, billing_end,
                ))
            elif res["type"] == "vpc_vpn":
                rows.append(_shared_infra_row(
                    res, "AmazonVPC", "USE1-VPN-Usage-Hours", "CreateVpnConnection",
                    "Amazon Virtual Private Cloud", hour, billing_start, billing_end,
                ))
            elif res["type"] == "cloudtrail":
                rows.append(_shared_infra_row(
                    res, "AWSCloudTrail", "USE1-DigestEvent", "LookupEvents",
                    "AWS CloudTrail", hour, billing_start, billing_end,
                ))

    # Monthly fee rows: one RIFee or SavingsPlanRecurringFee per RI/SP EC2 resource
    for rid, info in ec2_hour_counts.items():
        res = info["res"]
        used = info["used"]
        if res["discount"] == "ri" and info["amortized"] > 0:
            rows.append(ri_fee_row(res, billing_start, billing_end,
                                   info["amortized"], cfg.sample_hours))
        elif res["discount"] == "sp" and info["sp_rate"] > 0:
            rows.append(sp_recurring_fee_row(res, billing_start, billing_end,
                                             info["sp_rate"], used, cfg.sample_hours))

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
