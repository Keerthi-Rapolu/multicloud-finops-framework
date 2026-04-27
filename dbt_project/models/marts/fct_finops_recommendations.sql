with signals as (
    select *
    from {{ ref('fct_finops_signals') }}
),

team_scope as (
    select
        billing_month,
        cloud_provider,
        team,
        any_value(owner_email) as owner_email,
        any_value(application) as application,
        any_value(environment) as environment,
        any_value(workload_criticality) as workload_criticality,
        any_value(sla_tier) as sla_tier,
        any_value(support_group) as support_group
    from {{ ref('int_team_monthly_scope') }}
    group by 1, 2, 3
),

resource_scope as (
    select *
    from {{ ref('int_resource_monthly_scope') }}
),

account_scope as (
    select
        billing_month,
        cloud_provider,
        account_id,
        any_value(owner_email) as owner_email,
        any_value(application) as application,
        any_value(environment) as environment,
        any_value(workload_criticality) as workload_criticality,
        any_value(sla_tier) as sla_tier,
        any_value(support_group) as support_group
    from {{ ref('fct_unified_billing') }}
    group by 1, 2, 3
),

signals_enriched as (
    select
        s.*,
        case s.signal_type
            when 'tagging_gap' then 'enforce_tags'
            when 'unattributed_cost_gap' then 'enforce_tags'
            when 'commitment_waste' then 'release_commitment'
            when 'zombie_resource' then 'remove_resource'
            when 'idle_compute_proxy' then 'resize_down'
            when 'shared_cost_concentration' then 'rebalance_shared_cost'
            when 'cost_anomaly' then 'investigate_anomaly'
            when 'forecasted_month_end_risk' then 'review_forecast_risk'
            else 'investigate_anomaly'
        end as action_type,
        case s.signal_type
            when 'tagging_gap' then 'missing_owner_team_cost_center_environment_tags'
            when 'unattributed_cost_gap' then 'cannot_allocate_cost_to_accountable_team'
            when 'commitment_waste' then 'unused_ri_sp_cud_capacity'
            when 'zombie_resource' then 'no_activity_or_near_zero_cost'
            when 'idle_compute_proxy' then 'billing_side_idle_compute_proxy'
            when 'shared_cost_concentration' then 'shared_services_concentrated_to_single_team_or_account'
            when 'cost_anomaly' then 'abnormal_nec_movement_from_billing_trend'
            when 'forecasted_month_end_risk' then 'month_end_nec_run_rate_exceeds_expected_baseline'
            else 'unclassified FinOps issue'
        end as root_cause_type,
        case
            when s.entity_type = 'account' then coalesce(a.owner_email, 'unassigned-owner@company.com')
            when s.entity_type = 'resource' then coalesce(r.owner_email, 'unassigned-owner@company.com')
            else coalesce(t.owner_email, 'unassigned-owner@company.com')
        end as owner_email,
        case
            when s.entity_type = 'account' then coalesce(a.application, 'unassigned')
            when s.entity_type = 'resource' then coalesce(r.application, 'unassigned')
            else coalesce(t.application, 'unassigned')
        end as application,
        case
            when s.entity_type = 'account' then coalesce(a.environment, 'nonprod')
            when s.entity_type = 'resource' then coalesce(r.environment, 'nonprod')
            else coalesce(t.environment, 'nonprod')
        end as environment,
        case
            when s.entity_type = 'account' then coalesce(a.workload_criticality, 'medium')
            when s.entity_type = 'resource' then coalesce(r.workload_criticality, 'medium')
            else coalesce(t.workload_criticality, 'medium')
        end as workload_criticality,
        case
            when s.entity_type = 'account' then coalesce(a.sla_tier, 'silver')
            when s.entity_type = 'resource' then coalesce(r.sla_tier, 'silver')
            else coalesce(t.sla_tier, 'silver')
        end as sla_tier,
        case
            when s.entity_type = 'account' then coalesce(a.support_group, 'finops-governance')
            when s.entity_type = 'resource' then coalesce(r.support_group, 'finops-governance')
            else coalesce(t.support_group, 'finops-governance')
        end as support_group
    from signals s
    left join team_scope t
        on s.entity_type = 'team'
       and s.billing_month = t.billing_month
       and s.cloud_provider = t.cloud_provider
       and s.team = t.team
    left join resource_scope r
        on s.entity_type = 'resource'
       and s.billing_month = r.billing_month
       and s.cloud_provider = r.cloud_provider
       and s.resource_id = r.resource_id
    left join account_scope a
        on s.entity_type = 'account'
       and s.billing_month = a.billing_month
       and s.cloud_provider = a.cloud_provider
       and s.account_id = a.account_id
),

scored as (
    select
        md5(concat_ws('|', signal_id, action_type)) as recommendation_id,
        signal_id,
        entity_id,
        signal_type,
        action_type,
        root_cause_type,
        billing_month,
        cloud_provider,
        coalesce(team, 'unattributed') as team,
        account_id,
        resource_id,
        nec_impact_usd,
        case signal_type
            when 'commitment_waste' then round(nec_impact_usd * 0.60, 2)
            when 'zombie_resource' then round(nec_impact_usd * 1.00, 2)
            when 'idle_compute_proxy' then round(nec_impact_usd * 0.60, 2)
            else 0.0
        end as estimated_savings_usd,
        {{ risk_score_expr('workload_criticality', 'environment', 'sla_tier', 'action_type') }} as risk_score,
        {{ effort_score_expr('action_type') }} as effort_score,
        case
            when signal_type in ('cost_anomaly', 'forecasted_month_end_risk') then greatest(0.85, {{ urgency_score_expr('waste_growth_rate', 'anomaly_score') }})
            when signal_type in ('tagging_gap', 'unattributed_cost_gap') and sla_breached then greatest(0.80, {{ urgency_score_expr('waste_growth_rate', 'anomaly_score') }})
            else {{ urgency_score_expr('waste_growth_rate', 'anomaly_score') }}
        end as urgency,
        {{ governance_severity_expr('signal_type', 'owner_missing', 'sla_breached') }} as governance_severity,
        case
            when lower(environment) = 'prod'
              or lower(workload_criticality) in ('high', 'mission_critical')
              or {{ risk_score_expr('workload_criticality', 'environment', 'sla_tier', 'action_type') }} >= 60
                then true
            else false
        end as approval_required,
        confidence,
        owner_email,
        application,
        environment,
        workload_criticality,
        sla_tier,
        support_group,
        metric_name,
        metric_value,
        threshold,
        direction,
        signal_weight,
        data_window,
        owner_missing,
        sla_breached,
        anomaly_score,
        waste_growth_rate,
        created_at
    from signals_enriched
),

with_bonus as (
    select
        *,
        count(*) over (
            partition by billing_month, cloud_provider, team
        ) as coincident_signal_count,
        least(
            0.99,
            greatest(
                0.05,
                confidence
                + case when count(*) over (partition by billing_month, cloud_provider, team) >= 2 then 0.05 else 0.0 end
                + case when data_window like '%3_month%' then 0.05 else 0.0 end
                - case when signal_type = 'cost_anomaly' then 0.05 else 0.0 end
            )
        ) as calibrated_confidence,
        {{ low_risk_bonus_expr('risk_score', 'approval_required', 'action_type') }} as low_risk_bonus,
        max(estimated_savings_usd) over (partition by billing_month, cloud_provider) as max_savings_in_scope
    from scored
)

select
    recommendation_id,
    entity_id,
    signal_type,
    action_type,
    root_cause_type,
    round(nec_impact_usd, 2) as modeled_opportunity_usd,
    estimated_savings_usd,
    round(
        case
            when nec_impact_usd > 0 then estimated_savings_usd / nec_impact_usd
            else 0.0
        end,
        4
    ) as recoverability_rate,
    effort_score,
    cast(round(risk_score, 0) as integer) as risk_score,
    round(calibrated_confidence, 6) as confidence,
    round({{ normalize_ratio('estimated_savings_usd', 'greatest(max_savings_in_scope, 1.0)', 1.0) }}, 6) as normalized_savings,
    {{ priority_score_expr(
        normalize_ratio('estimated_savings_usd', 'greatest(max_savings_in_scope, 1.0)', 1.0),
        'calibrated_confidence',
        'governance_severity',
        'urgency',
        'low_risk_bonus'
    ) }} as priority_score,
    created_at,
    billing_month,
    cloud_provider,
    team,
    account_id,
    resource_id,
    round(nec_impact_usd, 2) as nec_impact_usd,
    round(governance_severity, 6) as governance_severity,
    round(urgency, 6) as urgency,
    round(low_risk_bonus, 6) as low_risk_bonus,
    case lower(action_type)
        when 'assign_owner' then 1
        when 'enforce_tags' then 3
        when 'remove_resource' then 3
        when 'resize_down' then 7
        when 'release_commitment' then 30
        when 'rebalance_shared_cost' then 7
        when 'investigate_anomaly' then 3
        when 'review_forecast_risk' then 3
        else 7
    end as time_to_value_days,
    approval_required,
    signal_weight as evidence_strength,
    'recommended' as status,
    owner_email,
    application,
    environment,
    workload_criticality,
    sla_tier,
    support_group,
    metric_name,
    metric_value,
    threshold,
    direction,
    to_json([signal_id]) as signal_ids
from with_bonus
