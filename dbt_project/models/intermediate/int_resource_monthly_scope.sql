with base as (
    select *
    from {{ ref('fct_unified_billing') }}
    where resource_id is not null
),

scoped as (
    select
        billing_month,
        cloud_provider,
        resource_id,
        account_id,
        any_value(coalesce(allocated_team, 'unattributed')) as team,
        any_value(coalesce(application, 'unassigned')) as application,
        any_value(coalesce(environment, 'nonprod')) as environment,
        any_value(coalesce(workload_criticality, 'medium')) as workload_criticality,
        any_value(coalesce(sla_tier, 'silver')) as sla_tier,
        any_value(coalesce(owner_email, 'unassigned-owner@company.com')) as owner_email,
        any_value(coalesce(support_group, 'finops-governance')) as support_group,
        any_value(service_category) as service_category,
        sum(nec) as nec_impact_usd,
        sum(nec_waste) as waste_usd,
        avg(cpu_util_pct) as cpu_util_pct,
        avg(memory_util_pct) as memory_util_pct,
        avg(disk_util_pct) as disk_util_pct,
        max(idle_hours) as idle_hours,
        sum(coalesce(vcpu, 0)) as vcpu,
        sum(
            case when environment is not null then 1 else 0 end
            + case when application is not null then 1 else 0 end
            + case when owner_email is not null then 1 else 0 end
            + case when support_group is not null then 1 else 0 end
            + case when workload_criticality is not null then 1 else 0 end
            + case when sla_tier is not null then 1 else 0 end
        ) / greatest(count(*), 1) / 6.0 as data_completeness_score
    from base
    group by 1, 2, 3, 4
),

with_history as (
    select
        *,
        lag(waste_usd) over (partition by cloud_provider, resource_id order by billing_month) as prev_waste_usd,
        avg(nec_impact_usd) over (
            partition by cloud_provider, resource_id
            order by billing_month
            rows between 3 preceding and 1 preceding
        ) as prior_mean_nec,
        stddev_pop(nec_impact_usd) over (
            partition by cloud_provider, resource_id
            order by billing_month
            rows between 3 preceding and 1 preceding
        ) as prior_std_nec,
        count(*) over (partition by cloud_provider, resource_id) as history_months,
        row_number() over (partition by cloud_provider, resource_id order by billing_month desc) as month_rank
    from scoped
)

select
    billing_month,
    cloud_provider,
    resource_id,
    account_id,
    team,
    application,
    environment,
    workload_criticality,
    sla_tier,
    owner_email,
    support_group,
    service_category,
    nec_impact_usd,
    waste_usd,
    cpu_util_pct,
    memory_util_pct,
    disk_util_pct,
    idle_hours,
    vcpu,
    case
        when cpu_util_pct is not null or memory_util_pct is not null or disk_util_pct is not null then
            (
                coalesce(cpu_util_pct, 0.0)
                + coalesce(memory_util_pct, 0.0)
                + coalesce(disk_util_pct, 0.0)
            ) / nullif(
                (case when cpu_util_pct is not null then 1 else 0 end)
                + (case when memory_util_pct is not null then 1 else 0 end)
                + (case when disk_util_pct is not null then 1 else 0 end),
                0
            ) / 100.0
        when vcpu > 0 then least(nec_impact_usd / greatest(vcpu * 50.0, 1.0), 1.0)
        else 0.0
    end as utilization_score,
    case
        when prev_waste_usd is null or prev_waste_usd <= 0 then 0.0
        else greatest((waste_usd - prev_waste_usd) / prev_waste_usd, 0.0)
    end as waste_growth_rate,
    case
        when prior_std_nec is null or prior_std_nec <= 0 then 0.0
        else abs(nec_impact_usd - prior_mean_nec) / prior_std_nec
    end as anomaly_score,
    data_completeness_score,
    history_months,
    month_rank
from with_history
