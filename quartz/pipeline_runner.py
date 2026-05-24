"""
PipelineRunner
Thin orchestrator for the Quartz data pipeline.

Dispatches to task modules in quartz/tasks/. Each task is independently
importable and runnable without going through PipelineRunner.

Usage:
    from quartz.tournament_config import load_tournament_config
    from quartz.pipeline_runner import PipelineRunner, Task

    config = load_tournament_config()
    runner = PipelineRunner(config)
    runner.run_task(Task.LOCAL_CSV_INGEST)
"""

import os

from quartz.tasks import Task  # re-exported so existing imports still work
from quartz.utils.logging import info_print, success_print, configure_file_logging
from quartz.tournament_config import TournamentConfig
from quartz.player_registry import PlayerRegistry

from quartz.tasks import (
    local_csv_ingest,
    opgg_scrape_rank,
    aggregate_rank_stats,
    pv_compute as pv_compute_task,
    export as export_task,
)


class PipelineRunner:
    """
    Orchestrates the Quartz data pipeline for a given tournament.

    [param] config: TournamentConfig loaded from active_tournament.yaml
    """

    def __init__(self, config: TournamentConfig):
        self.config = config
        self.registry = PlayerRegistry(config.abs_players_dir)
        log_path = os.path.join(config.abs_data_dir, "logs", "pipeline.log")
        configure_file_logging(log_path)

    def run_task(self, task: Task, players: list[str] = None, **kwargs) -> tuple[set[str], set[str]]:
        """
        Run a pipeline task.

        [param] task:     Task enum value
        [param] players:  optional list of discord_usernames / riot_ids to limit scope.
                          None = run on all players.
        [param] **kwargs: task-specific options (PV_COMPUTE accepts: weights=PVWeights)

        Returns (soft_errors, not_found) — sets of riot_ids with partial failures.
        """
        info_print(f"=== PIPELINE: starting task '{task.value}' (round={self.config.round_id}) ===")

        dispatch = {
            Task.LOCAL_CSV_INGEST:     local_csv_ingest.run,
            Task.OPGG_SCRAPE_RANK:     opgg_scrape_rank.run,
            Task.AGGREGATE_RANK_STATS: aggregate_rank_stats.run,
            Task.PV_COMPUTE:           pv_compute_task.run,
            Task.EXPORT:               export_task.run,
        }

        fn = dispatch.get(task)
        if fn is None:
            raise NotImplementedError(f"{task.value} not yet implemented")

        result = fn(self.config, self.registry, players, **kwargs)
        soft_errors, not_found = result if isinstance(result, tuple) else (result or set(), set())

        success_print(f"=== PIPELINE: task '{task.value}' complete ===")
        return soft_errors, not_found
