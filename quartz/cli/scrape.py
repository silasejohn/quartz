"""
quartz scrape — subcommands for scraping external data sources.

    quartz scrape opgg [PLAYERS...]                 targeted OP.GG rank scrape
    quartz scrape opgg-batch [--reset] [--status]   batch OP.GG with progress tracking
    quartz scrape riot-puuid [PLAYERS...] [--force] populate Account.puuid via Riot API
"""

import json
import os
from typing import Optional

import typer

from quartz.cli.filters import resolve_players
from quartz.pipeline_runner import PipelineRunner, Task
from quartz.player_registry import PlayerRegistry
from quartz.tournament_config import load_tournament_config
from quartz.utils.logging import info_print, success_print

app = typer.Typer(no_args_is_help=True)

_PROGRESS_FILENAME = "opgg_enrich_progress.json"
_PROGRESS_KEYS = ("completed", "soft_failed", "failed", "needs_riot_id")
_PLAYERS_HELP = "Player IDs or Riot IDs to scrape (default: all)"


def _load_progress(path: str) -> dict:
    defaults = {k: [] for k in _PROGRESS_KEYS}
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
        for k in _PROGRESS_KEYS:
            data.setdefault(k, [])
        return data
    return defaults


def _save_progress(progress: dict, path: str) -> None:
    with open(path, "w") as f:
        json.dump(progress, f, indent=2)


def _resolve(players: Optional[list[str]], config) -> Optional[list[str]]:
    """Disambiguate player search terms, prompting when a term matches multiple profiles."""
    if not players:
        return None
    registry = PlayerRegistry(config.abs_players_dir)
    resolved = resolve_players(registry, players)
    if resolved is None:
        raise typer.Exit(1)
    return [p.effective_id for p in resolved]


@app.command("dpm")
def dpm(
    players: Optional[list[str]] = typer.Argument(None, help=_PLAYERS_HELP),
    force: bool = typer.Option(False, "--force", help="Re-scrape even if champion_data already present"),
):
    """Scrape DPM.lol champion data for all accounts (headless, no login required)."""
    config = load_tournament_config()
    runner = PipelineRunner(config)
    runner.run_task(Task.DPM_SCRAPE_CHAMP, players=_resolve(players, config), force=force)


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


@app.command("opgg-champ")
def opgg_champ(
    players: Optional[list[str]] = typer.Argument(None, help=_PLAYERS_HELP),
    force: bool = typer.Option(False, "--force", help="Re-scrape even if opgg_scraped_at already set"),
):
    """Scrape OP.GG champion stats (wins/losses/OP Score) for all tracked seasons and both queues."""
    config = load_tournament_config()
    runner = PipelineRunner(config)
    runner.run_task(Task.OPGG_SCRAPE_CHAMP, players=_resolve(players, config), force=force)


@app.command("champ")
def champ(
    players: Optional[list[str]] = typer.Argument(None, help=_PLAYERS_HELP),
    force: bool = typer.Option(False, "--force", help="Strip existing champion data for each source and re-scrape from scratch"),
):
    """Scrape champion pool data from both DPM.lol and OP.GG for all accounts."""
    config = load_tournament_config()
    runner = PipelineRunner(config)
    resolved = _resolve(players, config)
    runner.run_task(Task.DPM_SCRAPE_CHAMP, players=resolved, force=force)
    runner.run_task(Task.OPGG_SCRAPE_CHAMP, players=resolved, force=force)


@app.command("opgg")
def opgg(
    players: Optional[list[str]] = typer.Argument(None, help=_PLAYERS_HELP),
    force: bool = typer.Option(False, "--force", help="Re-scrape even if rank data already present"),
):
    """Scrape OP.GG solo queue rank data for specific players (or all if none given)."""
    config = load_tournament_config()
    runner = PipelineRunner(config)
    resolved = _resolve(players, config)
    runner.run_task(Task.OPGG_SCRAPE_RANK, players=resolved, force=force)
    runner.run_task(Task.AGGREGATE_RANK_STATS, players=resolved)


@app.command("opgg-batch")
def opgg_batch(
    reset: bool = typer.Option(False, "--reset", help="Clear progress and start fresh"),
    status: bool = typer.Option(False, "--status", help="Show progress summary and exit"),
):
    """
    Batch-scrape OP.GG rank data for all players with progress tracking.
    Safe to re-run — skips completed accounts, retries failed ones.

    Progress states per riot_id:
      completed     — scraped cleanly, skipped on re-run
      soft_failed   — scraped but data incomplete, retried on re-run
      failed        — hard error during scrape, retried on re-run
      needs_riot_id — OP.GG profile not found (name changed), skipped on re-run
    """
    config = load_tournament_config()
    progress_file = os.path.join(config.abs_data_dir, _PROGRESS_FILENAME)

    if reset:
        if os.path.exists(progress_file):
            os.remove(progress_file)
        success_print("Progress reset.")
        return

    progress = _load_progress(progress_file)

    if status:
        registry    = PlayerRegistry(config.abs_players_dir)
        all_profiles = registry.load_all()
        all_accounts = [
            a.riot_id for p in all_profiles for a in p.accounts if not a.archived
        ]
        skip    = set(progress["completed"]) | set(progress["needs_riot_id"])
        remaining = [rid for rid in all_accounts if rid not in skip]

        typer.echo(f"\n  OP.GG Batch Progress — {config.round_id}")
        typer.echo(f"  {'─'*44}")
        typer.echo(f"  {'total accounts':<20} {len(all_accounts):>4}")
        typer.echo(f"  {'completed':<20} {len(progress['completed']):>4}")
        typer.echo(f"  {'soft_failed':<20} {len(progress['soft_failed']):>4}  (incomplete data, will retry)")
        typer.echo(f"  {'failed':<20} {len(progress['failed']):>4}  (hard error, will retry)")
        typer.echo(f"  {'needs_riot_id':<20} {len(progress['needs_riot_id']):>4}  (name changed — needs manual fix)")
        typer.echo(f"  {'remaining':<20} {len(remaining):>4}")
        typer.echo(f"  {'─'*44}")
        for label, key in [("Soft failed", "soft_failed"), ("Failed", "failed"), ("Needs riot_id", "needs_riot_id")]:
            if progress[key]:
                typer.echo(f"\n  {label}:")
                for rid in sorted(progress[key]):
                    typer.echo(f"    - {rid}")
        typer.echo("")
        return

    registry = PlayerRegistry(config.abs_players_dir)
    all_profiles = registry.load_all()

    skip = set(progress["completed"]) | set(progress["needs_riot_id"])
    pending_profiles = [
        p for p in all_profiles
        if any(a.riot_id not in skip for a in p.accounts if not a.archived)
    ]

    if not pending_profiles:
        success_print("All accounts already completed or skipped.")
        return

    info_print(f"Processing {len(pending_profiles)} profiles with pending accounts...")
    runner = PipelineRunner(config)

    for profile in pending_profiles:
        pending_ids = [
            a.riot_id for a in profile.accounts
            if not a.archived and a.riot_id not in skip
        ]
        if not pending_ids:
            continue

        soft_errors, not_found = runner.run_task(Task.OPGG_SCRAPE_RANK, players=[profile.effective_id])

        for riot_id in pending_ids:
            if riot_id in not_found:
                progress["needs_riot_id"].append(riot_id)
            elif riot_id in soft_errors:
                if riot_id in progress["soft_failed"]:
                    progress["soft_failed"].remove(riot_id)
                progress["soft_failed"].append(riot_id)
            else:
                for k in ("soft_failed", "failed"):
                    if riot_id in progress[k]:
                        progress[k].remove(riot_id)
                progress["completed"].append(riot_id)

        _save_progress(progress, progress_file)

    runner.run_task(Task.AGGREGATE_RANK_STATS)
    success_print("Batch complete. Run `quartz scrape opgg-batch --status` to review.")
