"""
Shared cost distribution engine.

Identifies unallocated shared-infrastructure rows in the billing DataFrame
and fans them out across teams using one of three configurable strategies:

  proportional — team_share = team_direct_nec / total_direct_nec
                 Teams that spend more get a larger share of shared costs.
                 Falls back to even if no direct spend is available.

  even         — team_share = 1 / N
                 Equal split regardless of team size or spend.

  weighted     — team_share = team_weight / sum(weights)
                 Useful when teams have contractual SLA commitments.

"Shared candidates" are rows that match BOTH conditions:
  1. service_name appears in shared_cost_weights.yml
  2. is_tagged = False  (no team tag → no direct owner)

Rows already fanned out by the dbt Azure model (is_shared_cost=True,
allocated_team set) pass through unchanged to avoid double-distribution.

Usage:
    from allocation.shared_cost import SharedCostDistributor

    dist = SharedCostDistributor()
    allocated_df = dist.distribute(billing_df)

    # Override strategy for a specific call
    allocated_df = dist.distribute(billing_df, strategy_override="even")
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

_DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "shared_cost_weights.yml"

Strategy = str  # Literal['proportional', 'even', 'weighted']
VALID_STRATEGIES = {"proportional", "even", "weighted"}


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_config(path: str | Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class SharedCostDistributor:
    """
    Loads strategy config once and exposes a distribute() method.

    Parameters
    ----------
    config_path : path to shared_cost_weights.yml (defaults to repo config/).
    """

    def __init__(self, config_path: str | Path = _DEFAULT_CONFIG):
        cfg = _load_config(config_path)

        self._default_strategy: Strategy = cfg.get("default_strategy", "proportional")
        self._all_teams: list[str] = cfg.get("teams", [])
        self._weights: dict[str, float] = cfg.get("weights", {})

        # Flat lookup: service_name → strategy
        self._service_strategy: dict[str, Strategy] = {}
        for svc in cfg.get("shared_services", []):
            strategy = svc.get("strategy", self._default_strategy)
            if strategy not in VALID_STRATEGIES:
                raise ValueError(f"Unknown strategy '{strategy}' for service '{svc.get('name')}'")
            for name in svc.get("service_names", []):
                self._service_strategy[name] = strategy

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def distribute(
        self,
        df: pd.DataFrame,
        teams: Optional[list[str]] = None,
        strategy_override: Optional[Strategy] = None,
    ) -> pd.DataFrame:
        """
        Fan out shared-cost rows; pass through everything else.

        Parameters
        ----------
        df : DataFrame with fct_unified_billing schema (or compatible).
        teams : override the team list from config.
        strategy_override : apply one strategy to all shared rows, ignoring
                            per-service config.

        Returns
        -------
        DataFrame where shared rows are replaced by N rows (one per team),
        each carrying their proportional/even/weighted share of the NEC.
        Column ``is_shared_cost`` is set True on all fanned rows.
        """
        if strategy_override and strategy_override not in VALID_STRATEGIES:
            raise ValueError(f"strategy_override must be one of {VALID_STRATEGIES}")

        resolved_teams = teams if teams is not None else self._all_teams
        if not resolved_teams:
            raise ValueError(
                "No teams available. Set teams in config or pass teams= parameter."
            )

        shared_mask = self._shared_candidate_mask(df)
        shared_df = df[shared_mask].reset_index(drop=True)
        direct_df = df[~shared_mask].reset_index(drop=True)

        if shared_df.empty:
            return df.copy()

        # Pre-compute all three share dicts once — results are identical for every row.
        tagged_direct = direct_df[direct_df["is_tagged"].fillna(False)]
        proportional_shares = self._compute_shares("proportional", resolved_teams, tagged_direct)
        weighted_shares     = self._compute_shares("weighted",     resolved_teams, tagged_direct)
        even_shares         = self._compute_shares("even",         resolved_teams, tagged_direct)

        fanned: list[pd.DataFrame] = []

        for _, row in shared_df.iterrows():
            strategy = strategy_override or self._service_strategy.get(
                row["service_name"], self._default_strategy
            )

            if strategy == "proportional":
                shares = proportional_shares
            elif strategy == "weighted":
                shares = weighted_shares
            else:
                shares = even_shares

            fanned.append(_fanout_row(row, shares))

        result = pd.concat([direct_df] + fanned, ignore_index=True)
        return result

    # ------------------------------------------------------------------
    # Strategy summary — useful for the paper's evaluation section
    # ------------------------------------------------------------------

    def allocation_summary(
        self,
        df: pd.DataFrame,
        teams: Optional[list[str]] = None,
    ) -> pd.DataFrame:
        """
        Return a summary of how each shared service's NEC is split across teams
        under each strategy. Used in the paper evaluation (Section 4).
        """
        resolved_teams = teams if teams is not None else self._all_teams
        tagged_direct = df[df["is_tagged"].fillna(False) & ~self._shared_candidate_mask(df)]

        shared_mask = self._shared_candidate_mask(df)
        shared_df = df[shared_mask]
        if shared_df.empty:
            return pd.DataFrame()

        rows = []
        for strategy in VALID_STRATEGIES:
            shares = self._compute_shares(strategy, resolved_teams, tagged_direct)
            total_shared_nec = shared_df["nec"].sum()
            for team, share in shares.items():
                rows.append(
                    {
                        "strategy": strategy,
                        "team": team,
                        "share_pct": round(share * 100, 1),
                        "allocated_nec": round(total_shared_nec * share, 4),
                    }
                )
        return pd.DataFrame(rows).sort_values(["strategy", "team"])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _shared_candidate_mask(self, df: pd.DataFrame) -> pd.Series:
        """
        True for rows that need distribution:
          - service_name is in a configured shared service list, AND
          - is_tagged = False (no direct team owner)

        Rows already fanned out by dbt (is_shared_cost=True, allocated_team set)
        are NOT re-distributed — they pass through unchanged.
        """
        already_allocated = (
            df["is_shared_cost"].fillna(False)
            & df["allocated_team"].notna()
        )
        new_candidates = (
            df["service_name"].isin(self._service_strategy)
            & (~df["is_tagged"].fillna(False))
        )
        return new_candidates & ~already_allocated

    def _compute_shares(
        self,
        strategy: Strategy,
        teams: list[str],
        direct_df: pd.DataFrame,
    ) -> dict[str, float]:
        """
        Return {team: share} where values sum to 1.0.

        proportional: weighted by each team's total direct NEC.
                      Falls back to even if total direct spend is zero.
        even:         1/N for each team.
        weighted:     from config weights, normalized to sum to 1.0.
                      Falls back to even if no weights configured.
        """
        n = len(teams)

        if strategy == "even":
            return {t: 1.0 / n for t in teams}

        if strategy == "weighted":
            raw = {t: self._weights.get(t, 0.0) for t in teams}
            total = sum(raw.values())
            if total == 0:
                return {t: 1.0 / n for t in teams}
            return {t: w / total for t, w in raw.items()}

        # proportional
        if direct_df.empty:
            return {t: 1.0 / n for t in teams}

        team_spend = (
            direct_df[direct_df["allocated_team"].isin(teams)]
            .groupby("allocated_team")["nec"]
            .sum()
            .reindex(teams, fill_value=0.0)
        )
        total = float(team_spend.sum())
        if total == 0:
            return {t: 1.0 / n for t in teams}

        return {t: float(team_spend[t]) / total for t in teams}


# ---------------------------------------------------------------------------
# Row fan-out helper (module-level, no state)
# ---------------------------------------------------------------------------

def _fanout_row(row: pd.Series, shares: dict[str, float]) -> pd.DataFrame:
    """
    Expand a single shared-cost row into one row per team.
    Each team row gets its proportional share of the original NEC.
    """
    records = []
    for team, share in shares.items():
        r = row.to_dict()
        r["allocated_team"] = team
        r["allocated_nec"] = float(row["nec"]) * share
        r["is_shared_cost"] = True
        records.append(r)
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Convenience function — mirrors nec_model.py's functional API style
# ---------------------------------------------------------------------------

def distribute_shared_costs(
    df: pd.DataFrame,
    config_path: str | Path = _DEFAULT_CONFIG,
    teams: Optional[list[str]] = None,
    strategy_override: Optional[Strategy] = None,
) -> pd.DataFrame:
    """
    Functional wrapper around SharedCostDistributor.distribute().
    Use this when you don't need to reuse the distributor instance.
    """
    return SharedCostDistributor(config_path).distribute(
        df, teams=teams, strategy_override=strategy_override
    )
