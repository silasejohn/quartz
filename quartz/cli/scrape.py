"""
quartz scrape — subcommands for scraping external data sources.

    quartz scrape opgg [PLAYERS...]         targeted OP.GG rank scrape
    quartz scrape opgg-batch [--reset] [--status]   batch OP.GG with progress tracking
"""

import json
import os
from typing import Optional

import typer

from quartz.tournament_config import load_tournament_config
from quartz.pipeline_runner import PipelineRunner, Task
from quartz.player_registry import PlayerRegistry
from quartz.utils.color_utils import info_print, success_print, warning_print, error_print

app = typer.Typer(no_args_is_help=True)

_PROGRESS_FILENAME = "opgg_batch_progress.json"
_PROGRESS_KEYS = ("completed", "soft_failed", "failed", "needs_riot_id")


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


@app.command("opgg")
def opgg(
    players: Optional[list[str]] = typer.Argument(None, help="Player IDs or Riot IDs to scrape (default: all)"),
):
    """Scrape OP.GG solo queue rank data for specific players (or all if none given)."""
    config = load_tournament_config()
    runner = PipelineRunner(config)
    runner.run_task(Task.OPGG_ENRICH_RANK, players=players or None)
    runner.run_task(Task.CALCULATE_RANK_STATS, players=players or None)


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
        total = sum(len(progress[k]) for k in _PROGRESS_KEYS)
        typer.echo(f"\n  OP.GG Batch Progress — {config.round_id}")
        typer.echo(f"  {'─'*40}")
        for k in _PROGRESS_KEYS:
            typer.echo(f"  {k:<16} {len(progress[k]):>4}")
        typer.echo(f"  {'─'*40}")
        typer.echo(f"  {'total tracked':<16} {total:>4}\n")
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

        soft_errors, not_found = runner.run_task(Task.OPGG_ENRICH_RANK, players=[profile.effective_id])

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

    runner.run_task(Task.CALCULATE_RANK_STATS)
    success_print("Batch complete. Run `quartz scrape opgg-batch --status` to review.")
