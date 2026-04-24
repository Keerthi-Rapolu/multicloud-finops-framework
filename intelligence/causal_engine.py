"""
Causal Reasoning Engine.

Explains WHY cloud cost looks the way it does for each team, by reasoning over
structured facts derived from fct_unified_billing and the waste detector output.

Design constraints (Phase 2):
  - No external event stream (no CloudWatch, no deployment logs).
  - All facts are derived from billing data alone.
  - Works with a single billing month (facts from billing patterns).
  - Strengthens automatically when multiple months are loaded (MoM trend + z-score).

Pipeline:
  build_nec_trend(df)          → per-team NEC by month, with MoM pct_change
  compute_zscore_anomaly(df)   → flag latest period as anomaly (needs ≥3 months)
  build_causal_facts(df, wf)   → list of Fact dicts per team
  reason(facts, trend, scope)  → CausalInsight for one team
  run(df, waste_findings)      → list[CausalInsight], one per team

Entry point: run(df, waste_findings) → list[CausalInsight]
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from intelligence import CausalInsight, RootCause


# ---------------------------------------------------------------------------
# Internal Fact dataclass
# ---------------------------------------------------------------------------

@dataclass
class _Fact:
    """A single causal signal scoped to a team (or global)."""
    scope:      str          # team name or '_global'
    fact_type:  str          # see FACT_TYPES below
    cause:      str          # human-readable label for RootCause.cause
    evidence:   str          # one-sentence supporting detail
    weight:     float        # 0.0 – 1.0 relative importance
    data:       dict = field(default_factory=dict)  # raw supporting values


# Ordered priority — higher index = checked last (lower priority in ranking)
FACT_PRIORITY = [
    "commitment_waste_identified",
    "idle_resources_detected",
    "team_cost_spike",
    "untagged_cost_gap",
    "service_category_dominance",
]


# ---------------------------------------------------------------------------
# 6A — build_nec_trend
# ---------------------------------------------------------------------------

def build_nec_trend(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-team NEC by billing month with month-over-month pct_change.

    Returns a DataFrame with columns:
        billing_month, allocated_team, period_nec, pct_change

    pct_change is NaN for the first month of each team (no prior period).
    With a single billing month all pct_change values will be NaN.
    """
    team_month = (
        df.groupby(["billing_month", "allocated_team"], dropna=False)["nec_used"]
        .sum()
        .reset_index()
        .rename(columns={"nec_used": "period_nec", "allocated_team": "allocated_team"})
        .sort_values(["allocated_team", "billing_month"])
    )

    team_month["pct_change"] = (
        team_month
        .groupby("allocated_team", dropna=False)["period_nec"]
        .pct_change() * 100
    )

    return team_month.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 6B — compute_zscore_anomaly
# ---------------------------------------------------------------------------

def compute_zscore_anomaly(
    trend_df: pd.DataFrame,
    threshold: float = 2.0,
    min_periods: int = 3,
) -> pd.DataFrame:
    """
    Add an `anomaly` boolean column to the trend DataFrame.

    For each team, the latest period is flagged as anomalous if its z-score
    relative to all prior periods exceeds `threshold`.

    With fewer than `min_periods` observations the flag is always False —
    documented in paper section 8 as a known limitation.
    """
    out = trend_df.copy()
    out["z_score"] = np.nan
    out["anomaly"] = False

    for team, grp in out.groupby("allocated_team", dropna=False):
        if len(grp) < min_periods:
            continue
        grp_sorted = grp.sort_values("billing_month")
        values = grp_sorted["period_nec"].values
        # Compute z-score for each point relative to all prior values
        z_scores = []
        for i, v in enumerate(values):
            prior = values[:i]
            if len(prior) < 2:
                z_scores.append(np.nan)
                continue
            mean, std = prior.mean(), prior.std()
            if std > 0:
                z_scores.append((v - mean) / std)
            elif v != mean:
                # std=0 means all prior values identical; any deviation is extreme
                z_scores.append(float("inf"))
            else:
                z_scores.append(0.0)
        idx = grp_sorted.index
        out.loc[idx, "z_score"] = z_scores
        out.loc[idx, "anomaly"] = [
            (abs(z) > threshold if (not np.isnan(z) and not np.isinf(z)) else bool(np.isinf(z)))
            for z in z_scores
        ]

    return out


# ---------------------------------------------------------------------------
# 6C — build_causal_facts
# ---------------------------------------------------------------------------

def build_causal_facts(
    df: pd.DataFrame,
    waste_findings: list[dict],
) -> list[_Fact]:
    """
    Derive structured causal facts from billing data and waste findings.

    Produces facts scoped to individual teams and a '_global' scope.
    Each Fact has a weight that reflects how strongly it explains cost behaviour.
    """
    facts: list[_Fact] = []
    teams = [t for t in df["allocated_team"].dropna().unique()]

    # ------------------------------------------------------------------
    # Per-team facts
    # ------------------------------------------------------------------
    for team in teams:
        team_df = df[df["allocated_team"] == team]
        team_nec = team_df["nec_used"].sum()
        if team_nec <= 0:
            continue

        # Fact: commitment waste identified
        team_waste = [
            f for f in waste_findings
            if f["allocated_team"] == team
            and f["waste_type"] in ("unused_commitment", "underutilized_commitment")
        ]
        if team_waste:
            waste_total = sum(
                f["nec_waste"] if f["nec_waste"] > 0 else f["nec_used"]
                for f in team_waste
            )
            waste_pct = waste_total / team_nec * 100
            facts.append(_Fact(
                scope=team,
                fact_type="commitment_waste_identified",
                cause="commitment_waste_identified",
                evidence=(
                    f"${waste_total:,.2f} ({waste_pct:.1f}% of team NEC) in "
                    f"unused or underutilised RI/SP commitments."
                ),
                weight=0.90,
                data={"waste_total": waste_total, "waste_pct": waste_pct,
                      "n_findings": len(team_waste)},
            ))

        # Fact: idle / zombie resources
        team_idle = [
            f for f in waste_findings
            if f["allocated_team"] == team
            and f["waste_type"] in ("idle_compute", "zombie_resource")
        ]
        if team_idle:
            idle_nec = sum(
                f["nec_waste"] if f["nec_waste"] > 0 else f["nec_used"]
                for f in team_idle
            )
            facts.append(_Fact(
                scope=team,
                fact_type="idle_resources_detected",
                cause="idle_resources_detected",
                evidence=(
                    f"{len(team_idle)} idle or zombie resource(s) found "
                    f"accounting for ${idle_nec:,.2f} in avoidable spend."
                ),
                weight=0.75,
                data={"n_resources": len(team_idle), "idle_nec": idle_nec},
            ))

        # Fact: untagged cost gap
        untagged_nec = team_df.loc[~team_df["is_tagged"].fillna(False), "nec_used"].sum()
        untagged_pct = untagged_nec / team_nec * 100 if team_nec else 0
        if untagged_pct >= 10:
            facts.append(_Fact(
                scope=team,
                fact_type="untagged_cost_gap",
                cause="untagged_cost_gap",
                evidence=(
                    f"{untagged_pct:.1f}% of team NEC (${untagged_nec:,.2f}) "
                    f"is untagged — cost cannot be fully attributed."
                ),
                weight=0.60,
                data={"untagged_pct": untagged_pct, "untagged_nec": untagged_nec},
            ))

        # Fact: single service category dominance
        by_svc = team_df.groupby("service_category")["nec_used"].sum()
        if not by_svc.empty:
            top_svc = by_svc.idxmax()
            top_pct = by_svc.max() / team_nec * 100
            if top_pct >= 50:
                facts.append(_Fact(
                    scope=team,
                    fact_type="service_category_dominance",
                    cause="service_category_dominance",
                    evidence=(
                        f"{top_svc} accounts for {top_pct:.1f}% of team NEC "
                        f"(${by_svc.max():,.2f}) — optimising this category "
                        f"has the highest leverage."
                    ),
                    weight=0.50,
                    data={"service": top_svc, "pct": top_pct},
                ))

    # ------------------------------------------------------------------
    # Global facts (apply to all teams as context)
    # ------------------------------------------------------------------
    total_nec   = df["nec_used"].sum()
    total_waste = df["nec_waste"].sum()
    waste_pct   = total_waste / total_nec * 100 if total_nec else 0

    if waste_pct >= 5:
        facts.append(_Fact(
            scope="_global",
            fact_type="commitment_waste_increased",
            cause="commitment_waste_identified",
            evidence=(
                f"Portfolio-wide commitment waste is {waste_pct:.1f}% of NEC "
                f"(${total_waste:,.2f}) — review RI/SP sizing across all teams."
            ),
            weight=0.80,
            data={"waste_pct": waste_pct, "total_waste": total_waste},
        ))

    return facts


# ---------------------------------------------------------------------------
# 6D — reason
# ---------------------------------------------------------------------------

def reason(
    facts: list[_Fact],
    trend_df: pd.DataFrame,
    team: str,
) -> CausalInsight:
    """
    Build a CausalInsight for a single team from the pre-computed facts and trend.

    Root causes are ranked by weight and capped at 3. If no team-specific facts
    exist the global facts are used as fallback so the insight is never empty.
    """
    # Gather facts for this team + global context
    team_facts  = [f for f in facts if f.scope == team]
    global_facts = [f for f in facts if f.scope == "_global"]
    combined    = team_facts + global_facts

    # Cost change from trend (latest period for this team)
    team_trend = trend_df[trend_df["allocated_team"] == team]
    if not team_trend.empty:
        latest = team_trend.sort_values("billing_month").iloc[-1]
        cost_change_pct = float(latest["pct_change"]) if not _isnan(latest["pct_change"]) else 0.0
        anomaly = bool(latest.get("anomaly", False))
    else:
        cost_change_pct = 0.0
        anomaly = False

    # If MoM cost increased significantly, add a spike fact
    if cost_change_pct > 15:
        combined.append(_Fact(
            scope=team,
            fact_type="team_cost_spike",
            cause="team_cost_spike",
            evidence=(
                f"Team NEC increased {cost_change_pct:+.1f}% month-over-month — "
                f"investigate recent deployments or resource additions."
            ),
            weight=0.85,
            data={"cost_change_pct": cost_change_pct},
        ))
    elif cost_change_pct < -15:
        combined.append(_Fact(
            scope=team,
            fact_type="team_cost_spike",
            cause="team_cost_decrease",
            evidence=(
                f"Team NEC decreased {cost_change_pct:+.1f}% month-over-month — "
                f"likely from decommissioning or increased commitment coverage."
            ),
            weight=0.70,
            data={"cost_change_pct": cost_change_pct},
        ))

    # Sort by priority then weight
    priority_order = {k: i for i, k in enumerate(FACT_PRIORITY)}
    combined.sort(
        key=lambda f: (priority_order.get(f.fact_type, 99), -f.weight)
    )

    # De-duplicate by cause label (keep highest weight)
    seen: dict[str, _Fact] = {}
    for f in combined:
        if f.cause not in seen or f.weight > seen[f.cause].weight:
            seen[f.cause] = f

    top_facts = list(seen.values())[:3]

    root_causes: list[RootCause] = [
        RootCause(cause=f.cause, evidence=f.evidence, weight=round(f.weight, 2))
        for f in top_facts
    ]

    # Confidence = weighted average of top facts; floor at 0.40 so insight is
    # always expressed even when only global facts are available.
    if root_causes:
        weights = [rc["weight"] for rc in root_causes]
        confidence = round(sum(weights) / len(weights), 2)
    else:
        confidence = 0.40

    # If truly no facts exist, add a baseline cause
    if not root_causes:
        root_causes.append(RootCause(
            cause="no_anomalies_detected",
            evidence="No significant waste, drift, or attribution issues detected for this team.",
            weight=0.40,
        ))

    # Latest billing month as the period
    period = trend_df["billing_month"].max() if not trend_df.empty else "unknown"

    return CausalInsight(
        scope=f"team:{team}",
        period=str(period),
        cost_change_pct=round(cost_change_pct, 1),
        root_causes=root_causes,
        confidence=min(confidence, 1.0),
        anomaly=anomaly,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _isnan(v) -> bool:
    try:
        return bool(np.isnan(v))
    except (TypeError, ValueError):
        return False


def _get_teams(df: pd.DataFrame) -> list[str]:
    """Return distinct non-null allocated_team values."""
    return sorted(t for t in df["allocated_team"].dropna().unique())


# ---------------------------------------------------------------------------
# 6E — run  (entry point)
# ---------------------------------------------------------------------------

def run(
    df: pd.DataFrame,
    waste_findings: list[dict],
) -> list[CausalInsight]:
    """
    Run the full causal reasoning pipeline and return one CausalInsight per team.

    Parameters
    ----------
    df            : fct_unified_billing DataFrame (one or more billing months).
    waste_findings: output of intelligence.waste_detector.run(df).

    Returns
    -------
    list[CausalInsight] sorted by abs(cost_change_pct) descending so the
    biggest movers appear first in the dashboard.
    """
    trend  = build_nec_trend(df)
    trend  = compute_zscore_anomaly(trend)
    facts  = build_causal_facts(df, waste_findings)
    teams  = _get_teams(df)

    insights = [reason(facts, trend, team) for team in teams]

    return sorted(
        insights,
        key=lambda i: abs(i["cost_change_pct"]),
        reverse=True,
    )


# ---------------------------------------------------------------------------
# CLI — python -m intelligence.causal_engine
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    from pathlib import Path
    import duckdb
    from intelligence.waste_detector import run as detect_waste

    parser = argparse.ArgumentParser(description="Run causal engine against DuckDB mart.")
    parser.add_argument("--db", default="finops_dbt.duckdb")
    parser.add_argument("--month", default=None)
    args = parser.parse_args()

    db = Path(args.db)
    if not db.exists():
        raise FileNotFoundError(f"DuckDB not found at {db}. Run `dbt run` first.")

    con = duckdb.connect(str(db), read_only=True)
    query = "SELECT * FROM marts.fct_unified_billing"
    if args.month:
        query += f" WHERE billing_month = '{args.month}'"
    df = con.execute(query).df()
    con.close()

    findings = detect_waste(df)
    insights = run(df, findings)

    print(f"\nCausal insights: {len(insights)}\n")
    for ins in insights:
        change = ins["cost_change_pct"]
        arrow  = "▲" if change > 0 else ("▼" if change < 0 else "→")
        print(f"  {ins['scope']:20s}  {arrow}{abs(change):5.1f}%  "
              f"anomaly={ins['anomaly']}  confidence={ins['confidence']:.2f}")
        for rc in ins["root_causes"]:
            print(f"    • [{rc['weight']:.2f}] {rc['cause']}: {rc['evidence'][:80]}")
        print()