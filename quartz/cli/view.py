"""quartz view — full profile + PV breakdown for one player."""

from typing import Optional
from urllib.parse import quote

import typer
from rich.markup import escape

from quartz.account_flags import FLAG_DESCRIPTIONS
from quartz.models.champion_data import OPGG_EXCLUSIVE_FIELDS
from quartz.cli.filters import prompt_existing_player, prompt_from_matches
from quartz.constants import PAST_YEAR_SEASONS, rank_score
from quartz.player_registry import PlayerRegistry
from quartz.tournament_config import load_tournament_config
from quartz.utils.logging import console

def _build_dpm_url(riot_id: str) -> str:
    name, tag = riot_id.split("#", 1) if "#" in riot_id else (riot_id, "NA1")
    return f"https://dpm.lol/{quote(name, safe='')}-{tag}"


SEP_HEAVY = "=" * 60
SEP_LIGHT = "─" * 60
SEP_MID   = "·" * 60


def _r(val, fallback="—"):
    return val if val is not None else fallback


def _pct(val, fallback="—"):
    return f"{val:.0%}" if val is not None else fallback


def _fmt(val, fmt=".1f", fallback="—"):
    return format(val, fmt) if val is not None else fallback


def _e(val) -> str:
    """Escape a value for safe use inside Rich markup strings."""
    return escape(str(val)) if val is not None else "—"


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

    from collections import defaultdict
    by_champ: dict[str, list] = defaultdict(list)
    for entry in pool.champions:
        by_champ[entry.champion.lower()].append(entry)

    display_rows: list[tuple] = []
    for entries in by_champ.values():
        named           = [e for e in entries if e.role != "ALL"]
        all_entry       = next((e for e in entries if e.role == "ALL"), None)
        named_with_data = [e for e in named if e.get_split(current_season) is not None]

        if len(named_with_data) == 1 and all_entry is not None:
            all_split = all_entry.get_split(current_season)
            # Gap-fill OPGG-exclusive fields from the ALL entry — valid because the
            # champion was only played in one role, so ALL and BOT cover identical games.
            overrides = (
                {f: v for f in OPGG_EXCLUSIVE_FIELDS if (v := getattr(all_split, f)) is not None}
                if all_split else {}
            )
            display_rows.append((named_with_data[0], overrides))
        else:
            for e in entries:
                if e.get_split(current_season) is not None:
                    display_rows.append((e, {}))

    display_rows.sort(
        key=lambda x: x[0].get_split(current_season).games if x[0].get_split(current_season) else 0,
        reverse=True,
    )

    total = len(display_rows)
    shown = display_rows[:limit]

    console.print(f"\n    [bold]{label}[/bold]  ({total} entries  {_pool_scraped_str(pool)})")
    print(f"    {'Champion':<14} {'Role':<5} {'G':>4}  {'WR%':>5}  {'DPM Sc':>6}  {'OP Sc':>5}  {'KDA':>5}  {'K/D/A':<13}  {'CS/m':>5}  {'KP%':>5}  {'Src':<5}")
    console.print(f"    [dim]{'·' * 88}[/dim]")

    for entry, overrides in shown:
        s = entry.get_split(current_season)
        if not s:
            continue
        role     = entry.role or "—"

        def _ov(field):
            v = overrides.get(field)
            return v if v is not None else getattr(s, field)

        op_score = _ov("op_score")
        kda_str  = "/".join([
            _fmt(s.kills_per_game,   ".1f"),
            _fmt(s.deaths_per_game,  ".1f"),
            _fmt(s.assists_per_game, ".1f"),
        ])
        src = "mix" if (s.source == "multi" or overrides) else s.source
        print(
            f"    {entry.champion:<14} {role:<5} {s.games:>4}  {_pct(s.win_rate):>5}  "
            f"{_fmt(s.dpm_score, '.1f'):>6}  {_fmt(op_score, '.1f'):>5}  {_fmt(s.kda, '.2f'):>5}  "
            f"{kda_str:<13}  {_fmt(s.cs_per_min, '.1f'):>5}  {_pct(s.kill_participation_pct):>5}  {src:<5}"
        )

    if total > limit:
        console.print(f"    [dim]… and {total - limit} more[/dim]")


def _print_champion_pools(profile) -> None:
    accounts_with_champs = [
        acc for acc in profile.accounts
        if not acc.archived and acc.champion_data
        and (acc.champion_data.solo.champions or acc.champion_data.flex.champions)
    ]
    if not accounts_with_champs:
        return

    config = load_tournament_config()

    console.print(f"\n  [bold]CHAMPION POOLS[/bold]")
    console.print(f"  [dim]{SEP_LIGHT}[/dim]")

    for acc in accounts_with_champs:
        console.print(f"\n  [bold]{_e(acc.riot_id)}[/bold]")
        cd = acc.champion_data
        _print_pool("Solo", cd.solo, config.current_lol_split)
        _print_pool("Flex", cd.flex, config.current_lol_split)
    print()


def print_profile(profile) -> None:
    console.print(f"\n[bold blue]{SEP_HEAVY}[/bold blue]")
    console.print(f"  [bold]{_e(profile.effective_id)}[/bold]  (discord: {_e(profile.discord_id)})")
    console.print(f"[bold blue]{SEP_HEAVY}[/bold blue]")

    # Season data
    console.print(f"\n  [bold]SEASON DATA[/bold]")
    console.print(f"  [dim]{SEP_LIGHT}[/dim]")
    for sd in profile.season_data:
        flagged_str = "  [bold red]FLAGGED[/bold red]" if profile.profile_flagged else ""
        console.print(f"  Season      {_e(sd.season)}{flagged_str}")
        console.print(f"  Type        {_e(sd.player_type)}")
        console.print(f"  Role        {_e(sd.primary_pos)} / {_e(sd.secondary_pos)}")
        console.print(f"  Stated Cur  {_e(sd.stated_current_rank)}")
        console.print(f"  Stated Peak {_e(sd.stated_peak_rank)}")
        console.print(f"  Point Value {_e(sd.point_value)}")
        if sd.inhouse_wins is not None or sd.inhouse_losses is not None:
            ih_w = sd.inhouse_wins or 0
            ih_l = sd.inhouse_losses or 0
            console.print(f"  In-House    {ih_w}W / {ih_l}L  ({ih_w + ih_l} games)")
        if sd.manual_adjustments:
            console.print(f"  Adjustments {len(sd.manual_adjustments)} adjustment(s)")
        print()

    # Accounts
    console.print(f"  [bold]ACCOUNTS[/bold]  ({len(profile.accounts)} total)")
    console.print(f"  [dim]{SEP_LIGHT}[/dim]")
    for acc in profile.accounts:
        status_parts = []
        if acc.archived:
            status_parts.append("[dim]ARCHIVED[/dim]")
        active_flags    = [f for f in acc.flags if not f.dismissed]
        dismissed_flags = [f for f in acc.flags if f.dismissed]
        for flag in active_flags:
            label = flag.flag_type.upper().replace("_", " ")
            status_parts.append(f"[red]{label}[/red]")
        for flag in dismissed_flags:
            label = flag.flag_type.upper().replace("_", " ")
            status_parts.append(f"[dim]{label} [dismissed][/dim]")
        status = "  [" + ", ".join(status_parts) + "]" if status_parts else ""

        console.print(f"  {_e(acc.riot_id)}  ({_e(acc.player_region)})  lv{_e(acc.account_level)}{status}")
        for flag in active_flags:
            desc = FLAG_DESCRIPTIONS.get(flag.flag_type, flag.flag_type)
            detail_str = f"  ({_e(flag.detail)})" if flag.detail else ""
            console.print(f"    [red]![/red] {escape(desc)}{detail_str}")
        if acc.urls.opgg_url:
            console.print(f"    [dim]OP.GG  {_e(acc.urls.opgg_url)}[/dim]")
        dpm_url = acc.urls.dpm_url or _build_dpm_url(acc.riot_id)
        console.print(f"    [dim]DPM    {_e(dpm_url)}[/dim]")

        if acc.rank_data and acc.rank_data.solo_splits:
            print(f"    {'Season':<14}  {'Peak Rank':<22}  {'Split Rank':<22}  W/L")
            console.print(f"    [dim]{'·'*56}[/dim]")
            for split in acc.rank_data.solo_splits:
                wins   = f"{split.wins}W"   if split.wins   is not None else "—"
                losses = f"{split.losses}L" if split.losses is not None else "—"
                wl     = f"{wins}/{losses}" if split.wins is not None or split.losses is not None else "—"
                print(f"    {split.season:<14}  {_r(split.peak_rank):<22}  {_r(split.split_rank):<22}  {wl}")
        else:
            console.print("    [dim](no rank data scraped)[/dim]")
        print()

    _print_champion_pools(profile)

    # Enrichment
    d = profile.stats
    if not d:
        console.print("  [dim]ENRICHMENT  (not computed — run AGGREGATE_RANK_STATS)[/dim]")
        return

    console.print(f"  [bold]ENRICHMENT[/bold]")
    console.print(f"  [dim]{SEP_LIGHT}[/dim]")
    console.print(f"  All-Time Peak   {_e(d.all_time_peak_rank)}")
    console.print(f"  Current Rank    {_e(d.current_rank)}")

    if d.rank_data and d.rank_data.solo_splits:
        console.print("\n  [bold]Aggregated Split History[/bold] (best across all accounts)")
        print(f"  {'Season':<14}  {'Peak Rank':<22}  {'Split Rank':<22}  W/L/WR")
        console.print(f"  [dim]{'·'*60}[/dim]")
        for agg in d.rank_data.solo_splits:
            wins   = f"{agg.wins}W"    if agg.wins     is not None else "—"
            losses = f"{agg.losses}L"  if agg.losses   is not None else "—"
            wr     = f"{agg.win_rate}%" if agg.win_rate is not None else "—"
            wl     = f"{wins}/{losses} ({wr})" if agg.wins is not None else "—"
            print(f"  {agg.season:<14}  {_r(agg.peak_rank):<22}  {_r(agg.split_rank):<22}  {wl}")

    # PV breakdown
    pv = d.computed_pv
    if not pv:
        console.print("\n  [dim]PV  (not computed — run PV_COMPUTE)[/dim]")
        return

    f = pv.features
    w = pv.weights_used

    console.print(f"\n  [bold]PV BREAKDOWN[/bold]")
    console.print(f"  [dim]{SEP_LIGHT}[/dim]")

    console.print("  [bold]Feature 1[/bold] — Time-Decayed Historical Peak")
    console.print(f"    Score       {_r(f.historical_score)}  ({f.splits_used} splits used, coverage={_pct(f.f1_confidence)})")
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
                console.print(f"    [dim]{season_key:<14}  (no data)[/dim]")

    console.print("\n  [bold]Feature 2[/bold] — Confidence-Adjusted Current Rank")
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
        console.print("\n  [bold]Feature 3[/bold] — In-House Modifier")
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
        console.print("\n  [bold]Feature 4[/bold] — Manual Adjustments")
        for sd in seasons_with_adj:
            console.print(f"    {_e(sd.season)}")
            for adj in sd.manual_adjustments:
                note_str = f"  ({_e(adj.note)})" if adj.note else ""
                print(f"      {adj.category:<28}  -{adj.value:.1f}{note_str}")
            season_total = sum(adj.value for adj in sd.manual_adjustments)
            console.print(f"      [dim]{'─'*36}[/dim]")
            print(f"      Total reduction   {season_total:.1f}")
        if f.manual_adjustment_total > 0:
            print(f"    Applied this PV:  -{f.manual_adjustment_total:.1f}")

    console.print(f"\n  [dim]{SEP_MID}[/dim]")
    print(f"  F1 (historical)   {_r(f.historical_score):<10}  weight={w.w_historical}  coverage={_pct(f.f1_confidence)}")
    print(f"  F2 (current adj)  {_r(f.adjusted_current_pts):<10}  weight={w.w_current}")
    print(f"  base_pv           {pv.pv_rank_only}")
    print(f"  + baseline        +{w.baseline}")
    print(f"  - inhouse mod     {-f.inhouse_modifier:+.2f}")
    print(f"  - manual adj      {-f.manual_adjustment_total:+.2f}")
    console.print(f"  [dim]{'─'*36}[/dim]")
    if pv.flag_reason == "no_data":
        pv_suffix = "  [bold red]FLAGGED (no data)[/bold red]"
    elif pv.flag_reason == "ineligible":
        shadow_str = f"  shadow={round(pv.shadow_pv)}" if pv.shadow_pv is not None else ""
        pv_suffix = f"  [bold yellow]INF (ineligible)[/bold yellow]{shadow_str}"
    else:
        pv_suffix = ""
    console.print(f"  [bold]POINT VALUE[/bold]       {_e(pv.point_value)}{pv_suffix}")
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
            profile = prompt_from_matches(matches)
        else:
            profile = matches[0]
    else:
        profile = prompt_existing_player(registry)

    if not profile:
        typer.echo("No player selected.")
        raise typer.Exit(1)

    print_profile(profile)


