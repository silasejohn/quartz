"""
PipelineRunner
Task-based orchestrator for the Quartz data pipeline.

Tasks run independently and in any order after LOCAL_CSV_INGEST.
Add new tasks by implementing _run_{task_name}() and adding to Task enum.

Usage:
    from quartz.tournament_config import load_tournament_config
    from quartz.pipeline_runner import PipelineRunner, Task

    config = load_tournament_config()
    runner = PipelineRunner(config)
    runner.run_task(Task.LOCAL_CSV_INGEST)
"""

import os
import time
from enum import Enum

from quartz.utils.color_utils import info_print, warning_print, error_print, success_print
from quartz.tournament_config import TournamentConfig
from quartz.constants import SEASON_ORDER
from quartz.local_csv_input import LocalCSVInput
from quartz.player_registry import PlayerRegistry
from quartz.models.player_profile import PlayerProfile, SeasonData, Account


class Task(str, Enum):
    LOCAL_CSV_INGEST      = "local_csv_ingest"      # Local CSV -> player JSONs          <- implemented
    REMOTE_CSV_INGEST     = "remote_csv_ingest"     # Google Sheets -> player JSONs      <- stub
    OPGG_ENRICH_RANK      = "opgg_enrich_rank"      # OP.GG -> Account.rank_data         <- implemented
    OPGG_CHAMP            = "opgg_champ"            # OP.GG -> champion_pool             <- stub
    DPM_CHAMP             = "dpm_champ"             # DPM.LOL -> champion_pool           <- stub
    CALCULATE_RANK_STATS  = "calculate_rank_stats"  # Account.rank_data -> PlayerEnrichment.rank_data <- implemented
    PV_COMPUTE            = "pv_compute"            # rank_data -> point values          <- implemented
    EXPORT                = "export"                # Player JSONs -> CSV slices         <- stub


class PipelineRunner:
    """
    Orchestrates the Quartz data pipeline for a given tournament.

    [param] config: TournamentConfig loaded from active_tournament.yaml
    """

    def __init__(self, config: TournamentConfig):
        self.config = config
        self.season = config.current_round          # tournament round e.g. "S4"
        self.base_data_dir = config.abs_data_dir
        self.raw_csv = config.abs_raw_csv
        self.registry = PlayerRegistry(config.abs_players_dir)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run_task(self, task: Task, players: list[str] = None, **kwargs) -> set[str]:
        """
        Run a pipeline task.

        [param] task:    Task enum value
        [param] players: optional list of discord_usernames / riot_ids to limit scope.
                         None = run on all players.
        [param] **kwargs: task-specific options forwarded to the handler.
                         PV_COMPUTE accepts: weights=PVWeights (optional)

        Returns a set of riot_ids that had soft errors — scraped but with incomplete
        data (e.g. current rank selector failed). Profile is still saved with whatever
        was scraped. Caller should mark these for re-run rather than as completed.
        """
        info_print(f"=== PIPELINE: starting task '{task.value}' (tournament={self.config.tournament}, round={self.season}) ===")

        dispatch = {
            Task.LOCAL_CSV_INGEST:     self._run_local_csv_ingest,
            Task.REMOTE_CSV_INGEST:    self._run_remote_csv_ingest,
            Task.OPGG_ENRICH_RANK:     self._run_opgg_enrich_rank,
            Task.OPGG_CHAMP:           self._run_opgg_champ,
            Task.DPM_CHAMP:            self._run_dpm_champ,
            Task.CALCULATE_RANK_STATS: self._run_calculate_rank_stats,
            Task.PV_COMPUTE:           self._run_pv_compute,
            Task.EXPORT:               self._run_export,
        }

        result = dispatch[task](players, **kwargs)
        if isinstance(result, tuple):
            soft_errors, not_found = result
        else:
            soft_errors = result or set()
            not_found = set()
        success_print(f"=== PIPELINE: task '{task.value}' complete ===")
        return soft_errors, not_found

    # ------------------------------------------------------------------
    # Implemented tasks
    # ------------------------------------------------------------------

    def _run_local_csv_ingest(self, players: list[str] = None) -> None:
        """
        Read the local form response CSV and create/update player JSONs.
        Safe to re-run — existing profiles get their season entry upserted,
        new players get a fresh JSON created.
        """
        reader = LocalCSVInput(self.raw_csv)
        rows = reader.load()

        # Filter to specific players if requested
        if players:
            players_lower = {p.lower() for p in players}
            rows = [r for r in rows if r["discord_username"].lower() in players_lower]
            info_print(f"Filtered to {len(rows)} rows for players: {players}")

        created = 0
        updated = 0
        unchanged = 0

        for row in rows:
            discord = row["discord_username"]

            if self.registry.exists(discord):
                profile = self.registry.load(discord)
                changed = False

                # --- Season data ---
                new_season = SeasonData(
                    season=self.season,
                    player_type=row.get("player_type_override") or "main",
                    primary_pos=row.get("primary_role"),
                    secondary_pos=row.get("secondary_role"),
                    stated_current_rank=row.get("stated_current_rank"),
                    stated_peak_rank=row.get("stated_peak_rank"),
                )
                existing_season = next((sd for sd in profile.season_data if sd.season == self.season), None)
                if existing_season is None or existing_season.model_dump() != new_season.model_dump():
                    profile.upsert_season(new_season)
                    changed = True

                # --- Accounts ---
                # Build lookup of existing accounts by riot_id
                existing_by_id = {a.riot_id: a for a in profile.accounts}
                csv_riot_ids = {a["riot_id"] for a in row.get("accounts", []) if a.get("riot_id")}

                for acc_data in row.get("accounts", []):
                    rid = acc_data.get("riot_id")
                    if not rid:
                        continue
                    if rid in existing_by_id:
                        acc = existing_by_id[rid]
                        # Unarchive if it's back, update region if changed
                        if acc.archived or acc.player_region != acc_data["player_region"]:
                            acc.archived = False
                            acc.player_region = acc_data["player_region"]
                            changed = True
                    else:
                        profile.accounts.append(
                            Account(riot_id=rid, player_region=acc_data["player_region"])
                        )
                        changed = True

                # Archive accounts no longer in the CSV
                for acc in profile.accounts:
                    if acc.riot_id not in csv_riot_ids and not acc.archived:
                        acc.archived = True
                        changed = True

                if changed:
                    profile.touch()
                    self.registry.save(profile)
                    info_print(f"  Updated: {profile.effective_id}")
                    updated += 1
                else:
                    info_print(f"  Unchanged: {profile.effective_id}")
                    unchanged += 1
            else:
                # New player — create a fresh profile
                profile = PlayerProfile.from_csv_row(row, self.season)
                self.registry.save(profile)
                info_print(f"  Created: {profile.effective_id}")
                created += 1

        success_print(f"LOCAL_CSV_INGEST: {created} created, {updated} updated, {unchanged} unchanged "
                      f"({self.registry.count()} total players in registry)")

    def _run_opgg_enrich_rank(self, players: list[str] = None) -> set[str]:
        """
        Scrape OP.GG for each non-archived account and populate Account.rank_data.

        Lock strategy:
          - Profile is loaded (read lock) before scraping begins.
          - No lock is held during browser scraping (can take 30s+).
          - Write lock is acquired only during registry.save().

        Returns a set of riot_ids that had soft errors (profile saved but data incomplete).
        """
        from quartz.scrapers.opgg_scraper import OPGGScraper

        delay = 4  # seconds between accounts

        all_profiles = self.registry.load_all()
        players_lower = {p.lower() for p in players} if players else None
        if players_lower:
            all_profiles = [
                p for p in all_profiles
                if p.effective_id.lower() in players_lower
                or any(a.riot_id.lower() in players_lower for a in p.accounts)
            ]
            info_print(f"Filtered to {len(all_profiles)} profiles: {players}")

        scraper = OPGGScraper()
        if scraper.setup() == -1:
            error_print("OPGG_ENRICH_RANK: failed to set up browser — aborting")
            return set()

        scraped = 0
        skipped = 0
        errors  = 0
        soft_errors: set[str] = set()
        not_found:   set[str] = set()

        try:
            for profile in all_profiles:
                info_print(f"  Processing: {profile.effective_id}")
                profile_changed = False

                for account in profile.accounts:
                    if account.archived:
                        continue

                    # If filtering by specific riot_ids, only scrape the matched account
                    if players_lower and account.riot_id.lower() not in players_lower and profile.effective_id.lower() not in players_lower:
                        continue

                    # Navigate and scrape (no lock held during browser work)
                    ok, opgg_url = scraper.navigate_to_profile(account.riot_id, account.player_region)
                    if not ok:
                        warning_print(f"    Skipped: {account.riot_id} (profile not found — name may have changed)")
                        account.update_riot_id = True
                        account.account_flagged = True
                        not_found.add(account.riot_id)
                        profile_changed = True
                        skipped += 1
                        continue

                    # Profile found — reset update_riot_id if it was previously flagged
                    if account.update_riot_id:
                        account.update_riot_id = False

                    # Always update opgg_url — ensures locale (/en/) and format stay current
                    if opgg_url:
                        account.urls.opgg_url = opgg_url
                        profile_changed = True

                    # Extract rank data, passing existing data for comparison
                    account.rank_data = scraper.extract_rank_data(existing=account.rank_data)

                    # Soft error: current rank selector failed (not Unranked — genuinely missing)
                    current_split = account.rank_data.get_split(SEASON_ORDER[0]) if account.rank_data else None
                    if current_split and current_split.split_rank is None:
                        warning_print(f"    Soft error: current rank missing for {account.riot_id} — will re-run")
                        soft_errors.add(account.riot_id)

                    # Extract account level — flag if suspiciously low (smurf indicator)
                    # Never overwrite a stored level with None if the scrape fails
                    level = scraper.extract_account_level()
                    if level is not None:
                        account.account_level = level
                        if level < 100:
                            account.account_flagged = True
                            warning_print(f"    Account level {level} < 100 — flagging account")
                        else:
                            account.account_flagged = False
                            info_print(f"  OPGGScraper: account level -> {level}")

                    profile_changed = True
                    scraped += 1

                    time.sleep(delay)

                if profile_changed:
                    profile.touch()
                    self.registry.save(profile)  # write lock acquired here
                    success_print(f"  Saved: {profile.effective_id}")

        finally:
            scraper.close()

        success_print(
            f"OPGG_ENRICH_RANK: {scraped} accounts scraped, "
            f"{skipped} skipped (of which {len(not_found)} need riot_id update), "
            f"{errors} errors, {len(soft_errors)} soft errors"
        )
        return soft_errors, not_found

    def _run_calculate_rank_stats(self, players: list[str] = None) -> None:
        """
        Aggregate Account.rank_data across all accounts -> PlayerEnrichment.

        Populates profile.data with:
          - rank_data (AggregatedRankData — best per season across all accounts)
          - all_time_peak_rank
          - current_rank (best split_rank for SEASON_ORDER[0])

        Safe to re-run — idempotent. Requires OPGG_ENRICH_RANK to have run first.
        """
        from quartz.models.rank_data import compute_enrichment

        all_profiles = self.registry.load_all()
        players_lower = {p.lower() for p in players} if players else None
        if players_lower:
            all_profiles = [p for p in all_profiles if p.effective_id.lower() in players_lower]

        computed = 0
        for profile in all_profiles:
            profile.data = compute_enrichment(profile.accounts)
            profile.touch()
            self.registry.save(profile)
            info_print(
                f"  {profile.effective_id}: "
                f"peak={profile.data.all_time_peak_rank}, "
                f"current={profile.data.current_rank}"
            )
            computed += 1

        success_print(f"CALCULATE_RANK_STATS: {computed} profiles enriched")

    def _run_pv_compute(self, players: list[str] = None, weights=None) -> None:
        """
        Compute Point Value for each player and write to profile.data.computed_pv.

        Also writes round(point_value) to SeasonData.point_value for the current
        tournament season for easy downstream access.

        Requires CALCULATE_RANK_STATS to have run first (profile.data must be populated).
        N threshold is derived from the full pool regardless of any player filter.

        [param] weights: PVWeights instance to use. If None, loads from pv_weights.json
                         in base_data_dir, falling back to PVWeights() defaults.
        """
        from quartz.pv_compute import compute_N_threshold, compute_realistic_max, compute_pv
        from quartz.pv_weights_io import load_weights

        if weights is None:
            weights, from_file = load_weights(self.base_data_dir)
            source = "pv_weights.json" if from_file else "defaults"
            info_print(f"PV_COMPUTE: using weights from {source}")
        current_lol_season = SEASON_ORDER[0]

        all_profiles = self.registry.load_all()
        players_lower = {p.lower() for p in players} if players else None
        target_profiles = (
            [p for p in all_profiles if p.effective_id.lower() in players_lower]
            if players_lower else all_profiles
        )

        # Compute pool-level parameters from the full pool (not the filtered subset) for consistency
        N = compute_N_threshold(all_profiles, weights, current_lol_season)
        info_print(
            f"PV_COMPUTE: N threshold = {N} games "
            f"(strategy={weights.confidence_strategy}, pool={len(all_profiles)} players)"
        )
        realistic_max = compute_realistic_max(all_profiles, weights, self.season)
        info_print(f"PV_COMPUTE: in-house realistic_max Wilson LB = {realistic_max:.4f}")

        computed = 0
        flagged = 0
        for profile in target_profiles:
            if not profile.data:
                warning_print(
                    f"  Skipping {profile.effective_id} — no enrichment data "
                    f"(run CALCULATE_RANK_STATS first)"
                )
                continue

            pv_result = compute_pv(profile, weights, N, self.season, realistic_max)
            profile.data.computed_pv = pv_result

            # Write rounded PV to current SeasonData for easy downstream access
            season_entry = next(
                (sd for sd in profile.season_data if sd.season == self.season), None
            )
            if season_entry:
                season_entry.point_value = (
                    None if pv_result.flagged else round(pv_result.point_value)
                )

            profile.touch()
            self.registry.save(profile)

            if pv_result.flagged:
                flagged += 1
                warning_print(f"  {profile.effective_id}: PV = 9999 (no usable rank data)")
            else:
                info_print(f"  {profile.effective_id}: PV = {pv_result.point_value}")
            computed += 1

        success_print(
            f"PV_COMPUTE: {computed} profiles processed, {flagged} flagged (9999)"
        )

    # ------------------------------------------------------------------
    # Stub tasks — implemented when their dependencies are built
    # ------------------------------------------------------------------

    def _run_remote_csv_ingest(self, players: list[str] = None) -> None:
        raise NotImplementedError(
            "remote_csv_ingest: build RemoteCSVInput (Google Sheets reader) first"
        )

    def _run_opgg_champ(self, players: list[str] = None) -> None:
        raise NotImplementedError(
            "opgg_champ: implement extract_champion_pool() on OPGGScraper first"
        )

    def _run_dpm_champ(self, players: list[str] = None) -> None:
        raise NotImplementedError(
            "dpm_champ: build DPMScraper first"
        )

    def _run_export(self, players: list[str] = None) -> None:
        raise NotImplementedError(
            "export: build CSVExporter first"
        )
