from quartz.pipeline_runner import PipelineRunner, Task
from quartz.tournament_config import load_active_tournament


def ingest():
    """Load the local tournament form response CSV into player profiles."""
    config = load_active_tournament()
    runner = PipelineRunner(config)
    runner.run_task(Task.LOCAL_CSV_INGEST)


def ingest_sheets():
    """Load player profiles from the Google Sheets form response (not yet implemented)."""
    config = load_active_tournament()
    runner = PipelineRunner(config)
    runner.run_task(Task.REMOTE_CSV_INGEST)
