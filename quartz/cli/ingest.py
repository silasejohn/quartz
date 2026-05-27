from typing import Optional

import typer

from quartz.pipeline_runner import PipelineRunner, Task
from quartz.tournament_config import load_tournament_config


def ingest(
    force: bool = typer.Option(False, "--force", help="Upsert all rows; default skips players already in registry."),
    limit: Optional[int] = typer.Option(None, "--limit", help="Process only the first N rows (useful for testing)."),
) -> None:
    """Load the local tournament form response CSV into player profiles."""
    config = load_tournament_config()
    runner = PipelineRunner(config)
    runner.run_task(Task.LOCAL_CSV_INGEST, force=force, limit=limit)


def ingest_sheets():
    """Load player profiles from the Google Sheets form response (not yet implemented)."""
    config = load_tournament_config()
    runner = PipelineRunner(config)
    runner.run_task(Task.REMOTE_CSV_INGEST)
