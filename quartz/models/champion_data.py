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

# Field sets for selective strip logic (force re-scrape of one source).
# Used by _strip_dpm_data and _strip_opgg_champ_data to preserve the other source's data.
OPGG_EXCLUSIVE_FIELDS: frozenset[str] = frozenset({
    "op_score", "expected_op_score", "op_laning_score", "expected_laning_pct", "avg_vision_score",
    "avg_cs_per_game", "avg_gold_per_game",
})

DPM_EXCLUSIVE_FIELDS: frozenset[str] = frozenset({
    "dpm_score", "cs_at_15", "first_blood_rate", "solo_kills_per_game",
    "kill_participation_pct", "gold_share_pct", "vision_score_per_min",
})


class ChampionSplitStats(BaseModel):
    """
    Stats for one champion in one LoL split on one account.

    Source attribution:
      contested  — both "dpm" and "opgg" can populate; more-games-wins merge applies
      dpm        — populated only by DPM.lol scraper
      opgg       — populated only by OP.GG scraper
      riot_api   — populated only by Riot API (future)
    """
    lol_season: str                                  # e.g. "S2026" — key from SEASON_ORDER
    games: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: Optional[float] = None                 # recomputed from wins/losses        (contested)

    kills_per_game:   Optional[float] = None         # (contested)
    deaths_per_game:  Optional[float] = None         # (contested)
    assists_per_game: Optional[float] = None         # (contested)
    kda: Optional[float] = None                     # (K+A)/D float                      (contested)

    # Composite scores — source-exclusive, see ChampionEntry._SOURCE_EXCLUSIVE
    dpm_score: Optional[float] = None               # DPM.lol composite score per game    (dpm)
    op_score: Optional[float] = None                # OP.GG avg OP score per game         (opgg)
    expected_op_score: Optional[float] = None       # OP.GG matchup-adj expected OP score (opgg)
    op_laning_score: Optional[float] = None         # laning score, e.g. 51 from "51:49" (opgg)
    expected_laning_pct: Optional[float] = None     # matchup-adj expected laning win %   (opgg)

    # Cluster 1 — Laning / Early Game
    cs_per_min: Optional[float] = None              # CS per minute                       (contested)
    cs_at_15: Optional[float] = None                # absolute CS at 15 min, normalized   (dpm)
    csd_at_10: Optional[float] = None               # CS diff vs opponent at 10 min       (riot_api)
    early_deaths_per_game: Optional[float] = None   # deaths before 14 min per game       (riot_api)
    first_blood_rate: Optional[float] = None        # % of games with FB participation    (dpm)

    # Cluster 2 — Combat / Carry Impact
    dpm: Optional[float] = None                     # damage per minute                   (contested)
    damage_share_pct: Optional[float] = None        # % of team damage dealt              (contested)
    solo_kills_per_game: Optional[float] = None     # (dpm)
    kill_participation_pct: Optional[float] = None  # KP %                                (dpm)

    # Cluster 3 — Macro / Team Contribution
    gpm: Optional[float] = None                     # gold per minute                     (contested)
    avg_gold_per_game: Optional[float] = None       # avg total gold earned per game      (opgg)
    gold_share_pct: Optional[float] = None          # % of team gold earned               (dpm)
    objective_participation_pct: Optional[float] = None  # (riot_api)
    vision_score_per_min: Optional[float] = None    # vision score per minute             (dpm)
    avg_vision_score: Optional[float] = None        # raw vision score per game           (opgg)
    avg_cs_per_game: Optional[float] = None         # avg total CS per game               (opgg)

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

    # Fields owned exclusively by one source — never overwritten by another source,
    # even when the incoming source has more games. Maps field_name → owning_source.
    # Contested fields (both dpm and opgg can provide) are intentionally absent.
    _SOURCE_EXCLUSIVE: dict[str, str] = {
        # opgg-only
        "op_score":             "opgg",
        "expected_op_score":    "opgg",
        "op_laning_score":      "opgg",
        "expected_laning_pct":  "opgg",
        "avg_vision_score":     "opgg",
        "avg_cs_per_game":      "opgg",
        "avg_gold_per_game":    "opgg",
        # dpm-only
        "dpm_score":            "dpm",
        "cs_at_15":             "dpm",
        "first_blood_rate":     "dpm",
        "solo_kills_per_game":  "dpm",
        "kill_participation_pct": "dpm",
        "gold_share_pct":       "dpm",
        "vision_score_per_min": "dpm",
        # riot_api-only
        "csd_at_10":                    "riot_api",
        "early_deaths_per_game":        "riot_api",
        "objective_participation_pct":  "riot_api",
    }

    def merge_split(self, new: ChampionSplitStats) -> None:
        """
        Merge a new split into this entry's split list for the matching season.

        More games  → new source wins: overwrites all non-None fields (takes control).
        Same/fewer  → gap-fill only: writes fields that are currently None, never overwrites.
        No match    → append as new split.

        Source-exclusive fields are never overwritten by a different source regardless
        of game count. Contested fields (kda, dpm, cs_per_min, etc.) follow more-games-wins.

        source is set to "multi" when both DPM-exclusive and OPGG-exclusive fields are
        present in the merged result — signals that strip must preserve the other source.
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
            merged = existing.model_copy(update=patch)
            has_opgg = any(getattr(merged, f) is not None for f in OPGG_EXCLUSIVE_FIELDS)
            has_dpm  = any(getattr(merged, f) is not None for f in DPM_EXCLUSIVE_FIELDS)
            if has_opgg and has_dpm:
                merged = merged.model_copy(update={"source": "multi"})
            self.splits[i] = merged
            return
        self.splits.append(new)


class AccountQueueChampionPool(BaseModel):
    """Champion data for one queue type on one account."""
    champions: list[ChampionEntry] = []

    # DPM scrape state — DPM covers the current split only
    dpm_scrape_started_at: Optional[datetime] = None   # stamped before DPM navigation
    dpm_scraped_at: Optional[datetime] = None          # stamped only on successful DPM save
    dpm_scraped_for_split: Optional[str] = None        # split key active when DPM scrape completed
    dpm_last_scrape_error: Optional[str] = None        # set on DPM failure, cleared on success

    # OPGG scrape state — OPGG covers all historical splits
    opgg_scrape_started_at: Optional[datetime] = None  # stamped before OPGG navigation
    opgg_scraped_at: Optional[datetime] = None         # stamped only on successful OPGG save
    opgg_last_scrape_error: Optional[str] = None       # set on OPGG failure, cleared on success

    def dpm_complete(self, current_lol_split: str) -> bool:
        """True if DPM data was successfully scraped for the current split."""
        return (
            self.dpm_scraped_at is not None
            and self.dpm_last_scrape_error is None
            and self.dpm_scraped_for_split == current_lol_split
        )

    def opgg_complete(self) -> bool:
        """True if OPGG champion data was successfully scraped (covers all historical splits)."""
        return (
            self.opgg_scraped_at is not None
            and self.opgg_last_scrape_error is None
        )

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
