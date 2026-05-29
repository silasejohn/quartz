"""
Draft simulator for the Quartz snake draft.

Public API:
  run_draft(config, strategy, seed) -> DraftResult

Strategies:
  "greedy_pv"   — always pick lowest available PV (worst case for thresholds)
  "role_greedy" — pick lowest PV that fills an unfilled role; fallback to greedy_pv
  "random"      — random pick from available pool (Monte Carlo analysis)

Format-driven:
  All structural rules (picks_per_captain, reorder_after_round, soft_cap) come
  from DraftConfig — nothing is hardcoded. GCS S4 (4 picks, no reorder, soft cap)
  and LEPL S3 (6 picks, reorder after round 4, no soft cap) are both handled
  by the same simulator.

Threshold enforcement:
  R2 threshold: enforced on each team's round-2 pick.
  R4 threshold: enforced on each team's round-4 pick.
  Teams with an active soft cap have their effective thresholds raised above the
  global floor. If no eligible player can satisfy a team's effective threshold,
  a ValueError is raised (threshold infeasible).
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

    min_pv: if set, only players with pv >= min_pv are eligible.
            Raises ValueError if no eligible player exists.
    top_n:  for role_greedy, pick randomly from the top N lowest-PV candidates
            that fill a needed role (1 = deterministic, 5 = default randomness).
    """
    eligible = pool if min_pv is None else [p for p in pool if p["pv"] >= min_pv]

    if not eligible:
        if min_pv is not None:
            pool_min = min((p["pv"] for p in pool), default=float("inf"))
            raise ValueError(
                f"Threshold infeasible for {team.captain.effective_id}: "
                f"needs PV >= {min_pv:.1f} but pool minimum is {pool_min:.1f}"
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


def _threshold_min_pv(team: TeamState, effective_threshold: float) -> Optional[float]:
    """
    Return the minimum PV a pick must have to bring team_pv up to effective_threshold.
    Returns None if the team already satisfies the threshold.
    """
    needed = effective_threshold - team.total_pv
    return needed if needed > 0 else None


def _check_threshold(teams: dict[str, TeamState], base_threshold: float, after_round: int) -> ThresholdCheck:
    results = {}
    for eid, team in teams.items():
        eff = team.effective_threshold(base_threshold)
        pv  = team.total_pv
        results[eid] = {
            "team_pv":            round(pv, 1),
            "soft_cap_raise":     round(team.soft_cap_raise, 1),
            "effective_threshold": round(eff, 1),
            "passed":             pv >= eff,
        }
    return ThresholdCheck(after_round=after_round, base_threshold=base_threshold, results=results)


def _soft_cap_r1_eligible(
    available: list[dict],
    cap_pv: float,
    trigger: float,
    scale: float,
    r2_threshold: float,
) -> list[dict]:
    """
    Filter round-1 candidates to those that keep R2 feasible under soft cap.

    A pick is illegal if: picking it triggers the soft cap AND raises the effective
    R2 threshold beyond what any remaining player can satisfy.
    """
    legal = []
    for p in available:
        team_pv_after = cap_pv + p["pv"]
        if team_pv_after >= trigger:
            legal.append(p)
            continue
        raise_val    = (trigger - team_pv_after) * scale
        effective_r2 = r2_threshold + raise_val
        needed       = effective_r2 - team_pv_after
        remaining_max = max((q["pv"] for q in available if q is not p), default=0.0)
        if remaining_max >= needed:
            legal.append(p)
    return legal


def _apply_soft_cap(team: TeamState, config: DraftConfig) -> None:
    """Compute and store soft_cap_raise on team after their first pick."""
    if config.soft_cap_trigger is None:
        return
    pv_after_p1 = team.total_pv
    if pv_after_p1 < config.soft_cap_trigger:
        excess = config.soft_cap_trigger - pv_after_p1
        team.soft_cap_raise = round(excess * config.soft_cap_scale, 2)


def run_draft(
    config: DraftConfig,
    strategy: str = "role_greedy",
    seed: Optional[int] = None,
    top_n: int = 5,
) -> DraftResult:
    """
    Simulate one full snake draft driven entirely by DraftConfig.

    Rounds 1 to picks_per_captain are played in snake order.
    If reorder_after_round is set, the slot list is sorted by descending team PV
    at that boundary and the snake direction resets.
    Soft cap is evaluated per team immediately after their round-1 pick.
    R2 and R4 thresholds are enforced on rounds 2 and 4 respectively (per-team
    effective thresholds account for any soft cap raise).
    """
    if seed is not None:
        random.seed(seed)

    teams: dict[str, TeamState] = {c.effective_id: TeamState(captain=c) for c in config.captains}
    available = deepcopy(config.player_pool)

    slots = [c.effective_id for c in config.captains]
    play: list[str] = []
    r2_check = r4_check = None
    reorder_result: Optional[list[str]] = None

    # Local round index tracks snake direction; resets after a reorder.
    local_rnd = 0

    for rnd in range(1, config.picks_per_captain + 1):
        # Mid-draft reorder — triggers on the round immediately after reorder_after_round
        if config.reorder_after_round and rnd == config.reorder_after_round + 1:
            slots = sorted(slots, key=lambda eid: teams[eid].total_pv, reverse=True)
            reorder_result = list(slots)
            local_rnd = 0
            play.append("  REORDER  (weakest team picks first in remaining rounds)")
            for i, eid in enumerate(slots, 1):
                play.append(f"    {i}. {eid:<20}  team_pv={teams[eid].total_pv:.1f}")
            play.append("")

        local_rnd += 1
        order     = _snake_order(slots, local_rnd)
        direction = "->" if local_rnd % 2 == 1 else "<-"
        play.append(f"  Round {rnd}  [{direction}]")

        enforce_r2 = (rnd == 2 and config.r2_threshold > 0)
        enforce_r4 = (rnd == 4 and config.r4_threshold > 0)

        for eid in order:
            team = teams[eid]

            min_pv = None
            if enforce_r2:
                min_pv = _threshold_min_pv(team, team.effective_threshold(config.r2_threshold))
            elif enforce_r4:
                min_pv = _threshold_min_pv(team, team.effective_threshold(config.r4_threshold))

            # Round 1 soft cap lookahead: exclude picks that would make R2 infeasible
            if (rnd == 1
                    and config.soft_cap_trigger is not None
                    and config.r2_threshold > 0):
                pool = _soft_cap_r1_eligible(
                    available,
                    team.captain.pv,
                    config.soft_cap_trigger,
                    config.soft_cap_scale,
                    config.r2_threshold,
                )
                if not pool:
                    raise ValueError(
                        f"Soft cap: no legal R1 pick exists for {eid} — "
                        f"all candidates would make R2 infeasible"
                    )
            else:
                pool = available

            pick = _pick(team, pool, strategy, min_pv=min_pv, top_n=top_n)
            available.remove(pick)
            team.picks.append(pick)

            # Evaluate soft cap immediately after each team's first pick
            if rnd == 1:
                _apply_soft_cap(team, config)

            constraint_note = f"  [min>={min_pv:.1f}]" if min_pv else ""
            soft_note       = f"  [+{team.soft_cap_raise:.1f} cap]" if team.soft_cap_raise > 0 else ""
            play.append(
                f"    {eid:<20}  picks  {pick['effective_id']:<25}"
                f"  PV={pick['pv']:<6.1f}  {pick.get('primary_pos','?'):<4}"
                f"  team_pv={team.total_pv:.1f}{constraint_note}{soft_note}"
            )

        if rnd == 2 and config.r2_threshold > 0:
            r2_check = _check_threshold(teams, config.r2_threshold, 2)
            play.append(f"\n  -- R2 Threshold Check  (base >= {config.r2_threshold}) --")
            for eid, res in r2_check.results.items():
                mark    = "PASS" if res["passed"] else "FAIL"
                cap_str = f"  [effective={res['effective_threshold']:.1f}]" if res["soft_cap_raise"] > 0 else ""
                play.append(f"    {eid:<20}  {res['team_pv']:>7.1f}   {mark}{cap_str}")
            play.append("")

        if rnd == 4 and config.r4_threshold > 0:
            r4_check = _check_threshold(teams, config.r4_threshold, 4)
            play.append(f"\n  -- R4 Threshold Check  (base >= {config.r4_threshold}) --")
            for eid, res in r4_check.results.items():
                mark    = "PASS" if res["passed"] else "FAIL"
                cap_str = f"  [effective={res['effective_threshold']:.1f}]" if res["soft_cap_raise"] > 0 else ""
                play.append(f"    {eid:<20}  {res['team_pv']:>7.1f}   {mark}{cap_str}")
            play.append("")

    return DraftResult(
        teams={eid: t.model_dump() for eid, t in teams.items()},
        play_by_play=play,
        r2_check=r2_check,
        r4_check=r4_check,
        reorder=reorder_result,
    )
