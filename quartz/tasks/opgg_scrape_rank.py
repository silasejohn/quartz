"""
Task: OPGG_SCRAPE_RANK
Scrape OP.GG for each non-archived account and populate Account.rank_data (solo queue).

Skip logic  — per-account: if rank_data.is_complete(current_lol_split) and not force, skip.
Retry logic — per-account: if last_scrape_error is set, the account will not be skipped.
"""

import time
from datetime import datetime, timezone

from quartz.account_flags import FLAG_LOW_LEVEL, FLAG_NAME_CHANGED
from quartz.models.rank_data import AccountRankData
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

    all_profiles = registry.find_profiles(players) if players else registry.load_all()

    scraper = OPGGScraper()
    if scraper.setup() == -1:
        raise RuntimeError("OPGG_SCRAPE_RANK: failed to set up browser")

    try:
        for profile in all_profiles:
            info_print(f"  Processing: {profile.effective_id}")
            profile_changed = False

            try:
                for account in profile.accounts:
                    if account.archived:
                        result.outcomes.append(AccountScrapeOutcome(
                            riot_id=account.riot_id,
                            player_id=profile.effective_id,
                            status="skipped",
                            detail="archived",
                        ))
                        continue

                    if players and not any(
                        q.lower() in account.riot_id.lower() or q.lower() in profile.effective_id.lower()
                        for q in players
                    ):
                        continue

                    # Smart skip — only if complete and no prior error
                    if (
                        not force
                        and account.rank_data
                        and account.rank_data.is_complete(config.current_lol_split)
                        and account.rank_data.last_scrape_error is None
                    ):
                        result.outcomes.append(AccountScrapeOutcome(
                            riot_id=account.riot_id,
                            player_id=profile.effective_id,
                            status="skipped",
                            detail="rank data complete",
                        ))
                        continue

                    started_at = datetime.now(timezone.utc)

                    try:
                        ok, opgg_url, update_ok = scraper.navigate_to_profile(account.riot_id, account.player_region)
                        if not ok:
                            warning_print(f"    Skipped: {account.riot_id} (profile not found — name may have changed)")
                            if account.rank_data is None:
                                account.rank_data = AccountRankData()
                            account.rank_data.scrape_started_at = started_at
                            account.rank_data.last_scrape_error = "OP.GG profile not found — name change likely"
                            account.add_auto_flag(FLAG_NAME_CHANGED, detail="OP.GG profile not found — name change likely")
                            profile_changed = True
                            result.outcomes.append(AccountScrapeOutcome(
                                riot_id=account.riot_id,
                                player_id=profile.effective_id,
                                status="not_found",
                                detail="OP.GG returned no profile — name change likely",
                            ))
                            time.sleep(config.get_scraper_delay("opgg", 1.5))
                            continue

                        account.clear_auto_flag(FLAG_NAME_CHANGED)

                        if opgg_url:
                            account.urls.opgg_url = opgg_url
                            profile_changed = True

                        existing = None if force else account.rank_data
                        account.rank_data = scraper.extract_solo_rank_data(
                            existing=existing,
                            current_lol_split=config.current_lol_split,
                            scrape_started_at=started_at,
                        )
                        account.rank_data.last_scrape_error = (
                            None if update_ok
                            else "profile update timed out — rescrape to get fresh data"
                        )
                        profile_changed = True

                        current_split = account.rank_data.get_split(config.current_lol_split)
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
                                    account.add_auto_flag(FLAG_LOW_LEVEL, detail=f"account level {level} < 100")
                                    warning_print(f"    Account level {level} < 100 — flagging account")
                                    result.outcomes.append(AccountScrapeOutcome(
                                        riot_id=account.riot_id,
                                        player_id=profile.effective_id,
                                        status="flagged",
                                        detail=f"account level {level} < 100",
                                    ))
                                else:
                                    account.clear_auto_flag(FLAG_LOW_LEVEL)
                                    result.outcomes.append(AccountScrapeOutcome(
                                        riot_id=account.riot_id,
                                        player_id=profile.effective_id,
                                        status="ok" if update_ok else "stale",
                                        detail=None if update_ok else "profile update timed out",
                                    ))
                            else:
                                result.outcomes.append(AccountScrapeOutcome(
                                    riot_id=account.riot_id,
                                    player_id=profile.effective_id,
                                    status="ok" if update_ok else "stale",
                                    detail=None if update_ok else "profile update timed out",
                                ))

                    except Exception as e:
                        error_print(f"    Exception scraping {account.riot_id}: {e}")
                        if account.rank_data is None:
                            account.rank_data = AccountRankData()
                        account.rank_data.scrape_started_at = started_at
                        account.rank_data.last_scrape_error = str(e)
                        profile_changed = True
                        result.outcomes.append(AccountScrapeOutcome(
                            riot_id=account.riot_id,
                            player_id=profile.effective_id,
                            status="soft_error",
                            detail=str(e),
                        ))

                    time.sleep(config.get_scraper_delay("opgg", 1.5))

            except Exception as e:
                error_print(f"  Browser crash on {profile.effective_id}: {e} — attempting restart")
                try:
                    scraper.close()
                    if scraper.setup() == -1:
                        raise RuntimeError("browser restart failed")
                except Exception:
                    profile.touch(source="OPGG_SCRAPE_RANK")
                    registry.save(profile)
                    raise

            if profile_changed:
                profile.touch(source="OPGG_SCRAPE_RANK")
                registry.save(profile)
                success_print(f"  Saved: {profile.effective_id}")

    finally:
        scraper.close()

    success_print(result.summary())
    hint = result.retry_hint("opgg-rank")
    if hint:
        warning_print(f"  Retry: {hint}")

    return result
