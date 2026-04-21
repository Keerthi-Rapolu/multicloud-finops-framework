/*
  int_gcp_nec — GCP Net Effective Cost

  GCP credits (CUD, SUD) are stored as negative amounts in the credits JSON array.
  stg_gcp_billing already summed them into total_credit_amount.

  NEC = list_cost + total_credit_amount
      (credits are negative, so this subtracts the discount)

  nec_waste: when is_unused_reservation = true, the row represents idle CUD capacity.
  list_cost on those rows is the cost of the unused slot — treated as waste.
  nec_used = 0 on waste rows to avoid double-counting (same convention as AWS/Azure).

  discount_type:
    CUD (Committed Use Discount) → 'ri'   (a fixed-term commitment, like an RI)
    SUD (Sustained Use Discount) → 'on_demand'  (automatic, no commitment made)
    No credit                   → 'on_demand'
*/

with staged as (
    select * from {{ ref('stg_gcp_billing') }}
),

nec as (
    select
        -- Keys
        billing_account_id,
        account_id,
        account_name,
        project_number,
        project_ancestry,
        billing_month,
        invoice_month,
        usage_start_time,
        usage_end_time,
        resource_id,
        resource_global_name,
        service_id,
        service_name,
        sku_id,
        sku_description,
        region,
        zone,
        country,
        usage_amount,
        usage_unit,
        pricing_unit,
        currency,
        cost_type,

        -- Compute metadata (GCE rows only; null for Storage/BQ/SQL)
        compute_cores,
        compute_memory_gb,
        is_unused_reservation,

        -- Cost
        list_cost,
        cost_at_list,
        total_credit_amount,
        credits_raw,

        -- NEC used: cost of compute that actually ran.
        -- Waste rows (is_unused_reservation) get nec_used = 0 — their cost is in nec_waste.
        -- GREATEST clamps to zero: free-tier/promotional credits can push cost negative.
        case
            when is_unused_reservation then 0.0
            else greatest(
                coalesce(list_cost, 0.0) + coalesce(total_credit_amount, 0.0),
                0.0
            )
        end                                                               as nec_used,

        -- NEC waste: idle CUD capacity cost. list_cost on unused reservation rows
        -- is the full on-demand price of the unused slot (credits don't apply to waste rows).
        case
            when is_unused_reservation then coalesce(list_cost, 0.0)
            else 0.0
        end                                                               as nec_waste,

        -- net_cost already computed in staging (same formula, kept for convenience)
        net_cost,

        -- Discount type: CUD is a fixed-term commitment (→ 'ri').
        -- SUD is automatic, no commitment made (→ 'on_demand', not 'sp').
        case
            when credits_raw like '%COMMITTED_USAGE_DISCOUNT%' then 'ri'
            else                                                    'on_demand'
        end                                                               as discount_type,

        -- Tags
        tag_team,
        tag_environment,
        tag_cost_center,
        is_tagged,
        cloud_provider

    from staged
)

select
    *,
    nec_used as nec   -- nec = used cost only; waste surfaced separately (same convention as AWS/Azure)
from nec
