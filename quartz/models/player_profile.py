"""
PlayerProfile — Canonical player data model.
One JSON file per player in data/{tournament}/{round}/players/{player_id}.json

Sub-models:
  AccountURL        — profile links per account (grows as new sources are added)
  Account           — a single Riot account (persists across seasons)
  SeasonData        — per-tournament-round metadata (type, role, stated ranks, team, PV)
  PlayerProfile     — root model with I/O helpers

Enrichment sections (rank_data, champion_pool, computed_pv) are populated
incrementally as pipeline tasks run, stored in PlayerStats.
"""

import json
import os
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, computed_field, model_validator

from quartz.constants import PLAYER_TYPES
from quartz.models.champion_data import AccountChampionData
from quartz.models.rank_data import AccountRankData, PlayerStats

# ------------------------------------------------------------------
# Account sub-models
# ------------------------------------------------------------------

class AccountURL(BaseModel):
    opgg_url: Optional[str] = None
    dpm_url: Optional[str] = None


class AccountFlag(BaseModel):
    """A structured marker on one account indicating a condition that warrants review.

    See docs/flags.md for the full type catalogue.
    """
    flag_type: str                  # "low_level", "low_volume", "smurf_peak", "smurf_jump", "name_changed"
    detail: Optional[str] = None    # human-readable context, e.g. "peaked Emerald 2 in S2024 S1 (level 134)"
    auto: bool = True               # False = manually set by admin via `quartz flags add`
    dismissed: bool = False         # True = admin acknowledged false positive; still visible, excluded from account_flagged


class Account(BaseModel):
    riot_id: str                        # "GameName#Tag"
    player_region: str = "NA"           # "NA", "EUW", etc.
    account_level: Optional[int] = None
    archived: bool = False              # True if account was removed from form but we retain the data
    puuid: Optional[str] = None         # Riot PUUID — stable across name changes; populated by RIOT_ENRICH_PUUID
    urls: AccountURL = Field(default_factory=AccountURL)
    flags: list[AccountFlag] = []       # structured account flags — see docs/flags.md
    rank_data: Optional[AccountRankData] = None       # populated by OPGG_SCRAPE_RANK
    champion_data: Optional[AccountChampionData] = None  # populated by DPM_SCRAPE_CHAMP / OPGG_SCRAPE_CHAMP

    @model_validator(mode='before')
    @classmethod
    def _migrate_legacy_fields(cls, data: object) -> object:
        """Migrate account_flagged + update_riot_id booleans to the AccountFlag list."""
        if not isinstance(data, dict):
            return data
        flags = list(data.get('flags', []))
        existing_types = {
            (f.get('flag_type') if isinstance(f, dict) else f.flag_type)
            for f in flags
        }
        if data.get('update_riot_id') and 'name_changed' not in existing_types:
            flags.append({'flag_type': 'name_changed', 'auto': True,
                          'detail': 'migrated from update_riot_id'})
        data['flags'] = flags
        return data

    @computed_field
    @property
    def account_flagged(self) -> bool:
        """True if this account has any active (non-dismissed) flags."""
        return any(f for f in self.flags if not f.dismissed)

    # ------------------------------------------------------------------
    # Flag helpers
    # ------------------------------------------------------------------

    def add_auto_flag(self, flag_type: str, detail: Optional[str] = None) -> None:
        """Add or refresh an auto flag. No-ops if a dismissed flag of this type already exists."""
        for f in self.flags:
            if f.flag_type == flag_type and f.auto:
                if not f.dismissed:
                    f.detail = detail
                return
        self.flags.append(AccountFlag(flag_type=flag_type, detail=detail, auto=True))

    def clear_auto_flag(self, flag_type: str) -> None:
        """Remove all auto-generated flags of this type (including dismissed — condition no longer true)."""
        self.flags = [f for f in self.flags if not (f.flag_type == flag_type and f.auto)]

    def get_flag(self, flag_type: str) -> Optional[AccountFlag]:
        return next((f for f in self.flags if f.flag_type == flag_type), None)


# ------------------------------------------------------------------
# Season sub-model
# ------------------------------------------------------------------

class ManualAdjustment(BaseModel):
    """A single admin-set PV adjustment for one player in one tournament round."""
    category: str               # "tournament_win", "finals_appearance", "admin_bonus", etc.
    value: float                # positive = reduces PV (bonus); negative = increases PV (penalty)
    note: Optional[str] = None  # freeform context e.g. "Won GCS S3"


class SeasonData(BaseModel):
    season: str                              # tournament round key e.g. "GCS-S4"
    player_type: str = "main"               # from PLAYER_TYPES constants
    primary_pos: Optional[str] = None       # from ROLES constants
    secondary_pos: Optional[str] = None     # from ROLES constants
    stated_peak_rank: Optional[str] = None
    stated_current_rank: Optional[str] = None
    team_name: Optional[str] = None
    point_value: Optional[int] = None
    shadow_point_value: Optional[int] = None  # PV for ineligible players (as if eligible) — see docs/flags.md
    eligible: Optional[bool] = None           # None=not evaluated; set by PV_COMPUTE / resync
    inhouse_wins:   Optional[int] = None   # in-house games won this tournament round
    inhouse_losses: Optional[int] = None   # in-house games lost this tournament round
    manual_adjustments: list[ManualAdjustment] = []  # admin-set per-round PV bonuses/penalties


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
        """True only if every non-archived account has at least one active (non-dismissed) flag."""
        active = [a for a in self.accounts if not a.archived]
        return bool(active) and all(a.account_flagged for a in active)

    season_data: list[SeasonData] = []  # one entry per tournament round; use upsert_season()
    accounts: list[Account] = []        # persists across rounds
    stats: Optional[PlayerStats] = None  # aggregated enrichment; populated incrementally by pipeline tasks

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
    def from_csv_row(cls, row: dict, tournament_round: str) -> "PlayerProfile":
        """
        Build a PlayerProfile from a cleaned LocalCSVInput row.

        [param] row:             dict from LocalCSVInput._clean_row()
        [param] tournament_round: composite round key e.g. "GCS-S4"
        """
        player_type = row.get("player_type_override") or "main"
        if player_type not in PLAYER_TYPES:
            player_type = "main"

        season_entry = SeasonData(
            season=tournament_round,
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
        """Replace the existing SeasonData for that round, or append if new."""
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
