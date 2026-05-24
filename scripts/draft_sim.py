"""
draft_sim.py
Draft Simulator — threshold analysis and play-by-play simulation.

Usage:
    python3 draft_sim.py                   # analyze mode (200 sims)
    python3 draft_sim.py --simulate        # single play-by-play
    python3 draft_sim.py --analyze 500     # N sims, threshold distribution
    python3 draft_sim.py --strategy greedy_pv --analyze 200
"""

import argparse
import statistics

from quartz.tournament_config import load_tournament_config
from quartz.player_registry import PlayerRegistry
from quartz.models.draft_model import CaptainEntry, DraftConfig
from quartz.draft_simulator import run_draft

config = load_tournament_config()

# ---------------------------------------------------------------------------
# TODO: Update CAPTAIN_SLOTS for your tournament before running.
#
# Format: list of (draft_slot, effective_id) tuples in pick order.
# These are the captains who draft in snake order.
#
# Example (LEPL S3 — replace with your tournament's captains):
# ---------------------------------------------------------------------------
CAPTAIN_SLOTS = [
    (1, "superultraray"),
    (2, "seal"),
    (3, "SadderBread"),
    (4, "darianchibuzo"),
    (5, "gp"),
    (6, "lucashe"),
    (7, "donny"),
    (8, "Numinal"),
]
CAPTAIN_IDS = {eid for _, eid in CAPTAIN_SLOTS}

SEASON = config.round_id


# ---------------------------------------------------------------------------
# Config builder
# ---------------------------------------------------------------------------

def build_config(registry: PlayerRegistry, r2: float = 0.0, r4: float = 0.0) -> DraftConfig:
    captains = []
    for slot, eid in CAPTAIN_SLOTS:
        profile = registry.load(eid)
        if not profile:
            raise ValueError(f"Captain profile not found: {eid!r}")
        if not (profile.stats and profile.stats.computed_pv):
            raise ValueError(f"Captain {eid!r} has no computed PV — run PV_COMPUTE first")
        pv = profile.stats.computed_pv.point_value
        if pv is None:
            raise ValueError(f"Captain {eid!r} PV is flagged — check enrichment")
        sd = next((s for s in profile.season_data if s.season == SEASON), None)
        captains.append(CaptainEntry(
            effective_id=eid,
            pv=pv,
            primary_pos=sd.primary_pos if sd else None,
            secondary_pos=sd.secondary_pos if sd else None,
            slot=slot,
        ))

    player_pool = []
    for profile in registry.load_all():
        if profile.effective_id in CAPTAIN_IDS:
            continue
        sd = next((s for s in profile.season_data if s.season == SEASON), None)
        if not sd or sd.player_type not in ("main", "sub"):
            continue
        if not (profile.stats and profile.stats.computed_pv):
            continue
        pv = profile.stats.computed_pv.point_value
        if pv is None:
            continue
        player_pool.append({
            "effective_id": profile.effective_id,
            "pv": pv,
            "primary_pos": sd.primary_pos,
            "secondary_pos": sd.secondary_pos,
            "player_type": sd.player_type,
        })

    return DraftConfig(captains=captains, player_pool=player_pool,
                       r2_threshold=r2, r4_threshold=r4)


# ---------------------------------------------------------------------------
# Simulate command
# ---------------------------------------------------------------------------

def cmd_simulate(registry: PlayerRegistry, args) -> None:
    r2 = args.r2 or 0.0
    r4 = args.r4 or 0.0
    if not r2:
        r2_raw = input("\n  R2 threshold (press Enter to skip)  > ").strip()
        r2 = float(r2_raw) if r2_raw else 0.0
    if not r4:
        r4_raw = input("  R4 threshold (press Enter to skip)  > ").strip()
        r4 = float(r4_raw) if r4_raw else 0.0

    strategy = args.strategy or "role_greedy"
    cfg      = build_config(registry, r2, r4)
    result   = run_draft(cfg, strategy=strategy, seed=args.seed, top_n=args.top_n)

    print()
    for line in result.play_by_play:
        print(line)

    SEP = "=" * 72
    print(f"\n{SEP}")
    print(f"  FINAL TEAMS  (strategy={strategy})")
    print(SEP)
    for _, eid in CAPTAIN_SLOTS:
        t     = result.teams[eid]
        cap   = t["captain"]
        picks = t["picks"]
        total = cap["pv"] + sum(p["pv"] for p in picks)
        print(f"\n  {eid:<20}  captain_pv={cap['pv']:.1f}   total_pv={total:.1f}")
        print(f"    {'Player':<25}  {'PV':>6}  Role")
        print(f"    {'─'*42}")
        for p in picks:
            print(f"    {p['effective_id']:<25}  {p['pv']:>6.1f}  {p.get('primary_pos','?')}")
    print()


# ---------------------------------------------------------------------------
# Analyze command
# ---------------------------------------------------------------------------

def cmd_analyze(registry: PlayerRegistry, n_sims: int, args) -> None:
    strategy = args.strategy or "role_greedy"
    r2 = getattr(args, "r2", 0.0) or 0.0
    r4 = getattr(args, "r4", 0.0) or 0.0
    cfg = build_config(registry, r2, r4)

    greedy_cfg    = build_config(registry, r2, r4)
    greedy_result = run_draft(greedy_cfg, strategy="greedy_pv", seed=0)

    def _greedy_pv_at(eid: str, n_picks: int) -> float:
        t = greedy_result.teams[eid]
        return t["captain"]["pv"] + sum(p["pv"] for p in t["picks"][:n_picks])

    print(f"\n  Running {n_sims} simulations  (strategy={strategy})...")
    r2_pvs: dict[str, list[float]] = {eid: [] for _, eid in CAPTAIN_SLOTS}
    r4_pvs: dict[str, list[float]] = {eid: [] for _, eid in CAPTAIN_SLOTS}

    for i in range(n_sims):
        result = run_draft(cfg, strategy=strategy, seed=i, top_n=args.top_n)
        for eid, t in result.teams.items():
            cap_pv = t["captain"]["pv"]
            picks  = t["picks"]
            r2_pvs[eid].append(cap_pv + sum(p["pv"] for p in picks[:2]))
            r4_pvs[eid].append(cap_pv + sum(p["pv"] for p in picks[:4]))

    def _pct(vals: list[float], p: float) -> float:
        s   = sorted(vals)
        idx = int(len(s) * p / 100)
        return s[min(idx, len(s) - 1)]

    for label, pvs_dict, n_picks in [
        ("Round 2  (captain + 2 picks)", r2_pvs, 2),
        ("Round 4  (captain + 4 picks)", r4_pvs, 4),
    ]:
        print(f"\n  Team PV after {label}")
        print(f"  {'─'*82}")
        print(f"  {'Captain':<20}  {'Greedy':>7}  {'Min':>7}  {'P25':>7}  {'Median':>7}  {'P75':>7}  {'Max':>7}")
        print(f"  {'─'*82}")

        all_greedy: list[float] = []
        all_p25:    list[float] = []
        for _, eid in CAPTAIN_SLOTS:
            vals = pvs_dict[eid]
            g    = _greedy_pv_at(eid, n_picks)
            all_greedy.append(g)
            all_p25.append(_pct(vals, 25))
            print(
                f"  {eid:<20}  {g:>7.1f}  {min(vals):>7.1f}  "
                f"{_pct(vals,25):>7.1f}  {statistics.median(vals):>7.1f}  "
                f"{_pct(vals,75):>7.1f}  {max(vals):>7.1f}"
            )

        print(f"  {'─'*82}")
        greedy_min = min(all_greedy)
        suggested  = round(sum(all_p25) / len(all_p25), 1)
        print(f"  Greedy minimum:       {greedy_min:.1f}  (lowest team PV if any captain drafts pure greedy)")
        print(f"  Suggested threshold:  ~{suggested:.0f}  (avg P25 across captains — most teams pass with role picks)")
    print()


# ---------------------------------------------------------------------------
# Recommend command
# ---------------------------------------------------------------------------

def cmd_recommend(registry: PlayerRegistry, r2: float, r4: float, args) -> None:
    """
    Run one role_greedy simulation and print a clean per-captain pick sheet.
    Shows each pick by round with player name, PV, role, and running team total.
    Constrained picks (forced by threshold) are flagged.
    """
    strategy = args.strategy or "role_greedy"
    cfg      = build_config(registry, r2, r4)
    result   = run_draft(cfg, strategy=strategy, seed=0, top_n=args.top_n)

    SEP = "=" * 60
    thresh_str = f"R2≥{r2}" + (f"  R4≥{r4}" if r4 > 0 else "")
    print(f"\n{SEP}")
    print(f"  OPTIMAL PICK SHEET  |  {thresh_str}  |  {strategy}")
    print(SEP)

    for _, eid in CAPTAIN_SLOTS:
        t     = result.teams[eid]
        cap   = t["captain"]
        picks = t["picks"]
        total = cap["pv"] + sum(p["pv"] for p in picks)

        print(f"\n  {eid}  (captain  PV={cap['pv']:.1f})")
        print(f"  {'─'*54}")
        running = cap["pv"]
        for i, p in enumerate(picks):
            running += p["pv"]
            rnd  = i + 1
            flag = "  <- constrained" if (r2 > 0 and rnd == 2) or (r4 > 0 and rnd == 4) else ""
            print(
                f"    R{rnd}  {p['effective_id']:<25}  PV={p['pv']:<6.1f}"
                f"  {p.get('primary_pos','?'):<4}  total={running:.1f}{flag}"
            )
        print(f"  {'─'*54}")
        print(f"  Final team PV: {total:.1f}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=f"{config.tournament} Draft Simulator")
    parser.add_argument("--simulate", action="store_true",
                        help="Single play-by-play simulation")
    parser.add_argument("--analyze", type=int, metavar="N",
                        help="Run N simulations and show threshold distribution")
    parser.add_argument("--recommend", type=float, metavar="R2",
                        help="Show optimal pick sheet for given R2 threshold")
    parser.add_argument("--r2", type=float, default=0.0,
                        help="R2 threshold (use with --analyze or --simulate)")
    parser.add_argument("--r4", type=float, default=0.0,
                        help="R4 threshold (use with --analyze, --simulate, or --recommend)")
    parser.add_argument("--strategy", type=str, default=None,
                        help="greedy_pv | role_greedy | random  (default: role_greedy)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for --simulate (reproducible result)")
    parser.add_argument("--top-n", type=int, default=5,
                        help="role_greedy: pick randomly from top N lowest-PV role candidates (1=deterministic, default=5)")
    args = parser.parse_args()

    registry = PlayerRegistry(config.abs_players_dir)

    if args.simulate:
        cmd_simulate(registry, args)
    elif args.analyze:
        cmd_analyze(registry, args.analyze, args)
    elif args.recommend is not None:
        cmd_recommend(registry, args.recommend, args.r4, args)
    else:
        cmd_analyze(registry, 200, args)


if __name__ == "__main__":
    main()
