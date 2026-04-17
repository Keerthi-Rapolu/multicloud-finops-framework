{% macro extract_gcp_label(col, key) %}
    (
        select item->>'value'
        from (select unnest(try_cast({{ col }} as json[])) as item)
        where item->>'key' = '{{ key }}'
        limit 1
    )
{% endmacro %}


{% macro sum_gcp_credits(col) %}
    coalesce((
        select sum(try_cast(item->>'amount' as double))
        from (select unnest(try_cast({{ col }} as json[])) as item)
        where item->>'type' in (
            'COMMITTED_USAGE_DISCOUNT',
            'COMMITTED_USAGE_DISCOUNT_DOLLAR_BASE',
            'SUSTAINED_USE_DISCOUNT',
            'FREE_TIER',
            'PROMOTION'
        )
    ), 0.0)
{% endmacro %}
