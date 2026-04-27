with billing_scope as (
    select
        billing_month,
        cloud_provider,
        coalesce(allocated_team, 'unattributed') as team,
        sum(list_cost) as total_list_cost,
        sum(nec_used) as total_nec_used,
        sum(nec_waste) as total_nec_waste,
        sum(nec_used + nec_waste) as total_nec,
        sum(case when coalesce(is_commitment_waste, false) then nec_waste else 0.0 end) as total_commitment_waste,
        sum(case when not coalesce(is_tagged, false) then nec else 0.0 end) as total_unattributed_cost
    from {{ ref('fct_unified_billing') }}
    group by 1, 2, 3
),

recommendation_scope as (
    select
        billing_month,
        cloud_provider,
        coalesce(team, 'unattributed') as team,
        sum(estimated_savings_usd) as total_recoverable_savings
    from {{ ref('fct_finops_recommendations') }}
    group by 1, 2, 3
)

select
    b.billing_month,
    b.cloud_provider,
    b.team,
    round(b.total_list_cost, 2) as total_list_cost,
    round(b.total_nec_used, 2) as total_nec_used,
    round(b.total_nec_waste, 2) as total_nec_waste,
    round(round(b.total_nec_used, 2) + round(b.total_nec_waste, 2), 2) as total_nec,
    round(b.total_commitment_waste, 2) as total_commitment_waste,
    round(b.total_unattributed_cost, 2) as total_unattributed_cost,
    round(b.total_unattributed_cost, 2) as total_governance_gap,
    round(least(coalesce(r.total_recoverable_savings, 0.0), b.total_nec), 2) as total_recoverable_savings,
    round(least(coalesce(r.total_recoverable_savings, 0.0), b.total_nec), 2) as total_optimization_opportunity
from billing_scope b
left join recommendation_scope r
    on b.billing_month = r.billing_month
   and b.cloud_provider = r.cloud_provider
   and b.team = r.team
