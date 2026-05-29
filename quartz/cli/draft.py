"""quartz draft — threshold analysis, optimization, pick sheet, and play-by-play simulation."""

import random
import statistics
from typing import Optional

import typer
from rich.table import Table

from quartz.draft_simulator import run_draft
from quartz.models.draft_model import CaptainEntry, DraftConfig
from quartz.player_registry import PlayerRegistry
from quartz.tournament_config import TournamentConfig, load_tournament_config
from quartz.utils.logging import console


# 10 visually distinct team colors (bold text) for the pool table
_TEAM_PALETTE = [
    "bold red",
    "bold bright_green",
    "bold bright_blue",
    "bold bright_yellow",
    "bold bright_cyan",
    "bold bright_magenta",
    "bold orange3",
    "bold medium_purple1",
    "bold spring_green1",
    "bold hot_pink",
]


# ---------------------------------------------------------------------------
# Config builder
# ---------------------------------------------------------------------------

def _build_config(
    registry: PlayerRegistry,
    config: TournamentConfig,
    r2: float = 0.0,
    r4: float = 0.0,
    soft_cap: bool = False,
) -> DraftConfig:
    """
    Build a DraftConfig from the registry and tournament config.

    Captain verification: every entry in captain_slots must have a matching
    profile with player_type = "captain". Raises ValueError on mismatch.
    """
    fmt    = config.draft_format
    season = config.round_id

    # --- captains ---
    slots = list(config.captain_slots)
    if fmt.randomize_captain_order:
        indices = list(range(len(slots)))
        random.shuffle(indices)
        slots = [(i + 1, slots[idx][1]) for i, idx in enumerate(indices)]

    captain_ids: set[str] = set()
    captains: list[CaptainEntry] = []
    for slot, eid in slots:
        profile = registry.load(eid)
        if not profile:
            raise ValueError(f"Captain profile not found: {eid!r}")
        sd = next((s for s in profile.season_data if s.season == season), None)
        if not sd or sd.player_type != "captain":
            pt = sd.player_type if sd else "no season data"
            raise ValueError(
                f"Captain {eid!r} has player_type={pt!r} — expected 'captain'. "
                f"Fix the profile or remove from captain_slots."
            )
        if not (profile.stats and profile.stats.computed_pv):
            raise ValueError(f"Captain {eid!r} has no computed PV — run PV_COMPUTE first")
        pv = profile.stats.computed_pv.point_value
        if pv is None:
            raise ValueError(f"Captain {eid!r} PV is flagged — check enrichment")
        captain_ids.add(eid)
        captains.append(CaptainEntry(
            effective_id=eid,
            pv=pv,
            primary_pos=sd.primary_pos,
            secondary_pos=sd.secondary_pos,
            slot=slot,
        ))

    # --- player pool (main + sub, excluding captains) ---
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
            "pv":           pv,
            "primary_pos":  sd.primary_pos,
            "secondary_pos": sd.secondary_pos,
            "player_type":  sd.player_type,
        })

    return DraftConfig(
        captains=captains,
        player_pool=player_pool,
        picks_per_captain=fmt.picks_per_captain,
        r2_threshold=r2,
        r4_threshold=r4,
        reorder_after_round=fmt.reorder_after_round,
        soft_cap_trigger=fmt.soft_cap_trigger if soft_cap else None,
        soft_cap_scale=fmt.soft_cap_scale,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _frange(lo: float, hi: float, step: float) -> list[float]:
    """Inclusive float range."""
    vals, v = [], lo
    while v <= hi + 1e-9:
        vals.append(round(v, 2))
        v += step
    return vals


def _print_pool_table(cfg: DraftConfig, result, config: TournamentConfig) -> None:
    """Print all players sorted by PV, rows colored by the team they were drafted to."""
    captain_eids = [eid for _, eid in config.captain_slots]
    team_color   = {eid: _TEAM_PALETTE[i % len(_TEAM_PALETTE)] for i, eid in enumerate(captain_eids)}

    picked_by: dict[str, str] = {}
    for cap_eid, t in result.teams.items():
        for p in t["picks"]:
            picked_by[p["effective_id"]] = cap_eid

    rows: list[tuple[str, float, str, str, str | None]] = []
    for c in cfg.captains:
        role = f"{c.primary_pos}/{c.secondary_pos}" if c.secondary_pos else (c.primary_pos or "?")
        rows.append((c.effective_id, c.pv, role, "captain", c.effective_id))
    for p in cfg.player_pool:
        pri  = p.get("primary_pos", "?")
        sec  = p.get("secondary_pos")
        role = f"{pri}/{sec}" if sec else pri
        rows.append((p["effective_id"], p["pv"], role, p.get("player_type", "?"), picked_by.get(p["effective_id"])))

    rows.sort(key=lambda x: x[1])

    table = Table(title="Full Pool — Draft Result  (sorted by PV ascending, lower = stronger)")
    table.add_column("Player", no_wrap=True, min_width=22)
    table.add_column("Type",   min_width=7)
    table.add_column("PV",     justify="right", min_width=5)
    table.add_column("Role",   min_width=7)
    table.add_column("Team",   no_wrap=True)

    for eid, pv, role, ptype, cap_eid in rows:
        if cap_eid:
            style      = team_color.get(cap_eid, "")
            team_label = cap_eid
        else:
            style      = "dim"
            team_label = "—"
        table.add_row(eid, ptype, f"{pv:.1f}", role, team_label, style=style)

    console.print(table)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def _cmd_simulate(registry, config, r2, r4, strategy, seed, top_n, soft_cap: bool = False) -> None:
    if not r2:
        r2_raw = input("\n  R2 threshold (Enter to skip)  > ").strip()
        r2 = float(r2_raw) if r2_raw else 0.0
    if not r4:
        r4_raw = input("  R4 threshold (Enter to skip)  > ").strip()
        r4 = float(r4_raw) if r4_raw else 0.0

    strategy = strategy or "role_greedy"
    cfg    = _build_config(registry, config, r2, r4, soft_cap=soft_cap)
    result = run_draft(cfg, strategy=strategy, seed=seed, top_n=top_n or 5)

    print()
    for line in result.play_by_play:
        print(line)

    SEP = "=" * 72
    print(f"\n{SEP}")
    print(f"  FINAL TEAMS  (strategy={strategy})")
    print(SEP)

    for slot, eid in config.captain_slots:
        t     = result.teams[eid]
        cap   = t["captain"]
        picks = t["picks"]
        total = cap["pv"] + sum(p["pv"] for p in picks)

        cap_note = ""
        if t.get("soft_cap_raise", 0) > 0:
            cap_note = f"  [soft cap +{t['soft_cap_raise']:.1f}]"
        print(f"\n  {eid:<20}  captain_pv={cap['pv']:.1f}   total_pv={total:.1f}{cap_note}")
        print(f"    {'Rd':<3}  {'Player':<25}  {'PV':>6}  {'Role':<5}  {'TeamPV':>7}")
        print(f"    {'─'*56}")

        running = cap["pv"]
        for i, p in enumerate(picks):
            running += p["pv"]
            rnd = i + 1
            threshold_note = ""
            if rnd == 2 and result.r2_check:
                res = result.r2_check.results.get(eid, {})
                eff  = res.get("effective_threshold", r2)
                mark = "✓" if res.get("passed") else "✗"
                soft = f" +{res['soft_cap_raise']:.1f}" if res.get("soft_cap_raise", 0) > 0 else ""
                threshold_note = f"  [R2 needed>={eff:.1f}{soft} {mark}]"
            elif rnd == 4 and result.r4_check:
                res = result.r4_check.results.get(eid, {})
                eff  = res.get("effective_threshold", r4)
                mark = "✓" if res.get("passed") else "✗"
                soft = f" +{res['soft_cap_raise']:.1f}" if res.get("soft_cap_raise", 0) > 0 else ""
                threshold_note = f"  [R4 needed>={eff:.1f}{soft} {mark}]"
            print(f"    R{rnd}  {p['effective_id']:<25}  {p['pv']:>6.1f}  {p.get('primary_pos','?'):<5}  {running:>7.1f}{threshold_note}")
    print()

    _print_pool_table(cfg, result, config)


def _cmd_analyze(registry, config, n_sims, r2, r4, strategy, top_n) -> None:
    strategy = strategy or "role_greedy"
    r2 = r2 or 0.0
    r4 = r4 or 0.0
    cfg = _build_config(registry, config, r2, r4)

    greedy_cfg    = _build_config(registry, config, r2, r4)
    greedy_result = run_draft(greedy_cfg, strategy="greedy_pv", seed=0)

    captain_eids = [eid for _, eid in config.captain_slots]
    pool_eids    = [p["effective_id"] for p in cfg.player_pool]
    picks_per_draft = len(captain_eids) * cfg.picks_per_captain

    def _greedy_pv_at(eid: str, n_picks: int) -> float:
        t = greedy_result.teams[eid]
        return t["captain"]["pv"] + sum(p["pv"] for p in t["picks"][:n_picks])

    print(f"\n  Running {n_sims} simulations  (strategy={strategy}  r2={r2}  r4={r4})...")
    r2_pvs: dict[str, list[float]] = {eid: [] for eid in captain_eids}
    r4_pvs: dict[str, list[float]] = {eid: [] for eid in captain_eids}
    draft_counts: dict[str, int]   = {eid: 0 for eid in pool_eids}

    for i in range(n_sims):
        result = run_draft(cfg, strategy=strategy, seed=i, top_n=top_n or 5)
        for eid, t in result.teams.items():
            cap_pv = t["captain"]["pv"]
            picks  = t["picks"]
            r2_pvs[eid].append(cap_pv + sum(p["pv"] for p in picks[:2]))
            r4_pvs[eid].append(cap_pv + sum(p["pv"] for p in picks[:4]))
            for p in picks:
                pid = p["effective_id"]
                if pid in draft_counts:
                    draft_counts[pid] += 1

    def _pct(vals: list[float], p: float) -> float:
        s   = sorted(vals)
        idx = int(len(s) * p / 100)
        return s[min(idx, len(s) - 1)]

    for label, pvs_dict, n_picks in [
        ("Round 2  (captain + 2 picks)", r2_pvs, 2),
        ("Round 4  (captain + 4 picks)", r4_pvs, 4),
    ]:
        print(f"\n  Team PV after {label}")
        print(f"  {'─'*86}")
        print(f"  {'Captain':<20}  {'Greedy':>7}  {'Min':>7}  {'P25':>7}  {'Median':>7}  {'P75':>7}  {'Max':>7}  {'StdDev':>7}")
        print(f"  {'─'*86}")
        all_greedy: list[float] = []
        all_p25:    list[float] = []
        for eid in captain_eids:
            vals = pvs_dict[eid]
            g    = _greedy_pv_at(eid, n_picks)
            all_greedy.append(g)
            all_p25.append(_pct(vals, 25))
            print(
                f"  {eid:<20}  {g:>7.1f}  {min(vals):>7.1f}  "
                f"{_pct(vals,25):>7.1f}  {statistics.median(vals):>7.1f}  "
                f"{_pct(vals,75):>7.1f}  {max(vals):>7.1f}  {statistics.stdev(vals):>7.2f}"
            )
        print(f"  {'─'*86}")
        print(f"  Greedy minimum:       {min(all_greedy):.1f}")
        print(f"  Suggested threshold:  ~{round(sum(all_p25) / len(all_p25), 1):.0f}  (avg P25 across captains)")

    # --- undrafted breakdown ---
    pool_size        = len(pool_eids)
    avg_undrafted    = pool_size - picks_per_draft
    pct_undrafted    = avg_undrafted / pool_size * 100 if pool_size else 0.0

    print(f"\n  {'─'*60}")
    print(f"  UNDRAFTED PLAYERS")
    print(f"  {'─'*60}")
    print(f"  Pool size (mains + subs):  {pool_size}")
    print(f"  Draft slots per sim:       {picks_per_draft}  ({len(captain_eids)} captains × {cfg.picks_per_captain} picks)")
    print(f"  Avg undrafted per draft:   {avg_undrafted}  ({pct_undrafted:.1f}% of pool)")

    # players sorted by draft rate ascending (least-drafted first)
    by_rate = sorted(pool_eids, key=lambda e: draft_counts[e])
    rarely_drafted = [(e, draft_counts[e] / n_sims) for e in by_rate if draft_counts[e] / n_sims < 0.10]

    if rarely_drafted:
        print(f"\n  Rarely drafted  (<10% of sims):")
        print(f"  {'─'*40}")
        print(f"  {'Player':<25}  {'DraftRate':>9}")
        print(f"  {'─'*40}")
        for eid, rate in rarely_drafted:
            marker = "  never" if rate == 0.0 else ""
            print(f"  {eid:<25}  {rate:>8.1%}{marker}")
    else:
        print(f"\n  All players drafted in ≥10% of simulations.")
    print()


def _cmd_optimize(registry, config, n_sims, strategy, top_n, top_k, min_pass_rate: float = 0.95) -> None:
    """
    Grid search over (r2, r4) pairs to find thresholds that minimize the
    average standard deviation of final team PV across N simulated drafts.
    """
    strategy = strategy or "role_greedy"
    captain_eids = [eid for _, eid in config.captain_slots]

    # --- derive grid bounds from a quick diagnostic run ---
    base_cfg = _build_config(registry, config, 0.0, 0.0)
    pvs_quick: list[list[float]] = []
    for i in range(50):
        result = run_draft(base_cfg, strategy="random", seed=i)
        final_pvs = [
            result.teams[eid]["captain"]["pv"] + sum(p["pv"] for p in result.teams[eid]["picks"])
            for eid in captain_eids
        ]
        pvs_quick.append(final_pvs)

    # r2 grid: from pool P10 to P60 of (captain + 2 picks) distributions
    r2_pvs_flat = []
    r4_pvs_flat = []
    for i in range(50):
        result = run_draft(base_cfg, strategy="random", seed=100 + i)
        for eid in captain_eids:
            t = result.teams[eid]
            picks = t["picks"]
            r2_pvs_flat.append(t["captain"]["pv"] + sum(p["pv"] for p in picks[:2]))
            r4_pvs_flat.append(t["captain"]["pv"] + sum(p["pv"] for p in picks[:4]))

    def _pct(vals, p):
        s = sorted(vals)
        idx = int(len(s) * p / 100)
        return s[min(idx, len(s) - 1)]

    r2_lo = _pct(r2_pvs_flat, 10)
    r2_hi = _pct(r2_pvs_flat, 60)
    r4_lo = _pct(r4_pvs_flat, 10)
    r4_hi = _pct(r4_pvs_flat, 60)

    r2_step = max(1.0, round((r2_hi - r2_lo) / 8, 1))
    r4_step = max(2.0, round((r4_hi - r4_lo) / 8, 1))

    r2_candidates = _frange(r2_lo, r2_hi, r2_step)
    r4_candidates = _frange(r4_lo, r4_hi, r4_step)

    total = len(r2_candidates) * len(r4_candidates)
    print(f"\n  Optimizing thresholds — {total} pairs × {n_sims} sims  (strategy={strategy})")
    print(f"  R2 grid: {r2_lo:.1f} – {r2_hi:.1f}  step={r2_step}  ({len(r2_candidates)} values)")
    print(f"  R4 grid: {r4_lo:.1f} – {r4_hi:.1f}  step={r4_step}  ({len(r4_candidates)} values)")
    print()

    scored: list[tuple[float, float, float, float]] = []  # (score, pass_rate, r2, r4)

    for r2 in r2_candidates:
        for r4 in r4_candidates:
            if r4 < r2:
                continue
            cfg = _build_config(registry, config, r2, r4)
            sim_stdevs: list[float] = []
            infeasible = 0
            for i in range(n_sims):
                try:
                    result = run_draft(cfg, strategy=strategy, seed=i, top_n=top_n or 5)
                    final_pvs = [
                        result.teams[eid]["captain"]["pv"] + sum(p["pv"] for p in result.teams[eid]["picks"])
                        for eid in captain_eids
                    ]
                    sim_stdevs.append(statistics.stdev(final_pvs))
                except ValueError:
                    infeasible += 1

            if not sim_stdevs:
                continue

            score     = statistics.mean(sim_stdevs)
            pass_rate = (n_sims - infeasible) / n_sims
            scored.append((score, pass_rate, r2, r4))

    scored.sort(key=lambda x: x[0])

    feasible = [s for s in scored if s[1] >= min_pass_rate]
    top      = (feasible if feasible else scored)[:top_k]
    filtered = len(scored) - len(feasible)

    SEP = "=" * 64
    print(f"\n{SEP}")
    print(f"  OPTIMIZATION RESULTS  (top {top_k} by avg team PV std dev,  pass_rate >= {min_pass_rate:.0%})")
    print(SEP)
    if filtered:
        note = "all pairs" if not feasible else f"{filtered} pairs"
        print(f"  Note: {note} below {min_pass_rate:.0%} pass rate excluded{' — showing best available' if not feasible else ''}.")
    print(f"  {'Rank':<5}  {'R2':>7}  {'R4':>7}  {'AvgStdDev':>10}  {'PassRate':>9}")
    print(f"  {'─'*50}")
    for rank, (score, pass_rate, r2, r4) in enumerate(top, 1):
        flag = "  ⚠ low pass rate" if pass_rate < min_pass_rate else ""
        print(f"  {rank:<5}  {r2:>7.1f}  {r4:>7.1f}  {score:>10.2f}  {pass_rate:>8.1%}{flag}")
    print()

    if top:
        best_score, best_pass, best_r2, best_r4 = top[0]
        print(f"  Recommended:")
        print(f"    quartz draft --simulate --r2 {best_r2:.1f} --r4 {best_r4:.1f}")
        print(f"    quartz draft --recommend --r2 {best_r2:.1f} --r4 {best_r4:.1f}")
    print()


def _cmd_recommend(registry, config, r2, r4, strategy, top_n) -> None:
    strategy = strategy or "role_greedy"
    cfg    = _build_config(registry, config, r2, r4)
    result = run_draft(cfg, strategy=strategy, seed=0, top_n=top_n or 5)

    SEP = "=" * 60
    thresh_str = f"R2>={r2}" + (f"  R4>={r4}" if r4 > 0 else "")
    print(f"\n{SEP}")
    print(f"  PICK SHEET  |  {thresh_str}  |  {strategy}")
    print(SEP)

    for slot, eid in config.captain_slots:
        t     = result.teams[eid]
        cap   = t["captain"]
        picks = t["picks"]
        total = cap["pv"] + sum(p["pv"] for p in picks)
        soft  = t.get("soft_cap_raise", 0.0)
        cap_note = f"  [soft cap +{soft:.1f}]" if soft > 0 else ""
        print(f"\n  {eid}  (captain  PV={cap['pv']:.1f}){cap_note}")
        print(f"  {'─'*54}")
        running = cap["pv"]
        for i, p in enumerate(picks):
            running += p["pv"]
            rnd  = i + 1
            flag = "  <- threshold constrained" if (r2 > 0 and rnd == 2) or (r4 > 0 and rnd == 4) else ""
            print(f"    R{rnd}  {p['effective_id']:<25}  PV={p['pv']:<6.1f}  {p.get('primary_pos','?'):<4}  total={running:.1f}{flag}")
        print(f"  {'─'*54}")
        print(f"  Final team PV: {total:.1f}")
    print()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def draft(
    optimize:  bool            = typer.Option(False, "--optimize",  help="Grid-search for fair (r2, r4) thresholds"),
    analyze:   Optional[int]   = typer.Option(None,  "--analyze",   help="Run N Monte Carlo sims for a given (r2, r4)"),
    simulate:  bool            = typer.Option(False, "--simulate",  help="Play-by-play walkthrough"),
    recommend: bool            = typer.Option(False, "--recommend", help="Generate pick sheet for given (r2, r4)"),
    r2:        Optional[float] = typer.Option(None,  "--r2",        help="R2 threshold (captain + 2 picks)"),
    r4:        Optional[float] = typer.Option(None,  "--r4",        help="R4 threshold (captain + 4 picks)"),
    soft_cap:  bool            = typer.Option(False, "--soft-cap",  help="Apply soft cap from tournament config (trigger + scale) to --simulate"),
    strategy:  Optional[str]   = typer.Option(None,  "--strategy",  help="role_greedy | greedy_pv | random"),
    top_n:     Optional[int]   = typer.Option(None,  "--top-n",     help="Variance: pick from top N per role (role_greedy)"),
    top_k:          int             = typer.Option(10,   "--top-k",          help="Number of threshold pairs to show in --optimize"),
    min_pass_rate:  float           = typer.Option(0.95, "--min-pass-rate",  help="Minimum feasibility rate to include a pair in --optimize results"),
    sims:           int             = typer.Option(300,  "--sims",           help="Simulations per (r2, r4) pair (--optimize) or total (--analyze)"),
    seed:      Optional[int]   = typer.Option(None,  "--seed",      help="Random seed for reproducible simulation"),
):
    """Draft simulator — optimize thresholds, analyze distributions, or walk through a draft."""
    config   = load_tournament_config()
    registry = PlayerRegistry(config.abs_players_dir)

    if not config.captain_slots:
        typer.echo("No captain_slots configured in active_tournament.yaml — add them before running draft.")
        raise typer.Exit(1)

    if optimize:
        _cmd_optimize(registry, config, sims, strategy, top_n, top_k, min_pass_rate)
    elif simulate:
        _cmd_simulate(registry, config, r2 or 0.0, r4 or 0.0, strategy, seed, top_n, soft_cap=soft_cap)
    elif recommend:
        if not r2:
            typer.echo("--recommend requires --r2 (and optionally --r4)")
            raise typer.Exit(1)
        _cmd_recommend(registry, config, r2 or 0.0, r4 or 0.0, strategy, top_n)
    else:
        _cmd_analyze(registry, config, analyze or sims, r2, r4, strategy, top_n)
