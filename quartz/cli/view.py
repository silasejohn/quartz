"""quartz view — full profile + PV breakdown for one player."""

from typing import Optional

import typer

from quartz.cli.filters import prompt_existing_player
from quartz.constants import PAST_YEAR_SEASONS, rank_score
from quartz.player_registry import PlayerRegistry
from quartz.tournament_config import load_tournament_config

SEP_HEAVY = "=" * 60
SEP_LIGHT = "─" * 60
SEP_MID   = "·" * 60


def _r(val, fallback="—"):
    return val if val is not None else fallback


def _pct(val, fallback="—"):
    return f"{val:.0%}" if val is not None else fallback


def _fmt(val, fmt=".1f", fallback="—"):
    return format(val, fmt) if val is not None else fallback


def _pool_scraped_str(pool) -> str:
    parts = []
    if pool.dpm_scraped_at:
        parts.append(f"dpm {pool.dpm_scraped_at.strftime('%Y-%m-%d')}")
    if pool.opgg_scraped_at:
        parts.append(f"opgg {pool.opgg_scraped_at.strftime('%Y-%m-%d')}")
    return "  |  ".join(parts) if parts else "not scraped"


def _print_pool(label: str, pool, current_season: str, limit: int = 12) -> None:
    if not pool.champions:
        return

    # Group entries by champion name, then apply ALL deduplication:
    # If a champion has exactly one named-role entry with current-season data AND an ALL entry,
    # show the named-role row and pull op_score from ALL — suppress the ALL row.
    # Multiple named roles or ALL-only: show as-is.
    from collections import defaultdict
    by_champ: dict[str, list] = defaultdict(list)
    for entry in pool.champions:
        by_champ[entry.champion.lower()].append(entry)

    display_rows: list[tuple] = []  # (entry, op_score_override | None)
    for entries in by_champ.values():
        named           = [e for e in entries if e.role != "ALL"]
        all_entry       = next((e for e in entries if e.role == "ALL"), None)
        named_with_data = [e for e in named if e.get_split(current_season) is not None]

        if len(named_with_data) == 1 and all_entry is not None:
            all_split    = all_entry.get_split(current_season)
            op_override  = all_split.op_score if all_split else None
            display_rows.append((named_with_data[0], op_override))
        else:
            for e in entries:
                if e.get_split(current_season) is not None:
                    display_rows.append((e, None))

    display_rows.sort(
        key=lambda x: x[0].get_split(current_season).games if x[0].get_split(current_season) else 0,
        reverse=True,
    )

    total = len(display_rows)
    shown = display_rows[:limit]

    print(f"\n    {label}  ({total} entries  {_pool_scraped_str(pool)})")
    print(f"    {'Champion':<14} {'Role':<5} {'G':>4}  {'WR%':>5}  {'DPM Sc':>6}  {'OP Sc':>5}  {'KDA':>5}  {'K/D/A':<13}  {'CS/m':>5}  {'KP%':>5}  {'Src':<5}")
    print(f"    {'·' * 88}")

    for entry, op_override in shown:
        s = entry.get_split(current_season)
        if not s:
            continue
        role     = entry.role or "—"
        op_score = op_override if op_override is not None else s.op_score
        kda_str  = "/".join([
            _fmt(s.kills_per_game,   ".1f"),
            _fmt(s.deaths_per_game,  ".1f"),
            _fmt(s.assists_per_game, ".1f"),
        ])
        print(
            f"    {entry.champion:<14} {role:<5} {s.games:>4}  {_pct(s.win_rate):>5}  "
            f"{_fmt(s.dpm_score, '.1f'):>6}  {_fmt(op_score, '.1f'):>5}  {_fmt(s.kda, '.2f'):>5}  "
            f"{kda_str:<13}  {_fmt(s.cs_per_min, '.1f'):>5}  {_pct(s.kill_participation_pct):>5}  {s.source:<5}"
        )

    if total > limit:
        print(f"    … and {total - limit} more")


def _print_champion_pools(profile) -> None:
    accounts_with_champs = [
        acc for acc in profile.accounts
        if not acc.archived and acc.champion_data
        and (acc.champion_data.solo.champions or acc.champion_data.flex.champions)
    ]
    if not accounts_with_champs:
        return

    config = load_tournament_config()

    print("\n  CHAMPION POOLS")
    print(f"  {SEP_LIGHT}")

    for acc in accounts_with_champs:
        print(f"\n  {acc.riot_id}")
        cd = acc.champion_data
        _print_pool("Solo", cd.solo, config.current_lol_split)
        _print_pool("Flex", cd.flex, config.current_lol_split)
    print()


def print_profile(profile) -> None:
    print(f"\n{SEP_HEAVY}")
    print(f"  {profile.effective_id}  (discord: {profile.discord_id})")
    print(SEP_HEAVY)

    # Season data
    print("\n  SEASON DATA")
    print(f"  {SEP_LIGHT}")
    for sd in profile.season_data:
        flagged = "  FLAGGED" if profile.profile_flagged else ""
        print(f"  Season      {sd.season}{flagged}")
        print(f"  Type        {sd.player_type}")
        print(f"  Role        {_r(sd.primary_pos)} / {_r(sd.secondary_pos)}")
        print(f"  Stated Cur  {_r(sd.stated_current_rank)}")
        print(f"  Stated Peak {_r(sd.stated_peak_rank)}")
        print(f"  Point Value {_r(sd.point_value)}")
        if sd.inhouse_wins is not None or sd.inhouse_losses is not None:
            ih_w = sd.inhouse_wins or 0
            ih_l = sd.inhouse_losses or 0
            print(f"  In-House    {ih_w}W / {ih_l}L  ({ih_w + ih_l} games)")
        if sd.manual_adjustments:
            print(f"  Adjustments {len(sd.manual_adjustments)} adjustment(s)")
        print()

    # Accounts
    print(f"  ACCOUNTS  ({len(profile.accounts)} total)")
    print(f"  {SEP_LIGHT}")
    for acc in profile.accounts:
        status_parts = []
        if acc.archived:
            status_parts.append("ARCHIVED")
        for flag in acc.flags:
            label = flag.flag_type.upper().replace("_", " ")
            if flag.dismissed:
                label += " [DISMISSED]"
            status_parts.append(label)
        status = "  [" + ", ".join(status_parts) + "]" if status_parts else ""

        print(f"  {acc.riot_id}  ({acc.player_region})  lv{_r(acc.account_level)}{status}")
        if acc.urls.opgg_url:
            print(f"    OP.GG  {acc.urls.opgg_url}")

        if acc.rank_data and acc.rank_data.solo_splits:
            print(f"    {'Season':<14}  {'Peak Rank':<22}  {'Split Rank':<22}  W/L")
            print(f"    {'·'*56}")
            for split in acc.rank_data.solo_splits:
                wins   = f"{split.wins}W"   if split.wins   is not None else "—"
                losses = f"{split.losses}L" if split.losses is not None else "—"
                wl     = f"{wins}/{losses}" if split.wins is not None or split.losses is not None else "—"
                print(f"    {split.season:<14}  {_r(split.peak_rank):<22}  {_r(split.split_rank):<22}  {wl}")
        else:
            print("    (no rank data scraped)")
        print()

    _print_champion_pools(profile)

    # Enrichment
    d = profile.stats
    if not d:
        print("  ENRICHMENT  (not computed — run AGGREGATE_RANK_STATS)")
        return

    print("  ENRICHMENT")
    print(f"  {SEP_LIGHT}")
    print(f"  All-Time Peak   {_r(d.all_time_peak_rank)}")
    print(f"  Current Rank    {_r(d.current_rank)}")

    if d.rank_data and d.rank_data.solo_splits:
        print("\n  Aggregated Split History (best across all accounts)")
        print(f"  {'Season':<14}  {'Peak Rank':<22}  {'Split Rank':<22}  W/L/WR")
        print(f"  {'·'*60}")
        for agg in d.rank_data.solo_splits:
            wins    = f"{agg.wins}W"    if agg.wins     is not None else "—"
            losses  = f"{agg.losses}L"  if agg.losses   is not None else "—"
            wr      = f"{agg.win_rate}%" if agg.win_rate is not None else "—"
            wl      = f"{wins}/{losses} ({wr})" if agg.wins is not None else "—"
            print(f"  {agg.season:<14}  {_r(agg.peak_rank):<22}  {_r(agg.split_rank):<22}  {wl}")

    # PV breakdown
    pv = d.computed_pv
    if not pv:
        print("\n  PV  (not computed — run PV_COMPUTE)")
        return

    f = pv.features
    w = pv.weights_used

    print("\n  PV BREAKDOWN")
    print(f"  {SEP_LIGHT}")

    print("  Feature 1 — Time-Decayed Historical Peak")
    print(f"    Score       {_r(f.historical_score)}  ({f.splits_used} splits used, coverage={_pct(f.f1_confidence)})")
    if d.rank_data:
        splits_by_season = {agg.season: agg for agg in d.rank_data.solo_splits}
        base_weights = w.historical_base_weights[:w.history_splits]
        past_seasons = PAST_YEAR_SEASONS[:w.history_splits]
        scoreable_ws = [bw for s, bw in zip(past_seasons, base_weights)
                        if splits_by_season.get(s) and splits_by_season[s].peak_rank
                        and rank_score(splits_by_season[s].peak_rank) is not None]
        total_scoreable = sum(scoreable_ws) if scoreable_ws else 1
        for season_key, base_w in zip(past_seasons, base_weights):
            agg = splits_by_season.get(season_key)
            if agg and agg.peak_rank and rank_score(agg.peak_rank) is not None:
                pts = rank_score(agg.peak_rank)
                games = (agg.wins or 0) + (agg.losses or 0)
                games_str = f"{games}g" if games > 0 else "0g (excluded)"
                norm_w = base_w / total_scoreable
                print(f"    {season_key:<14}  peak={_r(agg.peak_rank):<22}  pts={pts:<7.3f}  base_w={norm_w:.3f}  games={games_str}")
            else:
                print(f"    {season_key:<14}  (no data)")

    print("\n  Feature 2 — Confidence-Adjusted Current Rank")
    print(f"    Current Rank    {_r(d.current_rank)}  ->  pts={_r(f.current_rank_pts)}")
    print(f"    Default Rank    {_r(f.default_rank_used)}  (all-time peak — regression target)")
    print(f"    Games Played    {_r(f.games_played)}  (N={_r(f.n_threshold_used)})")
    print(f"    Confidence      {_pct(f.confidence)}  ->  1 - e^(-{_r(f.games_played)}/{_r(f.n_threshold_used)})")
    print(f"    Adjusted Score  {_r(f.adjusted_current_pts)}")
    if f.stated_rank_diff is not None:
        direction = "understated" if f.stated_rank_diff > 0 else "overstated"
        print(f"    Stated Diff     {f.stated_rank_diff:+.3f}  ({direction})")

    if f.inhouse_total is not None:
        floor_str = f"  (floor: {w.min_games_threshold} games)"
        print("\n  Feature 3 — In-House Modifier")
        print(f"    Record      {_r(f.inhouse_wins)}W / {_r(f.inhouse_losses)}L  ({_r(f.inhouse_total)} games){floor_str}")
        if f.wilson_lower is not None:
            wlb_note = "  — WLB <= 0.50, no upside confidence" if (f.inhouse_modifier == 0.0 and f.wilson_lower <= 0.5) else ""
            print(f"    Wilson LB   {f.wilson_lower:.4f}{wlb_note}")
        elif f.inhouse_total < w.min_games_threshold:
            print(f"    Wilson LB   —  ({f.inhouse_total} < {w.min_games_threshold} games, below floor)")
        ceiling_str = f"{w.realistic_max_override:.4f} (override)" if w.realistic_max_override is not None else "derived from pool"
        print(f"    Ceiling     {ceiling_str}")
        print(f"    Modifier    {f.inhouse_modifier:+.2f}")

    seasons_with_adj = [sd for sd in profile.season_data if sd.manual_adjustments]
    if seasons_with_adj:
        print("\n  Feature 4 — Manual Adjustments")
        for sd in seasons_with_adj:
            print(f"    {sd.season}")
            for adj in sd.manual_adjustments:
                note_str = f"  ({adj.note})" if adj.note else ""
                print(f"      {adj.category:<28}  -{adj.value:.1f}{note_str}")
            season_total = sum(adj.value for adj in sd.manual_adjustments)
            print(f"      {'─'*36}")
            print(f"      Total reduction   {season_total:.1f}")
        if f.manual_adjustment_total > 0:
            print(f"    Applied this PV:  -{f.manual_adjustment_total:.1f}")

    print(f"\n  {SEP_MID}")
    print(f"  F1 (historical)   {_r(f.historical_score):<10}  weight={w.w_historical}  coverage={_pct(f.f1_confidence)}")
    print(f"  F2 (current adj)  {_r(f.adjusted_current_pts):<10}  weight={w.w_current}")
    print(f"  base_pv           {pv.pv_rank_only}")
    print(f"  + baseline        +{w.baseline}")
    print(f"  - inhouse mod     {-f.inhouse_modifier:+.2f}")
    print(f"  - manual adj      {-f.manual_adjustment_total:+.2f}")
    print(f"  {'─'*36}")
    if pv.flag_reason == "no_data":
        flag_str = "  FLAGGED (no data)"
    elif pv.flag_reason == "ineligible":
        shadow_str = f"  shadow={round(pv.shadow_pv)}" if pv.shadow_pv is not None else ""
        flag_str = f"  INF (ineligible){shadow_str}"
    else:
        flag_str = ""
    print(f"  POINT VALUE       {pv.point_value}{flag_str}")
    print()


def view(
    player: Optional[str] = typer.Argument(None, help="Player ID or partial name to inspect"),
):
    """Drill-down viewer — full profile, rank history, PV breakdown for one player."""
    config   = load_tournament_config()
    registry = PlayerRegistry(config.abs_players_dir)

    if player:
        matches = registry.find_profiles([player])
        if not matches:
            typer.echo(f"No player found matching '{player}'")
            raise typer.Exit(1)
        if len(matches) > 1:
            typer.echo(f"Multiple matches: {', '.join(p.effective_id for p in matches)}")
            raise typer.Exit(1)
        profile = matches[0]
    else:
        profile = prompt_existing_player(registry)

    if not profile:
        typer.echo("No player selected.")
        raise typer.Exit(1)

    print_profile(profile)
