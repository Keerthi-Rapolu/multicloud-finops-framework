"""
Shared export helpers for dashboard pages.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd


def _recommendation_frame(recommendations: list[dict]) -> pd.DataFrame:
    if not recommendations:
        return pd.DataFrame()

    rows = []
    for rec in recommendations:
        rows.append(
            {
                "Recommendation ID": rec.get("recommendation_id"),
                "Team": rec.get("allocated_team"),
                "Action Owner": rec.get("action_owner") or rec.get("owner_email") or rec.get("owner"),
                "Action": str(rec.get("action", "")).replace("_", " ").title(),
                "Status": str(rec.get("action_status", "recommended")).replace("_", " ").title(),
                "Risk": rec.get("risk"),
                "Risk Score": rec.get("risk_score"),
                "Approval Required": "Yes" if rec.get("approval_required") else "No",
                "Safety": str(rec.get("action_safety", "approval_required")).replace("_", " ").title(),
                "Current Cost": rec.get("current_cost"),
                "Estimated Monthly Savings": rec.get("estimated_savings"),
                "Savings %": rec.get("savings_pct"),
                "Time to Savings": rec.get("time_to_realize"),
                "ROI Score": rec.get("roi_score"),
                "Environment": rec.get("environment"),
                "Application": rec.get("application"),
                "Business Unit": rec.get("business_unit"),
                "Support Group": rec.get("support_group"),
                "Workload Criticality": rec.get("workload_criticality"),
                "SLA Tier": rec.get("sla_tier"),
                "Evidence Summary": rec.get("evidence_summary"),
                "Risk Reason": rec.get("risk_reason"),
                "Confidence": rec.get("confidence"),
                "Confidence Reason": rec.get("confidence_reason"),
            }
        )
    return pd.DataFrame(rows)


def recommendation_csv_bytes(recommendations: list[dict]) -> bytes:
    return _recommendation_frame(recommendations).to_csv(index=False).encode("utf-8")


def jira_action_csv_bytes(recommendations: list[dict]) -> bytes:
    rows = []
    for rec in recommendations:
        team = str(rec.get("allocated_team", "unassigned")).replace("-", " ").title()
        action = str(rec.get("action", "")).replace("_", " ").title()
        savings = float(rec.get("estimated_savings", 0.0) or 0.0)
        rows.append(
            {
                "Summary": f"{action} for {team} (${savings:,.0f}/month)",
                "Description": (
                    f"Recommendation ID: {rec.get('recommendation_id')}\n"
                    f"Risk: {rec.get('risk')} ({rec.get('risk_score', 0)}/100)\n"
                    f"Approval required: {'Yes' if rec.get('approval_required') else 'No'}\n"
                    f"Safety: {str(rec.get('action_safety', 'approval_required')).replace('_', ' ').title()}\n"
                    f"Estimated savings: ${savings:,.2f}/month\n"
                    f"Evidence: {rec.get('evidence_summary', '')}\n"
                    f"Risk reason: {rec.get('risk_reason', '')}"
                ),
                "Assignee": rec.get("action_owner") or rec.get("owner_email") or "",
                "Priority": rec.get("risk", "Medium"),
                "Labels": ",".join(
                    part
                    for part in [
                        "finops",
                        str(rec.get("cloud_provider", "")),
                        str(rec.get("waste_type", "")),
                        str(rec.get("action_safety", "")),
                    ]
                    if part
                ),
                "Expected Savings": round(savings, 2),
                "Status": str(rec.get("action_status", "recommended")).replace("_", " ").title(),
            }
        )
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8")


def executive_summary_markdown(
    *,
    title: str,
    total_nec: float,
    unattributed_spend: float,
    waste: float,
    estimated_savings: float,
    forecast_month: str,
    forecast_nec: float,
    forecast_waste: float,
    forecast_savings: float,
    forecast_basis: str,
    recommendations: list[dict],
) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    top_recs = sorted(
        recommendations,
        key=lambda rec: rec.get("estimated_savings", 0.0),
        reverse=True,
    )[:5]

    lines = [
        f"# {title}",
        "",
        f"_Generated: {generated_at}_",
        "",
        "## Current State",
        f"- Net Effective Cost (NEC): ${total_nec:,.0f}/month",
        f"- Unattributed Spend: ${unattributed_spend:,.0f}/month",
        f"- Waste: ${waste:,.0f}/month",
        f"- Realization-adjusted Monthly Savings: ${estimated_savings:,.0f}/month",
        "",
        f"## Forecast ({forecast_month})",
        f"- Projected month-end NEC: ${forecast_nec:,.0f}",
        f"- Forecast waste if no action is taken: ${forecast_waste:,.0f}",
        f"- Forecast savings if actions are applied ({forecast_basis}): ${forecast_savings:,.0f}",
        f"- Optimized month-end NEC: ${max(0.0, forecast_nec - forecast_savings):,.0f}",
        "",
        "## Priority Actions",
    ]

    if not top_recs:
        lines.append("- No recommendations available for the current scope.")
    else:
        for idx, rec in enumerate(top_recs, 1):
            lines.append(
                f"{idx}. {str(rec.get('action', '')).replace('_', ' ').title()} | "
                f"{str(rec.get('allocated_team', 'unassigned')).replace('-', ' ').title()} | "
                f"${float(rec.get('estimated_savings', 0.0) or 0.0):,.0f}/month | "
                f"Risk {rec.get('risk')} ({rec.get('risk_score', 0)}/100)"
            )

    lines.extend(
        [
            "",
            "## Notes",
            "- Forecasts are deterministic and based on billed NEC trend plus current-month run rate when available.",
            "- Savings assume either approved actions or low-risk actions when approval state is not yet set.",
        ]
    )
    return "\n".join(lines) + "\n"
