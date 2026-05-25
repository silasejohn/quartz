"""
Task: DPM_SCRAPE_CHAMP
Scrape DPM.lol champion data for each non-archived account and populate
Account.champion_data.solo (current split only).

Note: DPM uses its own internal player ID in API URLs — it is NOT the Riot PUUID.
Use RIOT_ENRICH_PUUID separately to populate Account.puuid.

Lock strategy:
  - Profile loaded before scraping begins.
  - No lock held during browser scraping.
  - Write lock acquired only during registry.save().
"""

import time

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

                if account.champion_data is not None and not force:
                    result.outcomes.append(AccountScrapeOutcome(
                        riot_id=account.riot_id,
                        player_id=profile.effective_id,
                        status="skipped",
                        detail="champion_data already present",
                    ))
                    continue

                ok, champ_data, _ = scraper.extract_champion_data(
                    account.riot_id, lol_season
                )
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

                account.champion_data = champ_data
                profile_changed = True

                champ_count = len(champ_data.solo.champions)
                success_print(f"    {account.riot_id}: {champ_count} champions scraped")
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
