"""
ingest_csv.py
Load the tournament form response CSV into player profiles.

Usage:
    python3 ingest_csv.py
"""

from quartz.tournament_config import load_tournament_config
from quartz.pipeline_runner import PipelineRunner, Task

config = load_tournament_config()
runner = PipelineRunner(config)
runner.run_task(Task.LOCAL_CSV_INGEST)
