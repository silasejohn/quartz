"""Tests for compute_enrichment() — rank aggregation across accounts."""

from datetime import datetime, timezone
import pytest

from quartz.models.rank_data import (
    AccountRankData, SplitRankEntry, compute_enrichment,
)
from quartz.models.player_profile import Account


def _account(riot_id: str, solo_splits: list[SplitRankEntry]) -> Account:
    return Account(
        riot_id=riot_id,
        rank_data=AccountRankData(solo_splits=solo_splits, scraped_at=datetime.now(timezone.utc)),
    )


def test_single_account_current_rank():
    acc = _account("Player#NA1", [
        SplitRankEntry(season="S2026", split_rank="Diamond 2", peak_rank="Diamond 1"),
    ])
    stats = compute_enrichment([acc], lol_season="S2026")
    assert stats.current_rank == "Diamond 2"
    assert stats.all_time_peak_rank == "Diamond 1"


def test_best_rank_wins_across_accounts():
    acc1 = _account("Main#NA1", [
        SplitRankEntry(season="S2026", split_rank="Gold 1", peak_rank="Platinum 2"),
    ])
    acc2 = _account("Smurf#NA1", [
        SplitRankEntry(season="S2026", split_rank="Diamond 4", peak_rank="Diamond 2"),
    ])
    stats = compute_enrichment([acc1, acc2], lol_season="S2026")
    assert stats.current_rank == "Diamond 4"
    assert stats.all_time_peak_rank == "Diamond 2"


def test_archived_account_contributes_to_peak():
    main = _account("Main#NA1", [
        SplitRankEntry(season="S2026", split_rank="Platinum 1", peak_rank="Platinum 1"),
    ])
    archived = Account(
        riot_id="Old#NA1",
        archived=True,
        rank_data=AccountRankData(solo_splits=[
            SplitRankEntry(season="S2025", split_rank="Diamond 1", peak_rank="Master 200 LP"),
        ]),
    )
    stats = compute_enrichment([main, archived], lol_season="S2026")
    assert stats.all_time_peak_rank == "Master 200 LP"


def test_wins_summed_across_accounts():
    acc1 = _account("A#NA1", [SplitRankEntry(season="S2026", split_rank="Gold 1", wins=50, losses=40)])
    acc2 = _account("B#NA1", [SplitRankEntry(season="S2026", split_rank="Gold 2", wins=30, losses=20)])
    stats = compute_enrichment([acc1, acc2], lol_season="S2026")
    s2026 = next(s for s in stats.rank_data.solo_splits if s.season == "S2026")
    assert s2026.wins == 80
    assert s2026.losses == 60


def test_no_accounts_returns_empty_stats():
    stats = compute_enrichment([], lol_season="S2026")
    assert stats.current_rank is None
    assert stats.all_time_peak_rank is None
    assert stats.rank_data.solo_splits == []


def test_unranked_not_counted_as_best():
    acc1 = _account("A#NA1", [SplitRankEntry(season="S2026", split_rank="Unranked", peak_rank="Unranked")])
    acc2 = _account("B#NA1", [SplitRankEntry(season="S2026", split_rank="Silver 2", peak_rank="Gold 1")])
    stats = compute_enrichment([acc1, acc2], lol_season="S2026")
    assert stats.current_rank == "Silver 2"
    assert stats.all_time_peak_rank == "Gold 1"
