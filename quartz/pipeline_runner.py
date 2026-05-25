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

from quartz.player_registry import PlayerRegistry
from quartz.scrapers.core.scrape_result import ScrapeResult
from quartz.tasks import (
    Task,  # re-exported so existing imports still work
    aggregate_rank_stats,
    dpm_scrape_champ,
    local_csv_ingest,
    opgg_scrape_rank,
    riot_enrich_puuid,
)
from quartz.tasks import export as export_task
from quartz.tasks import pv_compute as pv_compute_task
from quartz.tournament_config import TournamentConfig
from quartz.utils.logging import configure_file_logging, info_print, success_print


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

    def run_task(self, task: Task, players: list[str] = None, **kwargs) -> ScrapeResult | None:
        """
        Run a pipeline task.

        [param] task:     Task enum value
        [param] players:  optional list of discord_usernames / riot_ids to limit scope.
                          None = run on all players.
        [param] **kwargs: task-specific options (e.g. force=True for scrape tasks,
                          weights=PVWeights for PV_COMPUTE)

        Returns ScrapeResult for scrape tasks, None for all other tasks.
        """
        info_print(f"=== PIPELINE: starting task '{task.value}' (round={self.config.round_id}) ===")

        dispatch = {
            Task.LOCAL_CSV_INGEST:     local_csv_ingest.run,
            Task.OPGG_SCRAPE_RANK:     opgg_scrape_rank.run,
            Task.DPM_SCRAPE_CHAMP:     dpm_scrape_champ.run,
            Task.RIOT_ENRICH_PUUID:    riot_enrich_puuid.run,
            Task.AGGREGATE_RANK_STATS: aggregate_rank_stats.run,
            Task.PV_COMPUTE:           pv_compute_task.run,
            Task.EXPORT:               export_task.run,
        }

        fn = dispatch.get(task)
        if fn is None:
            raise NotImplementedError(f"{task.value} not yet implemented")

        result = fn(self.config, self.registry, players, **kwargs)

        success_print(f"=== PIPELINE: task '{task.value}' complete ===")
        return result if isinstance(result, ScrapeResult) else None
