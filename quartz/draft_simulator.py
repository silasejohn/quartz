"""
Draft simulator for the Quartz snake draft.

Public API:
  run_draft(config, strategy, seed) -> DraftResult

Strategies:
  "greedy_pv"   — always pick lowest available PV (worst case for thresholds)
  "role_greedy" — pick lowest PV that fills an unfilled role; fallback to greedy_pv
  "random"      — random pick from available pool (Monte Carlo analysis)

Threshold enforcement:
  On a captain's Round 2 pick and Round 4 pick (the final pick before each threshold
  check), the available pool is filtered to only players whose PV would bring the
  team total to >= the threshold. If no such player exists the threshold is infeasible
  and a ValueError is raised.
"""

import random
from copy import deepcopy
from typing import Optional

from quartz.models.draft_model import (
    DraftConfig,
    DraftResult,
    TeamState,
    ThresholdCheck,
)


def _snake_order(slots: list[str], round_num: int) -> list[str]:
    """Round is 1-indexed. Odd rounds go forward, even rounds reverse."""
    return slots if round_num % 2 == 1 else list(reversed(slots))


def _pick(team: TeamState, pool: list[dict], strategy: str,
          min_pv: Optional[float] = None, top_n: int = 5) -> dict:
    """
    Select a player from pool for team using strategy.

    [param] min_pv: if set, only players with pv >= min_pv are eligible.
                    Raises ValueError if no eligible player exists.
    [param] top_n:  for role_greedy, pick randomly from the top N lowest-PV candidates
                    that fill a needed role (1 = deterministic, 5 = default randomness).
    """
    eligible = pool if min_pv is None else [p for p in pool if p["pv"] >= min_pv]

    if not eligible:
        if min_pv is not None:
            raise ValueError(
                f"Threshold infeasible for {team.captain.effective_id}: "
                f"needs a pick with PV >= {min_pv:.1f} but none available "
                f"(pool min PV = {min(p['pv'] for p in pool):.1f} if pool else 'empty')"
            )
        raise ValueError(f"Player pool exhausted for {team.captain.effective_id}")

    if strategy == "greedy_pv":
        return min(eligible, key=lambda p: p["pv"])

    elif strategy == "role_greedy":
        unfilled = team.unfilled_roles()
        if unfilled:
            candidates = [
                p for p in eligible
                if p.get("primary_pos") in unfilled or p.get("secondary_pos") in unfilled
            ]
            if candidates:
                top = sorted(candidates, key=lambda p: p["pv"])[:top_n]
                return random.choice(top)
        top = sorted(eligible, key=lambda p: p["pv"])[:top_n]
        return random.choice(top)

    elif strategy == "random":
        return random.choice(eligible)

    raise ValueError(f"Unknown strategy: {strategy!r}. Use greedy_pv | role_greedy | random")


def _threshold_min_pv(team: TeamState, threshold: float) -> Optional[float]:
    """
    Return the minimum PV a pick must have to keep team_pv >= threshold after the pick.
    Returns None if the team already satisfies the threshold without any pick.
    """
    needed = threshold - team.total_pv
    return needed if needed > 0 else None


def _check_threshold(teams: dict, threshold: float, after_round: int) -> ThresholdCheck:
    results = {}
    for eid, team in teams.items():
        pv = team.total_pv
        results[eid] = {"team_pv": round(pv, 1), "passed": pv >= threshold}
    return ThresholdCheck(after_round=after_round, threshold=threshold, results=results)


def run_draft(
    config: DraftConfig,
    strategy: str = "role_greedy",
    seed: Optional[int] = None,
    top_n: int = 5,
) -> DraftResult:
    """
    Simulate one full snake draft.

    Phase 1 (rounds 1-4): snake with initial slot order.
      - Round 2 picks are constrained so every team satisfies r2_threshold.
      - R2 threshold check displayed after round 2.
      - Round 4 picks are constrained so every team satisfies r4_threshold.
      - R4 threshold check displayed after round 4.
    Reorder: sort captains by descending total team PV (weakest = largest PV picks first).
    Phase 2 (rounds 5-6): snake with reordered slots (no threshold constraints).
    """
    if seed is not None:
        random.seed(seed)

    teams = {c.effective_id: TeamState(captain=c) for c in config.captains}
    available = deepcopy(config.player_pool)

    phase1_slots = [c.effective_id for c in config.captains]  # slot order 1->8
    play: list[str] = []
    r2_check = r4_check = None

    # ------------------------------------------------------------------
    # Phase 1 — Rounds 1-4
    # ------------------------------------------------------------------
    play.append("  PHASE 1 -- SNAKE (Rounds 1-4)")

    for rnd in range(1, 5):
        order = _snake_order(phase1_slots, rnd)
        direction = "->" if rnd % 2 == 1 else "<-"
        play.append(f"  Round {rnd}  [{direction}]")

        # Enforce threshold constraint on the pick that closes the threshold window
        enforce_r2 = (rnd == 2 and config.r2_threshold > 0)
        enforce_r4 = (rnd == 4 and config.r4_threshold > 0)

        for eid in order:
            team = teams[eid]

            min_pv = None
            if enforce_r2:
                min_pv = _threshold_min_pv(team, config.r2_threshold)
            elif enforce_r4:
                min_pv = _threshold_min_pv(team, config.r4_threshold)

            pick = _pick(team, available, strategy, min_pv=min_pv, top_n=top_n)
            available.remove(pick)
            team.picks.append(pick)

            constraint_note = f"  [min PV >= {min_pv:.1f} enforced]" if min_pv else ""
            play.append(
                f"    {eid:<20}  picks  {pick['effective_id']:<25}"
                f"  PV={pick['pv']:<6.1f}  {pick.get('primary_pos','?'):<4}"
                f"  team_pv={team.total_pv:.1f}{constraint_note}"
            )

        if rnd == 2:
            r2_check = _check_threshold(teams, config.r2_threshold, 2)
            if config.r2_threshold > 0:
                play.append(f"\n  -- R2 Threshold Check  (team PV >= {config.r2_threshold}) --")
                for eid, res in r2_check.results.items():
                    mark = "PASS" if res["passed"] else "FAIL"
                    play.append(f"    {eid:<20}  {res['team_pv']:>7.1f}   {mark}")
                play.append("")

        if rnd == 4:
            r4_check = _check_threshold(teams, config.r4_threshold, 4)
            if config.r4_threshold > 0:
                play.append(f"\n  -- R4 Threshold Check  (team PV >= {config.r4_threshold}) --")
                for eid, res in r4_check.results.items():
                    mark = "PASS" if res["passed"] else "FAIL"
                    play.append(f"    {eid:<20}  {res['team_pv']:>7.1f}   {mark}")
                play.append("")

    # ------------------------------------------------------------------
    # Reorder — descending team PV (weakest/largest PV team picks first)
    # ------------------------------------------------------------------
    reordered = sorted(teams.keys(), key=lambda eid: teams[eid].total_pv, reverse=True)
    play.append("  REORDER  (descending team PV -- weakest team picks first in Phase 2)")
    for i, eid in enumerate(reordered, 1):
        play.append(f"    {i}. {eid:<20}  team_pv={teams[eid].total_pv:.1f}")
    play.append("")

    # ------------------------------------------------------------------
    # Phase 2 — Rounds 5-6
    # ------------------------------------------------------------------
    play.append("  PHASE 2 -- SNAKE (Rounds 5-6)")

    for rnd in range(5, 7):
        phase2_rnd = rnd - 4  # 1 or 2 within this phase
        order = _snake_order(reordered, phase2_rnd)
        direction = "->" if phase2_rnd % 2 == 1 else "<-"
        play.append(f"  Round {rnd}  [{direction}]")

        for eid in order:
            team = teams[eid]
            pick = _pick(team, available, strategy, top_n=top_n)
            available.remove(pick)
            team.picks.append(pick)
            play.append(
                f"    {eid:<20}  picks  {pick['effective_id']:<25}"
                f"  PV={pick['pv']:<6.1f}  {pick.get('primary_pos','?'):<4}"
                f"  team_pv={team.total_pv:.1f}"
            )

    return DraftResult(
        teams={eid: t.model_dump() for eid, t in teams.items()},
        play_by_play=play,
        r2_check=r2_check,
        r4_check=r4_check,
        reorder=reordered,
    )
