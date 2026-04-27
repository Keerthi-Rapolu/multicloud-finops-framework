with recommendations as (
    select *
    from {{ ref('fct_recommendations') }}
),

ranked as (
    select
        *,
        row_number() over (
            partition by entity_id
            order by priority_score desc, confidence desc, estimated_savings_usd desc, risk_score asc
        ) as decision_rank
    from recommendations
),

aggregated as (
    select
        entity_id,
        count(*) as candidate_count,
        to_json(list(recommendation_id order by priority_score desc, confidence desc, estimated_savings_usd desc, risk_score asc)) as candidate_recommendations,
        to_json(
            list(
                struct_pack(
                    recommendation_id := recommendation_id,
                    priority_score := priority_score,
                    risk_score := risk_score,
                    confidence := confidence,
                    action_type := action_type
                )
                order by priority_score desc, confidence desc, estimated_savings_usd desc, risk_score asc
            )
        ) as competing_scores
    from recommendations
    group by 1
)

select
    md5(concat_ws('|', r.entity_id, r.recommendation_id, 'decision')) as decision_id,
    r.entity_id,
    a.candidate_recommendations,
    r.recommendation_id as selected_recommendation,
    r.priority_score as decision_score,
    case
        when a.candidate_count > 1 then
            concat(
                'Selected ', r.action_type,
                ' for root cause ', r.root_cause_type,
                ' because it had the highest priority score (',
                cast(round(r.priority_score, 3) as varchar),
                ') among competing recommendations.'
            )
        else
            concat(
                'Selected ', r.action_type,
                ' for root cause ', r.root_cause_type,
                ' because it was the only recommendation candidate.'
            )
    end as decision_reason,
    a.competing_scores,
    r.created_at
from ranked r
inner join aggregated a
    on r.entity_id = a.entity_id
where r.decision_rank = 1
