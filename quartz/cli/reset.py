"""
quartz reset — clean-slate commands for rank and champion data.

    quartz reset rank  [PLAYERS...]   wipe raw rank data + aggregated stats + PV
    quartz reset champ [PLAYERS...]   wipe all champion data (both DPM and OP.GG)
"""

from typing import Optional

import typer

from quartz.player_registry import PlayerRegistry
from quartz.tournament_config import load_tournament_config
from quartz.utils.logging import info_print, success_print, warning_print

app = typer.Typer(no_args_is_help=True)


@app.command("rank")
def rank(
    players: Optional[list[str]] = typer.Argument(None, help="Player IDs or Riot IDs to reset (default: all)"),
):
    """
    Wipe all raw rank data and aggregated enrichment (peak rank, current rank, PV).
    Re-run `quartz scrape opgg` then `quartz pv` to rebuild from scratch.
    """
    config   = load_tournament_config()
    registry = PlayerRegistry(config.abs_players_dir)
    profiles = registry.find_profiles(players) if players else registry.load_all()

    cleared = 0
    for profile in profiles:
        changed = False

        for account in profile.accounts:
            if account.rank_data is not None:
                account.rank_data = None
                changed = True

        if profile.stats is not None:
            s = profile.stats
            s.rank_data          = None
            s.all_time_peak_rank = None
            s.current_rank       = None
            s.computed_pv        = None
            if s.champion_pool is None:
                profile.stats = None
            changed = True

        if changed:
            registry.save(profile)
            info_print(f"  reset rank: {profile.effective_id}")
            cleared += 1
        else:
            warning_print(f"  no rank data: {profile.effective_id} (skipped)")

    success_print(f"Rank data cleared for {cleared} player(s). Re-run `quartz scrape opgg` then `quartz pv`.")


@app.command("champ")
def champ(
    players: Optional[list[str]] = typer.Argument(None, help="Player IDs or Riot IDs to reset (default: all)"),
):
    """
    Wipe all champion data (both DPM.lol and OP.GG) for every account.
    Re-run `quartz scrape champ` to rebuild from scratch.
    """
    config   = load_tournament_config()
    registry = PlayerRegistry(config.abs_players_dir)
    profiles = registry.find_profiles(players) if players else registry.load_all()

    cleared = 0
    for profile in profiles:
        changed = False

        for account in profile.accounts:
            if account.champion_data is not None:
                account.champion_data = None
                changed = True

        if profile.stats is not None:
            s = profile.stats
            s.champion_pool = None
            if s.rank_data is None and s.all_time_peak_rank is None and s.computed_pv is None:
                profile.stats = None
            changed = True

        if changed:
            registry.save(profile)
            info_print(f"  reset champ: {profile.effective_id}")
            cleared += 1
        else:
            warning_print(f"  no champion data: {profile.effective_id} (skipped)")

    success_print(f"Champion data cleared for {cleared} player(s). Re-run `quartz scrape champ`.")
