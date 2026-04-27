with team_scope as (
    select *
    from {{ ref('int_team_monthly_scope') }}
),

resource_scope as (
    select *
    from {{ ref('int_resource_monthly_scope') }}
),

governance_gap as (
    select
        md5(concat_ws('|', billing_month, cloud_provider, team, 'governance_gap')) as signal_id,
        'governance_gap' as signal_type,
        concat_ws(':', cloud_provider, team, billing_month) as entity_id,
        'team' as entity_type,
        billing_month,
        cloud_provider as cloud,
        team,
        cast(null as varchar) as resource_id,
        'unattributed_pct' as metric_name,
        {{ normalize_ratio('unattributed_spend_usd', 'greatest(nec_usd, 1.0)', 1.0) }} as metric_value,
        0.20 as threshold,
        'above' as direction,
        {{ confidence_score_expr(
            'data_completeness_score',
            clamp01("(((" ~ safe_div('unattributed_spend_usd', 'greatest(nec_usd, 1.0)') ~ ") - 0.20) / 0.20)"),
            clamp01('least(history_months, 3) / 3.0')
        ) }} as confidence,
        0.90 as signal_weight,
        concat(cast(least(history_months, 3) as varchar), '_month_lookback') as data_window,
        current_timestamp as created_at
    from team_scope
    where {{ normalize_ratio('unattributed_spend_usd', 'greatest(nec_usd, 1.0)', 1.0) }} >= 0.20
),

commitment_waste as (
    select
        md5(concat_ws('|', billing_month, cloud_provider, team, 'commitment_waste')) as signal_id,
        'commitment_waste' as signal_type,
        concat_ws(':', cloud_provider, team, billing_month, 'commitment') as entity_id,
        'team' as entity_type,
        billing_month,
        cloud_provider as cloud,
        team,
        cast(null as varchar) as resource_id,
        'commitment_utilization_pct' as metric_name,
        commitment_utilization_pct as metric_value,
        0.75 as threshold,
        'below' as direction,
        {{ confidence_score_expr(
            'data_completeness_score',
            clamp01("((0.75 - commitment_utilization_pct) / 0.75)"),
            clamp01('least(history_months, 3) / 3.0')
        ) }} as confidence,
        0.85 as signal_weight,
        concat(cast(least(history_months, 3) as varchar), '_month_lookback') as data_window,
        current_timestamp as created_at
    from team_scope
    where commitment_waste_usd > 0
      and commitment_utilization_pct < 0.75
),

idle_resource as (
    select
        md5(concat_ws('|', billing_month, cloud_provider, resource_id, 'idle_resource')) as signal_id,
        'idle_resource' as signal_type,
        concat_ws(':', cloud_provider, resource_id, billing_month) as entity_id,
        'resource' as entity_type,
        billing_month,
        cloud_provider as cloud,
        team,
        resource_id,
        'utilization_score' as metric_name,
        utilization_score as metric_value,
        0.15 as threshold,
        'below' as direction,
        {{ confidence_score_expr(
            'data_completeness_score',
            clamp01("((0.15 - utilization_score) / 0.15)"),
            clamp01('least(history_months, 3) / 3.0')
        ) }} as confidence,
        0.80 as signal_weight,
        concat(cast(least(history_months, 3) as varchar), '_month_lookback') as data_window,
        current_timestamp as created_at
    from resource_scope
    where service_category = 'Compute'
      and utilization_score < 0.15
      and nec_impact_usd >= 5.0
),

zombie_resource as (
    select
        md5(concat_ws('|', billing_month, cloud_provider, resource_id, 'zombie_resource')) as signal_id,
        'zombie_resource' as signal_type,
        concat_ws(':', cloud_provider, resource_id, billing_month, 'zombie') as entity_id,
        'resource' as entity_type,
        billing_month,
        cloud_provider as cloud,
        team,
        resource_id,
        'nec_impact_usd' as metric_name,
        nec_impact_usd as metric_value,
        2.0 as threshold,
        'below' as direction,
        {{ confidence_score_expr(
            'data_completeness_score',
            clamp01("((2.0 - nec_impact_usd) / 2.0)"),
            clamp01('least(history_months, 3) / 3.0')
        ) }} as confidence,
        0.75 as signal_weight,
        concat(cast(least(history_months, 3) as varchar), '_month_lookback') as data_window,
        current_timestamp as created_at
    from resource_scope
    where service_category = 'Compute'
      and (nec_impact_usd <= 2.0 or coalesce(idle_hours, 0.0) >= 336.0)
)

select
    *,
    confidence as confidence_score
from governance_gap
union all
select
    *,
    confidence as confidence_score
from commitment_waste
union all
select
    *,
    confidence as confidence_score
from idle_resource
union all
select
    *,
    confidence as confidence_score
from zombie_resource
