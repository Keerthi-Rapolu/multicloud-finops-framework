with daily as (
    select
        billing_month,
        cloud_provider,
        coalesce(allocated_team, 'unattributed') as team,
        date_trunc('day', usage_date) as usage_day,
        sum(nec) as daily_nec
    from {{ ref('fct_unified_billing') }}
    group by 1, 2, 3, 4
),

monthly_actuals as (
    select
        billing_month,
        cloud_provider,
        team,
        sum(daily_nec) as actual_nec,
        max(day(last_day(usage_day))) as days_in_month
    from daily
    group by 1, 2, 3
),

mid_month_observed as (
    select
        billing_month,
        cloud_provider,
        team,
        sum(case when day(usage_day) <= 15 then daily_nec else 0.0 end) as mid_month_nec,
        count(distinct case when day(usage_day) <= 15 then usage_day end) as observed_days
    from daily
    group by 1, 2, 3
),

history as (
    select
        a.*,
        avg(actual_nec) over (
            partition by cloud_provider, team
            order by billing_month
            rows between 3 preceding and 1 preceding
        ) as trailing_3_month_avg_nec,
        count(actual_nec) over (
            partition by cloud_provider, team
            order by billing_month
            rows between 3 preceding and 1 preceding
        ) as history_months
    from monthly_actuals a
),

backtest as (
    select
        h.billing_month,
        h.cloud_provider,
        h.team,
        m.mid_month_nec,
        m.observed_days,
        h.days_in_month,
        h.actual_nec,
        case
            when coalesce(m.observed_days, 0) > 0
                then (m.mid_month_nec / greatest(m.observed_days, 1)) * h.days_in_month
            else h.actual_nec
        end as mid_month_run_rate_forecast,
        coalesce(h.trailing_3_month_avg_nec, 0.0) as trailing_3_month_avg_nec,
        h.history_months,
        case
            when h.history_months >= 3 then
                (
                    case
                        when coalesce(m.observed_days, 0) > 0
                            then (m.mid_month_nec / greatest(m.observed_days, 1)) * h.days_in_month
                        else h.actual_nec
                    end * 0.70
                ) + (coalesce(h.trailing_3_month_avg_nec, 0.0) * 0.30)
            else
                case
                    when coalesce(m.observed_days, 0) > 0
                        then (m.mid_month_nec / greatest(m.observed_days, 1)) * h.days_in_month
                    else h.actual_nec
                end
        end as forecast_nec,
        case
            when h.history_months >= 3 then '0.7 * current_month_run_rate + 0.3 * trailing_3_month_avg_nec'
            else 'current_month_run_rate'
        end as forecast_method
    from history h
    left join mid_month_observed m
        on h.billing_month = m.billing_month
       and h.cloud_provider = m.cloud_provider
       and h.team = m.team
)

select
    billing_month,
    cloud_provider,
    team,
    round(actual_nec, 2) as actual_nec,
    round(mid_month_run_rate_forecast, 2) as mid_month_run_rate_forecast,
    round(trailing_3_month_avg_nec, 2) as trailing_3_month_avg_nec,
    round(forecast_nec, 2) as forecast_nec,
    cast(history_months as bigint) as history_months,
    cast(observed_days as bigint) as observed_days,
    forecast_method,
    round(abs(actual_nec - forecast_nec), 2) as absolute_error_usd,
    round(
        case
            when actual_nec > 0 then abs(actual_nec - forecast_nec) / actual_nec
            else 0.0
        end,
        6
    ) as absolute_pct_error,
    round(
        case
            when actual_nec > 0 then 100.0 - ((abs(actual_nec - forecast_nec) / actual_nec) * 100.0)
            else 100.0
        end,
        2
    ) as accuracy_pct,
    case
        when actual_nec > 0 and abs(actual_nec - forecast_nec) / actual_nec <= 0.10 then true
        else false
    end as within_10pct
from backtest
where observed_days >= 7
