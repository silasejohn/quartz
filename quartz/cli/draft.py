"""quartz draft — threshold analysis, pick sheet, and play-by-play simulation."""

import statistics
import typer
from typing import Optional

from quartz.tournament_config import load_tournament_config
from quartz.player_registry import PlayerRegistry
from quartz.models.draft_model import CaptainEntry, DraftConfig
from quartz.draft_simulator import run_draft


def _build_config(registry: PlayerRegistry, captain_slots: list[tuple[int, str]], season: str, r2: float = 0.0, r4: float = 0.0) -> DraftConfig:
    captain_ids = {eid for _, eid in captain_slots}
    captains = []
    for slot, eid in captain_slots:
        profile = registry.load(eid)
        if not profile:
            raise ValueError(f"Captain profile not found: {eid!r}")
        if not (profile.stats and profile.stats.computed_pv):
            raise ValueError(f"Captain {eid!r} has no computed PV — run PV_COMPUTE first")
        pv = profile.stats.computed_pv.point_value
        if pv is None:
            raise ValueError(f"Captain {eid!r} PV is flagged — check enrichment")
        sd = next((s for s in profile.season_data if s.season == season), None)
        captains.append(CaptainEntry(
            effective_id=eid,
            pv=pv,
            primary_pos=sd.primary_pos if sd else None,
            secondary_pos=sd.secondary_pos if sd else None,
            slot=slot,
        ))

    player_pool = []
    for profile in registry.load_all():
        if profile.effective_id in captain_ids:
            continue
        sd = next((s for s in profile.season_data if s.season == season), None)
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

    return DraftConfig(captains=captains, player_pool=player_pool, r2_threshold=r2, r4_threshold=r4)


def _cmd_simulate(registry, captain_slots, season, r2, r4, strategy, seed, top_n) -> None:
    if not r2:
        r2_raw = input("\n  R2 threshold (press Enter to skip)  > ").strip()
        r2 = float(r2_raw) if r2_raw else 0.0
    if not r4:
        r4_raw = input("  R4 threshold (press Enter to skip)  > ").strip()
        r4 = float(r4_raw) if r4_raw else 0.0

    strategy = strategy or "role_greedy"
    cfg    = _build_config(registry, captain_slots, season, r2, r4)
    result = run_draft(cfg, strategy=strategy, seed=seed, top_n=top_n or 5)

    print()
    for line in result.play_by_play:
        print(line)

    SEP = "=" * 72
    print(f"\n{SEP}")
    print(f"  FINAL TEAMS  (strategy={strategy})")
    print(SEP)
    for _, eid in captain_slots:
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


def _cmd_analyze(registry, captain_slots, season, n_sims, r2, r4, strategy, top_n) -> None:
    strategy = strategy or "role_greedy"
    r2 = r2 or 0.0
    r4 = r4 or 0.0
    cfg = _build_config(registry, captain_slots, season, r2, r4)

    greedy_result = run_draft(_build_config(registry, captain_slots, season, r2, r4), strategy="greedy_pv", seed=0)

    def _greedy_pv_at(eid: str, n_picks: int) -> float:
        t = greedy_result.teams[eid]
        return t["captain"]["pv"] + sum(p["pv"] for p in t["picks"][:n_picks])

    print(f"\n  Running {n_sims} simulations  (strategy={strategy})...")
    r2_pvs: dict[str, list[float]] = {eid: [] for _, eid in captain_slots}
    r4_pvs: dict[str, list[float]] = {eid: [] for _, eid in captain_slots}

    for i in range(n_sims):
        result = run_draft(cfg, strategy=strategy, seed=i, top_n=top_n or 5)
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
        for _, eid in captain_slots:
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
        print(f"  Greedy minimum:       {min(all_greedy):.1f}")
        print(f"  Suggested threshold:  ~{round(sum(all_p25) / len(all_p25), 1):.0f}  (avg P25 across captains)")
    print()


def _cmd_recommend(registry, captain_slots, season, r2, r4, strategy, top_n) -> None:
    strategy = strategy or "role_greedy"
    cfg    = _build_config(registry, captain_slots, season, r2, r4)
    result = run_draft(cfg, strategy=strategy, seed=0, top_n=top_n or 5)

    SEP = "=" * 60
    thresh_str = f"R2≥{r2}" + (f"  R4≥{r4}" if r4 > 0 else "")
    print(f"\n{SEP}")
    print(f"  OPTIMAL PICK SHEET  |  {thresh_str}  |  {strategy}")
    print(SEP)

    for _, eid in captain_slots:
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
            print(f"    R{rnd}  {p['effective_id']:<25}  PV={p['pv']:<6.1f}  {p.get('primary_pos','?'):<4}  total={running:.1f}{flag}")
        print(f"  {'─'*54}")
        print(f"  Final team PV: {total:.1f}")
    print()


def draft(
    analyze:   Optional[int]   = typer.Option(None,  "--analyze",   help="Run N Monte Carlo simulations"),
    simulate:  bool             = typer.Option(False, "--simulate",  help="Play-by-play draft walkthrough"),
    recommend: Optional[float]  = typer.Option(None,  "--recommend", help="Generate pick sheet for given R2 threshold"),
    r2:        Optional[float]  = typer.Option(None,  "--r2",        help="R2 threshold"),
    r4:        Optional[float]  = typer.Option(None,  "--r4",        help="R4 threshold"),
    strategy:  Optional[str]    = typer.Option(None,  "--strategy",  help="role_greedy / greedy_pv"),
    top_n:     Optional[int]    = typer.Option(None,  "--top-n",     help="Pick variance — random from top N per role"),
    seed:      Optional[int]    = typer.Option(None,  "--seed",      help="Random seed for reproducible simulation"),
):
    """Draft simulator — threshold analysis, pick sheet, play-by-play."""
    config   = load_tournament_config()
    registry = PlayerRegistry(config.abs_players_dir)
    season   = config.round_id

    if not config.captain_slots:
        typer.echo("No captain_slots configured in active_tournament.yaml — add them before running draft.")
        raise typer.Exit(1)

    captain_slots = config.captain_slots

    if simulate:
        _cmd_simulate(registry, captain_slots, season, r2 or 0.0, r4 or 0.0, strategy, seed, top_n)
    elif recommend is not None:
        _cmd_recommend(registry, captain_slots, season, recommend, r4 or 0.0, strategy, top_n)
    elif analyze is not None:
        _cmd_analyze(registry, captain_slots, season, analyze, r2, r4, strategy, top_n)
    else:
        _cmd_analyze(registry, captain_slots, season, 200, r2, r4, strategy, top_n)
