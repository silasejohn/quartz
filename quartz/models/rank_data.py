"""
Rank data models for the Quartz pipeline.

AccountRankData  — raw scraped rank data per account (solo + flex splits), stored on Account
PlayerStats      — aggregated/computed data across all accounts, stored on PlayerProfile
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

from quartz.models.champion_data import AggregatedChampionPool
from quartz.models.pv_model import ComputedPV

# ------------------------------------------------------------------
# Account-level raw rank data (one per account, populated by OPGG_SCRAPE_RANK)
# ------------------------------------------------------------------

class SplitRankEntry(BaseModel):
    """Rank data for a single LoL season/split for one account."""
    season: str                             # e.g. "S2026" — key from SEASON_ORDER
    peak_rank: Optional[str] = None         # "Diamond 1 45 LP" or "Master 120 LP"
    split_rank: Optional[str] = None        # final rank for past splits; current rank for active split
    wins: Optional[int] = None              # solo/flex queue wins for this split
    losses: Optional[int] = None            # solo/flex queue losses for this split
    win_rate: Optional[float] = None        # wins / (wins + losses) * 100, rounded to 1dp


class AccountRankData(BaseModel):
    """All scraped rank data for one account across all tracked splits, separated by queue."""
    solo_splits: list[SplitRankEntry] = []   # solo queue rank history
    flex_splits: list[SplitRankEntry] = []   # flex queue rank history
    scraped_at: Optional[datetime] = None
    source: str = "opgg"

    def get_split(self, season: str, queue: str = "solo") -> Optional[SplitRankEntry]:
        """Return the SplitRankEntry for a given season and queue, or None if not present."""
        splits = self.solo_splits if queue == "solo" else self.flex_splits
        return next((s for s in splits if s.season == season), None)

    def upsert_split(self, entry: SplitRankEntry, queue: str = "solo") -> None:
        """Replace the existing entry for that season and queue, or append if new."""
        splits = self.solo_splits if queue == "solo" else self.flex_splits
        for i, s in enumerate(splits):
            if s.season == entry.season:
                splits[i] = entry
                return
        splits.append(entry)


# ------------------------------------------------------------------
# Profile-level enrichment (aggregated across all accounts)
# Populated by AGGREGATE_RANK_STATS and future tasks
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
    """Aggregated rank data across all accounts, both queues, all splits."""
    solo_splits: list[AggregatedSplitRank] = []
    flex_splits: list[AggregatedSplitRank] = []
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


class PlayerStats(BaseModel):
    """
    Aggregated, derived section of PlayerProfile. Populated incrementally by pipeline tasks.

    rank_data          <- compute_enrichment() (aggregated from Account.rank_data)
    all_time_peak_rank <- compute_enrichment() (best peak_rank across all accounts + all splits)
    current_rank       <- compute_enrichment() (best solo split_rank for lol_season across accounts)
    champion_pool      <- DPM_SCRAPE_CHAMP / OPGG_SCRAPE_CHAMP
    computed_pv        <- PV_COMPUTE
    """
    rank_data: Optional[AggregatedRankData] = None
    all_time_peak_rank: Optional[str] = None
    current_rank: Optional[str] = None
    champion_pool: Optional[AggregatedChampionPool] = None
    computed_pv: Optional["ComputedPV"] = None


def compute_enrichment(accounts: list, lol_season: str) -> "PlayerStats":
    """
    Aggregate solo queue rank data across ALL accounts (including archived) and populate PlayerStats.

    For each season: keeps the best peak_rank and split_rank (via rank_score), sums wins/losses.
    Archived accounts are included — they may hold the player's best historical rank.
    Flex queue data is aggregated separately.

    [param] accounts:   list of Account objects (from PlayerProfile.accounts)
    [param] lol_season: current LoL season key e.g. "S2026" — from TournamentConfig.lol_season
    """
    from quartz.constants import SEASON_ORDER, rank_score
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

    def aggregate_splits(
        accounts: list,
        queue: str,
    ) -> list[AggregatedSplitRank]:
        agg_by_season: dict[str, AggregatedSplitRank] = {}
        for account in accounts:
            if not account.rank_data:
                continue
            splits = account.rank_data.solo_splits if queue == "solo" else account.rank_data.flex_splits
            for split in splits:
                if split.season not in agg_by_season:
                    agg_by_season[split.season] = AggregatedSplitRank(season=split.season)
                agg = agg_by_season[split.season]
                agg.peak_rank  = better_rank(agg.peak_rank,  split.peak_rank)
                agg.split_rank = better_rank(agg.split_rank, split.split_rank)
                if split.wins is not None:
                    agg.wins = (agg.wins or 0) + split.wins
                if split.losses is not None:
                    agg.losses = (agg.losses or 0) + split.losses

        for agg in agg_by_season.values():
            total = (agg.wins or 0) + (agg.losses or 0)
            agg.win_rate = round(agg.wins / total * 100, 1) if total > 0 and agg.wins else None

        return sorted(
            agg_by_season.values(),
            key=lambda s: SEASON_ORDER.index(s.season) if s.season in SEASON_ORDER else 999,
        )

    solo_splits = aggregate_splits(accounts, "solo")
    flex_splits = aggregate_splits(accounts, "flex")

    rank_data = AggregatedRankData(
        solo_splits=solo_splits,
        flex_splits=flex_splits,
        computed_at=datetime.now(timezone.utc),
    )

    # All-time peak: best peak_rank across every solo split
    all_time_peak: Optional[str] = None
    for agg in solo_splits:
        all_time_peak = better_rank(all_time_peak, agg.peak_rank)

    # Current rank: solo split_rank for the current LoL season
    current_agg = next((s for s in solo_splits if s.season == lol_season), None)
    current_rank = current_agg.split_rank if current_agg else None

    return PlayerStats(
        rank_data=rank_data,
        all_time_peak_rank=all_time_peak,
        current_rank=current_rank,
    )
