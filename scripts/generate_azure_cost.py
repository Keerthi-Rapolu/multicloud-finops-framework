"""
Generate synthetic Azure Cost Management Export data (Amortized view).
- Daily grain (one row per resource per day)
- Amortized cost: RI/savings plan upfront fees spread daily, not lump-sum on purchase date
- Realistic meter categories, VM sizes, resource IDs, subscription structure
- ChargeType: Usage (majority), Purchase (marketplace/reservation fees)
"""
import csv
import json
import random
import uuid
from datetime import date, timedelta
from pathlib import Path

from scripts.config import GeneratorConfig

random.seed(42)

# ---------------------------------------------------------------------------
# Subscription & resource catalog
# ---------------------------------------------------------------------------
SUBSCRIPTIONS = {
    "a1b2c3d4-0001-0001-0001-000000000001": "platform-prod-sub",
    "a1b2c3d4-0002-0002-0002-000000000002": "data-eng-prod-sub",
    "a1b2c3d4-0003-0003-0003-000000000003": "app-prod-sub",
}

VM_SIZES = {
    # (meter_name, daily_od_cost_usd)
    "Standard_B2s":      ("B2s",    2.016),
    "Standard_D2s_v3":   ("D2s v3", 4.032),
    "Standard_D4s_v3":   ("D4s v3", 8.064),
    "Standard_E4s_v3":   ("E4s v3", 8.736),
    "Standard_F4s_v2":   ("F4s v2", 6.048),
    "Standard_D8s_v3":   ("D8s v3", 16.128),
    "Standard_E8s_v3":   ("E8s v3", 17.472),
}

# Resource definitions: (sku, team, env, subscription_id, resource_group, region)
VM_RESOURCES = [
    ("Standard_D2s_v3", "platform", "prod",    "a1b2c3d4-0001-0001-0001-000000000001", "rg-platform-prod",  "eastus"),
    ("Standard_D2s_v3", "platform", "prod",    "a1b2c3d4-0001-0001-0001-000000000001", "rg-platform-prod",  "eastus"),
    ("Standard_D4s_v3", "backend",  "prod",    "a1b2c3d4-0003-0003-0003-000000000003", "rg-app-prod",       "eastus"),
    ("Standard_E4s_v3", "data-eng", "prod",    "a1b2c3d4-0002-0002-0002-000000000002", "rg-data-prod",      "westeurope"),
    ("Standard_E8s_v3", "data-eng", "prod",    "a1b2c3d4-0002-0002-0002-000000000002", "rg-data-prod",      "westeurope"),
    ("Standard_F4s_v2", "ml",       "prod",    "a1b2c3d4-0002-0002-0002-000000000002", "rg-ml-prod",        "westeurope"),
    ("Standard_D8s_v3", "ml",       "prod",    "a1b2c3d4-0002-0002-0002-000000000002", "rg-ml-prod",        "westeurope"),
    ("Standard_B2s",    "frontend", "prod",    "a1b2c3d4-0003-0003-0003-000000000003", "rg-app-prod",       "southeastasia"),
    ("Standard_B2s",    "frontend", "staging", "a1b2c3d4-0003-0003-0003-000000000003", "rg-app-staging",    "southeastasia"),
    ("Standard_D2s_v3", "backend",  "staging", "a1b2c3d4-0003-0003-0003-000000000003", "rg-app-staging",    "eastus"),
    ("Standard_B2s",    "platform", "dev",     "a1b2c3d4-0001-0001-0001-000000000001", "rg-platform-dev",   "eastus"),
    ("Standard_B2s",    None,       "dev",     "a1b2c3d4-0003-0003-0003-000000000003", "rg-app-dev",        "eastus"),  # untagged
]

STORAGE_RESOURCES = [
    # (name, team, env, sub, rg, region, gb, tier)
    ("stplatformassets",  "platform", "prod",    "a1b2c3d4-0001-0001-0001-000000000001", "rg-platform-prod",  "eastus",      850.0, "LRS"),
    ("stdatalake",        "data-eng", "prod",    "a1b2c3d4-0002-0002-0002-000000000002", "rg-data-prod",      "westeurope",  3200.0, "ZRS"),
    ("stappassets",       "frontend", "prod",    "a1b2c3d4-0003-0003-0003-000000000003", "rg-app-prod",       "southeastasia",400.0, "LRS"),
    ("stmlmodels",        "ml",       "prod",    "a1b2c3d4-0002-0002-0002-000000000002", "rg-ml-prod",        "westeurope",  1100.0, "LRS"),
]

SQL_RESOURCES = [
    # (sku, team, env, sub, rg, region, daily_cost)
    ("Standard_S2",  "platform", "prod",    "a1b2c3d4-0001-0001-0001-000000000001", "rg-platform-prod",  "eastus",     7.44),
    ("Business Critical_BC_Gen5_4", "data-eng", "prod", "a1b2c3d4-0002-0002-0002-000000000002", "rg-data-prod", "westeurope", 52.80),
    ("General Purpose_GP_Gen5_2",   "backend",  "prod", "a1b2c3d4-0003-0003-0003-000000000003", "rg-app-prod",  "eastus",     14.40),
]

BENEFIT_NAMES = {
    "ri":      "Reserved VM Instance_{region}_1Year",
    "sp":      "Compute savings plan_1Year",
    "on_demand": "",
}
_DEFAULT_DISCOUNT_POOL = ["on_demand", "on_demand", "on_demand", "ri", "sp"]

COST_CENTERS = {"platform": "CC100", "data-eng": "CC200", "frontend": "CC300",
                "backend": "CC400", "ml": "CC500"}

def _resource_id(sub: str, rg: str, provider: str, resource_type: str, name: str) -> str:
    return f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{provider}/{resource_type}/{name}"

def _tags_str(team: str | None, env: str) -> str:
    if team is None:
        return "{}"
    return json.dumps({
        "team": team,
        "environment": env,
        "costcenter": COST_CENTERS.get(team, "CC999"),
        "application": f"{team}-app",
    })

def _vm_row(sku: str, team, env: str, sub: str, rg: str, region: str,
            day: date, vm_name: str, discount: str) -> dict:
    meter_name, daily_od = VM_SIZES[sku]
    ri_discount = random.uniform(0.30, 0.45)
    sp_discount = random.uniform(0.20, 0.35)

    if discount == "ri":
        amortized = round(daily_od * (1 - ri_discount) * random.uniform(0.98, 1.02), 6)
        benefit   = BENEFIT_NAMES["ri"].format(region=region)
        benefit_id = f"/providers/Microsoft.BillingBenefits/savingsPlanOrders/{uuid.uuid4()}"
    elif discount == "sp":
        amortized = round(daily_od * (1 - sp_discount) * random.uniform(0.98, 1.02), 6)
        benefit   = BENEFIT_NAMES["sp"]
        benefit_id = f"/providers/Microsoft.BillingBenefits/savingsPlanOrders/{uuid.uuid4()}"
    else:
        amortized = round(daily_od * random.uniform(0.99, 1.01), 6)
        benefit   = ""
        benefit_id = ""

    return {
        "InvoiceSectionName":       SUBSCRIPTIONS[sub],
        "AccountName":              SUBSCRIPTIONS[sub],
        "AccountOwnerId":           f"owner_{sub[-4:]}@company.com",
        "SubscriptionId":           sub,
        "SubscriptionName":         SUBSCRIPTIONS[sub],
        "ResourceGroup":            rg,
        "ResourceLocation":         region,
        "Date":                     day.isoformat(),
        "ProductName":              f"Virtual Machines {sku} - {region}",
        "MeterCategory":            "Virtual Machines",
        "MeterSubcategory":         f"{sku} Series",
        "MeterId":                  str(uuid.uuid5(uuid.NAMESPACE_DNS, sku + region)),
        "MeterName":                f"{meter_name}",
        "Quantity":                 24.0,
        "Unit":                     "1 Hour",
        "CostInBillingCurrency":    amortized,
        "UnitPrice":                round(daily_od / 24, 6),
        "BillingCurrency":          "USD",
        "ResourceId":               _resource_id(sub, rg, "Microsoft.Compute", "virtualMachines", vm_name),
        "Tags":                     _tags_str(team, env),
        "AdditionalInfo":           json.dumps({"ServiceType": "Standard", "VMName": vm_name}),
        "ServiceFamily":            "Compute",
        "ChargeType":               "Usage",
        "PublisherType":            "Azure",
        "BenefitId":                benefit_id,
        "BenefitName":              benefit,
    }


def _storage_row(name: str, team, env: str, sub: str, rg: str, region: str,
                 gb: float, tier: str, day: date) -> dict:
    # Azure Blob Storage LRS: ~$0.018/GB-month -> daily
    rate = 0.018 if tier == "LRS" else 0.023
    daily_cost = round((gb * rate / 30) * random.uniform(0.997, 1.003), 6)

    return {
        "InvoiceSectionName":       SUBSCRIPTIONS[sub],
        "AccountName":              SUBSCRIPTIONS[sub],
        "AccountOwnerId":           f"owner_{sub[-4:]}@company.com",
        "SubscriptionId":           sub,
        "SubscriptionName":         SUBSCRIPTIONS[sub],
        "ResourceGroup":            rg,
        "ResourceLocation":         region,
        "Date":                     day.isoformat(),
        "ProductName":              f"Blob Storage - {tier} - Hot - {region}",
        "MeterCategory":            "Storage",
        "MeterSubcategory":         f"Blobs - {tier} - Hot",
        "MeterId":                  str(uuid.uuid5(uuid.NAMESPACE_DNS, "storage" + tier + region)),
        "MeterName":                "Data Stored",
        "Quantity":                 round(gb * random.uniform(0.999, 1.001), 4),
        "Unit":                     "1 GB/Month",
        "CostInBillingCurrency":    daily_cost,
        "UnitPrice":                rate,
        "BillingCurrency":          "USD",
        "ResourceId":               _resource_id(sub, rg, "Microsoft.Storage", "storageAccounts", name),
        "Tags":                     _tags_str(team, env),
        "AdditionalInfo":           json.dumps({"AccountType": tier}),
        "ServiceFamily":            "Storage",
        "ChargeType":               "Usage",
        "PublisherType":            "Azure",
        "BenefitId":                "",
        "BenefitName":              "",
    }


def _sql_row(sku: str, team, env: str, sub: str, rg: str, region: str,
             daily_cost: float, db_name: str, day: date) -> dict:
    cost = round(daily_cost * random.uniform(0.99, 1.01), 6)
    return {
        "InvoiceSectionName":       SUBSCRIPTIONS[sub],
        "AccountName":              SUBSCRIPTIONS[sub],
        "AccountOwnerId":           f"owner_{sub[-4:]}@company.com",
        "SubscriptionId":           sub,
        "SubscriptionName":         SUBSCRIPTIONS[sub],
        "ResourceGroup":            rg,
        "ResourceLocation":         region,
        "Date":                     day.isoformat(),
        "ProductName":              f"Azure SQL Database {sku} - {region}",
        "MeterCategory":            "SQL Database",
        "MeterSubcategory":         sku,
        "MeterId":                  str(uuid.uuid5(uuid.NAMESPACE_DNS, "sql" + sku + region)),
        "MeterName":                "vCore Hours",
        "Quantity":                 24.0,
        "Unit":                     "1 Hour",
        "CostInBillingCurrency":    cost,
        "UnitPrice":                round(daily_cost / 24, 6),
        "BillingCurrency":          "USD",
        "ResourceId":               _resource_id(sub, rg, "Microsoft.Sql", "servers/databases", db_name),
        "Tags":                     _tags_str(team, env),
        "AdditionalInfo":           "{}",
        "ServiceFamily":            "Databases",
        "ChargeType":               "Usage",
        "PublisherType":            "Azure",
        "BenefitId":                "",
        "BenefitName":              "",
    }


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------
def generate(billing_month: str = "2026-03", cfg: GeneratorConfig | None = None) -> None:
    if cfg is None:
        cfg = GeneratorConfig()

    year, month = map(int, billing_month.split("-"))
    start = date(year, month, 1)
    next_m = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    days   = [start + timedelta(days=d) for d in range((next_m - start).days)]

    rows = []

    discount_pool = cfg.discount_pool()

    # Assign each VM a discount type once (persists all month)
    vm_discounts = [random.choice(discount_pool) for _ in VM_RESOURCES]
    vm_names = [f"vm-{sku.lower().replace('_','-')}-{i:02d}" for i, (sku, *_) in enumerate(VM_RESOURCES)]

    for day in days:
        for i, (sku, team, env, sub, rg, region) in enumerate(VM_RESOURCES):
            # Skip ~1% of days to simulate maintenance windows
            if random.random() < 0.01:
                continue
            rows.append(_vm_row(sku, team, env, sub, rg, region, day, vm_names[i], vm_discounts[i]))

        for name, team, env, sub, rg, region, gb, tier in STORAGE_RESOURCES:
            rows.append(_storage_row(name, team, env, sub, rg, region, gb, tier, day))

        for sku, team, env, sub, rg, region, daily_cost in SQL_RESOURCES:
            db_name = f"sqldb-{sku.split('_')[0].lower()}-{sub[-4:]}"
            rows.append(_sql_row(sku, team, env, sub, rg, region, daily_cost, db_name, day))

    # Apply untagged_pct: strip tags from a fraction of tagged rows
    rng = random.Random(99)
    untagged_count = 0
    for row in rows:
        tags = json.loads(row["Tags"]) if row["Tags"] else {}
        if tags.get("team") is not None and rng.random() < cfg.untagged_pct:
            row["Tags"] = "{}"
            untagged_count += 1

    out_dir  = Path(__file__).parent.parent / "data" / "synthetic" / "azure"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"azure_cost_{billing_month}.csv"

    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print(f"Generated {len(rows)} rows -> {out_file}  [config: {cfg.summary()}]")
    print(f"  Untagged rows: {untagged_count} ({untagged_count/len(rows):.1%})")
    services = {}
    for r in rows:
        s = r["MeterCategory"]
        services[s] = services.get(s, 0) + 1
    for k, v in services.items():
        print(f"  {k}: {v} rows")


if __name__ == "__main__":
    generate()
