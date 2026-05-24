"""
set_player_type.py
Change a player's type (captain, main, sub, other) for the current tournament round.

Accepts a player_id or RiotID#Tag to locate the profile, then prompts
for the new player type with input validation.

Usage:
    python3 set_player_type.py
"""

import sys

from quartz.tournament_config import load_tournament_config
from quartz.player_registry import PlayerRegistry
from quartz.models.player_profile import PlayerProfile, SeasonData
from quartz.constants import PLAYER_TYPES
from quartz.utils.color_utils import info_print, success_print, warning_print, error_print

config = load_tournament_config()
CURRENT_SEASON = config.round_id


def find_profile(registry: PlayerRegistry, query: str) -> PlayerProfile | None:
    """
    Look up a profile by player_id slug OR by RiotID#Tag (searches all accounts).
    Returns None if not found.
    """
    profile = registry.load(query)
    if profile:
        return profile

    # Try all profiles and match against riot_ids
    for p in registry.load_all():
        if any(a.riot_id.lower() == query.lower() for a in p.accounts):
            return p

    return None


def prompt(label: str) -> str:
    return input(f"  {label}: ").strip()


def prompt_choice(label: str, options: list[str]) -> str:
    options_str = " / ".join(options)
    while True:
        val = input(f"  {label} [{options_str}]: ").strip().lower()
        if val in [o.lower() for o in options]:
            return val
        error_print(f"    Invalid — must be one of: {options_str}")


def main() -> None:
    registry = PlayerRegistry(config.abs_players_dir)

    print()
    info_print(f"Set player type for season {CURRENT_SEASON}")
    print()

    # Step 1: find the profile
    while True:
        query = prompt("Player ID or RiotID#Tag")
        if not query:
            continue
        profile = find_profile(registry, query)
        if profile:
            break
        error_print(f"    No profile found for '{query}' — try their discord username or a riot_id")

    # Step 2: show current state
    existing = next((sd for sd in profile.season_data if sd.season == CURRENT_SEASON), None)
    current_type = existing.player_type if existing else "not set"
    info_print(f"    Found: {profile.effective_id}  (discord: {profile.discord_id})")
    info_print(f"    Current player type for {CURRENT_SEASON}: {current_type}")
    print()

    # Step 3: pick new type
    new_type = prompt_choice("New player type", PLAYER_TYPES)

    if new_type == current_type:
        warning_print("No change — player type is already set to that.")
        sys.exit(0)

    # Step 4: upsert season entry with updated type
    if existing:
        updated = SeasonData(
            season=existing.season,
            player_type=new_type,
            primary_pos=existing.primary_pos,
            secondary_pos=existing.secondary_pos,
            stated_peak_rank=existing.stated_peak_rank,
            stated_current_rank=existing.stated_current_rank,
            team_name=existing.team_name,
            point_value=existing.point_value,
        )
    else:
        updated = SeasonData(season=CURRENT_SEASON, player_type=new_type)

    profile.upsert_season(updated)
    profile.touch()
    registry.save(profile)

    print()
    success_print(f"Updated {profile.effective_id}: {current_type} -> {new_type} for {CURRENT_SEASON}")


if __name__ == "__main__":
    main()
