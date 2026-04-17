/*
  int_aws_nec — AWS Net Effective Cost

  NEC logic per line_item_type:
    DiscountedUsage          -> reservation_effective_cost  (RI amortized hourly)
    SavingsPlanCoveredUsage  -> savings_plan_effective_cost (SP effective rate × usage)
    Usage / RIFee / SP*      -> unblended_cost              (on-demand or fee rows)

  Excludes SavingsPlanRecurringFee and RIFee from NEC total to avoid double-counting
  commitment fees (they are kept for reference only via a flag).
*/

with staged as (
    select * from {{ ref('stg_aws_cur') }}
),

nec as (
    select
        -- Keys
        line_item_id,
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

        -- Raw costs (kept for reconciliation)
        unblended_cost,
        on_demand_cost,

        -- Commitment identifiers
        reservation_arn,
        savings_plan_arn,

        -- Discount type label
        case
            when line_item_type = 'DiscountedUsage'         then 'ri'
            when line_item_type = 'SavingsPlanCoveredUsage' then 'sp'
            else                                                 'on_demand'
        end                                                     as discount_type,

        -- NEC: the actual net cost after commitment discounts
        case
            when line_item_type = 'DiscountedUsage'
                then coalesce(reservation_effective_cost, 0.0)
            when line_item_type = 'SavingsPlanCoveredUsage'
                then coalesce(savings_plan_effective_cost, 0.0)
            else
                coalesce(unblended_cost, 0.0)
        end                                                     as nec,

        -- Flag fee rows so consumers can exclude if needed
        case
            when line_item_type in ('RIFee', 'SavingsPlanRecurringFee')
            then true else false
        end                                                     as is_commitment_fee,

        -- Tags
        tag_team,
        tag_environment,
        tag_cost_center,
        is_tagged,
        cloud_provider

    from staged
    where line_item_type not in ('RIFee', 'SavingsPlanRecurringFee')
)

select * from nec