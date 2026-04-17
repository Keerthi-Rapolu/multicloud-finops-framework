"""
GCP Cloud Billing — Detailed Usage Export schema definition.
Hourly grain for compute/SQL; daily grain for storage SKUs.
"""

COLUMN_DTYPES: dict[str, str] = {
    "billing_account_id":            "str",
    "service.id":                    "str",
    "service.description":           "str",
    "sku.id":                        "str",
    "sku.description":               "str",
    "usage_start_time":              "str",
    "usage_end_time":                "str",
    "project.id":                    "str",
    "project.name":                  "str",
    "project.number":                "str",
    "labels":                        "str",       # JSON list-of-dicts — parsed into tag_* columns
    "system_labels":                 "str",       # JSON list-of-dicts
    "location.location":             "str",
    "location.country":              "str",
    "location.region":               "str",
    "location.zone":                 "str",
    "resource.name":                 "str",
    "resource.global_name":          "str",
    "cost":                          "float64",
    "currency":                      "str",
    "currency_conversion_rate":      "float64",
    "usage.amount":                  "float64",
    "usage.unit":                    "str",
    "usage.amount_in_pricing_units": "float64",
    "usage.pricing_unit":            "str",
    "credits":                       "str",       # JSON list-of-dicts — parsed for CUD/SUD amounts
    "invoice.month":                 "str",
    "cost_type":                     "str",
    "adjustment_info.id":            "str",
    "adjustment_info.description":   "str",
    "adjustment_info.mode":          "str",
    "adjustment_info.type":          "str",
}

REQUIRED_COLUMNS: list[str] = [
    "billing_account_id",
    "service.description",
    "sku.description",
    "usage_start_time",
    "project.id",
    "resource.name",
    "cost",
    "currency",
    "invoice.month",
]

DATETIME_COLUMNS: list[str] = ["usage_start_time", "usage_end_time"]

NUMERIC_COLUMNS: list[str] = [
    c for c, t in COLUMN_DTYPES.items() if t == "float64"
]

# JSON columns parsed at ingest time
JSON_COLUMNS: list[str] = ["labels", "credits", "system_labels"]

# Keys to extract from the labels list-of-dicts
LABEL_KEYS: dict[str, str] = {
    "team":        "tag_team",
    "environment": "tag_environment",
    "cost_center": "tag_cost_center",
}

# Credit types that represent discounts (used by NEC model)
DISCOUNT_CREDIT_TYPES: set[str] = {
    "COMMITTED_USAGE_DISCOUNT",
    "COMMITTED_USAGE_DISCOUNT_DOLLAR_BASE",
    "SUSTAINED_USE_DISCOUNT",
    "FREE_TIER",
    "PROMOTION",
}

VALID_COST_TYPES: set[str] = {"regular", "tax", "adjustment", "rounding_error"}

DATE_PARTITION_COLUMN = "usage_start_time"
