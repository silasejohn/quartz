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
from quartz.tournament_config import TournamentConfig
from quartz.utils.logging import error_print, info_print, success_print, warning_print


def run(
    config: TournamentConfig,
    registry: PlayerRegistry,
    players: list[str] | None = None,
) -> tuple[set[str], set[str]]:
    """
    [param] config:   TournamentConfig — uses current_lol_split
    [param] registry: PlayerRegistry — profiles are loaded and saved here
    [param] players:  optional list of discord_usernames or riot_ids to limit scope. None = all.

    Returns (soft_errors, not_found):
      - soft_errors: riot_ids where profile saved but data is incomplete (e.g. current rank missing)
      - not_found:   riot_ids where OP.GG returned no profile (name change likely)
    """
    from quartz.scrapers.opgg_scraper import OPGGScraper

    delay = 4
    all_profiles = registry.load_all()
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
        error_print("OPGG_SCRAPE_RANK: failed to set up browser — aborting")
        return set(), set()

    scraped = skipped = errors = 0
    soft_errors: set[str] = set()
    not_found: set[str] = set()

    try:
        for profile in all_profiles:
            info_print(f"  Processing: {profile.effective_id}")
            profile_changed = False

            for account in profile.accounts:
                if account.archived:
                    continue
                if players_lower and account.riot_id.lower() not in players_lower and profile.effective_id.lower() not in players_lower:
                    continue

                ok, opgg_url = scraper.navigate_to_profile(account.riot_id, account.player_region)
                if not ok:
                    warning_print(f"    Skipped: {account.riot_id} (profile not found — name may have changed)")
                    account.update_riot_id = True
                    account.account_flagged = True
                    not_found.add(account.riot_id)
                    profile_changed = True
                    skipped += 1
                    continue

                if account.update_riot_id:
                    account.update_riot_id = False

                if opgg_url:
                    account.urls.opgg_url = opgg_url
                    profile_changed = True

                account.rank_data = scraper.extract_solo_rank_data(
                    existing=account.rank_data,
                    current_lol_split=config.current_lol_split,
                )

                current_split = account.rank_data.get_split(config.current_lol_split) if account.rank_data else None
                if current_split and current_split.split_rank is None:
                    warning_print(f"    Soft error: current rank missing for {account.riot_id} — will re-run")
                    soft_errors.add(account.riot_id)

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
                registry.save(profile)
                success_print(f"  Saved: {profile.effective_id}")

    finally:
        scraper.close()

    success_print(
        f"OPGG_SCRAPE_RANK: {scraped} accounts scraped, "
        f"{skipped} skipped ({len(not_found)} need riot_id update), "
        f"{errors} errors, {len(soft_errors)} soft errors"
    )
    return soft_errors, not_found
