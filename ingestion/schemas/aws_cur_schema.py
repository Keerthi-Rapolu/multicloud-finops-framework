"""
AWS Cost and Usage Report (CUR) schema definition.
Hourly grain — one row per resource per hour.
"""
from dataclasses import dataclass, field

# Columns and their pandas dtypes
COLUMN_DTYPES: dict[str, str] = {
    # Identity
    "identity/LineItemId":                      "str",
    "identity/TimeInterval":                    "str",
    # Billing period
    "bill/BillingPeriodStartDate":              "str",
    "bill/BillingPeriodEndDate":                "str",
    "bill/BillingEntity":                       "str",
    # Line item
    "lineItem/UsageAccountId":                  "str",
    "lineItem/LineItemType":                    "str",
    "lineItem/UsageStartDate":                  "str",
    "lineItem/UsageEndDate":                    "str",
    "lineItem/ProductCode":                     "str",
    "lineItem/UsageType":                       "str",
    "lineItem/Operation":                       "str",
    "lineItem/AvailabilityZone":                "str",
    "lineItem/ResourceId":                      "str",
    "lineItem/UsageAmount":                     "float64",
    "lineItem/NormalizationFactor":             "float64",
    "lineItem/NormalizedUsageAmount":           "float64",
    "lineItem/UnblendedRate":                   "float64",
    "lineItem/UnblendedCost":                   "float64",
    "lineItem/BlendedRate":                     "float64",
    "lineItem/BlendedCost":                     "float64",
    # Pricing
    "pricing/unit":                             "str",
    "pricing/publicOnDemandRate":               "float64",
    "pricing/publicOnDemandCost":               "float64",
    # Product
    "product/ProductName":                      "str",
    "product/instanceType":                     "str",
    "product/operatingSystem":                  "str",
    "product/region":                           "str",
    "product/servicecode":                      "str",
    # Tags
    "resourceTags/user:Team":                   "str",
    "resourceTags/user:Environment":            "str",
    "resourceTags/user:CostCenter":             "str",
    # Reservation (RI)
    "reservation/ReservationARN":               "str",
    "reservation/EffectiveCost":                "float64",
    "reservation/RecurringFeeForUsage":         "float64",
    "reservation/AmortizedUpfrontCostForUsage": "float64",
    # Savings Plan (SP)
    "savingsPlan/SavingsPlanARN":               "str",
    "savingsPlan/SavingsPlanEffectiveCost":      "float64",
    "savingsPlan/SavingsPlanRate":              "float64",
    "savingsPlan/UsedCommitment":               "float64",
}

# Columns that must be present — ingestor raises if missing
REQUIRED_COLUMNS: list[str] = [
    "identity/LineItemId",
    "lineItem/UsageAccountId",
    "lineItem/LineItemType",
    "lineItem/UsageStartDate",
    "lineItem/ProductCode",
    "lineItem/ResourceId",
    "lineItem/UnblendedCost",
]

# Datetime columns to parse
DATETIME_COLUMNS: list[str] = [
    "lineItem/UsageStartDate",
    "lineItem/UsageEndDate",
    "bill/BillingPeriodStartDate",
    "bill/BillingPeriodEndDate",
]

# Numeric columns that should be coerced (empty string → 0.0)
NUMERIC_COLUMNS: list[str] = [
    c for c, t in COLUMN_DTYPES.items() if t == "float64"
]

# Valid line item types
VALID_LINE_ITEM_TYPES: set[str] = {
    "Usage",
    "DiscountedUsage",
    "SavingsPlanCoveredUsage",
    "SavingsPlanRecurringFee",
    "RIFee",
    "Fee",
    "Credit",
    "Refund",
    "Tax",
}

# Column used to derive billing_month partition (YYYY-MM)
DATE_PARTITION_COLUMN = "lineItem/UsageStartDate"
