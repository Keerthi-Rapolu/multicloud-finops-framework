"""
Generate synthetic Azure Cost Management Export data (Amortized view).
- Daily grain (one row per resource per day)
- Amortized cost: RI/SP upfront fees spread daily, not lump-sum on purchase date
- Realistic meter categories, VM sizes, resource IDs, subscription structure
- ChargeType: Usage | UnusedReservation | UnusedSavingsPlan
- Shared-infra subscription: truly cross-team resources with no tag (spread in dbt)
- Unused commitment rows: ~20% of RI/SP days have partial waste row
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
SHARED_INFRA_SUB = "a1b2c3d4-9999-9999-9999-000000000099"

SUBSCRIPTIONS = {
    "a1b2c3d4-0001-0001-0001-000000000001": "platform-prod-sub",
    "a1b2c3d4-0002-0002-0002-000000000002": "data-eng-prod-sub",
    "a1b2c3d4-0003-0003-0003-000000000003": "app-prod-sub",
    SHARED_INFRA_SUB:                        "shared-infra-sub",
}

# Shared infra resources — no team owner, costs spread across all teams in dbt
# (meter_category, product_name, meter_name, service_family, rg, region, daily_cost_usd)
SHARED_RESOURCES = [
    ("Monitor",        "Azure Monitor",      "Data Ingested",  "Management",   "rg-shared-infra", "eastus",      45.00),
    ("Networking",     "Virtual Network",    "Intra-Region",   "Networking",   "rg-shared-infra", "eastus",      28.00),
    ("API Management", "API Management",     "Gateway Units",  "Integration",  "rg-shared-infra", "eastus",     120.00),
    ("Key Vault",      "Azure Key Vault",    "Operations",     "Security",     "rg-shared-infra", "eastus",       8.00),
    ("Storage",        "Azure Blob Storage", "Data Stored",    "Storage",      "rg-shared-infra", "eastus",      18.00),
]

VM_SIZES = {
    # (meter_name, daily_od_cost_usd, vcpus)
    "Standard_B2s":      ("B2s",    2.016,  2),
    "Standard_D2s_v3":   ("D2s v3", 4.032,  2),
    "Standard_D4s_v3":   ("D4s v3", 8.064,  4),
    "Standard_E4s_v3":   ("E4s v3", 8.736,  4),
    "Standard_F4s_v2":   ("F4s v2", 6.048,  4),
    "Standard_D8s_v3":   ("D8s v3", 16.128, 8),
    "Standard_E8s_v3":   ("E8s v3", 17.472, 8),
}

BILLING_ACCOUNT_ID = "EA-9876543210"   # synthetic EA enrollment number

# Azure resource provider per service type — used for ConsumedService column
CONSUMED_SERVICE = {
    "vm":      "Microsoft.Compute",
    "storage": "Microsoft.Storage",
    "sql":     "Microsoft.Sql",
    "shared":  "Microsoft.SharedInfra",
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
    meter_name, daily_od, vcpus = VM_SIZES[sku]
    payg_price  = round(daily_od / 24, 6)
    ri_discount = random.uniform(0.30, 0.45)
    sp_discount = random.uniform(0.20, 0.35)

    if discount == "ri":
        amortized     = round(daily_od * (1 - ri_discount) * random.uniform(0.98, 1.02), 6)
        pricing_model = "Reservation"
        benefit       = BENEFIT_NAMES["ri"].format(region=region)
        benefit_id    = f"/providers/Microsoft.BillingBenefits/savingsPlanOrders/{uuid.uuid4()}"
    elif discount == "sp":
        amortized     = round(daily_od * (1 - sp_discount) * random.uniform(0.98, 1.02), 6)
        pricing_model = "SavingsPlan"
        benefit       = BENEFIT_NAMES["sp"]
        benefit_id    = f"/providers/Microsoft.BillingBenefits/savingsPlanOrders/{uuid.uuid4()}"
    else:
        amortized     = round(daily_od * random.uniform(0.99, 1.01), 6)
        pricing_model = "OnDemand"
        benefit       = ""
        benefit_id    = ""

    return {
        "BillingAccountId":         BILLING_ACCOUNT_ID,
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
        "UnitPrice":                payg_price,
        "EffectivePrice":           round(amortized / 24, 6),
        "PayGPrice":                payg_price,
        "PricingModel":             pricing_model,
        "BillingCurrency":          "USD",
        "ConsumedService":          CONSUMED_SERVICE["vm"],
        "ResourceId":               _resource_id(sub, rg, "Microsoft.Compute", "virtualMachines", vm_name),
        "ResourceName":             vm_name,
        "Tags":                     _tags_str(team, env),
        "AdditionalInfo":           json.dumps({"ServiceType": "Standard", "VMName": vm_name, "vCPUs": vcpus}),
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
        "BillingAccountId":         BILLING_ACCOUNT_ID,
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
        "EffectivePrice":           rate,
        "PayGPrice":                rate,
        "PricingModel":             "OnDemand",
        "BillingCurrency":          "USD",
        "ConsumedService":          CONSUMED_SERVICE["storage"],
        "ResourceId":               _resource_id(sub, rg, "Microsoft.Storage", "storageAccounts", name),
        "ResourceName":             name,
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
    unit_price = round(daily_cost / 24, 6)
    return {
        "BillingAccountId":         BILLING_ACCOUNT_ID,
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
        "UnitPrice":                unit_price,
        "EffectivePrice":           unit_price,
        "PayGPrice":                unit_price,
        "PricingModel":             "OnDemand",
        "BillingCurrency":          "USD",
        "ConsumedService":          CONSUMED_SERVICE["sql"],
        "ResourceId":               _resource_id(sub, rg, "Microsoft.Sql", "servers/databases", db_name),
        "ResourceName":             db_name,
        "Tags":                     _tags_str(team, env),
        "AdditionalInfo":           "{}",
        "ServiceFamily":            "Databases",
        "ChargeType":               "Usage",
        "PublisherType":            "Azure",
        "BenefitId":                "",
        "BenefitName":              "",
    }


def _unused_commitment_row(team, env: str, sub: str, rg: str, region: str,
                           day: date, vm_name: str, discount: str,
                           daily_od: float, rng: random.Random) -> dict:
    """Represent unused RI/SP capacity for a day — waste that cost money but ran nothing."""
    waste_frac = rng.uniform(0.05, 0.30)
    if discount == "ri":
        daily_commitment = daily_od * 0.62   # approx 38% avg RI discount → committed at 62% OD
        charge_type  = "UnusedReservation"
        benefit_name = f"Reserved VM Instance_{region}_1Year"
    else:
        daily_commitment = daily_od * 0.73   # approx 27% avg SP discount
        charge_type  = "UnusedSavingsPlan"
        benefit_name = "Compute savings plan_1Year"

    waste_cost  = round(daily_commitment * waste_frac, 6)
    benefit_id  = f"/providers/Microsoft.BillingBenefits/savingsPlanOrders/{uuid.uuid4()}"

    pricing_model = "Reservation" if discount == "ri" else "SavingsPlan"
    return {
        "BillingAccountId":         BILLING_ACCOUNT_ID,
        "InvoiceSectionName":       SUBSCRIPTIONS[sub],
        "AccountName":              SUBSCRIPTIONS[sub],
        "AccountOwnerId":           f"owner_{sub[-4:]}@company.com",
        "SubscriptionId":           sub,
        "SubscriptionName":         SUBSCRIPTIONS[sub],
        "ResourceGroup":            rg,
        "ResourceLocation":         region,
        "Date":                     day.isoformat(),
        "ProductName":              f"Unused Reservation - {vm_name}",
        "MeterCategory":            "Virtual Machines",
        "MeterSubcategory":         "Unused Capacity",
        "MeterId":                  str(uuid.uuid5(uuid.NAMESPACE_DNS, f"unused-{vm_name}-{day}")),
        "MeterName":                "Unused",
        "Quantity":                 0.0,
        "Unit":                     "1 Hour",
        "CostInBillingCurrency":    waste_cost,
        "UnitPrice":                0.0,
        "EffectivePrice":           0.0,
        "PayGPrice":                round(daily_od / 24, 6),
        "PricingModel":             pricing_model,
        "BillingCurrency":          "USD",
        "ConsumedService":          CONSUMED_SERVICE["vm"],
        "ResourceId":               "",
        "ResourceName":             vm_name,
        "Tags":                     _tags_str(team, env),
        "AdditionalInfo":           "{}",
        "ServiceFamily":            "Compute",
        "ChargeType":               charge_type,
        "PublisherType":            "Azure",
        "BenefitId":                benefit_id,
        "BenefitName":              benefit_name,
    }


def _shared_resource_row(meter_cat: str, product: str, meter_name: str,
                         service_family: str, rg: str, region: str,
                         daily_cost: float, day: date) -> dict:
    """Shared-infra row — no team tag, cost spread across all teams in dbt."""
    cost     = round(daily_cost * random.uniform(0.99, 1.01), 6)
    res_name = meter_cat.lower().replace(" ", "-")
    return {
        "BillingAccountId":         BILLING_ACCOUNT_ID,
        "InvoiceSectionName":       SUBSCRIPTIONS[SHARED_INFRA_SUB],
        "AccountName":              SUBSCRIPTIONS[SHARED_INFRA_SUB],
        "AccountOwnerId":           "owner_infra@company.com",
        "SubscriptionId":           SHARED_INFRA_SUB,
        "SubscriptionName":         SUBSCRIPTIONS[SHARED_INFRA_SUB],
        "ResourceGroup":            rg,
        "ResourceLocation":         region,
        "Date":                     day.isoformat(),
        "ProductName":              product,
        "MeterCategory":            meter_cat,
        "MeterSubcategory":         meter_name,
        "MeterId":                  str(uuid.uuid5(uuid.NAMESPACE_DNS, meter_cat + region)),
        "MeterName":                meter_name,
        "Quantity":                 round(daily_cost / 0.045, 2),
        "Unit":                     "1 Unit",
        "CostInBillingCurrency":    cost,
        "UnitPrice":                0.045,
        "EffectivePrice":           0.045,
        "PayGPrice":                0.045,
        "PricingModel":             "OnDemand",
        "BillingCurrency":          "USD",
        "ConsumedService":          CONSUMED_SERVICE["shared"],
        "ResourceId":               _resource_id(SHARED_INFRA_SUB, rg, "Microsoft.SharedInfra", meter_cat, res_name),
        "ResourceName":             res_name,
        "Tags":                     "{}",
        "AdditionalInfo":           "{}",
        "ServiceFamily":            service_family,
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

    waste_rng = random.Random(77)   # separate seed — doesn't shift main data

    for day in days:
        for i, (sku, team, env, sub, rg, region) in enumerate(VM_RESOURCES):
            if random.random() < 0.01:
                continue
            discount = vm_discounts[i]
            rows.append(_vm_row(sku, team, env, sub, rg, region, day, vm_names[i], discount))

            # ~20% of RI/SP days emit an UnusedReservation / UnusedSavingsPlan row
            if discount in ("ri", "sp") and waste_rng.random() < 0.20:
                _, daily_od, _ = VM_SIZES[sku]
                rows.append(_unused_commitment_row(
                    team, env, sub, rg, region, day, vm_names[i], discount, daily_od, waste_rng
                ))

        for name, team, env, sub, rg, region, gb, tier in STORAGE_RESOURCES:
            rows.append(_storage_row(name, team, env, sub, rg, region, gb, tier, day))

        for sku, team, env, sub, rg, region, daily_cost in SQL_RESOURCES:
            db_name = f"sqldb-{sku.split('_')[0].lower()}-{sub[-4:]}"
            rows.append(_sql_row(sku, team, env, sub, rg, region, daily_cost, db_name, day))

        # Shared-infra: cross-team resources — tagged with no team, spread in dbt
        for meter_cat, product, meter_name, svc_family, rg, region, daily_cost in SHARED_RESOURCES:
            rows.append(_shared_resource_row(meter_cat, product, meter_name, svc_family, rg, region, daily_cost, day))

    # Apply untagged_pct: strip tags from a fraction of tagged Usage rows
    tag_rng = random.Random(99)
    untagged_count = 0
    for row in rows:
        if row["ChargeType"] != "Usage":
            continue                          # don't strip tags from waste rows
        tags = json.loads(row["Tags"]) if row["Tags"] else {}
        if tags.get("team") is not None and tag_rng.random() < cfg.untagged_pct:
            row["Tags"] = "{}"
            untagged_count += 1

    out_dir  = Path(__file__).parent.parent / "data" / "synthetic" / "azure"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"azure_cost_{billing_month}.csv"

    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    usage_rows  = [r for r in rows if r["ChargeType"] == "Usage"]
    waste_rows  = [r for r in rows if r["ChargeType"] in ("UnusedReservation", "UnusedSavingsPlan")]
    shared_rows = [r for r in rows if r["SubscriptionId"] == SHARED_INFRA_SUB]
    print(f"Generated {len(rows)} rows -> {out_file}  [config: {cfg.summary()}]")
    print(f"  Untagged rows (usage): {untagged_count} ({untagged_count/max(len(usage_rows),1):.1%})")
    print(f"  Unused commitment rows: {len(waste_rows)}")
    print(f"  Shared-infra rows: {len(shared_rows)}")
    services = {}
    for r in rows:
        s = r["MeterCategory"]
        services[s] = services.get(s, 0) + 1
    for k, v in services.items():
        print(f"  {k}: {v} rows")


if __name__ == "__main__":
    generate()
