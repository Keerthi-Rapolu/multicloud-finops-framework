"""
Canonical FinOps decision engine.

Pipeline:
  1. generate_signals()
  2. generate_candidate_recommendations()
  3. score_candidates()
  4. select_decisions()
  5. rank_recommendations()
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib

import pandas as pd

from intelligence import CanonicalDecision, CanonicalRecommendation, DecisionSignal
from intelligence.forecasting import build_forecast
from intelligence.scoring import (
    ROOT_CAUSE_BY_SIGNAL,
    ScoringConfig,
    SIGNAL_WEIGHT,
    calibrated_confidence_score,
    confidence_score,
    data_completeness_score,
    effort_score,
    evidence_strength,
    governance_severity_score,
    historical_stability_score,
    low_risk_bonus_score,
    normalize_savings,
    priority_score,
    risk_score,
    savings_estimate_usd,
    signal_strength_score,
    time_to_value_days,
    urgency_score,
)


RECOMMENDATION_ACTION = {
    "tagging_gap": "enforce_tags",
    "unattributed_cost_gap": "enforce_tags",
    "commitment_waste": "release_commitment",
    "zombie_resource": "remove_resource",
    "idle_compute_proxy": "resize_down",
    "shared_cost_concentration": "rebalance_shared_cost",
    "cost_anomaly": "investigate_anomaly",
    "forecasted_month_end_risk": "review_forecast_risk",
}

REQUIRED_GOVERNANCE_FIELDS = (
    "allocated_team",
    "cost_center",
    "environment",
    "owner_email",
)

ROOT_CAUSE_LABEL = {
    "tagging_gap": "missing owner/team/cost_center/environment tags",
    "unattributed_cost_gap": "cannot allocate cost to accountable team",
    "commitment_waste": "unused RI/SP/CUD capacity",
    "zombie_resource": "near-zero-cost orphaned resource or inactive billable artifact",
    "idle_compute_proxy": "billing-side proxy suggests over-provisioned compute",
    "shared_cost_concentration": "shared services are concentrated into one team or account",
    "cost_anomaly": "abnormal NEC movement from billing trend",
    "forecasted_month_end_risk": "month-end run rate exceeds trailing baseline",
}


@dataclass
class DecisionRun:
    signals: list[DecisionSignal]
    recommendations: list[CanonicalRecommendation]
    decisions: list[CanonicalDecision]


class DecisionEngine:
    def __init__(
        self,
        *,
        tagging_gap_threshold: float = 0.10,
        unattributed_gap_threshold: float = 0.10,
        commitment_utilization_threshold: float = 0.75,
        idle_nec_per_vcpu_threshold: float = 5.0,
        zombie_cost_threshold_usd: float = 2.0,
        shared_cost_concentration_threshold: float = 0.40,
        anomaly_threshold: float = 2.0,
        forecast_risk_threshold: float = 0.10,
        scoring_config: ScoringConfig | None = None,
    ) -> None:
        self.tagging_gap_threshold = tagging_gap_threshold
        self.unattributed_gap_threshold = unattributed_gap_threshold
        self.commitment_utilization_threshold = commitment_utilization_threshold
        self.idle_nec_per_vcpu_threshold = idle_nec_per_vcpu_threshold
        self.zombie_cost_threshold_usd = zombie_cost_threshold_usd
        self.shared_cost_concentration_threshold = shared_cost_concentration_threshold
        self.anomaly_threshold = anomaly_threshold
        self.forecast_risk_threshold = forecast_risk_threshold
        self.scoring_config = scoring_config or ScoringConfig()
        self._signal_context: dict[str, dict] = {}

    def run(self, billing_df: pd.DataFrame) -> DecisionRun:
        signals = self.generate_signals(billing_df)
        candidates = self.generate_candidate_recommendations(signals)
        scored = self.score_candidates(candidates)
        decisions = self.select_decisions(scored)
        ranked = self.rank_recommendations(scored)
        return DecisionRun(signals=signals, recommendations=ranked, decisions=decisions)

    def generate_signals(self, billing_df: pd.DataFrame) -> list[DecisionSignal]:
        if billing_df.empty:
            return []

        df = billing_df.copy()
        for column in REQUIRED_GOVERNANCE_FIELDS:
            if column not in df.columns:
                df[column] = pd.NA
        for column, default in {
            "is_tagged": False,
            "is_shared_cost": False,
            "is_commitment_waste": False,
            "vcpu": 0.0,
            "discount_type": "",
            "service_category": "Other",
        }.items():
            if column not in df.columns:
                df[column] = default
        for column in ("application", "support_group", "workload_criticality", "sla_tier", "usage_date"):
            if column not in df.columns:
                df[column] = pd.NA
        df["team_name"] = df.get("allocated_team", pd.Series(index=df.index)).fillna("unattributed")
        latest_month = str(df["billing_month"].max())
        latest_df = df[df["billing_month"] == latest_month].copy()
        created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        signals: list[DecisionSignal] = []
        self._signal_context = {}

        signals.extend(self._account_signals(df, latest_df, latest_month, created_at))
        signals.extend(self._team_signals(df, latest_df, latest_month, created_at))
        signals.extend(self._resource_signals(df, latest_df, latest_month, created_at))
        signals.extend(self._shared_cost_signals(latest_df, latest_month, created_at))
        signals.extend(self._forecast_signals(df, latest_df, latest_month, created_at))
        return signals

    def _account_signals(
        self,
        df: pd.DataFrame,
        latest_df: pd.DataFrame,
        latest_month: str,
        created_at: str,
    ) -> list[DecisionSignal]:
        account_scope = (
            latest_df.groupby(["cloud_provider", "account_id"], dropna=False)
            .agg(
                nec_usd=("nec", "sum"),
                unattributed_usd=("nec", lambda s: float(s[~latest_df.loc[s.index, "is_tagged"].fillna(False)].sum())),
                missing_required_tag_nec=(
                    "nec",
                    lambda s: float(
                        s[
                            latest_df.loc[s.index, "allocated_team"].isna()
                            | latest_df.loc[s.index, "environment"].isna()
                            | latest_df.loc[s.index, "owner_email"].fillna("").str.startswith("unassigned")
                            | latest_df.loc[s.index, "cost_center"].isna()
                        ].sum()
                    ),
                ),
                row_count=("nec", "count"),
                complete_tag_rows=(
                    "nec",
                    lambda s: int(
                        (
                            latest_df.loc[s.index, "allocated_team"].notna()
                            & latest_df.loc[s.index, "environment"].notna()
                            & latest_df.loc[s.index, "cost_center"].notna()
                            & ~latest_df.loc[s.index, "owner_email"].fillna("").str.startswith("unassigned")
                        ).sum()
                    ),
                ),
            )
            .reset_index()
        )

        signals: list[DecisionSignal] = []
        for row in account_scope.to_dict("records"):
            cloud = str(row["cloud_provider"])
            account_id = str(row["account_id"])
            account_df = latest_df[
                (latest_df["cloud_provider"] == cloud)
                & (latest_df["account_id"].astype(str) == account_id)
            ]
            data_complete = data_completeness_score(int(row["complete_tag_rows"]), int(row["row_count"]) or 1)

            missing_ratio = float(row["missing_required_tag_nec"]) / max(float(row["nec_usd"]), 1.0)
            if missing_ratio >= self.tagging_gap_threshold:
                signal = self._build_signal(
                    entity_type="account",
                    entity_id=f"{cloud}:{account_id}:{latest_month}:tagging_gap",
                    signal_type="tagging_gap",
                    metric_name="missing_required_tag_pct",
                    metric_value=missing_ratio,
                    threshold=self.tagging_gap_threshold,
                    direction="above",
                    data_window="current_billing_month",
                    confidence_value=confidence_score(
                        data_complete,
                        signal_strength_score(missing_ratio, self.tagging_gap_threshold, "above"),
                        0.80,
                        weights=self.scoring_config.confidence,
                    ),
                    created_at=created_at,
                )
                self._signal_context[signal["signal_id"]] = self._base_context(
                    billing_month=latest_month,
                    cloud=cloud,
                    team="unattributed",
                    account_id=account_id,
                    resource_id=None,
                    nec_impact_usd=float(row["missing_required_tag_nec"]),
                    application=self._first_value(account_df, "application", "unassigned"),
                    environment=self._first_value(account_df, "environment", "nonprod"),
                    owner_email=self._first_value(account_df, "owner_email", "unassigned-owner@company.com"),
                    support_group=self._first_value(account_df, "support_group", "finops-governance"),
                    workload_criticality=self._first_value(account_df, "workload_criticality", "medium"),
                    sla_tier=self._first_value(account_df, "sla_tier", "silver"),
                    waste_growth_rate=0.0,
                    anomaly_score=0.0,
                    metric_name="missing_required_tag_pct",
                    metric_value=missing_ratio,
                    owner_missing=True,
                    sla_breached=False,
                )
                signals.append(signal)

            unattributed_ratio = float(row["unattributed_usd"]) / max(float(row["nec_usd"]), 1.0)
            if unattributed_ratio >= self.unattributed_gap_threshold:
                signal = self._build_signal(
                    entity_type="account",
                    entity_id=f"{cloud}:{account_id}:{latest_month}:unattributed_cost_gap",
                    signal_type="unattributed_cost_gap",
                    metric_name="unattributed_nec_pct",
                    metric_value=unattributed_ratio,
                    threshold=self.unattributed_gap_threshold,
                    direction="above",
                    data_window="current_billing_month",
                    confidence_value=confidence_score(
                        data_complete,
                        signal_strength_score(unattributed_ratio, self.unattributed_gap_threshold, "above"),
                        0.80,
                        weights=self.scoring_config.confidence,
                    ),
                    created_at=created_at,
                )
                self._signal_context[signal["signal_id"]] = self._base_context(
                    billing_month=latest_month,
                    cloud=cloud,
                    team="unattributed",
                    account_id=account_id,
                    resource_id=None,
                    nec_impact_usd=float(row["unattributed_usd"]),
                    application=self._first_value(account_df, "application", "unassigned"),
                    environment=self._first_value(account_df, "environment", "nonprod"),
                    owner_email=self._first_value(account_df, "owner_email", "unassigned-owner@company.com"),
                    support_group=self._first_value(account_df, "support_group", "finops-governance"),
                    workload_criticality=self._first_value(account_df, "workload_criticality", "medium"),
                    sla_tier=self._first_value(account_df, "sla_tier", "silver"),
                    waste_growth_rate=0.0,
                    anomaly_score=0.0,
                    metric_name="unattributed_nec_pct",
                    metric_value=unattributed_ratio,
                    owner_missing=True,
                    sla_breached=True,
                )
                signals.append(signal)

        return signals

    def _team_signals(
        self,
        df: pd.DataFrame,
        latest_df: pd.DataFrame,
        latest_month: str,
        created_at: str,
    ) -> list[DecisionSignal]:
        team_scope = (
            latest_df.groupby(["cloud_provider", "team_name"], dropna=False)
            .agg(
                nec_usd=("nec", "sum"),
                commitment_waste_usd=("nec_waste", lambda s: float(s[latest_df.loc[s.index, "is_commitment_waste"].fillna(False)].sum())),
                commitment_covered_nec_usd=(
                    "nec_used",
                    lambda s: float(
                        s[latest_df.loc[s.index, "discount_type"].fillna("").isin(["ri", "sp", "cud"])].sum()
                    ),
                ),
                owner_email=("owner_email", "first"),
                application=("application", "first"),
                environment=("environment", "first"),
                support_group=("support_group", "first"),
                workload_criticality=("workload_criticality", "first"),
                sla_tier=("sla_tier", "first"),
            )
            .reset_index()
        )

        signals: list[DecisionSignal] = []
        for row in team_scope.to_dict("records"):
            cloud = str(row["cloud_provider"])
            team = str(row["team_name"])
            team_mask = (df["cloud_provider"] == cloud) & (df["team_name"] == team)
            team_df = df.loc[team_mask].copy()
            team_history = (
                team_df.groupby("billing_month", dropna=False)["nec"]
                .sum()
                .sort_index()
                .tolist()
            )
            history_stable = historical_stability_score(team_history)
            history_months = len(team_history)
            waste_growth = self._waste_growth_rate(team_df)
            anomaly = self._anomaly_score(team_history)
            data_complete = self._metadata_completeness(row)

            commitment_total = float(row["commitment_waste_usd"]) + float(row["commitment_covered_nec_usd"])
            commitment_utilization = 1.0 - (float(row["commitment_waste_usd"]) / max(commitment_total, 1.0))
            if float(row["commitment_waste_usd"]) > 0 and commitment_utilization < self.commitment_utilization_threshold:
                signal = self._build_signal(
                    entity_type="team",
                    entity_id=f"{cloud}:{team}:{latest_month}:commitment_waste",
                    signal_type="commitment_waste",
                    metric_name="commitment_utilization_pct",
                    metric_value=commitment_utilization,
                    threshold=self.commitment_utilization_threshold,
                    direction="below",
                    data_window=f"{min(history_months, 3)}_month_lookback",
                    confidence_value=confidence_score(
                        data_complete,
                        signal_strength_score(commitment_utilization, self.commitment_utilization_threshold, "below"),
                        history_stable,
                        weights=self.scoring_config.confidence,
                    ),
                    created_at=created_at,
                )
                self._signal_context[signal["signal_id"]] = self._base_context(
                    billing_month=latest_month,
                    cloud=cloud,
                    team=team,
                    account_id=None,
                    resource_id=None,
                    nec_impact_usd=float(row["commitment_waste_usd"]),
                    application=row.get("application"),
                    environment=row.get("environment"),
                    owner_email=row.get("owner_email"),
                    support_group=row.get("support_group"),
                    workload_criticality=row.get("workload_criticality"),
                    sla_tier=row.get("sla_tier"),
                    waste_growth_rate=waste_growth,
                    anomaly_score=anomaly,
                    metric_name="commitment_utilization_pct",
                    metric_value=commitment_utilization,
                    owner_missing=self._is_unassigned(row.get("owner_email")),
                    sla_breached=False,
                )
                signals.append(signal)

            if history_months >= 3 and anomaly >= self.anomaly_threshold:
                signal = self._build_signal(
                    entity_type="team",
                    entity_id=f"{cloud}:{team}:{latest_month}:cost_anomaly",
                    signal_type="cost_anomaly",
                    metric_name="anomaly_score",
                    metric_value=anomaly,
                    threshold=self.anomaly_threshold,
                    direction="above",
                    data_window=f"{min(history_months, 3)}_month_lookback",
                    confidence_value=confidence_score(
                        data_complete,
                        signal_strength_score(anomaly, self.anomaly_threshold, "above"),
                        history_stable,
                        weights=self.scoring_config.confidence,
                    ),
                    created_at=created_at,
                )
                prior_mean = sum(team_history[:-1]) / max(len(team_history[:-1]), 1)
                self._signal_context[signal["signal_id"]] = self._base_context(
                    billing_month=latest_month,
                    cloud=cloud,
                    team=team,
                    account_id=None,
                    resource_id=None,
                    nec_impact_usd=max(float(row["nec_usd"]) - prior_mean, 0.0),
                    application=row.get("application"),
                    environment=row.get("environment"),
                    owner_email=row.get("owner_email"),
                    support_group=row.get("support_group"),
                    workload_criticality=row.get("workload_criticality"),
                    sla_tier=row.get("sla_tier"),
                    waste_growth_rate=waste_growth,
                    anomaly_score=anomaly,
                    metric_name="anomaly_score",
                    metric_value=anomaly,
                    owner_missing=self._is_unassigned(row.get("owner_email")),
                    sla_breached=False,
                )
                signals.append(signal)

        return signals

    def _resource_signals(
        self,
        df: pd.DataFrame,
        latest_df: pd.DataFrame,
        latest_month: str,
        created_at: str,
    ) -> list[DecisionSignal]:
        if "resource_id" not in latest_df.columns:
            return []

        resource_scope = (
            latest_df[latest_df["resource_id"].notna()]
            .groupby(["cloud_provider", "resource_id"], dropna=False)
            .agg(
                team=("team_name", "first"),
                account_id=("account_id", "first"),
                application=("application", "first"),
                environment=("environment", "first"),
                owner_email=("owner_email", "first"),
                support_group=("support_group", "first"),
                workload_criticality=("workload_criticality", "first"),
                sla_tier=("sla_tier", "first"),
                service_category=("service_category", "first"),
                nec_impact_usd=("nec", "sum"),
                vcpu=("vcpu", "sum"),
            )
            .reset_index()
        )

        signals: list[DecisionSignal] = []
        for row in resource_scope.to_dict("records"):
            if str(row.get("service_category") or "Other") != "Compute":
                continue

            cloud = str(row["cloud_provider"])
            resource_id = str(row["resource_id"])
            resource_mask = (df["cloud_provider"] == cloud) & (df["resource_id"].astype(str) == resource_id)
            resource_df = df.loc[resource_mask]
            resource_history = (
                resource_df.groupby("billing_month", dropna=False)["nec"]
                .sum()
                .sort_index()
                .tolist()
            )
            history_months = len(resource_history)
            history_stable = historical_stability_score(resource_history)
            data_complete = self._metadata_completeness(row)
            nec_impact = float(row["nec_impact_usd"])
            vcpu = float(row.get("vcpu") or 0.0)
            billing_proxy = nec_impact / max(vcpu, 1.0) if vcpu > 0 else 0.0
            waste_growth = self._waste_growth_rate(resource_df)
            anomaly = self._anomaly_score(resource_history)

            if vcpu > 0 and nec_impact >= 5.0 and billing_proxy <= self.idle_nec_per_vcpu_threshold:
                signal = self._build_signal(
                    entity_type="resource",
                    entity_id=f"{cloud}:{resource_id}:{latest_month}:idle_compute_proxy",
                    signal_type="idle_compute_proxy",
                    metric_name="nec_per_vcpu_proxy",
                    metric_value=billing_proxy,
                    threshold=self.idle_nec_per_vcpu_threshold,
                    direction="below",
                    data_window=f"{min(history_months, 3)}_month_billing_proxy",
                    confidence_value=confidence_score(
                        data_complete,
                        signal_strength_score(billing_proxy, self.idle_nec_per_vcpu_threshold, "below"),
                        history_stable,
                        weights=self.scoring_config.confidence,
                    ),
                    created_at=created_at,
                )
                self._signal_context[signal["signal_id"]] = self._base_context(
                    billing_month=latest_month,
                    cloud=cloud,
                    team=row.get("team"),
                    account_id=row.get("account_id"),
                    resource_id=resource_id,
                    nec_impact_usd=nec_impact,
                    application=row.get("application"),
                    environment=row.get("environment"),
                    owner_email=row.get("owner_email"),
                    support_group=row.get("support_group"),
                    workload_criticality=row.get("workload_criticality"),
                    sla_tier=row.get("sla_tier"),
                    waste_growth_rate=waste_growth,
                    anomaly_score=anomaly,
                    metric_name="nec_per_vcpu_proxy",
                    metric_value=billing_proxy,
                    owner_missing=self._is_unassigned(row.get("owner_email")),
                    sla_breached=self._is_unassigned(row.get("owner_email")),
                )
                signals.append(signal)

            if nec_impact <= self.zombie_cost_threshold_usd:
                signal = self._build_signal(
                    entity_type="resource",
                    entity_id=f"{cloud}:{resource_id}:{latest_month}:zombie_resource",
                    signal_type="zombie_resource",
                    metric_name="nec_impact_usd",
                    metric_value=nec_impact,
                    threshold=self.zombie_cost_threshold_usd,
                    direction="below",
                    data_window=f"{min(history_months, 3)}_month_lookback",
                    confidence_value=confidence_score(
                        data_complete,
                        signal_strength_score(nec_impact, self.zombie_cost_threshold_usd, "below"),
                        history_stable,
                        weights=self.scoring_config.confidence,
                    ),
                    created_at=created_at,
                )
                self._signal_context[signal["signal_id"]] = self._base_context(
                    billing_month=latest_month,
                    cloud=cloud,
                    team=row.get("team"),
                    account_id=row.get("account_id"),
                    resource_id=resource_id,
                    nec_impact_usd=nec_impact,
                    application=row.get("application"),
                    environment=row.get("environment"),
                    owner_email=row.get("owner_email"),
                    support_group=row.get("support_group"),
                    workload_criticality=row.get("workload_criticality"),
                    sla_tier=row.get("sla_tier"),
                    waste_growth_rate=waste_growth,
                    anomaly_score=anomaly,
                    metric_name="nec_impact_usd",
                    metric_value=nec_impact,
                    owner_missing=self._is_unassigned(row.get("owner_email")),
                    sla_breached=self._is_unassigned(row.get("owner_email")),
                )
                signals.append(signal)

        return signals

    def _shared_cost_signals(
        self,
        latest_df: pd.DataFrame,
        latest_month: str,
        created_at: str,
    ) -> list[DecisionSignal]:
        if "is_shared_cost" not in latest_df.columns:
            return []

        shared_df = latest_df[latest_df["is_shared_cost"].fillna(False)].copy()
        if shared_df.empty:
            return []

        shared_scope = (
            shared_df.groupby(["cloud_provider", "team_name"], dropna=False)
            .agg(
                shared_cost_nec=("nec", "sum"),
                owner_email=("owner_email", "first"),
                application=("application", "first"),
                environment=("environment", "first"),
                support_group=("support_group", "first"),
                workload_criticality=("workload_criticality", "first"),
                sla_tier=("sla_tier", "first"),
            )
            .reset_index()
        )

        cloud_totals = shared_df.groupby("cloud_provider")["nec"].sum().to_dict()
        signals: list[DecisionSignal] = []
        for row in shared_scope.to_dict("records"):
            cloud = str(row["cloud_provider"])
            team = str(row["team_name"])
            share = float(row["shared_cost_nec"]) / max(float(cloud_totals.get(cloud, 0.0)), 1.0)
            if share < self.shared_cost_concentration_threshold:
                continue

            signal = self._build_signal(
                entity_type="team",
                entity_id=f"{cloud}:{team}:{latest_month}:shared_cost_concentration",
                signal_type="shared_cost_concentration",
                metric_name="shared_cost_share_pct",
                metric_value=share,
                threshold=self.shared_cost_concentration_threshold,
                direction="above",
                data_window="current_billing_month",
                confidence_value=confidence_score(
                    0.85,
                    signal_strength_score(share, self.shared_cost_concentration_threshold, "above"),
                    0.80,
                    weights=self.scoring_config.confidence,
                ),
                created_at=created_at,
            )
            self._signal_context[signal["signal_id"]] = self._base_context(
                billing_month=latest_month,
                cloud=cloud,
                team=team,
                account_id=None,
                resource_id=None,
                nec_impact_usd=float(row["shared_cost_nec"]),
                application=row.get("application"),
                environment=row.get("environment"),
                owner_email=row.get("owner_email"),
                support_group=row.get("support_group"),
                workload_criticality=row.get("workload_criticality"),
                sla_tier=row.get("sla_tier"),
                waste_growth_rate=0.0,
                anomaly_score=0.0,
                metric_name="shared_cost_share_pct",
                metric_value=share,
                owner_missing=self._is_unassigned(row.get("owner_email")),
                sla_breached=False,
            )
            signals.append(signal)

        return signals

    def _forecast_signals(
        self,
        df: pd.DataFrame,
        latest_df: pd.DataFrame,
        latest_month: str,
        created_at: str,
    ) -> list[DecisionSignal]:
        team_rows = (
            latest_df.groupby(["cloud_provider", "team_name"], dropna=False)
            .agg(
                owner_email=("owner_email", "first"),
                application=("application", "first"),
                environment=("environment", "first"),
                support_group=("support_group", "first"),
                workload_criticality=("workload_criticality", "first"),
                sla_tier=("sla_tier", "first"),
            )
            .reset_index()
        )

        signals: list[DecisionSignal] = []
        for row in team_rows.to_dict("records"):
            cloud = str(row["cloud_provider"])
            team = str(row["team_name"])
            team_df = df[(df["cloud_provider"] == cloud) & (df["team_name"] == team)].copy()
            latest_usage = pd.to_datetime(
                latest_df[
                    (latest_df["cloud_provider"] == cloud)
                    & (latest_df["team_name"] == team)
                ].get("usage_date"),
                errors="coerce",
            )
            if latest_usage.notna().any():
                as_of_date = latest_usage.max().date()
            else:
                as_of_date = date.today()

            forecast = build_forecast(
                team_df,
                recommendations=[],
                target_month=latest_month,
                as_of_date=as_of_date,
            )
            if forecast.forecast_risk_level not in {"medium", "high"}:
                continue

            denominator = max(forecast.trailing_3_month_avg_nec, 1.0)
            forecast_growth = max((forecast.projected_nec / denominator) - 1.0, 0.0)
            signal = self._build_signal(
                entity_type="team",
                entity_id=f"{cloud}:{team}:{latest_month}:forecasted_month_end_risk",
                signal_type="forecasted_month_end_risk",
                metric_name="forecast_growth_pct",
                metric_value=forecast_growth,
                threshold=self.forecast_risk_threshold,
                direction="above",
                data_window="3_month_blended_forecast" if forecast.minimum_data_met else "current_month_run_rate",
                confidence_value=forecast.confidence,
                created_at=created_at,
            )
            self._signal_context[signal["signal_id"]] = self._base_context(
                billing_month=latest_month,
                cloud=cloud,
                team=team,
                account_id=None,
                resource_id=None,
                nec_impact_usd=max(forecast.projected_nec - forecast.trailing_3_month_avg_nec, 0.0),
                application=row.get("application"),
                environment=row.get("environment"),
                owner_email=row.get("owner_email"),
                support_group=row.get("support_group"),
                workload_criticality=row.get("workload_criticality"),
                sla_tier=row.get("sla_tier"),
                waste_growth_rate=0.0,
                anomaly_score=0.0,
                metric_name="forecast_growth_pct",
                metric_value=forecast_growth,
                owner_missing=self._is_unassigned(row.get("owner_email")),
                sla_breached=False,
            )
            signals.append(signal)

        return signals

    def generate_candidate_recommendations(
        self,
        signals: list[DecisionSignal],
    ) -> list[CanonicalRecommendation]:
        recommendations: list[CanonicalRecommendation] = []
        created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        corroborating_counts: dict[str, int] = {}
        for signal in signals:
            corroborating_counts[signal["entity_id"]] = corroborating_counts.get(signal["entity_id"], 0) + 1
        for signal in signals:
            context = self._signal_context[signal["signal_id"]]
            action_type = RECOMMENDATION_ACTION[signal["signal_type"]]
            risk_value = risk_score(
                str(context.get("workload_criticality", "medium")),
                str(context.get("environment", "nonprod")),
                str(context.get("sla_tier", "silver")),
                action_type,
            )
            approval_required = (
                risk_value >= 60
                or str(context.get("environment", "")).lower() == "prod"
                or str(context.get("workload_criticality", "")).lower() in {"high", "mission_critical"}
            )
            urgency_value = urgency_score(
                float(context.get("waste_growth_rate", 0.0)),
                float(context.get("anomaly_score", 0.0)),
                weights=self.scoring_config.urgency,
            )
            governance_severity = governance_severity_score(
                signal["signal_type"],
                owner_missing=bool(context.get("owner_missing", False)),
                sla_breached=bool(context.get("sla_breached", False)),
            )
            persistent_periods = 3 if "3_month" in str(signal.get("data_window", "")) else 1
            calibrated_confidence = calibrated_confidence_score(
                float(signal["confidence"]),
                persistent_periods=persistent_periods,
                corroborating_signals=corroborating_counts.get(signal["entity_id"], 1),
                anomaly_score=float(context.get("anomaly_score", 0.0)),
            )
            low_risk_bonus = low_risk_bonus_score(
                risk_score_value=risk_value,
                approval_required=approval_required,
                action_type=action_type,
            )
            nec_impact = float(context.get("nec_impact_usd", 0.0))
            savings_estimate = savings_estimate_usd(signal["signal_type"], nec_impact)

            recommendations.append(
                CanonicalRecommendation(
                    recommendation_id=self._recommendation_id(signal, action_type),
                    entity_id=signal["entity_id"],
                    resource_id=context.get("resource_id"),
                    team=str(context.get("team") or "unattributed"),
                    cloud=str(context.get("cloud") or "multi-cloud"),
                    action_type=action_type,
                    root_cause_type=ROOT_CAUSE_BY_SIGNAL[signal["signal_type"]],
                    nec_impact_usd=round(nec_impact, 2),
                    savings_estimate_usd=round(savings_estimate, 2),
                    priority_score=0.0,
                    confidence=calibrated_confidence,
                    risk_score=risk_value,
                    effort_score=effort_score(action_type),
                    urgency_score=round(urgency_value, 6),
                    time_to_value_days=time_to_value_days(action_type, approval_required),
                    evidence_strength=evidence_strength([signal["signal_weight"]]),
                    signal_ids=[signal["signal_id"]],
                    status="recommended",
                    owner=str(context.get("owner_email") or "unassigned-owner@company.com"),
                    approval_required=approval_required,
                    created_at=created_at,
                    implemented_at=None,
                    verified_at=None,
                    realized_savings_usd=0.0,
                    explanation={
                        "issue_type": signal["signal_type"],
                        "root_cause_type": ROOT_CAUSE_LABEL[signal["signal_type"]],
                        "evidence": [signal],
                        "decision_basis": {
                            "confidence": calibrated_confidence,
                            "risk_score": risk_value,
                            "urgency_score": round(urgency_value, 6),
                            "effort_score": effort_score(action_type),
                            "governance_severity": governance_severity,
                            "low_risk_bonus": low_risk_bonus,
                            "approval_required": approval_required,
                            "persistent_periods": persistent_periods,
                            "corroborating_signals": corroborating_counts.get(signal["entity_id"], 1),
                        },
                        "rejected_alternatives": [],
                    },
                )
            )
        return recommendations

    def score_candidates(self, recommendations: list[CanonicalRecommendation]) -> list[CanonicalRecommendation]:
        if not recommendations:
            return []
        max_savings = max(float(rec["savings_estimate_usd"]) for rec in recommendations) or 1.0
        scored: list[CanonicalRecommendation] = []
        for rec in recommendations:
            governance_value = float(rec["explanation"]["decision_basis"]["governance_severity"])
            low_risk_bonus = float(rec["explanation"]["decision_basis"]["low_risk_bonus"])
            normalized_savings = normalize_savings(float(rec["savings_estimate_usd"]), max_savings)
            score = priority_score(
                normalized_savings=normalized_savings,
                confidence_score_value=float(rec["confidence"]),
                governance_severity_value=governance_value,
                urgency_score_value=float(rec["urgency_score"]),
                low_risk_bonus_value=low_risk_bonus,
                weights=self.scoring_config.priority,
            )
            updated = dict(rec)
            updated["priority_score"] = score
            updated["explanation"] = {
                **rec["explanation"],
                "decision_basis": {
                    **rec["explanation"]["decision_basis"],
                    "normalized_savings": normalized_savings,
                    "priority_score": score,
                    "max_savings_in_scope": round(max_savings, 2),
                },
            }
            scored.append(CanonicalRecommendation(**updated))
        return scored

    def select_decisions(self, recommendations: list[CanonicalRecommendation]) -> list[CanonicalDecision]:
        if not recommendations:
            return []

        grouped: dict[str, list[CanonicalRecommendation]] = {}
        for rec in recommendations:
            grouped.setdefault(rec["entity_id"], []).append(rec)

        decisions: list[CanonicalDecision] = []
        for entity_id, candidates in grouped.items():
            ranked = sorted(
                candidates,
                key=lambda rec: (
                    rec["priority_score"],
                    rec["confidence"],
                    rec["savings_estimate_usd"],
                    -rec["risk_score"],
                ),
                reverse=True,
            )
            selected = ranked[0]
            rejected = [
                {
                    "recommendation_id": rec["recommendation_id"],
                    "action_type": rec["action_type"],
                    "priority_score": rec["priority_score"],
                    "reason": "Lower FinOps priority score than selected recommendation.",
                }
                for rec in ranked[1:]
            ]
            selected["explanation"] = {
                **selected["explanation"],
                "rejected_alternatives": rejected,
            }
            decisions.append(
                CanonicalDecision(
                    decision_id=self._decision_id(entity_id, selected["recommendation_id"]),
                    entity_id=entity_id,
                    candidate_recommendations=[rec["recommendation_id"] for rec in ranked],
                    selected_recommendation=selected["recommendation_id"],
                    decision_score=selected["priority_score"],
                    decision_reason=(
                        f"Selected `{selected['action_type']}` because `{selected['root_cause_type']}` "
                        f"had the highest FinOps priority score ({selected['priority_score']:.3f})."
                    ),
                    competing_scores={rec["recommendation_id"]: rec["priority_score"] for rec in ranked},
                    created_at=selected["created_at"],
                )
            )
        return decisions

    def rank_recommendations(self, recommendations: list[CanonicalRecommendation]) -> list[CanonicalRecommendation]:
        return sorted(
            recommendations,
            key=lambda rec: (
                rec["priority_score"],
                rec["savings_estimate_usd"],
                rec["confidence"],
            ),
            reverse=True,
        )

    def _build_signal(
        self,
        *,
        entity_type: str,
        entity_id: str,
        signal_type: str,
        metric_name: str,
        metric_value: float,
        threshold: float,
        direction: str,
        data_window: str,
        confidence_value: float,
        created_at: str,
    ) -> DecisionSignal:
        raw = "|".join([entity_type, entity_id, signal_type, metric_name, f"{metric_value:.6f}"])
        return DecisionSignal(
            signal_id=hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16],
            entity_type=entity_type,
            entity_id=entity_id,
            signal_type=signal_type,
            metric_name=metric_name,
            metric_value=float(metric_value),
            threshold=float(threshold),
            direction=direction,
            data_window=data_window,
            signal_weight=SIGNAL_WEIGHT[signal_type],
            confidence=round(confidence_value, 6),
            created_at=created_at,
        )

    @staticmethod
    def _base_context(**kwargs) -> dict:
        return kwargs

    @staticmethod
    def _metadata_completeness(row: dict) -> float:
        available = sum(bool(str(row.get(field) or "").strip()) for field in ("environment", "application", "owner_email", "support_group", "workload_criticality", "sla_tier"))
        return data_completeness_score(available, 6)

    @staticmethod
    def _first_value(df: pd.DataFrame, column: str, default: str) -> str:
        if column not in df.columns or df.empty:
            return default
        series = df[column].dropna()
        if series.empty:
            return default
        value = series.iloc[0]
        return default if str(value).strip() == "" else str(value)

    @staticmethod
    def _is_unassigned(value: object) -> bool:
        text = str(value or "").strip().lower()
        return text == "" or text.startswith("unassigned")

    @staticmethod
    def _waste_growth_rate(scope_df: pd.DataFrame) -> float:
        if scope_df.empty or "nec_waste" not in scope_df.columns:
            return 0.0
        monthly = (
            scope_df.groupby("billing_month", dropna=False)["nec_waste"]
            .sum()
            .sort_index()
        )
        if len(monthly) < 2:
            return 0.0
        previous = float(monthly.iloc[-2])
        latest = float(monthly.iloc[-1])
        if previous <= 0:
            return 0.0 if latest <= 0 else 1.0
        return max((latest - previous) / previous, 0.0)

    @staticmethod
    def _anomaly_score(values: list[float]) -> float:
        history = [float(v) for v in values if v is not None]
        if len(history) < 3:
            return 0.0
        prior = history[:-1]
        latest = history[-1]
        mean_value = sum(prior) / len(prior)
        variance = sum((v - mean_value) ** 2 for v in prior) / len(prior)
        stddev = variance ** 0.5
        if stddev <= 1e-12:
            return 0.0
        return abs(latest - mean_value) / stddev

    @staticmethod
    def _recommendation_id(signal: DecisionSignal, action_type: str) -> str:
        raw = "|".join([signal["signal_id"], action_type])
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _decision_id(entity_id: str, recommendation_id: str) -> str:
        raw = "|".join([entity_id, recommendation_id])
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def example_run() -> DecisionRun:
    sample = pd.DataFrame(
        [
            {
                "billing_month": "2026-01",
                "usage_date": pd.Timestamp("2026-01-01"),
                "cloud_provider": "aws",
                "allocated_team": "platform",
                "account_id": "123456789012",
                "resource_id": "i-prod-001",
                "application": "platform-core",
                "environment": "prod",
                "owner_email": "platform-owner@company.com",
                "support_group": "platform-operations",
                "workload_criticality": "mission_critical",
                "sla_tier": "platinum",
                "service_category": "Compute",
                "discount_type": "sp",
                "is_tagged": False,
                "is_shared_cost": False,
                "is_commitment_waste": True,
                "cost_center": None,
                "nec": 140.0,
                "nec_used": 85.0,
                "nec_waste": 55.0,
                "vcpu": 64,
            },
            {
                "billing_month": "2026-02",
                "usage_date": pd.Timestamp("2026-02-01"),
                "cloud_provider": "aws",
                "allocated_team": "platform",
                "account_id": "123456789012",
                "resource_id": "i-prod-001",
                "application": "platform-core",
                "environment": "prod",
                "owner_email": "platform-owner@company.com",
                "support_group": "platform-operations",
                "workload_criticality": "mission_critical",
                "sla_tier": "platinum",
                "service_category": "Compute",
                "discount_type": "sp",
                "is_tagged": False,
                "is_shared_cost": False,
                "is_commitment_waste": True,
                "cost_center": None,
                "nec": 150.0,
                "nec_used": 90.0,
                "nec_waste": 60.0,
                "vcpu": 64,
            },
            {
                "billing_month": "2026-03",
                "usage_date": pd.Timestamp("2026-03-01"),
                "cloud_provider": "aws",
                "allocated_team": "platform",
                "account_id": "123456789012",
                "resource_id": "i-prod-001",
                "application": "platform-core",
                "environment": "prod",
                "owner_email": "platform-owner@company.com",
                "support_group": "platform-operations",
                "workload_criticality": "mission_critical",
                "sla_tier": "platinum",
                "service_category": "Compute",
                "discount_type": "sp",
                "is_tagged": False,
                "is_shared_cost": False,
                "is_commitment_waste": True,
                "cost_center": None,
                "nec": 160.0,
                "nec_used": 95.0,
                "nec_waste": 65.0,
                "vcpu": 64,
            },
            {
                "billing_month": "2026-04",
                "usage_date": pd.Timestamp("2026-04-15"),
                "cloud_provider": "aws",
                "allocated_team": "platform",
                "account_id": "123456789012",
                "resource_id": "i-prod-001",
                "application": "platform-core",
                "environment": "prod",
                "owner_email": "platform-owner@company.com",
                "support_group": "platform-operations",
                "workload_criticality": "mission_critical",
                "sla_tier": "platinum",
                "service_category": "Compute",
                "discount_type": "sp",
                "is_tagged": False,
                "is_shared_cost": False,
                "is_commitment_waste": True,
                "cost_center": None,
                "nec": 175.0,
                "nec_used": 100.0,
                "nec_waste": 75.0,
                "vcpu": 64,
            },
        ]
    )
    return DecisionEngine().run(sample)
