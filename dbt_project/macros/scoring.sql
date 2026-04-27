{% macro clamp01(expr) -%}
least(1.0, greatest(0.0, {{ expr }}))
{%- endmacro %}

{% macro safe_div(numerator, denominator) -%}
case
    when {{ denominator }} is null or abs({{ denominator }}) < 1e-12 then 0.0
    else {{ numerator }} / {{ denominator }}
end
{%- endmacro %}

{% macro normalize_ratio(numerator, denominator, cap=1.0) -%}
{{ clamp01("(" ~ safe_div(numerator, denominator) ~ ") / " ~ cap) }}
{%- endmacro %}

{% macro scoring_weights() -%}
{{ return(var('decision_engine_weights', {
    'priority': {
        'normalized_savings': 0.35,
        'confidence': 0.25,
        'governance_severity': 0.20,
        'urgency': 0.10,
        'low_risk_bonus': 0.10
    },
    'confidence': {
        'data_completeness': 0.40,
        'signal_strength': 0.35,
        'historical_stability': 0.25
    },
    'urgency': {
        'waste_growth_rate': 0.60,
        'anomaly_score': 0.40
    }
})) }}
{%- endmacro %}

{% macro confidence_score_expr(data_completeness, signal_strength, historical_stability) -%}
{% set weights = scoring_weights()['confidence'] %}
{{ clamp01(
    "(" ~ data_completeness ~ " * " ~ weights['data_completeness'] ~ ")"
    ~ " + (" ~ signal_strength ~ " * " ~ weights['signal_strength'] ~ ")"
    ~ " + (" ~ historical_stability ~ " * " ~ weights['historical_stability'] ~ ")"
) }}
{%- endmacro %}

{% macro effort_score_expr(action_type) -%}
case lower({{ action_type }})
    when 'assign_owner' then 1.0
    when 'enforce_tags' then 2.0
    when 'release_commitment' then 2.0
    when 'resize_down' then 3.0
    when 'remove_resource' then 4.0
    when 'rebalance_shared_cost' then 2.0
    when 'investigate_anomaly' then 2.0
    when 'review_forecast_risk' then 2.0
    else 3.0
end
{%- endmacro %}

{% macro risk_score_expr(workload_criticality, environment, sla_tier, action_type) -%}
least(100.0, greatest(0.0,
    (
        case lower({{ workload_criticality }})
            when 'low' then 15.0
            when 'medium' then 35.0
            when 'high' then 65.0
            when 'mission_critical' then 90.0
            else 35.0
        end
    ) * 0.35
    +
    (
        case lower({{ environment }})
            when 'sandbox' then 5.0
            when 'dev' then 15.0
            when 'test' then 25.0
            when 'qa' then 25.0
            when 'nonprod' then 30.0
            when 'staging' then 35.0
            when 'prod' then 80.0
            else 30.0
        end
    ) * 0.25
    +
    (
        case lower({{ sla_tier }})
            when 'bronze' then 10.0
            when 'silver' then 35.0
            when 'gold' then 65.0
            when 'platinum' then 90.0
            else 35.0
        end
    ) * 0.20
    +
    (
        case lower({{ action_type }})
            when 'assign_owner' then 10.0
            when 'enforce_tags' then 15.0
            when 'release_commitment' then 25.0
            when 'resize_down' then 60.0
            when 'remove_resource' then 85.0
            when 'rebalance_shared_cost' then 35.0
            when 'investigate_anomaly' then 20.0
            when 'review_forecast_risk' then 25.0
            else 50.0
        end
    ) * 0.20
))
{%- endmacro %}

{% macro governance_severity_expr(signal_type, owner_missing='false', sla_breached='false') -%}
least(1.0, greatest(0.0,
    (
        case lower({{ signal_type }})
            when 'tagging_gap' then 1.00
            when 'unattributed_cost_gap' then 1.00
            when 'shared_cost_concentration' then 0.80
            when 'cost_anomaly' then 0.65
            when 'forecasted_month_end_risk' then 0.65
            when 'commitment_waste' then 0.35
            when 'unused_commitment' then 0.35
            when 'underutilized_commitment' then 0.35
            when 'idle_compute_proxy' then 0.30
            when 'idle_compute' then 0.30
            when 'idle_resource' then 0.30
            when 'zombie_resource' then 0.30
            else 0.25
        end
    )
    + (case when {{ owner_missing }} then 0.10 else 0.0 end)
    + (case when {{ sla_breached }} then 0.10 else 0.0 end)
))
{%- endmacro %}

{% macro low_risk_bonus_expr(risk_score, approval_required, action_type) -%}
least(1.0, greatest(0.0,
    (1.0 - least(100.0, greatest(0.0, {{ risk_score }})) / 100.0)
    *
    (
        case
            when {{ approval_required }} then 0.0
            else case lower({{ action_type }})
                when 'enforce_tags' then 1.00
                when 'release_commitment' then 0.90
                when 'rebalance_shared_cost' then 0.80
                when 'investigate_anomaly' then 0.75
                when 'review_forecast_risk' then 0.75
                when 'resize_down' then 0.60
                when 'remove_resource' then 0.20
                else 0.50
            end
        end
    )
))
{%- endmacro %}

{% macro urgency_score_expr(waste_growth_rate, anomaly_score) -%}
{% set weights = scoring_weights()['urgency'] %}
{{ clamp01(
    "(" ~ clamp01("(" ~ waste_growth_rate ~ ") / 0.50") ~ " * " ~ weights['waste_growth_rate'] ~ ")"
    ~ " + (" ~ clamp01("abs(" ~ anomaly_score ~ ") / 3.0") ~ " * " ~ weights['anomaly_score'] ~ ")"
) }}
{%- endmacro %}

{% macro priority_score_expr(normalized_savings, confidence_score, governance_severity, urgency_score, low_risk_bonus) -%}
{% set weights = scoring_weights()['priority'] %}
{{ clamp01(
    "(" ~ normalized_savings ~ " * " ~ weights['normalized_savings'] ~ ")"
    ~ " + (" ~ confidence_score ~ " * " ~ weights['confidence'] ~ ")"
    ~ " + (" ~ governance_severity ~ " * " ~ weights['governance_severity'] ~ ")"
    ~ " + (" ~ urgency_score ~ " * " ~ weights['urgency'] ~ ")"
    ~ " + (" ~ low_risk_bonus ~ " * " ~ weights['low_risk_bonus'] ~ ")"
) }}
{%- endmacro %}

{% macro accuracy_pct_expr(expected_savings_usd, realized_savings_usd) -%}
case
    when {{ expected_savings_usd }} is null or {{ expected_savings_usd }} <= 0 then null
    else round((greatest(coalesce({{ realized_savings_usd }}, 0.0), 0.0) / {{ expected_savings_usd }}) * 100.0, 2)
end
{%- endmacro %}
