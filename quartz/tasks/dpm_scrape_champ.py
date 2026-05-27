"""
Task: DPM_SCRAPE_CHAMP
Scrape DPM.lol champion data (solo + flex, all 5 lanes) for each non-archived account.
Merges into Account.champion_data — OPGG historical data is preserved.

Lock strategy:
  - Profile loaded before scraping begins.
  - No lock held during browser scraping.
  - Write lock acquired only during registry.save().
"""

import time

from quartz.models.champion_data import OPGG_EXCLUSIVE_FIELDS, AccountChampionData, ChampionSplitStats
from quartz.player_registry import PlayerRegistry
from quartz.scrapers.core.scrape_result import AccountScrapeOutcome, ScrapeResult
from quartz.tournament_config import TournamentConfig
from quartz.utils.logging import error_print, info_print, success_print, warning_print


def run(
    config: TournamentConfig,
    registry: PlayerRegistry,
    players: list[str] | None = None,
    force: bool = False,
) -> ScrapeResult:
    """
    [param] config:   TournamentConfig — uses current_lol_split as the ChampionSplitStats season key
    [param] registry: PlayerRegistry — profiles are loaded and saved here
    [param] players:  optional list of discord_usernames or riot_ids to limit scope. None = all.
    [param] force:    if True, overwrite existing champion data
    """
    from quartz.scrapers.dpm_scraper import DPMScraper

    result = ScrapeResult(task="DPM_SCRAPE_CHAMP")
    lol_season = config.current_lol_split
    delay = config.get_scraper_delay("dpm", default=3)

    all_profiles = registry.find_profiles(players) if players else registry.load_all()

    scraper = DPMScraper()
    if scraper.setup() == -1:
        error_print("DPM_SCRAPE_CHAMP: failed to set up browser — aborting")
        return result

    try:
        for profile in all_profiles:
            info_print(f"  Processing: {profile.effective_id}")
            profile_changed = False

            for account in profile.accounts:
                if account.archived:
                    result.outcomes.append(AccountScrapeOutcome(
                        riot_id=account.riot_id,
                        player_id=profile.effective_id,
                        status="skipped",
                        detail="archived",
                    ))
                    continue

                existing = account.champion_data
                already_done = (
                    existing is not None
                    and existing.solo.dpm_scraped_at is not None
                    and existing.flex.dpm_scraped_at is not None
                )
                if already_done and not force:
                    result.outcomes.append(AccountScrapeOutcome(
                        riot_id=account.riot_id,
                        player_id=profile.effective_id,
                        status="skipped",
                        detail="dpm_scraped_at already set",
                    ))
                    continue

                api_timeout = scraper.config.get("timeouts.api_response", 10)
                ok, champ_data, puuid = scraper.extract_champion_data(
                    account.riot_id, lol_season, api_timeout=api_timeout
                )
                if puuid and not account.puuid:
                    account.puuid = puuid
                time.sleep(delay)

                if not ok:
                    warning_print(f"    {account.riot_id}: DPM scrape failed")
                    result.outcomes.append(AccountScrapeOutcome(
                        riot_id=account.riot_id,
                        player_id=profile.effective_id,
                        status="soft_error",
                        detail="champion API not captured — page may not have loaded",
                    ))
                    continue

                if account.champion_data is None:
                    account.champion_data = champ_data
                else:
                    if force:
                        _strip_dpm_data(account.champion_data)
                    _merge_dpm_into_existing(account.champion_data, champ_data)
                profile_changed = True

                solo_count = len(champ_data.solo.champions)
                flex_count = len(champ_data.flex.champions)
                success_print(f"    {account.riot_id}: {solo_count} solo, {flex_count} flex champion entries")
                result.outcomes.append(AccountScrapeOutcome(
                    riot_id=account.riot_id,
                    player_id=profile.effective_id,
                    status="ok",
                ))

            if profile_changed:
                registry.save(profile)

    finally:
        scraper.close()

    success_print(result.summary())
    return result


def _strip_dpm_data(data: AccountChampionData) -> None:
    """Remove DPM-sourced data from all splits before a force re-scrape.

    - source="dpm"   → remove the split entirely.
    - source="multi" → clear DPM-exclusive and contested fields; keep OPGG-exclusive
                       fields intact (op_score, etc.) and set source="opgg".
    - source="opgg"  → untouched.

    Entries with no remaining splits are removed entirely.
    """
    for queue in ("solo", "flex"):
        pool = getattr(data, queue)
        pool.dpm_scraped_at = None
        for entry in pool.champions:
            new_splits = []
            for s in entry.splits:
                if s.source == "dpm":
                    pass  # pure DPM — drop entirely
                elif s.source == "multi":
                    preserved = {f: getattr(s, f) for f in OPGG_EXCLUSIVE_FIELDS if getattr(s, f) is not None}
                    if preserved:
                        new_splits.append(ChampionSplitStats(
                            lol_season=s.lol_season,
                            games=0, wins=0, losses=0,
                            source="opgg",
                            **preserved,
                        ))
                    # else: nothing from OPGG to preserve — drop
                else:
                    new_splits.append(s)
            entry.splits = new_splits
        pool.champions = [e for e in pool.champions if e.splits]


def _merge_dpm_into_existing(existing: AccountChampionData, new: AccountChampionData) -> None:
    """
    Merge a fresh DPM scrape into existing AccountChampionData.

    Per (champion, role, lol_season):
      - New entry not yet seen → append it.
      - Existing entry found → merge_split() applies the games-count rule:
          more games = wins control of all fields; same/fewer = gap-fill only.
    """
    for queue in ("solo", "flex"):
        existing_pool = getattr(existing, queue)
        new_pool      = getattr(new, queue)

        existing_pool.dpm_scraped_at = new_pool.dpm_scraped_at

        for new_entry in new_pool.champions:
            existing_entry = existing_pool.get_champion(new_entry.champion, role=new_entry.role)
            if existing_entry is None:
                existing_pool.champions.append(new_entry)
            else:
                for split in new_entry.splits:
                    existing_entry.merge_split(split)
