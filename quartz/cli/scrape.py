"""
quartz scrape — subcommands for scraping external data sources.

    quartz scrape opgg [PLAYERS...]           combined OP.GG rank + champ in one session
    quartz scrape opgg --status               scrape coverage summary across all accounts
    quartz scrape opgg-rank [PLAYERS...]      OP.GG rank history only
    quartz scrape opgg-champ [PLAYERS...]     OP.GG champion stats (all historical seasons)
    quartz scrape dpm [PLAYERS...]            DPM.lol champion stats (current split)
    quartz scrape champ [PLAYERS...]          combined: DPM + OP.GG champion scrape
    quartz scrape riot-puuid [PLAYERS...]     populate Account.puuid via Riot API
"""

from typing import Optional

import typer

from quartz.cli.filters import confirm_batch_force, resolve_players
from quartz.pipeline_runner import PipelineRunner, Task
from quartz.player_registry import PlayerRegistry
from quartz.tournament_config import load_tournament_config

app = typer.Typer(no_args_is_help=True)

_PLAYERS_HELP = "Player IDs or Riot IDs to scrape (default: all)"
_TYPES_HELP   = "Comma-separated player types to include (e.g. main,captain — default: all)"


def _resolve(players: Optional[list[str]], config) -> Optional[list[str]]:
    """Disambiguate player search terms, prompting when a term matches multiple profiles."""
    if not players:
        return None
    registry = PlayerRegistry(config.abs_players_dir)
    resolved = resolve_players(registry, players)
    if resolved is None:
        raise typer.Exit(1)
    return [p.effective_id for p in resolved]


def _first_line(msg: str) -> str:
    """Return the first line of a (possibly multi-line) error message."""
    return msg.splitlines()[0].strip() if msg else msg


def _build_error_groups(config, check_rank: bool = True, check_champ: bool = False) -> list[tuple[str, set[str]]]:
    """Return sorted list of (error_key, player_ids) across all accounts with a scrape error."""
    from collections import defaultdict
    registry = PlayerRegistry(config.abs_players_dir)
    error_players: dict[str, set[str]] = defaultdict(set)
    for p in registry.load_all():
        for account in p.accounts:
            if account.archived:
                continue
            if check_rank and account.rank_data and account.rank_data.last_scrape_error:
                error_players[_first_line(account.rank_data.last_scrape_error)].add(p.effective_id)
            if check_champ and account.champion_data:
                cd = account.champion_data
                for err in filter(None, [cd.solo.opgg_last_scrape_error, cd.flex.opgg_last_scrape_error]):
                    error_players[_first_line(err)].add(p.effective_id)
    return sorted(error_players.items(), key=lambda kv: -len(kv[1]))


def _prompt_group_selection(groups: list[tuple[str, set[str]]], verb: str) -> Optional[set[int]]:
    """Print the error group table and return selected 0-based indices, or None if cancelled."""
    typer.echo(f"\n  {verb.capitalize()} queue — {sum(len(v) for _, v in groups)} error group(s):")
    typer.echo(f"  {'─' * 72}")
    for i, (err, players) in enumerate(groups, 1):
        typer.echo(f"  {i}.  [{len(players):>2} player(s)]  {err}")
        typer.echo(f"       {', '.join(sorted(players))}")
    typer.echo(f"  {'─' * 72}")

    raw = input(f"\n  Select groups to {verb} (e.g. 1,3  or 'all'  or q to cancel): ").strip().lower()
    if raw in ("q", ""):
        typer.echo("  Cancelled.")
        return None

    if raw == "all":
        return set(range(len(groups)))

    selected: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit() and 1 <= int(part) <= len(groups):
            selected.add(int(part) - 1)
        else:
            typer.echo(f"  Invalid selection '{part}' — enter numbers 1-{len(groups)}, 'all', or 'q'.")
            raise typer.Exit(1)
    return selected


def _resolve_errored(retry: bool, config, check_rank: bool = True, check_champ: bool = False) -> Optional[list[str]]:
    """Return effective_ids for all players with a scrape error set, for use with --retry."""
    if not retry:
        return None
    groups = _build_error_groups(config, check_rank, check_champ)
    if not groups:
        typer.echo("  No players with scrape errors found — nothing to retry.")
        raise typer.Exit(0)

    selected = _prompt_group_selection(groups, "retry")
    if selected is None:
        raise typer.Exit(0)

    matched: set[str] = set()
    for idx in selected:
        matched |= groups[idx][1]

    typer.echo(f"\n  Retrying {len(matched)} player(s): {', '.join(sorted(matched))}")
    return sorted(matched)


def _do_clear_errors(clear_errors: bool, config, check_rank: bool = True, check_champ: bool = False) -> None:
    """Prompt the user to select error groups to clear, then wipe last_scrape_error in-place."""
    if not clear_errors:
        return
    groups = _build_error_groups(config, check_rank, check_champ)
    if not groups:
        typer.echo("  No players with scrape errors found — nothing to clear.")
        raise typer.Exit(0)

    selected = _prompt_group_selection(groups, "clear")
    if selected is None:
        raise typer.Exit(0)

    matched: set[str] = set()
    for idx in selected:
        matched |= groups[idx][1]

    registry = PlayerRegistry(config.abs_players_dir)
    cleared = 0
    for profile in registry.find_profiles(list(matched)):
        changed = False
        for account in profile.accounts:
            if account.archived:
                continue
            if check_rank and account.rank_data and account.rank_data.last_scrape_error:
                account.rank_data.last_scrape_error = None
                changed = True
                cleared += 1
            if check_champ and account.champion_data:
                cd = account.champion_data
                if cd.solo.opgg_last_scrape_error:
                    cd.solo.opgg_last_scrape_error = None
                    changed = True
                    cleared += 1
                if cd.flex.opgg_last_scrape_error:
                    cd.flex.opgg_last_scrape_error = None
                    changed = True
                    cleared += 1
        if changed:
            profile.touch(source="clear_errors")
            registry.save(profile)

    typer.echo(f"\n  Cleared {cleared} error(s) across {len(matched)} player(s).")
    raise typer.Exit(0)


def _resolve_by_types(types_raw: Optional[str], config) -> Optional[list[str]]:
    """Return effective_ids for all players whose type in the current round is in types_raw."""
    if not types_raw:
        return None
    wanted = {t.strip().lower() for t in types_raw.split(",")}
    registry = PlayerRegistry(config.abs_players_dir)
    matched = [
        p.effective_id
        for p in registry.load_all()
        if any(
            sd.season == config.round_id and sd.player_type in wanted
            for sd in p.season_data
        )
    ]
    if not matched:
        typer.echo(f"  No players found with types: {types_raw}")
        raise typer.Exit(0)
    return matched


def _print_status(config) -> None:
    """Print a scrape coverage summary for all active accounts."""
    registry = PlayerRegistry(config.abs_players_dir)
    all_profiles = registry.load_all()
    lol_split = config.current_lol_split

    total = rank_done = champ_done = both_done = errors = never = needs_riot_id = 0

    for profile in all_profiles:
        for account in profile.accounts:
            if account.archived:
                continue
            total += 1

            has_name_change = any(
                f.flag_type == "name_changed" and not f.dismissed
                for f in account.flags
            )
            if has_name_change:
                needs_riot_id += 1
                continue

            rd = account.rank_data
            cd = account.champion_data

            rank_ok = rd is not None and rd.is_complete(lol_split)
            opgg_champ_ok = (
                cd is not None
                and cd.solo.opgg_complete()
                and cd.flex.opgg_complete()
            )

            has_error = (
                (rd is not None and rd.last_scrape_error is not None)
                or (cd is not None and (
                    cd.solo.opgg_last_scrape_error is not None
                    or cd.flex.opgg_last_scrape_error is not None
                ))
            )

            if rank_ok and opgg_champ_ok:
                both_done += 1
            elif rank_ok:
                rank_done += 1
            elif opgg_champ_ok:
                champ_done += 1
            elif has_error:
                errors += 1
            else:
                never += 1

    typer.echo(f"\n  OP.GG Scrape Coverage — {config.round_id}  (split: {lol_split})")
    typer.echo(f"  {'─'*46}")
    typer.echo(f"  {'total active accounts':<26} {total:>4}")
    typer.echo(f"  {'complete (rank + champ)':<26} {both_done:>4}")
    typer.echo(f"  {'rank only':<26} {rank_done:>4}")
    typer.echo(f"  {'champ only':<26} {champ_done:>4}")
    typer.echo(f"  {'has scrape error':<26} {errors:>4}  (will retry on next run)")
    typer.echo(f"  {'never attempted':<26} {never:>4}")
    typer.echo(f"  {'needs riot_id update':<26} {needs_riot_id:>4}  (name change — manual fix)")
    typer.echo(f"  {'─'*46}\n")


@app.command("opgg")
def opgg(
    players:      Optional[list[str]] = typer.Argument(None, help=_PLAYERS_HELP),
    force:        bool = typer.Option(False,  "--force",        help="Re-scrape even if data is already complete"),
    status:       bool = typer.Option(False,  "--status",       help="Show scrape coverage summary and exit"),
    retry:        bool = typer.Option(False,  "--retry",        help="Re-scrape all accounts with a recorded scrape error"),
    clear_errors: bool = typer.Option(False,  "--clear-errors", help="Clear recorded scrape errors without re-scraping"),
    types:        Optional[str] = typer.Option(None, "--types", help=_TYPES_HELP),
):
    """Scrape OP.GG rank history + champion stats in one browser session per account."""
    config = load_tournament_config()
    if status:
        _print_status(config)
        return
    _do_clear_errors(clear_errors, config, check_rank=True, check_champ=True)
    resolved = _resolve(players, config) or _resolve_errored(retry, config, check_rank=True, check_champ=True) or _resolve_by_types(types, config)
    if force and not resolved:
        confirm_batch_force("opgg", config)
    PipelineRunner(config).run_task(Task.OPGG_SCRAPE, players=resolved, force=force)


@app.command("opgg-rank")
def opgg_rank(
    players:      Optional[list[str]] = typer.Argument(None, help=_PLAYERS_HELP),
    force:        bool = typer.Option(False, "--force",        help="Re-scrape even if rank data already present"),
    retry:        bool = typer.Option(False, "--retry",        help="Re-scrape all accounts with a recorded rank scrape error"),
    clear_errors: bool = typer.Option(False, "--clear-errors", help="Clear recorded rank scrape errors without re-scraping"),
    types:        Optional[str] = typer.Option(None, "--types", help=_TYPES_HELP),
):
    """Scrape OP.GG solo queue rank history only (runs AGGREGATE_RANK_STATS after)."""
    config = load_tournament_config()
    _do_clear_errors(clear_errors, config, check_rank=True)
    resolved = _resolve(players, config) or _resolve_errored(retry, config, check_rank=True) or _resolve_by_types(types, config)
    if force and not resolved:
        confirm_batch_force("opgg-rank", config)
    runner = PipelineRunner(config)
    runner.run_task(Task.OPGG_SCRAPE_RANK, players=resolved, force=force)
    runner.run_task(Task.AGGREGATE_RANK_STATS, players=resolved)


@app.command("opgg-champ")
def opgg_champ(
    players:      Optional[list[str]] = typer.Argument(None, help=_PLAYERS_HELP),
    force:        bool = typer.Option(False, "--force",        help="Re-scrape even if champion data already complete"),
    retry:        bool = typer.Option(False, "--retry",        help="Re-scrape all accounts with a recorded champ scrape error"),
    clear_errors: bool = typer.Option(False, "--clear-errors", help="Clear recorded champ scrape errors without re-scraping"),
    types:        Optional[str] = typer.Option(None, "--types", help=_TYPES_HELP),
):
    """Scrape OP.GG champion stats (wins/losses/OP Score) for all tracked seasons and both queues."""
    config = load_tournament_config()
    _do_clear_errors(clear_errors, config, check_champ=True)
    resolved = _resolve(players, config) or _resolve_errored(retry, config, check_champ=True) or _resolve_by_types(types, config)
    if force and not resolved:
        confirm_batch_force("opgg-champ", config)
    PipelineRunner(config).run_task(Task.OPGG_SCRAPE_CHAMP, players=resolved, force=force)


@app.command("dpm")
def dpm(
    players:      Optional[list[str]] = typer.Argument(None, help=_PLAYERS_HELP),
    force:        bool = typer.Option(False, "--force",        help="Re-scrape even if champion_data already present"),
    retry:        bool = typer.Option(False, "--retry",        help="Re-scrape all accounts with a recorded DPM scrape error"),
    clear_errors: bool = typer.Option(False, "--clear-errors", help="Clear recorded champ scrape errors without re-scraping"),
    types:        Optional[str] = typer.Option(None, "--types", help=_TYPES_HELP),
    queue:        Optional[str] = typer.Option(None, "--queue", help="Limit to one queue: solo or flex"),
    lanes:        Optional[str] = typer.Option(None, "--lanes", help="Comma-separated lanes to scrape: top,jungle,middle,bottom,utility"),
):
    """Scrape DPM.lol champion data for all accounts (headless, no login required)."""
    config = load_tournament_config()
    _do_clear_errors(clear_errors, config, check_champ=True)
    resolved = _resolve(players, config) or _resolve_errored(retry, config, check_champ=True) or _resolve_by_types(types, config)
    if force and not resolved:
        confirm_batch_force("dpm", config)
    queues_filter = [queue.lower().strip()] if queue else None
    lanes_filter  = [l.strip().lower() for l in lanes.split(",")] if lanes else None
    PipelineRunner(config).run_task(Task.DPM_SCRAPE_CHAMP, players=resolved, force=force,
                                    queues=queues_filter, lanes=lanes_filter)


@app.command("champ")
def champ(
    players:      Optional[list[str]] = typer.Argument(None, help=_PLAYERS_HELP),
    force:        bool = typer.Option(False, "--force",        help="Strip existing champion data for each source and re-scrape from scratch"),
    retry:        bool = typer.Option(False, "--retry",        help="Re-scrape all accounts with a recorded champ scrape error"),
    clear_errors: bool = typer.Option(False, "--clear-errors", help="Clear recorded champ scrape errors without re-scraping"),
    types:        Optional[str] = typer.Option(None, "--types", help=_TYPES_HELP),
):
    """Scrape champion pool data from both DPM.lol and OP.GG for all accounts."""
    config = load_tournament_config()
    _do_clear_errors(clear_errors, config, check_champ=True)
    resolved = _resolve(players, config) or _resolve_errored(retry, config, check_champ=True) or _resolve_by_types(types, config)
    if force and not resolved:
        confirm_batch_force("champ", config)
    runner = PipelineRunner(config)
    runner.run_task(Task.DPM_SCRAPE_CHAMP, players=resolved, force=force)
    runner.run_task(Task.OPGG_SCRAPE_CHAMP, players=resolved, force=force)


@app.command("riot-puuid")
def riot_puuid(
    players: Optional[list[str]] = typer.Argument(None, help="Player IDs or Riot IDs to enrich (default: all)"),
    force:   bool = typer.Option(False, "--force", help="Re-fetch even if PUUID already present"),
    types:   Optional[str] = typer.Option(None, "--types", help=_TYPES_HELP),
):
    """
    Populate Account.puuid for all accounts via the Riot Account API.
    Requires RIOT_API_KEY to be set in your environment.
    Safe to re-run — skips accounts that already have a PUUID unless --force is passed.
    """
    config = load_tournament_config()
    resolved = _resolve(players, config) or _resolve_by_types(types, config)
    PipelineRunner(config).run_task(Task.RIOT_ENRICH_PUUID, players=resolved, force=force)
