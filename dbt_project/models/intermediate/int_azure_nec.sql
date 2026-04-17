/*
  int_azure_nec — Azure Net Effective Cost

  Azure Cost Management exports the *amortized* view — RI and Savings Plan
  upfront fees are already spread daily across the commitment term.
  So NEC = list_cost with no further adjustment needed.

  has_commitment flag identifies RI/SP-covered rows (BenefitName populated).
  discount_type is derived from benefit_name content.
*/

with staged as (
    select * from {{ ref('stg_azure_cost') }}
),

nec as (
    select
        -- Keys
        account_id,
        account_name,
        billing_month,
        usage_date,
        resource_id,
        resource_group,
        invoice_section,
        product_name,
        service_name,
        service_subcategory,
        meter_name,
        region,
        service_family,
        usage_amount,
        usage_unit,
        unit_price,
        currency,

        -- Commitment identifiers
        benefit_id,
        benefit_name,
        has_commitment,

        -- Discount type label
        case
            when benefit_name ilike '%Reserved%' then 'ri'
            when benefit_name ilike '%savings plan%' then 'sp'
            else 'on_demand'
        end                                         as discount_type,

        -- NEC: amortized cost is already net effective for Azure
        coalesce(list_cost, 0.0)                    as nec,
        list_cost,

        -- Tags
        tag_team,
        tag_environment,
        tag_cost_center,
        is_tagged,
        cloud_provider

    from staged
)

select * from nec