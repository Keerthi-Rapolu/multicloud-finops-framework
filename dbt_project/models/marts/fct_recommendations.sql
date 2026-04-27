with signals as (
    select *
    from {{ ref('fct_signals') }}
),

team_scope_base as (
    select *
    from {{ ref('int_team_monthly_scope') }}
),

team_scope as (
    select
        billing_month,
        cloud_provider,
        team,
        any_value(application) as application,
        any_value(environment) as environment,
        any_value(workload_criticality) as workload_criticality,
        any_value(sla_tier) as sla_tier,
        any_value(owner_email) as owner_email,
        any_value(support_group) as support_group,
        sum(list_cost_usd) as list_cost_usd,
        sum(nec_usd) as nec_usd,
        sum(waste_usd) as waste_usd,
        sum(unattributed_spend_usd) as unattributed_spend_usd,
        sum(commitment_waste_usd) as commitment_waste_usd,
        sum(commitment_covered_nec_usd) as commitment_covered_nec_usd,
        avg(tagging_coverage_pct) as tagging_coverage_pct,
        avg(commitment_utilization_pct) as commitment_utilization_pct,
        avg(waste_growth_rate) as waste_growth_rate,
        avg(anomaly_score) as anomaly_score,
        avg(data_completeness_score) as data_completeness_score,
        max(history_months) as history_months,
        min(month_rank) as month_rank
    from team_scope_base
    group by 1, 2, 3
),

resource_scope as (
    select *
    from {{ ref('int_resource_monthly_scope') }}
),

team_candidates as (
    select
        s.recommendation_id,
        s.entity_id,
        s.billing_month,
        s.signal_type,
        cast(null as varchar) as resource_id,
        t.team,
        t.cloud_provider as cloud,
        case s.signal_type
            when 'governance_gap' then 'enforce_tags'
            when 'commitment_waste' then 'release_commitment'
            else 'review'
        end as action_type,
        case s.signal_type
            when 'governance_gap' then 'missing_tags_or_ownership'
            when 'commitment_waste' then 'underutilized_commitment'
            else 'unclassified'
        end as root_cause_type,
        case s.signal_type
            when 'governance_gap' then t.unattributed_spend_usd
            when 'commitment_waste' then t.commitment_waste_usd
            else t.waste_usd
        end as nec_impact_usd,
        case s.signal_type
            when 'governance_gap' then 0.0
            when 'commitment_waste' then round(t.commitment_waste_usd * 0.60, 2)
            else round(t.waste_usd * 0.50, 2)
        end as estimated_savings_usd,
        s.confidence,
        s.confidence_score,
        {{ risk_score_expr('t.workload_criticality', 't.environment', 't.sla_tier', "
            case s.signal_type
                when 'governance_gap' then 'enforce_tags'
                when 'commitment_waste' then 'release_commitment'
                else 'review'
            end
        ") }} as risk_score,
        {{ effort_score_expr("
            case s.signal_type
                when 'governance_gap' then 'enforce_tags'
                when 'commitment_waste' then 'release_commitment'
                else 'review'
            end
        ") }} as effort_score,
        {{ urgency_score_expr('t.waste_growth_rate', 't.anomaly_score') }} as urgency_score,
        case
            when lower(t.environment) = 'prod'
                or lower(t.workload_criticality) in ('high', 'mission_critical')
                or {{ risk_score_expr('t.workload_criticality', 't.environment', 't.sla_tier', "
                    case s.signal_type
                        when 'governance_gap' then 'enforce_tags'
                        when 'commitment_waste' then 'release_commitment'
                        else 'review'
                    end
                ") }} >= 60
                then true
            else false
        end as approval_required,
        case
            when lower(t.environment) = 'prod'
                or lower(t.workload_criticality) in ('high', 'mission_critical')
                or {{ risk_score_expr('t.workload_criticality', 't.environment', 't.sla_tier', "
                    case s.signal_type
                        when 'governance_gap' then 'enforce_tags'
                        when 'commitment_waste' then 'release_commitment'
                        else 'review'
                    end
                ") }} >= 60
                then case s.signal_type when 'governance_gap' then 10 else 37 end
            when s.signal_type = 'governance_gap' then 3
            else 30
        end as time_to_value_days,
        s.signal_weight as evidence_strength,
        to_json([s.signal_id]) as signal_ids,
        'recommended' as status,
        t.owner_email as owner,
        t.application,
        t.environment,
        t.workload_criticality,
        t.sla_tier,
        t.support_group,
        s.metric_name,
        s.metric_value,
        s.threshold,
        s.direction,
        s.created_at
    from (
        select *, md5(concat_ws('|', signal_id, signal_type)) as recommendation_id
        from signals
        where entity_type = 'team'
    ) s
    inner join team_scope t
        on s.billing_month = t.billing_month
       and s.cloud = t.cloud_provider
       and s.team = t.team
),

resource_candidates as (
    select
        s.recommendation_id,
        s.entity_id,
        s.billing_month,
        s.signal_type,
        r.resource_id as resource_id,
        r.team,
        r.cloud_provider as cloud,
        case s.signal_type
            when 'idle_resource' then 'resize_down'
            when 'zombie_resource' then 'remove_resource'
            else 'review'
        end as action_type,
        case s.signal_type
            when 'idle_resource' then 'low_utilization'
            when 'zombie_resource' then 'no_activity_or_near_zero_cost'
            else 'unclassified'
        end as root_cause_type,
        r.nec_impact_usd,
        case s.signal_type
            when 'idle_resource' then round(r.nec_impact_usd * 0.80, 2)
            when 'zombie_resource' then round(r.nec_impact_usd * 1.00, 2)
            else round(r.nec_impact_usd * 0.50, 2)
        end as estimated_savings_usd,
        s.confidence,
        s.confidence_score,
        {{ risk_score_expr('r.workload_criticality', 'r.environment', 'r.sla_tier', "
            case s.signal_type
                when 'idle_resource' then 'resize_down'
                when 'zombie_resource' then 'remove_resource'
                else 'review'
            end
        ") }} as risk_score,
        {{ effort_score_expr("
            case s.signal_type
                when 'idle_resource' then 'resize_down'
                when 'zombie_resource' then 'remove_resource'
                else 'review'
            end
        ") }} as effort_score,
        {{ urgency_score_expr('r.waste_growth_rate', 'r.anomaly_score') }} as urgency_score,
        case
            when lower(r.environment) = 'prod'
                or lower(r.workload_criticality) in ('high', 'mission_critical')
                or {{ risk_score_expr('r.workload_criticality', 'r.environment', 'r.sla_tier', "
                    case s.signal_type
                        when 'idle_resource' then 'resize_down'
                        when 'zombie_resource' then 'remove_resource'
                        else 'review'
                    end
                ") }} >= 60
                then true
            else false
        end as approval_required,
        case
            when lower(r.environment) = 'prod'
                or lower(r.workload_criticality) in ('high', 'mission_critical')
                or {{ risk_score_expr('r.workload_criticality', 'r.environment', 'r.sla_tier', "
                    case s.signal_type
                        when 'idle_resource' then 'resize_down'
                        when 'zombie_resource' then 'remove_resource'
                        else 'review'
                    end
                ") }} >= 60
                then case s.signal_type when 'zombie_resource' then 10 else 14 end
            when s.signal_type = 'zombie_resource' then 3
            else 7
        end as time_to_value_days,
        s.signal_weight as evidence_strength,
        to_json([s.signal_id]) as signal_ids,
        'recommended' as status,
        r.owner_email as owner,
        r.application,
        r.environment,
        r.workload_criticality,
        r.sla_tier,
        r.support_group,
        s.metric_name,
        s.metric_value,
        s.threshold,
        s.direction,
        s.created_at
    from (
        select *, md5(concat_ws('|', signal_id, signal_type)) as recommendation_id
        from signals
        where entity_type = 'resource'
    ) s
    inner join resource_scope r
        on s.billing_month = r.billing_month
       and s.cloud = r.cloud_provider
       and s.resource_id = r.resource_id
),

combined as (
    select * from team_candidates
    union all
    select * from resource_candidates
),

scoped as (
    select
        *,
        max(estimated_savings_usd) over (partition by billing_month, cloud) as max_savings_in_scope
    from combined
)

select
    recommendation_id,
    entity_id,
    resource_id,
    team,
    cloud,
    action_type,
    root_cause_type,
    round(nec_impact_usd, 2) as nec_impact_usd,
    round(estimated_savings_usd, 2) as estimated_savings_usd,
    {{ priority_score_expr(
        normalize_ratio('estimated_savings_usd', 'greatest(max_savings_in_scope, 1.0)', 1.0),
        'confidence',
        'risk_score',
        'urgency_score',
        'effort_score'
    ) }} as priority_score,
    round(confidence, 6) as confidence,
    round(confidence_score, 6) as confidence_score,
    cast(round(risk_score, 0) as integer) as risk_score,
    round(effort_score, 2) as effort_score,
    round(urgency_score, 6) as urgency_score,
    time_to_value_days,
    round(evidence_strength, 6) as evidence_strength,
    signal_ids,
    status,
    owner,
    approval_required,
    created_at,
    cast(null as timestamp) as implemented_at,
    cast(null as timestamp) as verified_at,
    0.0 as realized_savings_usd,
    billing_month,
    signal_type,
    application,
    environment,
    workload_criticality,
    sla_tier,
    support_group,
    metric_name,
    metric_value,
    threshold,
    direction
from scoped
