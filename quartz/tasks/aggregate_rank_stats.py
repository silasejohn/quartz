"""
Task: AGGREGATE_RANK_STATS
Aggregate Account.rank_data across all accounts -> PlayerStats.

Populates profile.stats with rank_data (solo + flex AggregatedRankData),
all_time_peak_rank, and current_rank.

Safe to re-run — idempotent. Requires OPGG_SCRAPE_RANK to have run first.
"""

from quartz.tournament_config import TournamentConfig
from quartz.player_registry import PlayerRegistry
from quartz.utils.logging import info_print, success_print


def run(config: TournamentConfig, registry: PlayerRegistry, players: list[str] | None = None) -> None:
    """
    [param] config:   TournamentConfig — uses current_lol_split
    [param] registry: PlayerRegistry — profiles are loaded and saved here
    [param] players:  optional list of discord_usernames to limit scope. None = all.
    """
    from quartz.models.rank_data import compute_enrichment

    all_profiles = registry.load_all()
    players_lower = {p.lower() for p in players} if players else None
    if players_lower:
        all_profiles = [p for p in all_profiles if p.effective_id.lower() in players_lower]

    computed = 0
    for profile in all_profiles:
        profile.stats = compute_enrichment(profile.accounts, config.current_lol_split)
        profile.touch()
        registry.save(profile)
        info_print(
            f"  {profile.effective_id}: "
            f"peak={profile.stats.all_time_peak_rank}, "
            f"current={profile.stats.current_rank}"
        )
        computed += 1

    success_print(f"AGGREGATE_RANK_STATS: {computed} profiles aggregated")
