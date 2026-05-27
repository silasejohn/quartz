"""
Task: OPGG_SCRAPE
Combined OP.GG scrape — rank history + champion stats in one browser session per account.

Skip logic — per-component, per-account:
  - Rank:  skip if rank_data.is_complete(current_lol_split) and not force
  - Champ: skip if champion_data.solo.opgg_complete() and champion_data.flex.opgg_complete() and not force
  Both skipped → skip navigation entirely.

Runs AGGREGATE_RANK_STATS at the end.
"""

import time
from datetime import datetime, timezone

from quartz.account_flags import FLAG_LOW_LEVEL, FLAG_NAME_CHANGED
from quartz.models.champion_data import AccountChampionData
from quartz.models.rank_data import AccountRankData
from quartz.player_registry import PlayerRegistry
from quartz.scrapers.core.scrape_result import AccountScrapeOutcome, ScrapeResult
from quartz.tasks.opgg_scrape_champ import _backfill_rank_wl, _merge_season_data, _strip_opgg_champ_data
from quartz.tournament_config import TournamentConfig
from quartz.utils.logging import error_print, info_print, success_print, warning_print

_ERR_PROFILE_NOT_FOUND = "OP.GG profile not found — name change likely"


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
    [param] force:    if True, overwrite existing data for both rank and champ
    """
    from quartz.scrapers.opgg_scraper import OPGGScraper
    from quartz.tasks import aggregate_rank_stats

    result = ScrapeResult(task="OPGG_SCRAPE")
    current_split = config.current_lol_split

    all_profiles = registry.find_profiles(players) if players else registry.load_all()

    scraper = OPGGScraper()
    if scraper.setup() == -1:
        error_print("OPGG_SCRAPE: failed to set up browser — aborting")
        return result

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

                    rank_done = (
                        not force
                        and account.rank_data is not None
                        and account.rank_data.is_complete(current_split)
                        and account.rank_data.last_scrape_error is None
                    )
                    champ_done = (
                        not force
                        and account.champion_data is not None
                        and account.champion_data.solo.opgg_complete()
                        and account.champion_data.flex.opgg_complete()
                    )

                    if rank_done and champ_done:
                        result.outcomes.append(AccountScrapeOutcome(
                            riot_id=account.riot_id,
                            player_id=profile.effective_id,
                            status="skipped",
                            detail="rank and champion data complete",
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
                            account.rank_data.last_scrape_error = _ERR_PROFILE_NOT_FOUND
                            if account.champion_data is None:
                                account.champion_data = AccountChampionData()
                            account.champion_data.solo.opgg_scrape_started_at = started_at
                            account.champion_data.flex.opgg_scrape_started_at = started_at
                            account.champion_data.solo.opgg_last_scrape_error = _ERR_PROFILE_NOT_FOUND
                            account.champion_data.flex.opgg_last_scrape_error = _ERR_PROFILE_NOT_FOUND
                            account.add_auto_flag(FLAG_NAME_CHANGED, detail=_ERR_PROFILE_NOT_FOUND)
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

                        # --- Rank ---
                        if not rank_done:
                            try:
                                existing_rank = None if force else account.rank_data
                                account.rank_data = scraper.extract_solo_rank_data(
                                    existing=existing_rank,
                                    current_lol_split=current_split,
                                    scrape_started_at=started_at,
                                )
                                account.rank_data.last_scrape_error = (
                                    None if update_ok
                                    else "profile update timed out — rescrape to get fresh data"
                                )
                                profile_changed = True

                                level = scraper.extract_account_level()
                                if level is not None:
                                    account.account_level = level
                                    if level < 100:
                                        account.add_auto_flag(FLAG_LOW_LEVEL, detail=f"account level {level} < 100")
                                        warning_print(f"    Account level {level} < 100 — flagging account")
                                    else:
                                        account.clear_auto_flag(FLAG_LOW_LEVEL)
                            except Exception as e:
                                error_print(f"    Rank exception for {account.riot_id}: {e}")
                                if account.rank_data is None:
                                    account.rank_data = AccountRankData()
                                account.rank_data.scrape_started_at = started_at
                                account.rank_data.last_scrape_error = str(e)
                                profile_changed = True

                        # --- Champion ---
                        if not champ_done:
                            if account.champion_data is None:
                                account.champion_data = AccountChampionData()
                            if force:
                                _strip_opgg_champ_data(account.champion_data)
                            account.champion_data.solo.opgg_scrape_started_at = started_at
                            account.champion_data.flex.opgg_scrape_started_at = started_at

                            try:

                                season_data = scraper.extract_all_champion_seasons(
                                    account.riot_id, account.player_region
                                )

                                if not season_data:
                                    warning_print(f"    {account.riot_id}: no champion data returned")
                                    account.champion_data.solo.opgg_last_scrape_error = "no season data returned"
                                    account.champion_data.flex.opgg_last_scrape_error = "no season data returned"
                                    profile_changed = True
                                else:
                                    _merge_season_data(account.champion_data, season_data)
                                    _backfill_rank_wl(account, season_data)
                                    now = datetime.now(timezone.utc)
                                    account.champion_data.solo.opgg_scraped_at = now
                                    account.champion_data.flex.opgg_scraped_at = now
                                    account.champion_data.solo.opgg_last_scrape_error = None
                                    account.champion_data.flex.opgg_last_scrape_error = None
                                    profile_changed = True

                            except Exception as e:
                                error_print(f"    Champion exception for {account.riot_id}: {e}")
                                account.champion_data.solo.opgg_last_scrape_error = str(e)
                                account.champion_data.flex.opgg_last_scrape_error = str(e)
                                profile_changed = True

                        # Determine final outcome for this account
                        rank_ok = account.rank_data and account.rank_data.last_scrape_error is None
                        champ_ok = (
                            account.champion_data
                            and account.champion_data.solo.opgg_last_scrape_error is None
                            and account.champion_data.flex.opgg_last_scrape_error is None
                        )
                        level = account.account_level or 0
                        if not rank_ok or not champ_ok:
                            result.outcomes.append(AccountScrapeOutcome(
                                riot_id=account.riot_id,
                                player_id=profile.effective_id,
                                status="soft_error",
                                detail="partial scrape failure — see last_scrape_error fields",
                            ))
                        elif level > 0 and level < 100:
                            result.outcomes.append(AccountScrapeOutcome(
                                riot_id=account.riot_id,
                                player_id=profile.effective_id,
                                status="flagged",
                                detail=f"account level {level} < 100",
                            ))
                        else:
                            result.outcomes.append(AccountScrapeOutcome(
                                riot_id=account.riot_id,
                                player_id=profile.effective_id,
                                status="ok",
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
                    profile.touch(source="OPGG_SCRAPE")
                    registry.save(profile)
                    raise

            if profile_changed:
                profile.touch(source="OPGG_SCRAPE")
                registry.save(profile)
                success_print(f"  Saved: {profile.effective_id}")

    finally:
        scraper.close()

    # Aggregate rank stats across all profiles after all scraping is done
    aggregate_rank_stats.run(config, registry, players)

    success_print(result.summary())
    hint = result.retry_hint("opgg")
    if hint:
        warning_print(f"  Retry: {hint}")

    return result
