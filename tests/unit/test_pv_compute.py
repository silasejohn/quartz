"""Tests for compute_pv() — PV formula correctness."""

from datetime import datetime, timezone

import pytest

from quartz.models.player_profile import PlayerProfile, SeasonData
from quartz.models.pv_model import PVWeights
from quartz.models.rank_data import AggregatedRankData, AggregatedSplitRank, PlayerStats
from quartz.pv_compute import compute_pv


def _make_profile(
    discord_id: str = "testplayer",
    current_rank: str = "Gold 1",
    peak_rank: str = "Gold 1",
    f1_rank: str = "Gold 1",
    tournament_round: str = "GCS-S4",
    lol_season: str = "S2026",
    games: int = 100,
    inhouse_wins: int = None,
    inhouse_losses: int = None,
) -> PlayerProfile:
    solo_splits = [
        AggregatedSplitRank(season=lol_season, split_rank=current_rank, peak_rank=peak_rank, wins=games, losses=games),
        AggregatedSplitRank(season="S2025", peak_rank=f1_rank),
    ]
    return PlayerProfile(
        discord_id=discord_id,
        season_data=[SeasonData(
            season=tournament_round,
            inhouse_wins=inhouse_wins,
            inhouse_losses=inhouse_losses,
        )],
        stats=PlayerStats(
            rank_data=AggregatedRankData(solo_splits=solo_splits),
            current_rank=current_rank,
            all_time_peak_rank=peak_rank,
        ),
        created_at=datetime.now(timezone.utc),
        last_updated_at=datetime.now(timezone.utc),
    )


def test_flagged_when_no_data():
    profile = PlayerProfile(
        discord_id="nodata",
        season_data=[SeasonData(season="GCS-S4")],
        stats=PlayerStats(),
        created_at=datetime.now(timezone.utc),
        last_updated_at=datetime.now(timezone.utc),
    )
    result = compute_pv(profile, PVWeights(), N_threshold=50, tournament_round="GCS-S4", current_lol_split="S2026")
    assert result.flag_reason == "no_data"
    assert result.point_value is None
    assert result.pv_rank_only is None


def test_challenger_lower_pv_than_iron():
    chall = _make_profile(current_rank="Challenger 1000 LP", peak_rank="Challenger 1000 LP", f1_rank="Challenger 1000 LP")
    iron  = _make_profile(current_rank="Iron 4", peak_rank="Iron 4", f1_rank="Iron 4")
    weights = PVWeights()
    chall_pv = compute_pv(chall, weights, N_threshold=50, tournament_round="GCS-S4", current_lol_split="S2026")
    iron_pv  = compute_pv(iron,  weights, N_threshold=50, tournament_round="GCS-S4", current_lol_split="S2026")
    assert chall_pv.point_value < iron_pv.point_value


def test_inhouse_bonus_reduces_pv():
    base    = _make_profile()
    boosted = _make_profile(inhouse_wins=20, inhouse_losses=3)
    weights = PVWeights()
    N = 50
    base_result    = compute_pv(base,    weights, N, "GCS-S4", "S2026", realistic_max=0.85)
    boosted_result = compute_pv(boosted, weights, N, "GCS-S4", "S2026", realistic_max=0.85)
    assert boosted_result.point_value < base_result.point_value


def test_low_games_confidence_regresses_to_peak():
    weights = PVWeights(w_historical=0.0, w_current=1.0)  # F2 only
    profile = _make_profile(current_rank="Silver 1", peak_rank="Diamond 2", games=0)
    result = compute_pv(profile, weights, N_threshold=50, tournament_round="GCS-S4", current_lol_split="S2026")
    # With 0 games, F2 should regress entirely to peak (Diamond 2), not current (Silver 1)
    assert result.features.confidence == pytest.approx(0.0, abs=0.01)
    assert result.features.default_rank_used == "Diamond 2"
