/*
  int_aws_nec — AWS Net Effective Cost

  NEC logic per line_item_type:

    Usage                     → nec_used = unblended_cost          (on-demand actual charge)
    DiscountedUsage           → nec_used = reservation_effective_cost   (RI amortized hourly)
    SavingsPlanCoveredUsage   → nec_used = savings_plan_effective_cost  (SP rate × usage)

    RIFee                     → nec_used = 0   (used cost already captured per-hour above)
                                nec_waste = reservation_unused_upfront_fee
                                          + reservation_unused_recurring_fee
    SavingsPlanRecurringFee   → nec_used = 0
                                nec_waste = recurring_commitment - used_commitment

  RIFee/SPRecurringFee rows are INCLUDED (not filtered) so waste is visible in the mart.
  Their nec_used = 0 prevents double-counting with the per-hour effective cost rows.

  SavingsPlanNegation rows are intentionally excluded in stg_aws_cur (WHERE filter).
  They are negative-cost offsets that would double-subtract SP discounts — the effective
  cost is already correct on SavingsPlanCoveredUsage rows without them.

  Waste modeling note: nec_waste is approximate for SavingsPlanRecurringFee rows.
  The derived formula (recurring_commitment − used_commitment) is equivalent to the
  direct savingsPlan/SavingsPlanUnusedCommitment field in real CUR (not in synthetic schema).

  Why not unblended_cost alone?
    - RI-covered hours: unblended_cost = $0  (RI paid for it — usage looks free)
    - SP-covered hours: unblended_cost = OD rate (discount invisible — cost overstated)
*/

with staged as (
    select * from {{ ref('stg_aws_cur') }}
),

nec as (
    select
        -- Keys
        line_item_id,
        payer_account_id,
        account_id,
        billing_month,
        usage_start_time,
        usage_end_time,
        resource_id,
        service_name,
        product_name,
        instance_type,
        operating_system,
        region,
        availability_zone,
        usage_amount,
        pricing_unit,

        -- Compute metadata (EC2 only; null for S3/RDS)
        vcpu,
        memory,

        -- Raw costs (kept for reconciliation)
        unblended_cost,
        on_demand_cost,

        -- Commitment identifiers
        reservation_arn,
        savings_plan_arn,

        -- Discount type
        case
            when line_item_type in ('DiscountedUsage', 'RIFee')
                then 'ri'
            when line_item_type in ('SavingsPlanCoveredUsage', 'SavingsPlanRecurringFee')
                then 'sp'
            else 'on_demand'
        end                                                         as discount_type,

        -- NEC used: cost of compute that actually ran
        case
            when line_item_type = 'DiscountedUsage'
                then coalesce(reservation_effective_cost, 0.0)
            when line_item_type = 'SavingsPlanCoveredUsage'
                then coalesce(savings_plan_effective_cost, 0.0)
            when line_item_type in ('RIFee', 'SavingsPlanRecurringFee')
                then 0.0    -- used cost already captured on per-hour rows above
            else
                coalesce(unblended_cost, 0.0)
        end                                                         as nec_used,

        -- NEC waste: commitment cost that bought zero compute.
        -- RI: unused_upfront_fee + unused_recurring_fee is correct — the amortized upfront
        --   portion is already embedded in reservation_effective_cost on used hours, so
        --   only the unused slice appears here without double-counting.
        -- SP: recurring_commitment − used_commitment = unused commitment.
        --   Real CUR also has savingsPlan/SavingsPlanUnusedCommitment as a direct field
        --   (not in our synthetic schema). Our derived formula is equivalent.
        case
            when line_item_type = 'RIFee'
                then coalesce(reservation_unused_upfront_fee, 0.0)
                   + coalesce(reservation_unused_recurring_fee, 0.0)
            when line_item_type = 'SavingsPlanRecurringFee'
                then greatest(
                    coalesce(savings_plan_recurring_commitment, 0.0)
                    - coalesce(savings_plan_used_commitment, 0.0),
                    0.0
                )
            else 0.0
        end                                                         as nec_waste,

        -- is_commitment_waste: true when this row carries idle commitment cost
        case
            when line_item_type = 'RIFee'
             and (coalesce(reservation_unused_upfront_fee, 0.0)
                + coalesce(reservation_unused_recurring_fee, 0.0)) > 0
                then true
            when line_item_type = 'SavingsPlanRecurringFee'
             and coalesce(savings_plan_recurring_commitment, 0.0)
               > coalesce(savings_plan_used_commitment, 0.0)
                then true
            else false
        end                                                         as is_commitment_waste,

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
    nec_used as nec   -- nec = used cost only; waste surfaced separately (same convention as Azure)
from nec
