"""
Task: OPGG_SCRAPE_CHAMP
Scrape OP.GG champion stats (wins/losses/OP Score) for every tracked season
(S2026–S2024 S1) across both Solo/Duo and Flex queues, and merge into
Account.champion_data without overwriting DPM-sourced stats.

Skip logic  — per-account: if both pools pass opgg_complete() and not force, skip.
Retry logic — per-account: if opgg_last_scrape_error is set, the account will not be skipped.
"""

import time
from datetime import datetime, timezone

from quartz.models.champion_data import (
    OPGG_EXCLUSIVE_FIELDS,
    AccountChampionData,
    AccountQueueChampionPool,
    ChampionEntry,
    ChampionSplitStats,
)
from quartz.models.player_profile import Account
from quartz.player_registry import PlayerRegistry
from quartz.scrapers.core.scrape_result import AccountScrapeOutcome, ScrapeResult
from quartz.tournament_config import TournamentConfig
from quartz.utils.logging import error_print, info_print, success_print, warning_print

_ERR_NO_SEASON_DATA = "no season data returned"


def run(
    config: TournamentConfig,
    registry: PlayerRegistry,
    players: list[str] | None = None,
    force: bool = False,
) -> ScrapeResult:
    """
    [param] config:   TournamentConfig
    [param] registry: PlayerRegistry
    [param] players:  optional list of discord_usernames or riot_ids to limit scope. None = all.
    [param] force:    if True, re-scrape even if champion data is already complete
    """
    from quartz.scrapers.opgg_scraper import OPGGScraper

    result = ScrapeResult(task="OPGG_SCRAPE_CHAMP")

    all_profiles = registry.find_profiles(players) if players else registry.load_all()

    scraper = OPGGScraper()
    if scraper.setup() == -1:
        error_print("OPGG_SCRAPE_CHAMP: failed to set up browser — aborting")
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

                    existing = account.champion_data
                    if (
                        not force
                        and existing is not None
                        and existing.solo.opgg_complete()
                        and existing.flex.opgg_complete()
                    ):
                        result.outcomes.append(AccountScrapeOutcome(
                            riot_id=account.riot_id,
                            player_id=profile.effective_id,
                            status="skipped",
                            detail="opgg champion data complete",
                        ))
                        continue

                    started_at = datetime.now(timezone.utc)
                    if account.champion_data is None:
                        account.champion_data = AccountChampionData()
                    if force:
                        _strip_opgg_champ_data(account.champion_data)
                    account.champion_data.solo.opgg_scrape_started_at = started_at
                    account.champion_data.flex.opgg_scrape_started_at = started_at

                    try:
                        info_print(f"    {account.riot_id}: scraping champion seasons...")

                        season_data = scraper.extract_all_champion_seasons(
                            account.riot_id, account.player_region
                        )

                        if not season_data:
                            warning_print(f"    {account.riot_id}: no champion data returned")
                            account.champion_data.solo.opgg_last_scrape_error = _ERR_NO_SEASON_DATA
                            account.champion_data.flex.opgg_last_scrape_error = _ERR_NO_SEASON_DATA
                            profile_changed = True
                            result.outcomes.append(AccountScrapeOutcome(
                                riot_id=account.riot_id,
                                player_id=profile.effective_id,
                                status="soft_error",
                                detail=_ERR_NO_SEASON_DATA,
                            ))
                            time.sleep(config.get_scraper_delay("opgg", 1.5))
                            continue

                        _merge_season_data(account.champion_data, season_data)
                        _backfill_rank_wl(account, season_data)

                        now = datetime.now(timezone.utc)
                        account.champion_data.solo.opgg_scraped_at = now
                        account.champion_data.flex.opgg_scraped_at = now
                        account.champion_data.solo.opgg_last_scrape_error = None
                        account.champion_data.flex.opgg_last_scrape_error = None
                        profile_changed = True

                        total_champs = sum(
                            len(qd.get("champions", {}))
                            for sd in season_data.values()
                            for qd in sd.values()
                        )
                        success_print(f"    {account.riot_id}: {len(season_data)} seasons, {total_champs} champion-season entries")
                        result.outcomes.append(AccountScrapeOutcome(
                            riot_id=account.riot_id,
                            player_id=profile.effective_id,
                            status="ok",
                        ))

                    except Exception as e:
                        error_print(f"    Exception scraping {account.riot_id}: {e}")
                        account.champion_data.solo.opgg_last_scrape_error = str(e)
                        account.champion_data.flex.opgg_last_scrape_error = str(e)
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
                    profile.touch(source="OPGG_SCRAPE_CHAMP")
                    registry.save(profile)
                    raise

            if profile_changed:
                profile.touch(source="OPGG_SCRAPE_CHAMP")
                registry.save(profile)
                success_print(f"  Saved: {profile.effective_id}")

    finally:
        scraper.close()

    success_print(result.summary())
    hint = result.retry_hint("opgg-champ")
    if hint:
        warning_print(f"  Retry: {hint}")

    return result


def _strip_opgg_champ_data(data: AccountChampionData) -> None:
    """Remove OPGG-sourced data from all splits before a force re-scrape.

    - source="opgg"  → remove the split entirely.
    - source="multi" → clear OPGG-exclusive fields; keep DPM data; set source="dpm".
    - source="dpm"   → untouched.

    Also resets OPGG scrape state fields on both pools.
    """
    for queue in ("solo", "flex"):
        pool = getattr(data, queue)
        pool.opgg_scrape_started_at = None
        pool.opgg_scraped_at = None
        pool.opgg_last_scrape_error = None
        for entry in pool.champions:
            new_splits = []
            for s in entry.splits:
                if s.source == "opgg":
                    pass  # pure OPGG — drop entirely
                elif s.source == "multi":
                    cleared = dict.fromkeys(OPGG_EXCLUSIVE_FIELDS)
                    cleared["source"] = "dpm"
                    new_splits.append(s.model_copy(update=cleared))
                else:
                    new_splits.append(s)
            entry.splits = new_splits
        pool.champions = [e for e in pool.champions if e.splits]


def _backfill_rank_wl(account: Account, season_data: dict) -> None:
    """
    Gap-fill W/L on existing SplitRankEntry objects from OPGG champion season totals.

    The champion scraper sums wins+losses across all champions per season — that total
    equals the account's overall season W/L. Write it onto rank_data splits where
    wins is currently None. Never overwrites existing W/L data.
    """
    if not account.rank_data:
        return

    queue_map = {"solo": account.rank_data.solo_splits, "flex": account.rank_data.flex_splits}

    for lol_season, queues in season_data.items():
        for queue_key, data in queues.items():
            wins   = data.get("wins")
            losses = data.get("losses")
            if wins is None and losses is None:
                continue

            splits = queue_map.get(queue_key, [])
            for split in splits:
                if split.season == lol_season and split.wins is None:
                    split.wins   = wins
                    split.losses = losses
                    if wins is not None and losses is not None and (wins + losses) > 0:
                        split.win_rate = round(wins / (wins + losses) * 100, 1)


def _merge_season_data(champion_data: AccountChampionData, season_data: dict) -> None:
    """
    Merge extract_all_champion_seasons() output into AccountChampionData.

    season_data shape:
      {lol_season: {"solo": {"wins", "losses", "champions": {name: {field: value, ...}}},
                    "flex": {...}}}

    Only fields present in the champion dict are passed to ChampionSplitStats — absent
    fields are left as None so merge_split never overwrites existing DPM-sourced data.
    """
    for lol_season, queues in season_data.items():
        for queue_key, data in queues.items():
            pool: AccountQueueChampionPool = (
                champion_data.solo if queue_key == "solo" else champion_data.flex
            )
            champions_dict: dict = data.get("champions", {})

            for champ_name, cd in champions_dict.items():
                wins   = cd.get("wins")   or 0
                losses = cd.get("losses") or 0
                total  = wins + losses

                entry = pool.get_champion(champ_name, role="ALL")
                if entry is None:
                    entry = ChampionEntry(champion=champ_name, role="ALL")
                    pool.champions.append(entry)

                entry.merge_split(ChampionSplitStats(
                    lol_season=lol_season,
                    games=total,
                    wins=wins,
                    losses=losses,
                    win_rate=wins / total if total > 0 else None,
                    op_score=cd.get("op_score"),
                    expected_op_score=cd.get("expected_op_score"),
                    op_laning_score=cd.get("op_laning_score"),
                    expected_laning_pct=cd.get("expected_laning_pct"),
                    kda=cd.get("kda"),
                    kills_per_game=cd.get("kills_per_game"),
                    deaths_per_game=cd.get("deaths_per_game"),
                    assists_per_game=cd.get("assists_per_game"),
                    dpm=cd.get("dpm"),
                    damage_share_pct=cd.get("damage_share_pct"),
                    avg_vision_score=cd.get("avg_vision_score"),
                    cs_per_min=cd.get("cs_per_min"),
                    avg_cs_per_game=cd.get("avg_cs_per_game"),
                    gpm=cd.get("gpm"),
                    avg_gold_per_game=cd.get("avg_gold_per_game"),
                    source="opgg",
                ))
