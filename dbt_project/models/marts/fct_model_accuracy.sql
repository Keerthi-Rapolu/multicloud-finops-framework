with lifecycle as (
    select *
    from {{ ref('fct_action_lifecycle') }}
),

recommendations as (
    select recommendation_id, action_type, confidence
    from {{ ref('fct_finops_recommendations') }}
),

joined as (
    select
        r.action_type,
        case
            when r.confidence >= 0.80 then '0.80-1.00'
            when r.confidence >= 0.60 then '0.60-0.79'
            when r.confidence >= 0.40 then '0.40-0.59'
            else '0.00-0.39'
        end as confidence_bucket,
        r.confidence,
        l.expected_savings_usd,
        l.realized_savings_usd,
        l.accuracy_pct
    from recommendations r
    inner join lifecycle l
        on r.recommendation_id = l.recommendation_id
),

by_action as (
    select
        action_type,
        cast(null as varchar) as confidence_bucket,
        count(*) as evaluation_count,
        round(avg(accuracy_pct), 2) as avg_accuracy_pct,
        round(avg(confidence) * 100.0, 2) as avg_confidence_pct,
        round(abs(avg(confidence) * 100.0 - avg(accuracy_pct)), 2) as confidence_calibration_gap_pct
    from joined
    where accuracy_pct is not null
    group by 1
),

by_bucket as (
    select
        action_type,
        confidence_bucket,
        count(*) as evaluation_count,
        round(avg(accuracy_pct), 2) as avg_accuracy_pct,
        round(avg(confidence) * 100.0, 2) as avg_confidence_pct,
        round(abs(avg(confidence) * 100.0 - avg(accuracy_pct)), 2) as confidence_calibration_gap_pct
    from joined
    where accuracy_pct is not null
    group by 1, 2
),

forecast_backtest as (
    select *
    from {{ ref('fct_forecast_backtest') }}
),

forecast_summary as (
    select
        '__forecast__' as action_type,
        'backtest' as confidence_bucket,
        count(*) as evaluation_count,
        round(avg(accuracy_pct), 2) as avg_accuracy_pct,
        cast(null as double) as avg_confidence_pct,
        cast(null as double) as confidence_calibration_gap_pct
    from forecast_backtest
)

select * from by_action
union all
select * from by_bucket
union all
select * from forecast_summary
