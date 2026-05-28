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


def _resolve(players: Optional[list[str]], config) -> Optional[list[str]]:
    """Disambiguate player search terms, prompting when a term matches multiple profiles."""
    if not players:
        return None
    registry = PlayerRegistry(config.abs_players_dir)
    resolved = resolve_players(registry, players)
    if resolved is None:
        raise typer.Exit(1)
    return [p.effective_id for p in resolved]


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
    players: Optional[list[str]] = typer.Argument(None, help=_PLAYERS_HELP),
    force: bool = typer.Option(False, "--force", help="Re-scrape even if data is already complete"),
    status: bool = typer.Option(False, "--status", help="Show scrape coverage summary and exit"),
):
    """Scrape OP.GG rank history + champion stats in one browser session per account."""
    config = load_tournament_config()
    if status:
        _print_status(config)
        return
    if force and not players:
        confirm_batch_force("opgg", config)
    runner = PipelineRunner(config)
    runner.run_task(Task.OPGG_SCRAPE, players=_resolve(players, config), force=force)


@app.command("opgg-rank")
def opgg_rank(
    players: Optional[list[str]] = typer.Argument(None, help=_PLAYERS_HELP),
    force: bool = typer.Option(False, "--force", help="Re-scrape even if rank data already present"),
):
    """Scrape OP.GG solo queue rank history only (runs AGGREGATE_RANK_STATS after)."""
    config = load_tournament_config()
    if force and not players:
        confirm_batch_force("opgg-rank", config)
    runner = PipelineRunner(config)
    resolved = _resolve(players, config)
    runner.run_task(Task.OPGG_SCRAPE_RANK, players=resolved, force=force)
    runner.run_task(Task.AGGREGATE_RANK_STATS, players=resolved)


@app.command("opgg-champ")
def opgg_champ(
    players: Optional[list[str]] = typer.Argument(None, help=_PLAYERS_HELP),
    force: bool = typer.Option(False, "--force", help="Re-scrape even if champion data already complete"),
):
    """Scrape OP.GG champion stats (wins/losses/OP Score) for all tracked seasons and both queues."""
    config = load_tournament_config()
    if force and not players:
        confirm_batch_force("opgg-champ", config)
    runner = PipelineRunner(config)
    runner.run_task(Task.OPGG_SCRAPE_CHAMP, players=_resolve(players, config), force=force)


@app.command("dpm")
def dpm(
    players: Optional[list[str]] = typer.Argument(None, help=_PLAYERS_HELP),
    force: bool = typer.Option(False, "--force", help="Re-scrape even if champion_data already present"),
):
    """Scrape DPM.lol champion data for all accounts (headless, no login required)."""
    config = load_tournament_config()
    if force and not players:
        confirm_batch_force("dpm", config)
    runner = PipelineRunner(config)
    runner.run_task(Task.DPM_SCRAPE_CHAMP, players=_resolve(players, config), force=force)


@app.command("champ")
def champ(
    players: Optional[list[str]] = typer.Argument(None, help=_PLAYERS_HELP),
    force: bool = typer.Option(False, "--force", help="Strip existing champion data for each source and re-scrape from scratch"),
):
    """Scrape champion pool data from both DPM.lol and OP.GG for all accounts."""
    config = load_tournament_config()
    if force and not players:
        confirm_batch_force("champ", config)
    runner = PipelineRunner(config)
    resolved = _resolve(players, config)
    runner.run_task(Task.DPM_SCRAPE_CHAMP, players=resolved, force=force)
    runner.run_task(Task.OPGG_SCRAPE_CHAMP, players=resolved, force=force)


@app.command("riot-puuid")
def riot_puuid(
    players: Optional[list[str]] = typer.Argument(None, help="Player IDs or Riot IDs to enrich (default: all)"),
    force: bool = typer.Option(False, "--force", help="Re-fetch even if PUUID already present"),
):
    """
    Populate Account.puuid for all accounts via the Riot Account API.
    Requires RIOT_API_KEY to be set in your environment.
    Safe to re-run — skips accounts that already have a PUUID unless --force is passed.
    """
    config = load_tournament_config()
    runner = PipelineRunner(config)
    runner.run_task(Task.RIOT_ENRICH_PUUID, players=_resolve(players, config), force=force)
