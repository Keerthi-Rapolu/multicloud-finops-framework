with recommendations as (
    select *
    from {{ ref('fct_finops_recommendations') }}
),

persisted_actions as (
    select
        recommendation_id,
        action_status,
        try_cast(nullif(created_date, '') as timestamp) as created_at,
        try_cast(nullif(approved_at, '') as timestamp) as approved_at,
        try_cast(nullif(implementation_date, '') as timestamp) as implemented_at,
        try_cast(nullif(verified_at, '') as timestamp) as verified_at,
        action_owner as owner,
        try_cast(expected_savings as double) as expected_savings_usd,
        try_cast(realized_savings as double) as realized_savings_usd,
        verification_status,
        verification_notes,
        try_cast(realization_rate as double) as realization_rate
    from read_csv_auto(
        '../data/recommendation_actions_flat.csv',
        header=true,
        all_varchar=true,
        nullstr=''
    )
),

joined as (
    select
        r.recommendation_id,
        coalesce(a.action_status, 'recommended') as status,
        a.created_at,
        a.approved_at,
        a.implemented_at as implementation_date,
        a.verified_at,
        coalesce(a.owner, r.owner_email) as owner,
        coalesce(a.expected_savings_usd, r.estimated_savings_usd) as expected_savings_usd,
        coalesce(a.realized_savings_usd, 0.0) as realized_savings_usd,
        case
            when a.verified_at is not null then strftime(a.verified_at, '%Y-%m')
            when a.implemented_at is not null then strftime(a.implemented_at, '%Y-%m')
            else null
        end as verification_month,
        coalesce(a.verification_status, 'pending') as verification_status,
        coalesce(a.verification_notes, '') as verification_notes,
        coalesce(
            a.realization_rate,
            case
                when coalesce(a.expected_savings_usd, r.estimated_savings_usd) > 0
                    then coalesce(a.realized_savings_usd, 0.0) / coalesce(a.expected_savings_usd, r.estimated_savings_usd)
                else 0.0
            end
        ) as realization_rate
    from recommendations r
    left join persisted_actions a
        on r.recommendation_id = a.recommendation_id
)

select
    recommendation_id,
    status,
    created_at,
    approved_at,
    implementation_date,
    verified_at,
    owner,
    round(expected_savings_usd, 2) as expected_savings_usd,
    round(realized_savings_usd, 2) as realized_savings_usd,
    verification_month,
    verification_status,
    verification_notes,
    round(realization_rate, 4) as realization_rate,
    {{ accuracy_pct_expr('expected_savings_usd', 'realized_savings_usd') }} as accuracy_pct
from joined
