"""
Champion pool data models for the Quartz pipeline.

AccountQueueChampionPool — per-queue champion list for one account
AccountChampionData      — solo + flex pools for one account (stored on Account)
AggregatedChampionPool   — champion pool aggregated across all accounts (stored on PlayerStats)

Stats are tracked per champion, per LoL split, to support peak/current/trajectory
temporal features defined in CHAMP_FEATURES.md.

Three feature clusters per split:
  Cluster 1 — Laning/Early Game:  cs_per_min, csd_at_10, early_deaths_per_game, first_blood_rate
  Cluster 2 — Combat/Carry:       dpm, damage_share_pct, solo_kills_per_game, kill_participation_pct
  Cluster 3 — Macro:              gpm, gold_share_pct, objective_participation_pct, vision_score_per_min
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ChampionSplitStats(BaseModel):
    """Stats for one champion in one LoL split on one account."""
    lol_season: str                                  # e.g. "S2026" — key from SEASON_ORDER
    games: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: Optional[float] = None                 # recomputed from wins/losses

    kda: Optional[float] = None

    # Cluster 1 — Laning / Early Game
    cs_per_min: Optional[float] = None
    csd_at_10: Optional[float] = None               # CS difference at 10 minutes vs opponent
    early_deaths_per_game: Optional[float] = None   # deaths before 14 min, per game
    first_blood_rate: Optional[float] = None        # % of games with first blood participation

    # Cluster 2 — Combat / Carry Impact
    dpm: Optional[float] = None                     # damage per minute
    damage_share_pct: Optional[float] = None        # % of team damage dealt
    solo_kills_per_game: Optional[float] = None
    kill_participation_pct: Optional[float] = None  # KP %

    # Cluster 3 — Macro / Team Contribution
    gpm: Optional[float] = None                     # gold per minute
    gold_share_pct: Optional[float] = None          # % of team gold earned
    objective_participation_pct: Optional[float] = None
    vision_score_per_min: Optional[float] = None    # VSM

    source: str                                     # "opgg", "dpm", "riot_api"


class ChampionEntry(BaseModel):
    """All split data for one champion on one account in one queue."""
    champion: str
    role: Optional[str] = None                      # canonical role from ROLES constants
    splits: list[ChampionSplitStats] = []

    def get_split(self, lol_season: str) -> Optional[ChampionSplitStats]:
        return next((s for s in self.splits if s.lol_season == lol_season), None)

    def upsert_split(self, entry: ChampionSplitStats) -> None:
        for i, s in enumerate(self.splits):
            if s.lol_season == entry.lol_season:
                self.splits[i] = entry
                return
        self.splits.append(entry)


class AccountQueueChampionPool(BaseModel):
    """Champion data for one queue type on one account."""
    champions: list[ChampionEntry] = []
    scraped_at: Optional[datetime] = None

    def get_champion(self, champion: str, role: Optional[str] = None) -> Optional[ChampionEntry]:
        return next(
            (c for c in self.champions if c.champion == champion and c.role == role),
            None,
        )


class AccountChampionData(BaseModel):
    """Champion pool for one account across both queues."""
    solo: AccountQueueChampionPool = Field(default_factory=AccountQueueChampionPool)
    flex: AccountQueueChampionPool = Field(default_factory=AccountQueueChampionPool)


# ------------------------------------------------------------------
# Aggregated champion pool (profile-level, across all accounts)
# ------------------------------------------------------------------

class AggregatedChampionEntry(BaseModel):
    """Champion stats aggregated across all accounts for one queue."""
    champion: str
    role: Optional[str] = None
    splits: list[ChampionSplitStats] = []


class AggregatedChampionPool(BaseModel):
    """Champion pool aggregated across all accounts. Stored on PlayerStats."""
    solo: list[AggregatedChampionEntry] = []
    flex: list[AggregatedChampionEntry] = []
    computed_at: Optional[datetime] = None
