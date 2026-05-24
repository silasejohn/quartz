import typer
from quartz.tournament_config import load_tournament_config
from quartz.pipeline_runner import PipelineRunner, Task


def ingest():
    """Load the local tournament form response CSV into player profiles."""
    config = load_tournament_config()
    runner = PipelineRunner(config)
    runner.run_task(Task.LOCAL_CSV_INGEST)


def ingest_sheets():
    """Load player profiles from the Google Sheets form response (not yet implemented)."""
    config = load_tournament_config()
    runner = PipelineRunner(config)
    runner.run_task(Task.REMOTE_CSV_INGEST)
