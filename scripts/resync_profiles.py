"""
resync_profiles.py
Applies manual edits made directly to player JSON files.

Re-saves every profile through the registry so things like:
  - manually set player_id  -> renames the file and cleans up the old one
  - any other hand-edited fields -> written back cleanly via Pydantic

Also rebuilds the discord_id -> slug index and recomputes enrichment.
Safe to re-run at any time.
"""

import os

from quartz.tournament_config import load_tournament_config
from quartz.player_registry import PlayerRegistry
from quartz.models.rank_data import compute_enrichment
from quartz.utils.logging import info_print, success_print, warning_print

config = load_tournament_config()
registry = PlayerRegistry(config.abs_players_dir)

# Rebuild the discord_id -> slug index from current files on disk
registry.rebuild_index()

profiles = registry.load_all()

renamed  = 0
ok       = 0

for profile in profiles:
    old_slug = profile.make_player_id(profile.discord_id)
    new_slug = profile.effective_id
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
