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

from quartz.utils.champion_names import champion_key


class ChampionSplitStats(BaseModel):
    """Stats for one champion in one LoL split on one account."""
    lol_season: str                                  # e.g. "S2026" — key from SEASON_ORDER
    games: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: Optional[float] = None                 # recomputed from wins/losses

    kills_per_game:   Optional[float] = None
    deaths_per_game:  Optional[float] = None
    assists_per_game: Optional[float] = None
    kda: Optional[float] = None

    # Composite scores (source-computed, used as MVP champion feature)
    dpm_score: Optional[float] = None               # DPM.lol's internal per-champ performance score (source: "dpm")
    op_score: Optional[float] = None                # OP.GG's internal per-champ performance score (source: "opgg")

    # Cluster 1 — Laning / Early Game
    cs_per_min: Optional[float] = None
    cs_at_15: Optional[float] = None                # absolute CS at 15 min, rank/champ normalized (source: "dpm")
    csd_at_10: Optional[float] = None               # CS difference vs opponent at 10 min (source: "riot_api")
    early_deaths_per_game: Optional[float] = None   # deaths before 14 min, per game (source: "riot_api")
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
    mastery_points: Optional[int] = None            # cumulative Riot mastery points (source: "opgg"), not split-specific
    splits: list[ChampionSplitStats] = []

    def get_split(self, lol_season: str) -> Optional[ChampionSplitStats]:
        return next((s for s in self.splits if s.lol_season == lol_season), None)

    def upsert_split(self, entry: ChampionSplitStats) -> None:
        for i, s in enumerate(self.splits):
            if s.lol_season == entry.lol_season:
                self.splits[i] = entry
                return
        self.splits.append(entry)

    # Fields owned exclusively by one source — never overwritten by another source.
    _SOURCE_EXCLUSIVE: dict[str, str] = {"dpm_score": "dpm", "op_score": "opgg"}

    def merge_split(self, new: ChampionSplitStats) -> None:
        """
        Merge a new split into this entry's split list for the matching season.

        More games  → new source wins: overwrites all non-None fields (takes control).
        Same/fewer  → gap-fill only: writes fields that are currently None, never overwrites.
        No match    → append as new split.

        Source-exclusive fields (dpm_score, op_score) are never overwritten by
        a different source regardless of game count.
        """
        for i, existing in enumerate(self.splits):
            if existing.lol_season != new.lol_season:
                continue
            if new.games > existing.games:
                patch = {
                    k: v for k, v in new.model_dump().items()
                    if v is not None
                    and self._SOURCE_EXCLUSIVE.get(k, new.source) == new.source
                }
            else:
                patch = {
                    k: v for k, v in new.model_dump().items()
                    if v is not None
                    and getattr(existing, k) is None
                    and self._SOURCE_EXCLUSIVE.get(k, new.source) == new.source
                }
            self.splits[i] = existing.model_copy(update=patch)
            return
        self.splits.append(new)


class AccountQueueChampionPool(BaseModel):
    """Champion data for one queue type on one account."""
    champions: list[ChampionEntry] = []
    dpm_scraped_at: Optional[datetime] = None         # set by DPM_SCRAPE_CHAMP (current split)
    opgg_scraped_at: Optional[datetime] = None        # set by OPGG_SCRAPE_CHAMP (historical splits)

    def get_champion(self, champion: str, role: Optional[str] = None) -> Optional[ChampionEntry]:
        key = champion_key(champion)
        return next(
            (c for c in self.champions if champion_key(c.champion) == key and c.role == role),
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
