"""quartz debug/util — set-type, resync, and opgg-dump commands."""

import os
import time
from typing import Optional

import typer

from quartz.constants import PLAYER_TYPES
from quartz.models.player_profile import PlayerProfile, SeasonData
from quartz.models.rank_data import compute_enrichment
from quartz.player_registry import PlayerRegistry
from quartz.tournament_config import load_active_tournament
from quartz.utils.logging import error_print, info_print, success_print, warning_print

app = typer.Typer(no_args_is_help=True)


def _find_profile(registry: PlayerRegistry, query: str) -> PlayerProfile | None:
    profile = registry.load(query)
    if profile:
        return profile
    for p in registry.load_all():
        if any(a.riot_id.lower() == query.lower() for a in p.accounts):
            return p
    return None


def set_type(
    player:      str = typer.Argument(..., help="Player ID or RiotID#Tag"),
    player_type: str = typer.Argument(..., help=f"New type: {', '.join(PLAYER_TYPES)}"),
):
    """Change a player's tournament role (captain / main / sub / other)."""
    if player_type not in PLAYER_TYPES:
        error_print(f"Invalid type '{player_type}' — must be one of: {', '.join(PLAYER_TYPES)}")
        raise typer.Exit(1)

    config   = load_active_tournament()
    registry = PlayerRegistry(config.abs_players_dir)
    season   = config.round_id

    profile = _find_profile(registry, player)
    if not profile:
        error_print(f"No profile found for '{player}' — try their discord username or a Riot ID")
        raise typer.Exit(1)

    existing     = next((sd for sd in profile.season_data if sd.season == season), None)
    current_type = existing.player_type if existing else "not set"

    info_print(f"  Found: {profile.effective_id}  (discord: {profile.discord_id})")
    info_print(f"  Current player type for {season}: {current_type}")

    if player_type == current_type:
        warning_print("No change — player type is already set to that.")
        return

    if existing:
        updated = SeasonData(
            season=existing.season,
            player_type=player_type,
            primary_pos=existing.primary_pos,
            secondary_pos=existing.secondary_pos,
            stated_peak_rank=existing.stated_peak_rank,
            stated_current_rank=existing.stated_current_rank,
            team_name=existing.team_name,
            point_value=existing.point_value,
        )
    else:
        updated = SeasonData(season=season, player_type=player_type)

    profile.upsert_season(updated)
    profile.touch()
    registry.save(profile)
    success_print(f"Updated {profile.effective_id}: {current_type} -> {player_type} for {season}")


def resync():
    """Re-save all profiles through the registry after manual JSON edits."""
    config   = load_active_tournament()
    registry = PlayerRegistry(config.abs_players_dir)

    registry.rebuild_index()
    profiles = registry.load_all()

    renamed = 0
    ok      = 0

    for profile in profiles:
        old_slug       = profile.make_player_id(profile.discord_id)
        new_slug       = profile.effective_id
        old_file_exists = (old_slug != new_slug) and os.path.exists(
            os.path.join(config.abs_players_dir, old_slug + ".json")
        )

        profile.stats = compute_enrichment(profile.accounts, config.current_lol_split)
        registry.save(profile)

        if old_file_exists:
            info_print(f"  Renamed: {old_slug} -> {new_slug}")
            renamed += 1
        else:
            ok += 1

    success_print(f"Done: {renamed} renamed, {ok} unchanged ({len(profiles)} total)")


@app.command("opgg-dump")
def opgg_dump(
    player: str = typer.Argument(..., help="Player ID or Riot ID (e.g. PlayerName#NA1)"),
    out: Optional[str] = typer.Option(None, "--out", help="Output HTML file path (default: opgg_dump.html)"),
    region: str = typer.Option("na", "--region", help="Region code (default: na)"),
):
    """Dump OP.GG page HTML for inspecting/updating CSS selectors."""
    from quartz.scrapers.opgg_scraper import OPGGScraper

    out_path = out or "opgg_dump.html"

    scraper = OPGGScraper()
    if scraper.setup() == -1:
        error_print("Failed to set up browser — aborting")
        raise typer.Exit(1)

    try:
        ok, url = scraper.navigate_to_profile(player, region)
        if not ok:
            error_print(f"Profile not found for {player}")
            raise typer.Exit(1)

        info_print("Waiting 3s for page to settle...")
        time.sleep(3)

        html = scraper.driver.page_source
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)

        success_print(f"HTML dumped to: {out_path}  ({len(html):,} chars)")
        info_print("Search for rank-related class names with:")
        info_print("  grep -i 'tier\\|rank\\|lp\\|solo' opgg_dump.html | head -60")
    finally:
        scraper.close()
