"""Tests for pool-level helpers in pv_compute.py."""

from datetime import datetime, timezone

import pytest

from quartz.models.player_profile import PlayerProfile, SeasonData
from quartz.models.pv_model import ConfidenceThresholdStrategy, PVWeights
from quartz.models.rank_data import AggregatedRankData, AggregatedSplitRank, PlayerStats
from quartz.pv_compute import (
    _wilson_lower,
    compute_n_historical_thresholds,
    compute_N_threshold,
    compute_pv,
    compute_realistic_max,
    evaluate_eligibility,
)
from quartz.tournament_config import EligibilityConfig


def _profile(
    discord_id: str = "p",
    current_rank: str = "Gold 1",
    peak_rank: str = "Gold 1",
    games_by_season: dict | None = None,
    inhouse_wins: int | None = None,
    inhouse_losses: int | None = None,
    tournament_round: str = "GCS-S4",
) -> PlayerProfile:
    games_by_season = games_by_season or {}
    solo_splits = [
        AggregatedSplitRank(
            season=season,
            split_rank=current_rank if season == "S2026" else None,
            peak_rank=peak_rank,
            wins=g,
            losses=g,
            win_rate=50.0,
        )
        for season, g in games_by_season.items()
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


# ── _wilson_lower ───────────────────────────────────────────────────────────

def test_wilson_lower_zero_total():
    assert _wilson_lower(0, 0) == 0.0


def test_wilson_lower_perfect_record():
    lb = _wilson_lower(100, 100)
    assert 0.9 < lb <= 1.0


def test_wilson_lower_50pct_small_sample():
    lb = _wilson_lower(5, 10)
    assert 0.0 < lb < 0.5


# ── compute_N_threshold ─────────────────────────────────────────────────────

def test_n_threshold_override():
    weights = PVWeights(n_override=99)
    result = compute_N_threshold([], weights, "S2026")
    assert result == 99


def test_n_threshold_clamps_override_to_1():
    weights = PVWeights(n_override=0)
    result = compute_N_threshold([], weights, "S2026")
    assert result == 1


def test_n_threshold_fallback_when_no_games():
    weights = PVWeights()
    result = compute_N_threshold([], weights, "S2026")
    assert result == 50  # _FALLBACK_N


def test_n_threshold_median_strategy():
    # _profile sets wins=g AND losses=g, so total games = 2*g per profile
    profiles = [
        _profile("a", games_by_season={"S2026": 50}),   # 100 total games
        _profile("b", games_by_season={"S2026": 100}),  # 200 total games
        _profile("c", games_by_season={"S2026": 200}),  # 400 total games
    ]
    weights = PVWeights(confidence_strategy=ConfidenceThresholdStrategy.MEDIAN)
    result = compute_N_threshold(profiles, weights, "S2026")
    assert result == 200  # median of [100, 200, 400]


def test_n_threshold_p25_strategy():
    profiles = [
        _profile("a", games_by_season={"S2026": 50}),
        _profile("b", games_by_season={"S2026": 100}),
        _profile("c", games_by_season={"S2026": 200}),
        _profile("d", games_by_season={"S2026": 400}),
    ]
    weights = PVWeights(confidence_strategy=ConfidenceThresholdStrategy.P25)
    result = compute_N_threshold(profiles, weights, "S2026")
    assert result >= 1


def test_n_threshold_mean_1sd_strategy():
    profiles = [
        _profile("a", games_by_season={"S2026": 50}),
        _profile("b", games_by_season={"S2026": 100}),
        _profile("c", games_by_season={"S2026": 200}),
    ]
    weights = PVWeights(confidence_strategy=ConfidenceThresholdStrategy.MEAN_1SD)
    result = compute_N_threshold(profiles, weights, "S2026")
    assert result >= 1


def test_n_threshold_skips_profiles_with_no_stats():
    profiles = [
        PlayerProfile(
            discord_id="nodata",
            season_data=[],
            stats=None,
            created_at=datetime.now(timezone.utc),
            last_updated_at=datetime.now(timezone.utc),
        ),
        _profile("real", games_by_season={"S2026": 80}),  # wins=80 + losses=80 = 160 total
    ]
    weights = PVWeights()
    result = compute_N_threshold(profiles, weights, "S2026")
    assert result == 160  # only "real" contributes; total = wins + losses = 160


# ── compute_n_historical_thresholds ────────────────────────────────────────

def test_n_hist_no_data_for_season():
    weights = PVWeights(n_historical_floor=30)
    result = compute_n_historical_thresholds([], weights, ["S2025"])
    assert result["S2025"] == 30  # falls back to floor


def test_n_hist_respects_floor():
    profiles = [_profile("a", games_by_season={"S2025": 5})]
    weights = PVWeights(n_historical_floor=30)
    result = compute_n_historical_thresholds(profiles, weights, ["S2025"])
    assert result["S2025"] >= 30


def test_n_hist_multiple_seasons():
    profiles = [
        _profile("a", games_by_season={"S2025": 100, "S2024 S3": 60}),
        _profile("b", games_by_season={"S2025": 200}),
    ]
    weights = PVWeights(n_historical_floor=10)
    result = compute_n_historical_thresholds(profiles, weights, ["S2025", "S2024 S3"])
    assert "S2025" in result
    assert "S2024 S3" in result
    assert result["S2025"] >= result["S2024 S3"]


def test_n_hist_p25_strategy():
    profiles = [
        _profile(f"p{i}", games_by_season={"S2025": (i + 1) * 25}) for i in range(4)
    ]
    weights = PVWeights(
        confidence_strategy=ConfidenceThresholdStrategy.P25,
        n_historical_floor=10,
    )
    result = compute_n_historical_thresholds(profiles, weights, ["S2025"])
    assert result["S2025"] >= 10


def test_n_hist_mean_1sd_strategy():
    profiles = [
        _profile("a", games_by_season={"S2025": 50}),
        _profile("b", games_by_season={"S2025": 150}),
    ]
    weights = PVWeights(
        confidence_strategy=ConfidenceThresholdStrategy.MEAN_1SD,
        n_historical_floor=1,
    )
    result = compute_n_historical_thresholds(profiles, weights, ["S2025"])
    assert result["S2025"] >= 1


# ── evaluate_eligibility ────────────────────────────────────────────────────

def test_eligibility_no_config_always_eligible():
    profile = _profile(games_by_season={"S2026": 5})
    assert evaluate_eligibility(profile, None) is True


def test_eligibility_no_stats_fails():
    profile = PlayerProfile(
        discord_id="nodata",
        season_data=[],
        stats=None,
        created_at=datetime.now(timezone.utc),
        last_updated_at=datetime.now(timezone.utc),
    )
    cfg = EligibilityConfig(primary_split="S2026", primary_min_games=30)
    assert evaluate_eligibility(profile, cfg) is False


def test_eligibility_primary_games_met():
    profile = _profile(games_by_season={"S2026": 50})
    cfg = EligibilityConfig(primary_split="S2026", primary_min_games=30)
    assert evaluate_eligibility(profile, cfg) is True


def test_eligibility_primary_not_met_backup_met():
    profile = _profile(games_by_season={"S2026": 10, "S2025": 60})
    cfg = EligibilityConfig(
        primary_split="S2026", primary_min_games=30,
        backup_split="S2025", backup_min_games=50,
    )
    assert evaluate_eligibility(profile, cfg) is True


def test_eligibility_neither_met():
    profile = _profile(games_by_season={"S2026": 5, "S2025": 10})
    cfg = EligibilityConfig(
        primary_split="S2026", primary_min_games=30,
        backup_split="S2025", backup_min_games=50,
    )
    assert evaluate_eligibility(profile, cfg) is False


def test_eligibility_primary_not_met_no_backup():
    profile = _profile(games_by_season={"S2026": 5})
    cfg = EligibilityConfig(primary_split="S2026", primary_min_games=30)
    assert evaluate_eligibility(profile, cfg) is False


# ── compute_realistic_max ───────────────────────────────────────────────────

def test_realistic_max_override():
    weights = PVWeights(realistic_max_override=0.90)
    result = compute_realistic_max([], weights, "GCS-S4")
    assert result == pytest.approx(0.90)


def test_realistic_max_fallback_when_no_inhouse_data():
    profile = _profile()  # no inhouse data
    weights = PVWeights()
    result = compute_realistic_max([profile], weights, "GCS-S4")
    assert result == pytest.approx(0.75)  # _FALLBACK_REALISTIC_MAX


def test_realistic_max_computed_from_pool():
    # 18W-2L on inhouse → high Wilson LB
    profile = _profile(inhouse_wins=18, inhouse_losses=2)
    weights = PVWeights(min_games_threshold=5)
    result = compute_realistic_max([profile], weights, "GCS-S4")
    assert result > 0.75


def test_realistic_max_ignores_low_game_accounts():
    profile = _profile(inhouse_wins=2, inhouse_losses=0)
    weights = PVWeights(min_games_threshold=10)
    result = compute_realistic_max([profile], weights, "GCS-S4")
    assert result == pytest.approx(0.75)  # below threshold → fallback


# ── compute_pv — additional branches ───────────────────────────────────────

def test_compute_pv_with_f1_historical_data():
    profile = PlayerProfile(
        discord_id="histplayer",
        season_data=[SeasonData(season="GCS-S4")],
        stats=PlayerStats(
            rank_data=AggregatedRankData(solo_splits=[
                AggregatedSplitRank(season="S2026", split_rank="Gold 1", peak_rank="Gold 1", wins=100, losses=50, win_rate=66.7),
                AggregatedSplitRank(season="S2025", peak_rank="Platinum 2", wins=200, losses=100, win_rate=66.7),
            ]),
            current_rank="Gold 1",
            all_time_peak_rank="Platinum 2",
        ),
        created_at=datetime.now(timezone.utc),
        last_updated_at=datetime.now(timezone.utc),
    )
    weights = PVWeights()
    result = compute_pv(profile, weights, N_threshold=100, tournament_round="GCS-S4", current_lol_split="S2026")
    assert result.point_value is not None
    assert result.features.historical_score is not None
    assert result.features.splits_used == 1
    assert result.features.f1_confidence is not None


def test_compute_pv_no_atp_uses_current_rank_with_full_confidence():
    profile = PlayerProfile(
        discord_id="noatp",
        season_data=[SeasonData(season="GCS-S4")],
        stats=PlayerStats(
            rank_data=AggregatedRankData(solo_splits=[
                AggregatedSplitRank(season="S2026", split_rank="Silver 1", peak_rank=None, wins=10, losses=10, win_rate=50.0),
            ]),
            current_rank="Silver 1",
            all_time_peak_rank=None,
        ),
        created_at=datetime.now(timezone.utc),
        last_updated_at=datetime.now(timezone.utc),
    )
    weights = PVWeights(w_historical=0.0, w_current=1.0)
    result = compute_pv(profile, weights, N_threshold=50, tournament_round="GCS-S4", current_lol_split="S2026")
    assert result.point_value is not None
    assert result.features.confidence == pytest.approx(1.0)


def test_compute_pv_stated_rank_diff_computed():
    profile = PlayerProfile(
        discord_id="statedrank",
        season_data=[SeasonData(
            season="GCS-S4",
            stated_current_rank="Diamond 4",
        )],
        stats=PlayerStats(
            rank_data=AggregatedRankData(solo_splits=[
                AggregatedSplitRank(season="S2026", split_rank="Gold 1", peak_rank="Diamond 4", wins=100, losses=50, win_rate=66.7),
            ]),
            current_rank="Gold 1",
            all_time_peak_rank="Diamond 4",
        ),
        created_at=datetime.now(timezone.utc),
        last_updated_at=datetime.now(timezone.utc),
    )
    result = compute_pv(profile, PVWeights(), N_threshold=50, tournament_round="GCS-S4", current_lol_split="S2026")
    assert result.features.stated_rank_diff is not None
    # stated_rank_diff = rank_score(stated) - rank_score(current)
    # Diamond 4 is stronger than Gold 1 → lower score → negative diff
    assert result.features.stated_rank_diff < 0
