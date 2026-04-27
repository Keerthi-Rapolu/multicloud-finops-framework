with base as (
    select *
    from {{ ref('fct_unified_billing') }}
),

latest_month as (
    select max(billing_month) as billing_month
    from base
),

latest_base as (
    select
        b.*,
        coalesce(b.allocated_team, 'unattributed') as team_name
    from base b
    inner join latest_month lm
        on b.billing_month = lm.billing_month
),

team_history as (
    select *
    from {{ ref('int_team_monthly_scope') }}
),

team_scope as (
    select *
    from team_history
    where month_rank = 1
),

resource_scope as (
    select *
    from {{ ref('int_resource_monthly_scope') }}
    where month_rank = 1
),

forecast_daily_scope as (
    select
        billing_month,
        cloud_provider,
        team_name as team,
        date_trunc('day', usage_date) as usage_day,
        sum(nec) as daily_nec
    from latest_base
    group by 1, 2, 3, 4
),

forecast_current_scope as (
    select
        billing_month,
        cloud_provider,
        team,
        sum(daily_nec) as current_mtd_nec,
        count(distinct usage_day) as observed_days,
        max(day(last_day(usage_day))) as days_in_month
    from forecast_daily_scope
    group by 1, 2, 3
),

forecast_history_last_three as (
    select
        cloud_provider,
        team,
        avg(case when month_rank between 2 and 4 then nec_usd end) as trailing_3_month_avg_nec,
        count(case when month_rank between 2 and 4 then 1 end) as history_months
    from team_history
    group by 1, 2
),

forecast as (
    select *
    from (
        select
            c.billing_month,
            c.cloud_provider,
            c.team,
            c.current_mtd_nec,
            c.observed_days,
            case
                when c.observed_days > 0 then (c.current_mtd_nec / greatest(c.observed_days, 1)) * c.days_in_month
                else c.current_mtd_nec
            end as forecast_month_end_nec,
            coalesce(h.trailing_3_month_avg_nec, 0.0) as trailing_3_month_avg_nec,
            coalesce(h.history_months, 0) as history_months,
            case
                when coalesce(h.history_months, 0) >= 3 then
                    (
                        case
                            when c.observed_days > 0 then (c.current_mtd_nec / greatest(c.observed_days, 1)) * c.days_in_month
                            else c.current_mtd_nec
                        end * 0.70
                    ) + (coalesce(h.trailing_3_month_avg_nec, 0.0) * 0.30)
                else
                    case
                        when c.observed_days > 0 then (c.current_mtd_nec / greatest(c.observed_days, 1)) * c.days_in_month
                        else c.current_mtd_nec
                    end
            end as projected_month_end_nec,
            case
                when coalesce(h.history_months, 0) >= 3 then 0.85
                when c.observed_days >= 7 then 0.60
                else 0.40
            end as forecast_confidence,
            case when coalesce(h.history_months, 0) >= 3 then true else false end as minimum_data_met,
            case
                when coalesce(h.history_months, 0) >= 3
                     and coalesce(h.trailing_3_month_avg_nec, 0.0) > 0
                     and (
                        (
                            (
                                case
                                    when c.observed_days > 0 then (c.current_mtd_nec / greatest(c.observed_days, 1)) * c.days_in_month
                                    else c.current_mtd_nec
                                end * 0.70
                            ) + (coalesce(h.trailing_3_month_avg_nec, 0.0) * 0.30)
                        ) / h.trailing_3_month_avg_nec
                     ) >= 1.10
                    then 'medium'
                when c.observed_days >= 7
                     and (
                        case
                            when c.observed_days > 0 then (c.current_mtd_nec / greatest(c.observed_days, 1)) * c.days_in_month
                            else c.current_mtd_nec
                        end
                     ) >= c.current_mtd_nec * 1.15
                    then 'medium'
                else 'low'
            end as forecast_risk_level
        from forecast_current_scope c
        left join forecast_history_last_three h
            on c.cloud_provider = h.cloud_provider
           and c.team = h.team
    )
),

account_scope as (
    select
        billing_month,
        cloud_provider,
        account_id,
        sum(nec) as nec_usd,
        sum(case when not coalesce(is_tagged, false) then nec else 0.0 end) as unattributed_usd,
        sum(
            case
                when tag_team is null
                  or tag_environment is null
                  or tag_cost_center is null
                  or coalesce(owner_email, '') like 'unassigned%'
                then nec
                else 0.0
            end
        ) as missing_required_tag_nec,
        count(*) as row_count,
        count(
            case
                when tag_team is not null
                  and tag_environment is not null
                  and tag_cost_center is not null
                  and coalesce(owner_email, '') not like 'unassigned%'
                then 1
            end
        ) as complete_tag_rows
    from latest_base
    group by 1, 2, 3
),

shared_cost_grouped as (
    select
        billing_month,
        cloud_provider,
        team_name as team,
        sum(case when coalesce(is_shared_cost, false) then nec else 0.0 end) as shared_cost_nec
    from latest_base
    group by 1, 2, 3
),

shared_cost_scope as (
    select
        billing_month,
        cloud_provider,
        team,
        shared_cost_nec,
        sum(shared_cost_nec) over (
            partition by billing_month, cloud_provider
        ) as cloud_shared_cost_nec
    from shared_cost_grouped
),

tagging_gap as (
    select
        md5(concat_ws('|', billing_month, cloud_provider, account_id, 'tagging_gap')) as signal_id,
        'tagging_gap' as signal_type,
        concat_ws(':', cloud_provider, account_id, billing_month, 'tagging_gap') as entity_id,
        'account' as entity_type,
        billing_month,
        cloud_provider,
        cast(null as varchar) as team,
        account_id,
        cast(null as varchar) as resource_id,
        'missing_required_tag_pct' as metric_name,
        {{ normalize_ratio('missing_required_tag_nec', 'greatest(nec_usd, 1.0)', 1.0) }} as metric_value,
        0.10 as threshold,
        'above' as direction,
        {{ confidence_score_expr(
            clamp01(safe_div('complete_tag_rows', 'greatest(row_count, 1)')),
            clamp01("(((" ~ safe_div('missing_required_tag_nec', 'greatest(nec_usd, 1.0)') ~ ") - 0.10) / 0.10)"),
            '0.80'
        ) }} as confidence,
        0.95 as signal_weight,
        'current_billing_month' as data_window,
        current_timestamp as created_at,
        round(missing_required_tag_nec, 2) as nec_impact_usd,
        true as owner_missing,
        false as sla_breached,
        0.0 as anomaly_score,
        0.0 as waste_growth_rate
    from account_scope
    where {{ normalize_ratio('missing_required_tag_nec', 'greatest(nec_usd, 1.0)', 1.0) }} >= 0.10
),

unattributed_cost_gap as (
    select
        md5(concat_ws('|', billing_month, cloud_provider, account_id, 'unattributed_cost_gap')) as signal_id,
        'unattributed_cost_gap' as signal_type,
        concat_ws(':', cloud_provider, account_id, billing_month, 'unattributed_cost_gap') as entity_id,
        'account' as entity_type,
        billing_month,
        cloud_provider,
        cast(null as varchar) as team,
        account_id,
        cast(null as varchar) as resource_id,
        'unattributed_nec_pct' as metric_name,
        {{ normalize_ratio('unattributed_usd', 'greatest(nec_usd, 1.0)', 1.0) }} as metric_value,
        0.10 as threshold,
        'above' as direction,
        {{ confidence_score_expr(
            clamp01(safe_div('complete_tag_rows', 'greatest(row_count, 1)')),
            clamp01("(((" ~ safe_div('unattributed_usd', 'greatest(nec_usd, 1.0)') ~ ") - 0.10) / 0.10)"),
            '0.80'
        ) }} as confidence,
        0.95 as signal_weight,
        'current_billing_month' as data_window,
        current_timestamp as created_at,
        round(unattributed_usd, 2) as nec_impact_usd,
        true as owner_missing,
        true as sla_breached,
        0.0 as anomaly_score,
        0.0 as waste_growth_rate
    from account_scope
    where {{ normalize_ratio('unattributed_usd', 'greatest(nec_usd, 1.0)', 1.0) }} >= 0.10
),

commitment_waste as (
    select
        md5(concat_ws('|', billing_month, cloud_provider, team, 'commitment_waste')) as signal_id,
        'commitment_waste' as signal_type,
        concat_ws(':', cloud_provider, team, billing_month, 'commitment_waste') as entity_id,
        'team' as entity_type,
        billing_month,
        cloud_provider,
        team,
        cast(null as varchar) as account_id,
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
        0.90 as signal_weight,
        concat(cast(least(history_months, 3) as varchar), '_month_lookback') as data_window,
        current_timestamp as created_at,
        round(commitment_waste_usd, 2) as nec_impact_usd,
        false as owner_missing,
        false as sla_breached,
        anomaly_score,
        waste_growth_rate
    from team_scope
    where commitment_waste_usd > 0
      and commitment_utilization_pct < 0.75
),

idle_compute_proxy as (
    select
        md5(concat_ws('|', billing_month, cloud_provider, resource_id, 'idle_compute_proxy')) as signal_id,
        'idle_compute_proxy' as signal_type,
        concat_ws(':', cloud_provider, resource_id, billing_month, 'idle_compute_proxy') as entity_id,
        'resource' as entity_type,
        billing_month,
        cloud_provider,
        coalesce(team, 'unattributed') as team,
        account_id,
        resource_id,
        'nec_per_vcpu_proxy' as metric_name,
        round(nec_impact_usd / greatest(vcpu, 1.0), 4) as metric_value,
        5.0 as threshold,
        'below' as direction,
        {{ confidence_score_expr(
            'data_completeness_score',
            clamp01("((5.0 - (nec_impact_usd / greatest(vcpu, 1.0))) / 5.0)"),
            clamp01('least(history_months, 3) / 3.0')
        ) }} as confidence,
        0.70 as signal_weight,
        concat(cast(least(history_months, 3) as varchar), '_month_billing_proxy') as data_window,
        current_timestamp as created_at,
        round(nec_impact_usd, 2) as nec_impact_usd,
        coalesce(owner_email, '') like 'unassigned%' as owner_missing,
        coalesce(owner_email, '') like 'unassigned%' as sla_breached,
        anomaly_score,
        waste_growth_rate
    from resource_scope
    where service_category = 'Compute'
      and vcpu > 0
      and (nec_impact_usd / greatest(vcpu, 1.0)) <= 5.0
      and nec_impact_usd >= 5.0
),

zombie_resource as (
    select
        md5(concat_ws('|', billing_month, cloud_provider, resource_id, 'zombie_resource')) as signal_id,
        'zombie_resource' as signal_type,
        concat_ws(':', cloud_provider, resource_id, billing_month, 'zombie_resource') as entity_id,
        'resource' as entity_type,
        billing_month,
        cloud_provider,
        coalesce(team, 'unattributed') as team,
        account_id,
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
        current_timestamp as created_at,
        round(nec_impact_usd, 2) as nec_impact_usd,
        coalesce(owner_email, '') like 'unassigned%' as owner_missing,
        coalesce(owner_email, '') like 'unassigned%' as sla_breached,
        anomaly_score,
        waste_growth_rate
    from resource_scope
    where nec_impact_usd <= 2.0
),

shared_cost_concentration as (
    select
        md5(concat_ws('|', billing_month, cloud_provider, team, 'shared_cost_concentration')) as signal_id,
        'shared_cost_concentration' as signal_type,
        concat_ws(':', cloud_provider, team, billing_month, 'shared_cost_concentration') as entity_id,
        'team' as entity_type,
        billing_month,
        cloud_provider,
        team,
        cast(null as varchar) as account_id,
        cast(null as varchar) as resource_id,
        'shared_cost_share_pct' as metric_name,
        {{ normalize_ratio('shared_cost_nec', 'greatest(cloud_shared_cost_nec, 1.0)', 1.0) }} as metric_value,
        0.40 as threshold,
        'above' as direction,
        {{ confidence_score_expr(
            '0.85',
            clamp01("(((" ~ safe_div('shared_cost_nec', 'greatest(cloud_shared_cost_nec, 1.0)') ~ ") - 0.40) / 0.40)"),
            '0.80'
        ) }} as confidence,
        0.85 as signal_weight,
        'current_billing_month' as data_window,
        current_timestamp as created_at,
        round(shared_cost_nec, 2) as nec_impact_usd,
        false as owner_missing,
        false as sla_breached,
        0.0 as anomaly_score,
        0.0 as waste_growth_rate
    from shared_cost_scope
    where cloud_shared_cost_nec > 0
      and {{ normalize_ratio('shared_cost_nec', 'greatest(cloud_shared_cost_nec, 1.0)', 1.0) }} >= 0.40
),

cost_anomaly as (
    select
        md5(concat_ws('|', billing_month, cloud_provider, team, 'cost_anomaly')) as signal_id,
        'cost_anomaly' as signal_type,
        concat_ws(':', cloud_provider, team, billing_month, 'cost_anomaly') as entity_id,
        'team' as entity_type,
        billing_month,
        cloud_provider,
        team,
        cast(null as varchar) as account_id,
        cast(null as varchar) as resource_id,
        'anomaly_score' as metric_name,
        anomaly_score as metric_value,
        2.0 as threshold,
        'above' as direction,
        {{ confidence_score_expr(
            'data_completeness_score',
            clamp01("((anomaly_score - 2.0) / 2.0)"),
            clamp01('least(history_months, 3) / 3.0')
        ) }} as confidence,
        0.80 as signal_weight,
        concat(cast(least(history_months, 3) as varchar), '_month_lookback') as data_window,
        current_timestamp as created_at,
        round(greatest(nec_usd - coalesce(prior_mean_nec, nec_usd), 0.0), 2) as nec_impact_usd,
        coalesce(owner_email, '') like 'unassigned%' as owner_missing,
        false as sla_breached,
        anomaly_score,
        waste_growth_rate
    from (
        select
            ts.*,
            avg(nec_usd) over (
                partition by cloud_provider, team
                order by billing_month
                rows between 3 preceding and 1 preceding
            ) as prior_mean_nec
        from team_scope ts
    )
    where history_months >= 3
      and anomaly_score >= 2.0
),

forecasted_month_end_risk as (
    select
        md5(concat_ws('|', billing_month, cloud_provider, team, 'forecasted_month_end_risk')) as signal_id,
        'forecasted_month_end_risk' as signal_type,
        concat_ws(':', cloud_provider, team, billing_month, 'forecasted_month_end_risk') as entity_id,
        'team' as entity_type,
        billing_month,
        cloud_provider,
        team,
        cast(null as varchar) as account_id,
        cast(null as varchar) as resource_id,
        'forecast_growth_pct' as metric_name,
        case
            when trailing_3_month_avg_nec > 0 then (projected_month_end_nec / trailing_3_month_avg_nec) - 1.0
            else 0.0
        end as metric_value,
        0.10 as threshold,
        'above' as direction,
        {{ confidence_score_expr(
            'forecast_confidence',
            clamp01("(((" ~ safe_div('projected_month_end_nec', 'greatest(trailing_3_month_avg_nec, 1.0)') ~ ") - 1.10) / 0.10)"),
            'forecast_confidence'
        ) }} as confidence,
        0.80 as signal_weight,
        case when minimum_data_met then '3_month_blended_forecast' else '1_month_run_rate' end as data_window,
        current_timestamp as created_at,
        round(greatest(projected_month_end_nec - trailing_3_month_avg_nec, 0.0), 2) as nec_impact_usd,
        false as owner_missing,
        false as sla_breached,
        0.0 as anomaly_score,
        0.0 as waste_growth_rate
    from forecast
    where forecast_risk_level in ('medium', 'high')
)

select * from tagging_gap
union all
select * from unattributed_cost_gap
union all
select * from commitment_waste
union all
select * from zombie_resource
union all
select * from idle_compute_proxy
union all
select * from shared_cost_concentration
union all
select * from cost_anomaly
union all
select * from forecasted_month_end_risk
