with base as (
    select *
    from {{ ref('fct_unified_billing') }}
),

latest_month as (
    select max(billing_month) as billing_month
    from base
),

daily_scope as (
    select
        b.billing_month,
        b.cloud_provider,
        coalesce(b.allocated_team, 'unattributed') as team,
        date_trunc('day', b.usage_date) as usage_day,
        sum(b.nec) as daily_nec
    from base b
    group by 1, 2, 3, 4
),

monthly_scope as (
    select
        billing_month,
        cloud_provider,
        coalesce(allocated_team, 'unattributed') as team,
        sum(nec) as nec_usd,
        sum(nec_waste) as waste_usd,
        sum(case when not coalesce(is_tagged, false) then nec else 0.0 end) as unattributed_usd
    from base
    group by 1, 2, 3
),

current_scope as (
    select
        d.billing_month,
        d.cloud_provider,
        d.team,
        sum(d.daily_nec) as current_mtd_nec,
        count(distinct d.usage_day) as observed_days,
        max(day(last_day(d.usage_day))) as days_in_month
    from daily_scope d
    inner join latest_month lm
        on d.billing_month = lm.billing_month
    group by 1, 2, 3
),

history as (
    select
        m.*,
        row_number() over (
            partition by cloud_provider, team
            order by billing_month desc
        ) as month_rank
    from monthly_scope m
),

history_last_three as (
    select
        cloud_provider,
        team,
        avg(case when month_rank between 2 and 4 then nec_usd end) as trailing_3_month_avg_nec,
        avg(case when month_rank between 2 and 4 then waste_usd / greatest(nec_usd, 1.0) end) as trailing_3_month_waste_ratio,
        avg(case when month_rank between 2 and 4 then unattributed_usd / greatest(nec_usd, 1.0) end) as trailing_3_month_unattributed_ratio,
        var_pop(case when month_rank between 2 and 4 then nec_usd end) as nec_variance,
        stddev_pop(case when month_rank between 2 and 4 then nec_usd end) as nec_stddev,
        count(case when month_rank between 2 and 4 then 1 end) as history_months
    from history
    group by 1, 2
), 

recommendation_scope as (
    select
        billing_month,
        cloud_provider,
        coalesce(team, 'unattributed') as team,
        sum(case when status = 'rejected' then 0.0 else estimated_savings_usd end) as actionable_savings_usd,
        sum(
            case
                when status = 'rejected' then 0
                when risk_score <= 35 then 1
                else 0
            end
        ) as low_risk_actions,
        sum(case when status = 'rejected' then 0 else 1 end) as actionable_actions
    from {{ ref('fct_finops_recommendations') }}
    group by 1, 2, 3
),

final as (
    select
        c.billing_month,
        c.cloud_provider,
        c.team,
        c.current_mtd_nec,
        c.observed_days,
        c.days_in_month,
        case
            when c.observed_days > 0
                then (c.current_mtd_nec / greatest(c.observed_days, 1)) * c.days_in_month
            else c.current_mtd_nec
        end as forecast_month_end_nec,
        coalesce(h.trailing_3_month_avg_nec, 0.0) as trailing_3_month_avg_nec,
        coalesce(h.trailing_3_month_waste_ratio, 0.0) as trailing_3_month_waste_ratio,
        coalesce(h.trailing_3_month_unattributed_ratio, 0.0) as trailing_3_month_unattributed_ratio,
        coalesce(h.nec_variance, 0.0) as variance,
        coalesce(h.nec_stddev, 0.0) as stddev,
        coalesce(h.history_months, 0) as history_months,
        coalesce(r.actionable_savings_usd, 0.0) as actionable_savings_usd,
        coalesce(r.low_risk_actions, 0) as low_risk_actions,
        coalesce(r.actionable_actions, 0) as actionable_actions
    from current_scope c
    left join history_last_three h
        on c.cloud_provider = h.cloud_provider
       and c.team = h.team
    left join recommendation_scope r
        on c.billing_month = r.billing_month
       and c.cloud_provider = r.cloud_provider
       and c.team = r.team
)

select
    billing_month as target_month,
    billing_month,
    cloud_provider as cloud,
    cloud_provider,
    team,
    round(current_mtd_nec, 2) as current_mtd_nec,
    round(forecast_month_end_nec, 2) as forecast_month_end_nec,
    round(trailing_3_month_avg_nec, 2) as trailing_3_month_avg_nec,
    round(
        case
            when history_months >= 3 then (forecast_month_end_nec * 0.70) + (trailing_3_month_avg_nec * 0.30)
            else forecast_month_end_nec
        end,
        2
    ) as forecast_blended_nec,
    round(
        case
            when history_months >= 3 then (forecast_month_end_nec * 0.70) + (trailing_3_month_avg_nec * 0.30)
            else forecast_month_end_nec
        end,
        2
    ) as projected_month_end_nec,
    round(
        case
            when history_months >= 3 then ((forecast_month_end_nec * 0.70) + (trailing_3_month_avg_nec * 0.30)) * trailing_3_month_waste_ratio
            else forecast_month_end_nec * trailing_3_month_waste_ratio
        end,
        2
    ) as projected_waste_usd,
    round(
        case
            when history_months >= 3 then ((forecast_month_end_nec * 0.70) + (trailing_3_month_avg_nec * 0.30)) * trailing_3_month_unattributed_ratio
            else forecast_month_end_nec * trailing_3_month_unattributed_ratio
        end,
        2
    ) as projected_unattributed_usd,
    round(actionable_savings_usd, 2) as projected_savings_usd,
    round(
        case
            when actionable_actions = 0 then 0.70
            when low_risk_actions = actionable_actions then 0.80
            when low_risk_actions > 0 then 0.70
            else 0.60
        end,
        2
    ) as realization_rate,
    round(
        actionable_savings_usd *
        case
            when actionable_actions = 0 then 0.70
            when low_risk_actions = actionable_actions then 0.80
            when low_risk_actions > 0 then 0.70
            else 0.60
        end,
        2
    ) as projected_realized_savings_usd,
    round(
        greatest(
            0.0,
            (
                case
                    when history_months >= 3 then (forecast_month_end_nec * 0.70) + (trailing_3_month_avg_nec * 0.30)
                    else forecast_month_end_nec
                end
            ) - (
                actionable_savings_usd *
                case
                    when actionable_actions = 0 then 0.70
                    when low_risk_actions = actionable_actions then 0.80
                    when low_risk_actions > 0 then 0.70
                    else 0.60
                end
            )
        ),
        2
    ) as optimized_month_end_nec,
    round(variance, 4) as variance,
    round(stddev, 2) as error_bound_usd,
    round(
        case
            when history_months >= 3 and greatest((forecast_month_end_nec * 0.70) + (trailing_3_month_avg_nec * 0.30), 1.0) > 0
                then least(
                    1.0,
                    greatest(
                        0.0,
                        1.0 - (
                            stddev / greatest((forecast_month_end_nec * 0.70) + (trailing_3_month_avg_nec * 0.30), 1.0)
                        )
                    )
                )
            when observed_days >= 7 then 0.60
            else 0.40
        end,
        4
    ) as forecast_confidence,
    case
        when history_months >= 3
             and trailing_3_month_avg_nec > 0
             and (((forecast_month_end_nec * 0.70) + (trailing_3_month_avg_nec * 0.30)) / trailing_3_month_avg_nec) >= 1.20
            then 'high'
        when history_months >= 3
             and trailing_3_month_avg_nec > 0
             and (((forecast_month_end_nec * 0.70) + (trailing_3_month_avg_nec * 0.30)) / trailing_3_month_avg_nec) >= 1.10
            then 'medium'
        when observed_days >= 7 and forecast_month_end_nec >= current_mtd_nec * 1.15
            then 'medium'
        else 'low'
    end as forecast_risk_level,
    round(
        greatest(
            0.0,
            (
                case
                    when history_months >= 3 then (forecast_month_end_nec * 0.70) + (trailing_3_month_avg_nec * 0.30)
                    else forecast_month_end_nec
                end
            ) - (1.96 * stddev)
        ),
        2
    ) as lower_bound_usd,
    round(
        (
            case
                when history_months >= 3 then (forecast_month_end_nec * 0.70) + (trailing_3_month_avg_nec * 0.30)
                else forecast_month_end_nec
            end
        ) + (1.96 * stddev),
        2
    ) as upper_bound_usd,
    case
        when history_months >= 3 then '0.7 * current_month_run_rate + 0.3 * trailing_3_month_avg_nec'
        else 'current_month_run_rate'
    end as forecast_method,
    case when history_months >= 3 then true else false end as minimum_data_met
from final
