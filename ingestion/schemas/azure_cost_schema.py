"""
Azure Cost Management Export schema definition.
Amortized view — daily grain, one row per resource per day.
"""

COLUMN_DTYPES: dict[str, str] = {
    "InvoiceSectionName":    "str",
    "AccountName":           "str",
    "AccountOwnerId":        "str",
    "SubscriptionId":        "str",
    "SubscriptionName":      "str",
    "ResourceGroup":         "str",
    "ResourceLocation":      "str",
    "Date":                  "str",
    "ProductName":           "str",
    "MeterCategory":         "str",
    "MeterSubcategory":      "str",
    "MeterId":               "str",
    "MeterName":             "str",
    "Quantity":              "float64",
    "Unit":                  "str",
    "CostInBillingCurrency": "float64",
    "UnitPrice":             "float64",
    "BillingCurrency":       "str",
    "ResourceId":            "str",
    "Tags":                  "str",       # JSON string — parsed into tag_* columns
    "AdditionalInfo":        "str",       # JSON string
    "ServiceFamily":         "str",
    "ChargeType":            "str",
    "PublisherType":         "str",
    "BenefitId":             "str",
    "BenefitName":           "str",
}

REQUIRED_COLUMNS: list[str] = [
    "SubscriptionId",
    "ResourceId",
    "Date",
    "MeterCategory",
    "CostInBillingCurrency",
    "BillingCurrency",
    "ChargeType",
]

DATETIME_COLUMNS: list[str] = ["Date"]

NUMERIC_COLUMNS: list[str] = [
    c for c, t in COLUMN_DTYPES.items() if t == "float64"
]

JSON_COLUMNS: list[str] = ["Tags", "AdditionalInfo"]

# Maps tag keys inside the Tags JSON blob → normalised column names
TAG_KEYS: dict[str, str] = {
    "team":        "tag_team",
    "environment": "tag_environment",
    "costcenter":  "tag_cost_center",
}

VALID_CHARGE_TYPES: set[str] = {"Usage", "Purchase", "Refund", "Adjustment"}

DATE_PARTITION_COLUMN = "Date"
