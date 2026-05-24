"""
Rank data models for the Quartz pipeline.

AccountRankData  — raw scraped rank data per account (all splits), stored on Account
PlayerEnrichment — aggregated/computed data across all accounts, stored on PlayerProfile
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel

from quartz.models.pv_model import ComputedPV


# ------------------------------------------------------------------
# Account-level raw rank data (one per account, populated by OPGG_ENRICH_RANK)
# ------------------------------------------------------------------

class SplitRankEntry(BaseModel):
    """Rank data for a single season/split for one account."""
    season: str                             # e.g. "S2025" — key from SEASON_ORDER
    peak_rank: Optional[str] = None         # "Diamond 1 45 LP" or "Master 120 LP"
    split_rank: Optional[str] = None        # final rank for past splits; current rank for active split
    wins: Optional[int] = None              # solo queue wins for this split
    losses: Optional[int] = None            # solo queue losses for this split
    win_rate: Optional[float] = None        # wins / (wins + losses) * 100, rounded to 1dp


class AccountRankData(BaseModel):
    """All scraped rank data for one account across all tracked splits."""
    splits: list[SplitRankEntry] = []
    scraped_at: Optional[datetime] = None
    source: str = "opgg"

    def get_split(self, season: str) -> Optional[SplitRankEntry]:
        """Return the SplitRankEntry for a given season, or None if not present."""
        return next((s for s in self.splits if s.season == season), None)

    def upsert_split(self, entry: SplitRankEntry) -> None:
        """Replace the existing entry for that season, or append if new."""
        for i, s in enumerate(self.splits):
            if s.season == entry.season:
                self.splits[i] = entry
                return
        self.splits.append(entry)


# ------------------------------------------------------------------
# Profile-level enrichment (aggregated across all accounts)
# Populated by CALCULATE_RANK_STATS and future tasks
# ------------------------------------------------------------------

class AggregatedSplitRank(BaseModel):
    """Best rank across all accounts for a single season/split."""
    season: str
    peak_rank: Optional[str] = None         # best peak rank across all accounts
    split_rank: Optional[str] = None        # best split rank across all accounts
    wins: Optional[int] = None              # total wins across all accounts for this split
    losses: Optional[int] = None            # total losses across all accounts for this split
    win_rate: Optional[float] = None        # combined win rate across all accounts


class AggregatedRankData(BaseModel):
    """Aggregated rank data across all accounts, all splits."""
    splits: list[AggregatedSplitRank] = []
    computed_at: Optional[datetime] = None


def merge_split_entries(existing: "SplitRankEntry", scraped: "SplitRankEntry") -> "SplitRankEntry":
    """
    Merge two SplitRankEntries for the same historical season.

    For split_rank and peak_rank: keep whichever has the better (lower) rank score.
    If new data is None, existing value is preserved. If existing is None, new value is used.
    For wins/losses/win_rate: use scraped value if not None (final for past splits).

    Not scraper-specific — any source producing SplitRankEntry data should use this.
    """
    from quartz.constants import rank_score

    def better_rank(old: Optional[str], new: Optional[str]) -> Optional[str]:
        if new is None:
            return old
        if old is None:
            return new
        old_score = rank_score(old)
        new_score = rank_score(new)
        if old_score is None:
            return new
        if new_score is None:
            return old
        return new if new_score < old_score else old

    return SplitRankEntry(
        season=existing.season,
        split_rank=better_rank(existing.split_rank, scraped.split_rank),
        peak_rank=better_rank(existing.peak_rank, scraped.peak_rank),
        wins=scraped.wins if scraped.wins is not None else existing.wins,
        losses=scraped.losses if scraped.losses is not None else existing.losses,
        win_rate=scraped.win_rate if scraped.win_rate is not None else existing.win_rate,
    )


class PlayerEnrichment(BaseModel):
    """
    Umbrella enrichment section on PlayerProfile.
    Populated incrementally as pipeline tasks run.

    rank_data         <- compute_enrichment() (aggregated from Account.rank_data)
    all_time_peak_rank<- compute_enrichment() (best peak_rank across all accounts + all splits)
    current_rank      <- compute_enrichment() (best split_rank for S2026 across all accounts)
    champion_pool     <- OPGG_CHAMP / DPM_CHAMP  (stub)
    computed_pv       <- PV_COMPUTE               (stub)
    """
    rank_data: Optional[AggregatedRankData] = None
    all_time_peak_rank: Optional[str] = None    # best peak_rank across all accounts + all splits
    current_rank: Optional[str] = None           # best split_rank for SEASON_ORDER[0] across all accounts
    champion_pool: None = None                   # stub — implemented when OPGG_CHAMP task is built
    computed_pv: Optional["ComputedPV"] = None   # populated by PV_COMPUTE task


def compute_enrichment(accounts: list) -> "PlayerEnrichment":
    """
    Aggregate rank data across ALL accounts (including archived) and populate PlayerEnrichment.

    For each season: keeps the best peak_rank and split_rank (via rank_score), sums wins/losses.
    Archived accounts are included — they may hold the player's best historical rank.

    [param] accounts: list of Account objects (from PlayerProfile.accounts)
    """
    from quartz.constants import rank_score, SEASON_ORDER

    def better_rank(old: Optional[str], new: Optional[str]) -> Optional[str]:
        if new is None or new == "Unranked":
            return old
        if old is None or old == "Unranked":
            return new
        old_score = rank_score(old)
        new_score = rank_score(new)
        if old_score is None:
            return new
        if new_score is None:
            return old
        return new if new_score < old_score else old

    agg_by_season: dict[str, AggregatedSplitRank] = {}

    for account in accounts:
        if not account.rank_data:
            continue
        for split in account.rank_data.splits:
            if split.season not in agg_by_season:
                agg_by_season[split.season] = AggregatedSplitRank(season=split.season)
            agg = agg_by_season[split.season]
            agg.peak_rank  = better_rank(agg.peak_rank,  split.peak_rank)
            agg.split_rank = better_rank(agg.split_rank, split.split_rank)
            if split.wins is not None:
                agg.wins = (agg.wins or 0) + split.wins
            if split.losses is not None:
                agg.losses = (agg.losses or 0) + split.losses

    # Recompute combined win_rate per season
    for agg in agg_by_season.values():
        total = (agg.wins or 0) + (agg.losses or 0)
        agg.win_rate = round(agg.wins / total * 100, 1) if total > 0 and agg.wins else None

    # Sort most-recent-first per SEASON_ORDER
    splits = sorted(
        agg_by_season.values(),
        key=lambda s: SEASON_ORDER.index(s.season) if s.season in SEASON_ORDER else 999,
    )

    rank_data = AggregatedRankData(splits=splits, computed_at=datetime.now(timezone.utc))

    # All-time peak: best peak_rank across every aggregated split
    all_time_peak: Optional[str] = None
    for agg in splits:
        all_time_peak = better_rank(all_time_peak, agg.peak_rank)

    # Current rank: split_rank for the current LoL season
    current_season = SEASON_ORDER[0]
    current_agg = agg_by_season.get(current_season)
    current_rank = current_agg.split_rank if current_agg else None

    return PlayerEnrichment(
        rank_data=rank_data,
        all_time_peak_rank=all_time_peak,
        current_rank=current_rank,
    )
