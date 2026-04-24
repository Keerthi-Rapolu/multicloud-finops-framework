"""
Impact Simulator.

Converts WasteFinding objects from the waste detector into prioritised
Recommendation dicts, estimating recoverable savings and assigning risk levels.

Design constraints (Phase 2):
  - Input: list[WasteFinding] from waste_detector.run()
  - Output: list[Recommendation] sorted by priority_score DESC
  - No external pricing APIs — savings derived from billing waste signals only
  - Conservative recovery rates (see RECOVERY_RATES)

Pipeline:
  action_for_waste_type(waste_type) → ActionType string
  estimate_savings(finding)         → (estimated_savings, savings_pct)
  risk_score(finding)               → RiskLevel string
  build_rationale(finding, action, savings) → str
  run(waste_findings)               → list[Recommendation]

Entry point: run(waste_findings) → list[Recommendation]
"""

from __future__ import annotations

from intelligence import Recommendation

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACTION_MAP: dict[str, str] = {
    "unused_commitment":        "release_commitment",
    "idle_compute":             "resize_down",
    "zombie_resource":          "remove_resource",
    "underutilized_commitment": "release_commitment",
}

# Conservative: fraction of the waste signal that is realistically recoverable
RECOVERY_RATES: dict[str, float] = {
    "unused_commitment":        1.00,  # 100% — commitment can be fully released
    "idle_compute":             0.80,  # 80%  — right-sizing saves most but not all
    "zombie_resource":          1.00,  # 100% — full removal eliminates all spend
    "underutilized_commitment": 0.60,  # 60%  — partial right-sizing avoids early-exit penalty
}

RISK_MAP: dict[str, str] = {
    "unused_commitment":        "Low",
    "idle_compute":             "Medium",
    "zombie_resource":          "Low",
    "underutilized_commitment": "High",
}

# Effort to execute: "Low" = 1-click, "Medium" = needs approval + testing, "High" = migration
EFFORT_MAP: dict[str, str] = {
    "release_commitment": "Low",    # single API call or console click
    "resize_down":        "Medium", # requires workload testing + team approval
    "remove_resource":    "Low",    # manual verify + delete
}

# When savings appear in billing after action taken
TIME_MAP: dict[str, str] = {
    "release_commitment": "Immediate",  # next billing cycle (~days)
    "resize_down":        "1 week",     # test period + resize window
    "remove_resource":    "Immediate",  # next billing cycle
}

# Effort hours per level — used to compute ROI (annual savings / hours of work)
_EFFORT_HOURS: dict[str, float] = {"Low": 1.0, "Medium": 4.0, "High": 16.0}

_MIN_SAVINGS = 1.00  # recommendations below this dollar threshold are suppressed


# ---------------------------------------------------------------------------
# 9A — action_for_waste_type
# ---------------------------------------------------------------------------

def action_for_waste_type(waste_type: str) -> str:
    """Map a waste type to the recommended remediation action."""
    return ACTION_MAP[waste_type]


# ---------------------------------------------------------------------------
# 9B — estimate_savings
# ---------------------------------------------------------------------------

def estimate_savings(finding: dict) -> tuple[float, float]:
    """
    Return (estimated_savings, savings_pct) for a WasteFinding.

    For commitment findings the waste signal is in nec_waste; for idle_compute
    and zombie_resource the cost is in nec_used (nec_waste is 0).
    """
    base = finding["nec_waste"] if finding["nec_waste"] > 0 else finding["nec_used"]
    rate = RECOVERY_RATES[finding["waste_type"]]
    estimated_savings = base * rate
    total_cost = finding["nec_used"] + finding["nec_waste"]
    savings_pct = estimated_savings / total_cost * 100 if total_cost > 0 else 0.0
    return estimated_savings, savings_pct


# ---------------------------------------------------------------------------
# 9C — risk_score
# ---------------------------------------------------------------------------

def risk_score(finding: dict) -> str:
    """Return 'Low', 'Medium', or 'High' risk level for a WasteFinding."""
    return RISK_MAP[finding["waste_type"]]


# ---------------------------------------------------------------------------
# 9D — build_rationale
# ---------------------------------------------------------------------------

_ACTION_CONTEXT: dict[str, dict] = {
    "release_commitment": {
        "why_points": [
            "Commitment utilisation is below the recoverable threshold",
            "No workload growth trend detected in billing signals",
        ],
        "alternative": "resize (lower savings, risk of early-exit penalty)",
        "chosen_because": "highest savings, lowest operational risk — no service interruption",
    },
    "resize_down": {
        "why_points": [
            "Cost-per-vCPU-hour is below the idle compute threshold",
            "Instance is over-provisioned relative to workload billing signals",
        ],
        "alternative": "remove (higher risk — may have intermittent usage)",
        "chosen_because": "maintains service availability while recovering ~80% of waste",
    },
    "remove_resource": {
        "why_points": [
            "Total spend is below $2/month — classified as zombie resource",
            "No usage value justifies continued provisioning cost",
        ],
        "alternative": "none — spend is too low to benefit from partial optimisation",
        "chosen_because": "full elimination recovers 100% of waste, zero service dependency",
    },
}


def build_rationale(finding: dict, action: str, savings: float) -> str:
    """Construct a structured rationale with action justification and alternatives."""
    resource  = finding["resource_id"]
    svc       = finding["service_category"]
    cloud     = finding["cloud_provider"].upper()
    team      = finding["allocated_team"]
    wtype     = finding["waste_type"].replace("_", " ")
    action_lbl = action.replace("_", " ").title()

    ctx = _ACTION_CONTEXT.get(action, {})
    why_lines = "\n".join(f"  - {pt}" for pt in ctx.get("why_points", []))
    alt       = ctx.get("alternative", "—")
    chosen    = ctx.get("chosen_because", "best savings-to-risk ratio")

    short_id = ("…" + resource[-48:]) if len(resource) > 50 else resource
    return (
        f"**{cloud} · {svc} · Team: {team}**  \n"
        f"Resource: `{short_id}`  \n"
        f"Waste detected: {wtype}  \n\n"
        f"**Why {action_lbl}:**\n{why_lines}\n"
        f"  - Alternative: {alt}\n\n"
        f"**Chosen because:** {chosen}  \n\n"
        f"**Estimated savings:** ${savings:,.2f}/month"
    )


# ---------------------------------------------------------------------------
# 9E — run  (entry point)
# ---------------------------------------------------------------------------

def run(waste_findings: list[dict]) -> list[Recommendation]:
    """
    Convert waste findings into prioritised Recommendation dicts.

    Parameters
    ----------
    waste_findings : output of intelligence.waste_detector.run(df)

    Returns
    -------
    list[Recommendation] sorted by priority_score descending so the
    highest-impact, highest-confidence actions appear first.
    """
    recs: list[Recommendation] = []

    for f in waste_findings:
        estimated_savings, savings_pct = estimate_savings(f)
        if estimated_savings < _MIN_SAVINGS:
            continue

        action = action_for_waste_type(f["waste_type"])
        current_cost = f["nec_used"] + f["nec_waste"]

        effort = EFFORT_MAP.get(action, "Medium")
        time_to_realize = TIME_MAP.get(action, "1 week")
        effort_hours = _EFFORT_HOURS[effort]
        roi_score = round((estimated_savings * 12) / effort_hours, 2)

        recs.append(Recommendation(
            resource_id=f["resource_id"],
            allocated_team=f["allocated_team"],
            action=action,
            current_cost=round(current_cost, 4),
            estimated_savings=round(estimated_savings, 4),
            savings_pct=round(savings_pct, 2),
            risk=risk_score(f),
            priority_score=round(savings_pct * f["confidence"], 4),
            rationale=build_rationale(f, action, estimated_savings),
            effort=effort,
            time_to_realize=time_to_realize,
            roi_score=roi_score,
            cloud_provider=f["cloud_provider"],
            waste_type=f["waste_type"],
            billing_month=f["billing_month"],
            confidence=round(f["confidence"], 4),
        ))

    return sorted(recs, key=lambda r: r["priority_score"], reverse=True)


# ---------------------------------------------------------------------------
# CLI — python -m intelligence.impact_simulator
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    from pathlib import Path
    import duckdb
    from intelligence.waste_detector import run as detect_waste

    parser = argparse.ArgumentParser(description="Run impact simulator against DuckDB mart.")
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
    recs     = run(findings)

    total_savings = sum(r["estimated_savings"] for r in recs)
    print(f"\nRecommendations: {len(recs)}  |  Total estimated savings: ${total_savings:,.2f}\n")
    for i, r in enumerate(recs[:10], 1):
        print(
            f"  {i:2d}. [{r['risk']:6s}] {r['action']:20s}  "
            f"save ${r['estimated_savings']:7,.2f}  "
            f"({r['savings_pct']:5.1f}%)  "
            f"priority={r['priority_score']:.1f}  "
            f"team={r['allocated_team']}"
        )
    print()
