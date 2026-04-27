with summary as (
    select
        billing_month,
        cloud_provider,
        team,
        total_list_cost as list_cost,
        total_nec as nec,
        total_unattributed_cost as unattributed_nec,
        total_governance_gap as governance_gap_usd,
        total_commitment_waste as commitment_waste,
        total_optimization_opportunity as recoverable_savings
    from {{ ref('fct_finops_summary') }}
),

recommendation_scope as (
    select
        billing_month,
        cloud_provider,
        team,
        sum(modeled_opportunity_usd) as waste_signal,
        sum(estimated_savings_usd) as recoverable_recommendation_savings,
        sum(case when risk_score < 70 then estimated_savings_usd else 0.0 end) as actionable_savings,
        sum(case when risk_score < 35 then estimated_savings_usd else 0.0 end) as low_risk_savings,
        sum(case when signal_type = 'cost_anomaly' then 1 else 0 end) as n_anomalies,
        count(*) as n_recommendations,
        sum(case when risk_score < 35 then 1 else 0 end) as n_low_risk
    from {{ ref('fct_finops_recommendations') }}
    group by 1, 2, 3
),

forecast as (
    select
        billing_month,
        cloud_provider,
        team,
        projected_month_end_nec as projected_nec,
        projected_savings_usd as actionable_forecast_savings,
        projected_realized_savings_usd as projected_savings,
        optimized_month_end_nec as optimized_nec,
        realization_rate,
        forecast_confidence as reliability_score,
        lower_bound_usd as lower_bound,
        upper_bound_usd as upper_bound
    from {{ ref('fct_month_end_forecast') }}
),

combined as (
    select
        s.billing_month,
        s.cloud_provider,
        s.team,
        s.list_cost,
        s.nec,
        s.unattributed_nec,
        case when s.nec > 0 then s.unattributed_nec / s.nec else 0.0 end as tagging_gap,
        s.commitment_waste,
        case when s.nec > 0 then s.commitment_waste / s.nec else 0.0 end as waste_rate,
        coalesce(r.waste_signal, 0.0) as waste_signal,
        greatest(s.recoverable_savings, coalesce(r.recoverable_recommendation_savings, 0.0)) as recoverable_savings,
        coalesce(f.actionable_forecast_savings, coalesce(r.actionable_savings, 0.0)) as actionable_savings,
        coalesce(f.projected_savings, 0.0) as projected_savings,
        coalesce(f.projected_nec, s.nec) as projected_nec,
        coalesce(f.optimized_nec, greatest(0.0, coalesce(f.projected_nec, s.nec) - coalesce(f.projected_savings, 0.0))) as optimized_nec,
        coalesce(r.low_risk_savings, 0.0) as low_risk_savings,
        coalesce(f.realization_rate, 0.70) as realization_rate,
        coalesce(f.reliability_score, 0.0) as reliability_score,
        coalesce(f.lower_bound, 0.0) as lower_bound,
        coalesce(f.upper_bound, 0.0) as upper_bound,
        coalesce(r.n_recommendations, 0) as n_recommendations,
        coalesce(r.n_low_risk, 0) as n_low_risk,
        coalesce(r.n_anomalies, 0) as n_anomalies
    from summary s
    left join recommendation_scope r
        on s.billing_month = r.billing_month
       and s.cloud_provider = r.cloud_provider
       and s.team = r.team
    left join forecast f
        on s.billing_month = f.billing_month
       and s.cloud_provider = f.cloud_provider
       and s.team = f.team
)

select
    billing_month,
    cloud_provider,
    team,
    round(list_cost, 2) as list_cost,
    round(nec, 2) as nec,
    round(unattributed_nec, 2) as unattributed_nec,
    round(tagging_gap, 6) as tagging_gap,
    round(commitment_waste, 2) as commitment_waste,
    round(waste_rate, 6) as waste_rate,
    round(waste_signal, 2) as waste_signal,
    round(recoverable_savings, 2) as recoverable_savings,
    round(actionable_savings, 2) as actionable_savings,
    round(projected_savings, 2) as projected_savings,
    round(projected_nec, 2) as projected_nec,
    round(optimized_nec, 2) as optimized_nec,
    round(low_risk_savings, 2) as low_risk_savings,
    round(realization_rate, 4) as realization_rate,
    round(reliability_score, 4) as reliability_score,
    round(lower_bound, 2) as lower_bound,
    round(upper_bound, 2) as upper_bound,
    cast(n_recommendations as bigint) as n_recommendations,
    cast(n_low_risk as bigint) as n_low_risk,
    cast(n_anomalies as bigint) as n_anomalies
from combined
