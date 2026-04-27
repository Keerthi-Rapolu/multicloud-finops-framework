select
    'tagging_gap' as signal_type,
    'missing required owner/team/cost_center/environment tags above threshold' as condition_logic,
    'enforce_tags' as action_type,
    'improves attribution coverage and unlocks accountable optimization' as expected_impact
union all
select
    'unattributed_cost_gap' as signal_type,
    'cost cannot be allocated to an accountable team above threshold' as condition_logic,
    'enforce_tags' as action_type,
    'reduces governance gap and improves chargeback accuracy' as expected_impact
union all
select
    'commitment_waste' as signal_type,
    'unused RI/SP/CUD capacity detected below utilization threshold' as condition_logic,
    'release_commitment' as action_type,
    'reduces commitment waste with partial savings realization over time' as expected_impact
union all
select
    'zombie_resource' as signal_type,
    'near-zero-cost orphaned or inactive billable artifact persists across billing window' as condition_logic,
    'remove_resource' as action_type,
    'eliminates avoidable cost when inactive assets are removed' as expected_impact
union all
select
    'idle_compute_proxy' as signal_type,
    'billing-side compute inefficiency persists below normalized cost threshold' as condition_logic,
    'resize_down' as action_type,
    'reduces recurring compute NEC when over-provisioned resources are right-sized' as expected_impact
union all
select
    'shared_cost_concentration' as signal_type,
    'shared service NEC is concentrated in one team or account beyond policy threshold' as condition_logic,
    'rebalance_shared_cost' as action_type,
    'improves allocation fairness and accountability across shared platforms' as expected_impact
union all
select
    'cost_anomaly' as signal_type,
    'NEC moves materially outside historical baseline or anomaly threshold' as condition_logic,
    'investigate_anomaly' as action_type,
    'contains unexpected spend before it propagates into future billing periods' as expected_impact
union all
select
    'forecasted_month_end_risk' as signal_type,
    'current month NEC run rate exceeds trailing baseline in blended forecast' as condition_logic,
    'review_forecast_risk' as action_type,
    'reduces projected month-end overspend through earlier corrective action' as expected_impact
