/*
  int_gcp_nec — GCP Net Effective Cost

  GCP credits (CUD, SUD) are stored as negative amounts in the credits JSON array.
  stg_gcp_billing already summed them into total_credit_amount.

  NEC = list_cost + total_credit_amount
      (credits are negative, so this subtracts the discount)

  discount_type is derived from the credit types present in credits_raw.
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
        billing_month,
        usage_start_time,
        usage_end_time,
        resource_id,
        service_name,
        sku_description,
        region,
        usage_amount,
        usage_unit,
        currency,
        cost_type,
        invoice_month,

        -- Raw cost and credits
        list_cost,
        total_credit_amount,
        credits_raw,

        -- NEC: list cost net of CUD/SUD credits
        coalesce(list_cost, 0.0) + coalesce(total_credit_amount, 0.0)   as nec,

        -- Discount type: inspect credits_raw for credit type
        case
            when credits_raw like '%COMMITTED_USAGE_DISCOUNT%' then 'ri'
            when credits_raw like '%SUSTAINED_USE_DISCOUNT%'   then 'sp'
            else                                                    'on_demand'
        end                                                             as discount_type,

        -- Tags
        tag_team,
        tag_environment,
        tag_cost_center,
        is_tagged,
        cloud_provider

    from staged
)

select * from nec
