"""
Task: RIOT_ENRICH_PUUID
Populate Account.puuid for all accounts that don't have one yet.

Uses Riot Account API v1: GET /riot/account/v1/accounts/by-riot-id/{gameName}/{tagLine}
Requires RIOT_API_KEY environment variable.

Lock strategy:
  - Profile loaded before API call begins.
  - No lock held during the HTTP request.
  - Write lock acquired only during registry.save().
"""

import time

from quartz.player_registry import PlayerRegistry
from quartz.scrapers.core.scrape_result import AccountScrapeOutcome, ScrapeResult
from quartz.tournament_config import TournamentConfig
from quartz.utils.logging import error_print, info_print, success_print, warning_print

_REQUEST_DELAY = 1.2  # seconds between API calls — stays within dev key limits (20 req/s)


def run(
    _config: TournamentConfig,
    registry: PlayerRegistry,
    players: list[str] | None = None,
    force: bool = False,
) -> ScrapeResult:
    """
    [param] _config:  TournamentConfig (unused but kept for task interface consistency)
    [param] registry: PlayerRegistry — profiles are loaded and saved here
    [param] players:  optional list of discord_usernames or riot_ids to limit scope. None = all.
    [param] force:    if True, re-fetch PUUID even if already present on the account
    """
    from quartz.scrapers.riot_api import RiotAPIClient

    result = ScrapeResult(task="RIOT_ENRICH_PUUID")

    try:
        client = RiotAPIClient()
    except RuntimeError as e:
        error_print(str(e))
        return result

    all_profiles = registry.find_profiles(players) if players else registry.load_all()

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

                if account.puuid and not force:
                    result.outcomes.append(AccountScrapeOutcome(
                        riot_id=account.riot_id,
                        player_id=profile.effective_id,
                        status="skipped",
                        detail="puuid already present",
                    ))
                    continue

                puuid = client.lookup_puuid(account.riot_id, region=account.player_region)
                time.sleep(_REQUEST_DELAY)

                if puuid:
                    account.puuid = puuid
                    profile_changed = True
                    success_print(f"    {account.riot_id} → {puuid[:16]}...")
                    result.outcomes.append(AccountScrapeOutcome(
                        riot_id=account.riot_id,
                        player_id=profile.effective_id,
                        status="ok",
                    ))
                else:
                    warning_print(f"    {account.riot_id}: not found on Riot API (name may have changed)")
                    result.outcomes.append(AccountScrapeOutcome(
                        riot_id=account.riot_id,
                        player_id=profile.effective_id,
                        status="not_found",
                        detail="account not found via Riot Account API",
                    ))

            if profile_changed:
                registry.save(profile)

    finally:
        client.close()

    success_print(result.summary())
    return result
