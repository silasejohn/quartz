"""quartz export — write enriched scouting CSV for Google Sheets."""

from typing import Optional

import typer

from quartz.tournament_config import load_tournament_config
from quartz.pipeline_runner import PipelineRunner, Task


def export(
    out:   Optional[str] = typer.Option(None, "--out",   help="Output CSV filename (default: auto-named in processed/)"),
    round: Optional[str] = typer.Option(None, "--round", help="Tournament round filter (default: current round_id)"),
):
    """Export enriched scouting data to CSV for Google Sheets."""
    config = load_tournament_config()
    runner = PipelineRunner(config)
    runner.run_task(Task.EXPORT, out_filename=out, round_key=round)
