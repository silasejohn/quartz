"""
Task: OPGG_SCRAPE_RANK
Scrape OP.GG for each non-archived account and populate Account.rank_data (solo queue).

Lock strategy:
  - Profile is loaded (read lock) before scraping begins.
  - No lock is held during browser scraping (can take 30s+).
  - Write lock is acquired only during registry.save().
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
    [param] config:   TournamentConfig — uses current_lol_split
    [param] registry: PlayerRegistry — profiles are loaded and saved here
    [param] players:  optional list of discord_usernames or riot_ids to limit scope. None = all.
    [param] force:    if True, overwrite existing rank data (destructive replace)

    Returns a ScrapeResult with per-account outcomes.
    """
    from quartz.scrapers.opgg_scraper import OPGGScraper

    result = ScrapeResult(task="OPGG_SCRAPE_RANK")
    delay = 4

    all_profiles = registry.find_profiles(players) if players else registry.load_all()

    scraper = OPGGScraper()
    if scraper.setup() == -1:
        error_print("OPGG_SCRAPE_RANK: failed to set up browser — aborting")
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

                if players and not any(q.lower() in account.riot_id.lower() or q.lower() in profile.effective_id.lower() for q in players):
                    continue

                ok, opgg_url = scraper.navigate_to_profile(account.riot_id, account.player_region)
                if not ok:
                    warning_print(f"    Skipped: {account.riot_id} (profile not found — name may have changed)")
                    account.update_riot_id = True
                    account.account_flagged = True
                    profile_changed = True
                    result.outcomes.append(AccountScrapeOutcome(
                        riot_id=account.riot_id,
                        player_id=profile.effective_id,
                        status="not_found",
                        detail="OP.GG returned no profile — name change likely",
                    ))
                    continue

                if account.update_riot_id:
                    account.update_riot_id = False

                if opgg_url:
                    account.urls.opgg_url = opgg_url
                    profile_changed = True

                existing = None if force else account.rank_data
                account.rank_data = scraper.extract_solo_rank_data(
                    existing=existing,
                    current_lol_split=config.current_lol_split,
                )

                current_split = account.rank_data.get_split(config.current_lol_split) if account.rank_data else None
                if current_split and current_split.split_rank is None:
                    warning_print(f"    Soft error: current rank missing for {account.riot_id}")
                    result.outcomes.append(AccountScrapeOutcome(
                        riot_id=account.riot_id,
                        player_id=profile.effective_id,
                        status="soft_error",
                        detail=f"solo split_rank is None for {config.current_lol_split}",
                    ))
                else:
                    level = scraper.extract_account_level()
                    if level is not None:
                        account.account_level = level
                        if level < 100:
                            account.account_flagged = True
                            warning_print(f"    Account level {level} < 100 — flagging account")
                            result.outcomes.append(AccountScrapeOutcome(
                                riot_id=account.riot_id,
                                player_id=profile.effective_id,
                                status="flagged",
                                detail=f"account level {level} < 100",
                            ))
                        else:
                            account.account_flagged = False
                            result.outcomes.append(AccountScrapeOutcome(
                                riot_id=account.riot_id,
                                player_id=profile.effective_id,
                                status="ok",
                            ))
                    else:
                        result.outcomes.append(AccountScrapeOutcome(
                            riot_id=account.riot_id,
                            player_id=profile.effective_id,
                            status="ok",
                        ))

                profile_changed = True
                time.sleep(delay)

            if profile_changed:
                profile.touch()
                registry.save(profile)
                success_print(f"  Saved: {profile.effective_id}")

    finally:
        scraper.close()

    success_print(result.summary())
    hint = result.retry_hint("opgg")
    if hint:
        warning_print(f"  Retry: {hint}")

    return result
