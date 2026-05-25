"""
PlayerRegistry
Owns all read/write of player JSON files in data/{tournament}/{season}/players/.
Single point of access for loading, saving, and listing player profiles.

Maintains _index.json — a discord_id -> effective_id slug map — so players
whose files are named after a custom player_id can still be looked up by
their Discord username.
"""

import glob
import json
import os
from typing import Optional

from filelock import FileLock

from quartz.models.player_profile import PlayerProfile
from quartz.utils.logging import error_print, info_print, success_print, warning_print

INDEX_FILE = "_index.json"


class PlayerRegistry:
    """
    Manages the on-disk store of PlayerProfile JSON files.

    Usage:
        registry = PlayerRegistry("data/gcs/s4/players")
        registry.save(profile)
        profile = registry.load("slaveknightkos")
        all_players = registry.load_all()
    """

    def __init__(self, players_dir: str):
        self.players_dir = players_dir
        os.makedirs(players_dir, exist_ok=True)
        self._index_cache: Optional[dict] = None  # invalidated on every save

    # ------------------------------------------------------------------
    # Index helpers
    # ------------------------------------------------------------------

    def _index_path(self) -> str:
        return os.path.join(self.players_dir, INDEX_FILE)

    def _load_index(self) -> dict:
        if self._index_cache is not None:
            return self._index_cache
        path = self._index_path()
        if not os.path.exists(path):
            return {}
        with open(path, encoding="utf-8") as f:
            self._index_cache = json.load(f)
        return self._index_cache

    def _save_index(self, index: dict) -> None:
        with open(self._index_path(), "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, sort_keys=True)
        self._index_cache = index

    def rebuild_index(self) -> None:
        """Rebuild _index.json by scanning all player JSONs on disk."""
        profiles = self.load_all()
        index = {p.discord_id: p.effective_id for p in profiles}
        self._save_index(index)
        success_print(f"PlayerRegistry: rebuilt index with {len(index)} entries")

    def _slug_for(self, discord_username: str) -> Optional[str]:
        """Return the effective_id slug for a discord_username via the index."""
        return self._load_index().get(discord_username)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def exists(self, discord_username: str) -> bool:
        slug = self._slug_for(discord_username) or PlayerProfile.make_player_id(discord_username)
        return os.path.exists(os.path.join(self.players_dir, slug + ".json"))

    def load(self, discord_username: str) -> Optional[PlayerProfile]:
        slug = self._slug_for(discord_username) or PlayerProfile.make_player_id(discord_username)
        path = os.path.join(self.players_dir, slug + ".json")
        if not os.path.exists(path):
            return None
        try:
            with FileLock(path + ".lock"):
                return PlayerProfile.from_json_file(path)
        except Exception as e:
            error_print(f"PlayerRegistry: failed to load {path}: {e}")
            return None

    def save(self, profile: PlayerProfile) -> None:
        new_path = os.path.join(self.players_dir, profile.effective_id + ".json")
        old_path = os.path.join(self.players_dir, PlayerProfile.make_player_id(profile.discord_id) + ".json")

        with FileLock(new_path + ".lock"):
            profile.to_json_file(new_path)

            # If player_id was manually set and differs from the discord-derived slug,
            # delete the old file so we don't leave an orphan behind
            if new_path != old_path and os.path.exists(old_path):
                os.remove(old_path)
                info_print(f"PlayerRegistry: renamed {os.path.basename(old_path)} -> {os.path.basename(new_path)}")

        # Keep the index up to date; invalidate cache so next read is fresh
        self._index_cache = None
        index = self._load_index()
        index[profile.discord_id] = profile.effective_id
        self._save_index(index)

    # ------------------------------------------------------------------
    # Bulk operations
    # ------------------------------------------------------------------

    def load_all(self) -> list[PlayerProfile]:
        """Load every player JSON in the registry directory (skips _index.json)."""
        paths = [
            p for p in glob.glob(os.path.join(self.players_dir, "*.json"))
            if os.path.basename(p) != INDEX_FILE
        ]
        profiles = []
        for path in sorted(paths):
            try:
                profiles.append(PlayerProfile.from_json_file(path))
            except Exception as e:
                warning_print(f"PlayerRegistry: skipping {path}: {e}")
        info_print(f"PlayerRegistry: loaded {len(profiles)} player profiles")
        return profiles

    def player_ids(self) -> list[str]:
        """Return all effective_id slugs (filename stems) in the registry."""
        paths = [
            p for p in glob.glob(os.path.join(self.players_dir, "*.json"))
            if os.path.basename(p) != INDEX_FILE
        ]
        return sorted(os.path.splitext(os.path.basename(p))[0] for p in paths)

    def find_profiles(self, queries: list[str]) -> list:
        """
        Return profiles matching any of the query strings.

        Matching is case-insensitive and accepts:
          - Substring of effective_id (discord username)
          - Exact riot_id ("GameName#TAG")
          - Substring of the game_name part of any riot_id (before the #)

        Used by scrape tasks so "PingSpam" resolves to "PingSpam#NA1".
        """
        all_profiles = self.load_all()
        matched = []
        for profile in all_profiles:
            for q in queries:
                q_lower = q.lower()
                if q_lower in profile.effective_id.lower():
                    matched.append(profile)
                    break
                for account in profile.accounts:
                    riot_lower = account.riot_id.lower()
                    game_name = riot_lower.split("#")[0]
                    if q_lower == riot_lower or q_lower in game_name:
                        matched.append(profile)
                        break
                else:
                    continue
                break
        info_print(f"PlayerRegistry: matched {len(matched)} profiles for {queries}")
        return matched

    def count(self) -> int:
        return len([
            p for p in glob.glob(os.path.join(self.players_dir, "*.json"))
            if os.path.basename(p) != INDEX_FILE
        ])
