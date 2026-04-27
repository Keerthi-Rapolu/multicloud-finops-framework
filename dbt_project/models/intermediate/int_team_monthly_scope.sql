with base as (
    select *
    from {{ ref('fct_unified_billing') }}
),

scoped as (
    select
        billing_month,
        cloud_provider,
        coalesce(allocated_team, 'unattributed') as team,
        coalesce(application, 'unassigned') as application,
        coalesce(environment, 'nonprod') as environment,
        coalesce(workload_criticality, 'medium') as workload_criticality,
        coalesce(sla_tier, 'silver') as sla_tier,
        coalesce(owner_email, 'unassigned-owner@company.com') as owner_email,
        coalesce(support_group, 'finops-governance') as support_group,
        sum(list_cost) as list_cost_usd,
        sum(nec) as nec_usd,
        sum(nec_waste) as waste_usd,
        sum(case when not coalesce(is_tagged, false) then nec else 0.0 end) as unattributed_spend_usd,
        sum(case when coalesce(is_commitment_waste, false) then nec_waste else 0.0 end) as commitment_waste_usd,
        sum(case when lower(coalesce(discount_type, '')) in ('ri', 'sp') then nec_used else 0.0 end) as commitment_covered_nec_usd,
        sum(
            case when environment is not null then 1 else 0 end
            + case when application is not null then 1 else 0 end
            + case when owner_email is not null then 1 else 0 end
            + case when support_group is not null then 1 else 0 end
            + case when workload_criticality is not null then 1 else 0 end
            + case when sla_tier is not null then 1 else 0 end
        ) / greatest(count(*), 1) / 6.0 as data_completeness_score
    from base
    group by 1, 2, 3, 4, 5, 6, 7, 8, 9
),

with_history as (
    select
        *,
        case
            when nec_usd > 0 then 1.0 - (unattributed_spend_usd / nec_usd)
            else 1.0
        end as tagging_coverage_pct,
        case
            when (commitment_waste_usd + commitment_covered_nec_usd) > 0
                then 1.0 - (commitment_waste_usd / (commitment_waste_usd + commitment_covered_nec_usd))
            else 1.0
        end as commitment_utilization_pct,
        lag(waste_usd) over (partition by cloud_provider, team order by billing_month) as prev_waste_usd,
        lag(nec_usd) over (partition by cloud_provider, team order by billing_month) as prev_nec_usd,
        avg(nec_usd) over (
            partition by cloud_provider, team
            order by billing_month
            rows between 3 preceding and 1 preceding
        ) as prior_mean_nec,
        stddev_pop(nec_usd) over (
            partition by cloud_provider, team
            order by billing_month
            rows between 3 preceding and 1 preceding
        ) as prior_std_nec,
        row_number() over (partition by cloud_provider, team order by billing_month desc) as month_rank,
        count(*) over (partition by cloud_provider, team) as history_months
    from scoped
)

select
    billing_month,
    cloud_provider,
    team,
    application,
    environment,
    workload_criticality,
    sla_tier,
    owner_email,
    support_group,
    list_cost_usd,
    nec_usd,
    waste_usd,
    unattributed_spend_usd,
    commitment_waste_usd,
    commitment_covered_nec_usd,
    tagging_coverage_pct,
    commitment_utilization_pct,
    case
        when prev_waste_usd is null or prev_waste_usd <= 0 then 0.0
        else greatest((waste_usd - prev_waste_usd) / prev_waste_usd, 0.0)
    end as waste_growth_rate,
    case
        when prior_std_nec is null or prior_std_nec <= 0 then 0.0
        else abs(nec_usd - prior_mean_nec) / prior_std_nec
    end as anomaly_score,
    data_completeness_score,
    history_months,
    month_rank
from with_history
