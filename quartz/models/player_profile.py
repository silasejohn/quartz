"""
PlayerProfile — Canonical player data model.
One JSON file per player in data/{tournament}/{season}/players/{player_id}.json

Sub-models:
  AccountURL   — profile links per account
  Account      — a single Riot account (persists across seasons)
  SeasonData   — per-season metadata (type, role, stated ranks, team, PV)
  PlayerProfile — root model with I/O helpers

Enrichment sections (rank_data, champion_pool, computed) are populated
incrementally as pipeline tasks run.
"""

import json
import os
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, computed_field

from quartz.constants import PLAYER_TYPES
from quartz.models.rank_data import AccountRankData, PlayerEnrichment


# ------------------------------------------------------------------
# Account sub-models
# ------------------------------------------------------------------

class AccountURL(BaseModel):
    opgg_url: Optional[str] = None
    dpm_url: Optional[str] = None


class Account(BaseModel):
    riot_id: str                        # "GameName#Tag"
    player_region: str = "NA"           # "NA", "EUW", etc.
    account_level: Optional[int] = None
    account_flagged: bool = False
    update_riot_id: bool = False        # True when OP.GG can't find this riot_id (name may have changed)
    archived: bool = False              # True if account was removed from form but we retain the data
    urls: AccountURL = Field(default_factory=AccountURL)
    rank_data: Optional[AccountRankData] = None   # populated by OPGG_ENRICH_RANK


# ------------------------------------------------------------------
# Season sub-model
# ------------------------------------------------------------------

class ManualAdjustment(BaseModel):
    """A single admin-set PV adjustment for one player in one tournament season."""
    category: str               # "tournament_win", "finals_appearance", "admin_bonus", etc.
    value: float                # positive = reduces PV (bonus); negative = increases PV (penalty)
    note: Optional[str] = None  # freeform context e.g. "Won GCS S3"


class SeasonData(BaseModel):
    season: str                              # tournament round e.g. "S4" — from active_tournament.yaml
    player_type: str = "main"               # from PLAYER_TYPES constants
    primary_pos: Optional[str] = None       # from ROLES constants
    secondary_pos: Optional[str] = None     # from ROLES constants
    stated_peak_rank: Optional[str] = None
    stated_current_rank: Optional[str] = None
    team_name: Optional[str] = None
    point_value: Optional[int] = None
    inhouse_wins:   Optional[int] = None   # in-house games won this tournament season
    inhouse_losses: Optional[int] = None   # in-house games lost this tournament season
    manual_adjustments: list[ManualAdjustment] = []  # admin-set per-season PV bonuses/penalties


# ------------------------------------------------------------------
# Root model
# ------------------------------------------------------------------

class PlayerProfile(BaseModel):
    player_id: Optional[str] = None     # manually set display slug; if None, derived from discord_id
    player_nickname: Optional[str] = None
    discord_id: str                     # raw Discord username from form

    @property
    def effective_id(self) -> str:
        """Slug used for filenames and lookups. player_id takes priority over discord_id."""
        return self.player_id if self.player_id else self.make_player_id(self.discord_id)

    @computed_field
    @property
    def profile_flagged(self) -> bool:
        """True only if every non-archived account is flagged. False if any active account is clean."""
        active = [a for a in self.accounts if not a.archived]
        return bool(active) and all(a.account_flagged for a in active)

    season_data: list[SeasonData] = []  # one entry per season; use upsert_season()
    accounts: list[Account] = []        # persists across seasons
    data: Optional[PlayerEnrichment] = None   # aggregated enrichment; populated by CALCULATE_RANK_STATS and later tasks

    created_at: datetime
    last_updated_at: datetime

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    @classmethod
    def from_json_file(cls, path: str) -> "PlayerProfile":
        """Load a PlayerProfile from a JSON file on disk."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"PlayerProfile not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.model_validate(data)

    def to_json_file(self, path: str) -> None:
        """Serialize and write this profile to disk, creating directories as needed."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(mode="json"), f, indent=2)

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_csv_row(cls, row: dict, season: str) -> "PlayerProfile":
        """
        Build a PlayerProfile from a cleaned LocalCSVInput row.

        [param] row:    dict from LocalCSVInput._clean_row()
        [param] season: tournament round string e.g. "S4" — from active_tournament.yaml
        """
        player_type = row.get("player_type_override") or "main"
        if player_type not in PLAYER_TYPES:
            player_type = "main"

        season_entry = SeasonData(
            season=season,
            player_type=player_type,
            primary_pos=row.get("primary_role"),
            secondary_pos=row.get("secondary_role"),
            stated_current_rank=row.get("stated_current_rank"),
            stated_peak_rank=row.get("stated_peak_rank"),
        )

        accounts = [
            Account(riot_id=a["riot_id"], player_region=a["player_region"])
            for a in row.get("accounts", [])
            if a.get("riot_id")
        ]

        now = datetime.now(timezone.utc)
        return cls(
            discord_id=row["discord_username"],
            season_data=[season_entry],
            accounts=accounts,
            created_at=now,
            last_updated_at=now,
        )

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def upsert_season(self, new_season: SeasonData) -> None:
        """Replace the existing SeasonData for that season, or append if new."""
        for i, sd in enumerate(self.season_data):
            if sd.season == new_season.season:
                self.season_data[i] = new_season
                return
        self.season_data.append(new_season)
        self.last_updated_at = datetime.now(timezone.utc)

    def touch(self) -> None:
        """Update last_updated_at to now."""
        self.last_updated_at = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def make_player_id(discord_username: str) -> str:
        return discord_username.lower().replace(" ", "_")

    @staticmethod
    def filename_for(discord_username: str) -> str:
        return PlayerProfile.make_player_id(discord_username) + ".json"
