"""quartz export — write enriched scouting CSV for Google Sheets."""

from typing import Optional

import typer

from quartz.pipeline_runner import PipelineRunner, Task
from quartz.tournament_config import load_tournament_config


def export(
    out:   Optional[str] = typer.Option(None, "--out",   help="Output CSV filename (default: auto-named in processed/)"),
    round: Optional[str] = typer.Option(None, "--round", help="Tournament round filter (default: current round_id)"),
    push:  bool          = typer.Option(False, "--push", help="Push to Google Sheets after writing CSV (requires sheets: config)"),
    team:  bool          = typer.Option(False, "--team", help="Export pool overview stats (player types, roles, rank tiers) instead of player rows"),
):
    """Export scouting data to CSV, optionally pushing to Google Sheets.

    Default: full player table sorted by PV.
    --team:  pool overview stats (captains+mains section, subs section).
    --push:  push the CSV to the configured Google Sheet tab.
    """
    config = load_tournament_config()
    runner = PipelineRunner(config)
    if team:
        runner.run_task(Task.EXPORT_STATS, push=push)
    else:
        runner.run_task(Task.EXPORT, out_filename=out, round_key=round, push=push)
