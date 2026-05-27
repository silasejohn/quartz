"""
Unit tests for F5/F6 champion pool PV modifiers.

Covers:
  - tier_width_at_pv()          — correct tier span at various PV levels, edge cases
  - compute_champion_modifier() — bracket logic, games-weighting, tanh saturation, empty/sparse pools
  - compute_pv() integration    — F5/F6 wired correctly into final PV formula
"""

import math
from datetime import datetime, timezone

import pytest

from quartz.models.champion_data import (
    AccountChampionData,
    AccountQueueChampionPool,
    ChampionEntry,
    ChampionSplitStats,
)
from quartz.models.player_profile import Account, PlayerProfile, SeasonData
from quartz.models.pv_model import PVWeights
from quartz.models.rank_data import AggregatedRankData, AggregatedSplitRank, PlayerStats
from quartz.pv_compute import _DPM_SCORE_BASELINE, compute_champion_modifier, compute_pv, tier_width_at_pv


# ------------------------------------------------------------------
# Fixtures / helpers
# ------------------------------------------------------------------

SPLIT = "S2026"
ROUND = "GCS-S4"


def _entry(champion: str, games: int, dpm_score: float, split: str = SPLIT) -> ChampionEntry:
    """Build a ChampionEntry with role=ALL and DPM data for the given split."""
    return ChampionEntry(
        champion=champion,
        role="ALL",
        splits=[ChampionSplitStats(
            lol_season=split,
            wins=games,
            losses=0,
            games=games,
            dpm_score=dpm_score,
            source="dpm",
        )],
    )


def _pool(*entries: ChampionEntry) -> AccountQueueChampionPool:
    return AccountQueueChampionPool(champions=list(entries))


def _profile_with_champ(
    solo_pool: AccountQueueChampionPool | None = None,
    flex_pool: AccountQueueChampionPool | None = None,
    current_rank: str = "Gold 1",
    peak_rank: str = "Gold 1",
    games: int = 100,
) -> PlayerProfile:
    """Profile with rank data + optional champion pool via accounts."""
    champ_data = None
    if solo_pool is not None or flex_pool is not None:
        champ_data = AccountChampionData(
            solo=solo_pool or AccountQueueChampionPool(),
            flex=flex_pool or AccountQueueChampionPool(),
        )

    account = Account(
        riot_id="TestPlayer#NA1",
        champion_data=champ_data,
    )

    solo_splits = [
        AggregatedSplitRank(season=SPLIT, split_rank=current_rank, peak_rank=peak_rank, wins=games, losses=games),
        AggregatedSplitRank(season="S2025", peak_rank=peak_rank),
    ]
    return PlayerProfile(
        discord_id="testplayer",
        accounts=[account],
        season_data=[SeasonData(season=ROUND)],
        stats=PlayerStats(
            rank_data=AggregatedRankData(solo_splits=solo_splits),
            current_rank=current_rank,
            all_time_peak_rank=peak_rank,
        ),
        created_at=datetime.now(timezone.utc),
        last_updated_at=datetime.now(timezone.utc),
    )


# ------------------------------------------------------------------
# tier_width_at_pv
# ------------------------------------------------------------------

class TestTierWidthAtPv:
    def test_gold_tier(self):
        from quartz.constants import RANK_POINTS
        expected = RANK_POINTS["Gold 4"] - RANK_POINTS["Gold 1"]
        assert tier_width_at_pv(62.1) == pytest.approx(expected, abs=0.01)  # Gold 2

    def test_diamond_tier(self):
        from quartz.constants import RANK_POINTS
        expected = RANK_POINTS["Diamond 4"] - RANK_POINTS["Diamond 1"]
        assert tier_width_at_pv(27.0) == pytest.approx(expected, abs=0.01)  # Diamond 2

    def test_apex_range_uses_diamond(self):
        """PV below Diamond 1 (apex zone) should return Diamond tier width."""
        diamond_width = tier_width_at_pv(22.7)  # exactly Diamond 1
        apex_width = tier_width_at_pv(5.0)      # deep Challenger
        assert apex_width == pytest.approx(diamond_width, abs=0.01)

    def test_iron_plateau_falls_back_to_bronze(self):
        """Iron ranks are all PV=85 (flat). Should fall back to Bronze tier width."""
        from quartz.constants import RANK_POINTS
        expected = RANK_POINTS["Bronze 4"] - RANK_POINTS["Bronze 1"]
        assert tier_width_at_pv(85.0) == pytest.approx(expected, abs=0.01)

    def test_width_increases_at_higher_ranks(self):
        """Diamond tier should be wider than Gold tier (rank model gets steeper at top)."""
        assert tier_width_at_pv(27.0) > tier_width_at_pv(62.1)

    def test_positive_for_all_tiers(self):
        for pv in [5.0, 22.7, 34.5, 46.8, 57.3, 62.1, 68.1, 75.2, 83.1]:
            assert tier_width_at_pv(pv) > 0


# ------------------------------------------------------------------
# compute_champion_modifier — pool construction
# ------------------------------------------------------------------

class TestComputeChampionModifier:
    W = PVWeights()
    RANK_PV = 62.1  # Gold 2

    def test_empty_pool_returns_zero(self):
        assert compute_champion_modifier(_pool(), self.RANK_PV, SPLIT, self.W) == 0.0

    def test_below_games_min_returns_zero(self):
        pool = _pool(_entry("Caitlyn", games=2, dpm_score=7.0))  # games_min=5
        assert compute_champion_modifier(pool, self.RANK_PV, SPLIT, self.W) == 0.0

    def test_average_pool_near_zero(self):
        """All dpm_scores = baseline → residuals = 0 → modifier = 0."""
        pool = _pool(
            _entry("Caitlyn", 80, _DPM_SCORE_BASELINE),
            _entry("Jinx",    40, _DPM_SCORE_BASELINE),
            _entry("Ezreal",  20, _DPM_SCORE_BASELINE),
        )
        result = compute_champion_modifier(pool, self.RANK_PV, SPLIT, self.W)
        assert result == pytest.approx(0.0, abs=1e-9)

    def test_above_average_pool_positive(self):
        """Above-baseline dpm_scores → positive modifier (lowers PV = stronger)."""
        pool = _pool(
            _entry("Caitlyn", 80, 7.0),
            _entry("Jinx",    40, 6.5),
        )
        assert compute_champion_modifier(pool, self.RANK_PV, SPLIT, self.W) > 0.0

    def test_below_average_pool_negative(self):
        """Below-baseline dpm_scores → negative modifier (raises PV = weaker)."""
        pool = _pool(
            _entry("Caitlyn", 80, 3.0),
            _entry("Jinx",    40, 3.5),
        )
        assert compute_champion_modifier(pool, self.RANK_PV, SPLIT, self.W) < 0.0

    def test_wrong_split_ignored(self):
        """Champions from a different split should not qualify."""
        pool = _pool(_entry("Caitlyn", 80, 9.0, split="S2025"))
        assert compute_champion_modifier(pool, self.RANK_PV, SPLIT, self.W) == 0.0

    def test_non_all_role_ignored(self):
        """Only role=ALL entries should count for bracket assignment."""
        entry = ChampionEntry(
            champion="Caitlyn",
            role="BOT",
            splits=[ChampionSplitStats(
                lol_season=SPLIT, wins=80, losses=0, games=80,
                dpm_score=9.0, source="dpm",
            )],
        )
        pool = AccountQueueChampionPool(champions=[entry])
        assert compute_champion_modifier(pool, self.RANK_PV, SPLIT, self.W) == 0.0

    def test_tanh_approaches_cap_not_exceeds(self):
        """Extreme dpm_scores drive modifier near cap but never past it."""
        pool = _pool(*[_entry(f"Champ{i}", 100, 20.0) for i in range(13)])
        cap = self.W.champ_alpha * tier_width_at_pv(self.RANK_PV)
        result = compute_champion_modifier(pool, self.RANK_PV, SPLIT, self.W)
        assert result <= cap + 1e-9   # tanh saturates at 1.0 in floating point — never exceeds cap
        assert result > cap * 0.9     # should be very close to cap with extreme scores

    def test_games_weighting_within_bracket(self):
        """
        B1 contains only Caitlyn (80 games, score 8.0). Jinx has fewer games (10)
        but higher score (10.0). B1 modifier should be dominated by Caitlyn, not Jinx.
        B1 is sorted by games, not score — Caitlyn (80g) is B1, Jinx (10g) is B2.
        """
        pool = _pool(
            _entry("Caitlyn", 80, 8.0),
            _entry("Jinx",    10, 10.0),
        )
        # B1 = Caitlyn only (80g, score 8.0), residual = 3.0
        # B2 = Jinx (10g, score 10.0), residual = 5.0
        # raw_delta = 1.0 * 3.0 + 0.8 * 5.0 = 7.0
        cap = self.W.champ_alpha * tier_width_at_pv(self.RANK_PV)
        expected_raw = 1.0 * (8.0 - 5.0) + 0.8 * (10.0 - 5.0)
        expected = cap * math.tanh(self.W.champ_scale_factor * expected_raw / cap)
        result = compute_champion_modifier(pool, self.RANK_PV, SPLIT, self.W)
        assert result == pytest.approx(expected, abs=0.001)

    def test_sparse_pool_only_b1_populated(self):
        """Only one qualifying champ → B2–B5 zero-fill → smaller modifier than full pool."""
        sparse = _pool(_entry("Caitlyn", 80, 8.0))
        full = _pool(*[_entry(f"C{i}", 80, 8.0) for i in range(13)])
        sparse_mod = compute_champion_modifier(sparse, self.RANK_PV, SPLIT, self.W)
        full_mod   = compute_champion_modifier(full,   self.RANK_PV, SPLIT, self.W)
        assert sparse_mod < full_mod

    def test_games_weighted_residual_in_bracket(self):
        """Within B2 (two champs), the higher-games champ should pull the residual harder."""
        # B1: Caitlyn 80g score 5.0 (neutral)
        # B2: Jinx 60g score 8.0, Ezreal 10g score 2.0
        # games-weighted B2 residual = (60*(8-5) + 10*(2-5)) / 70 = (180-30)/70 ≈ 2.14
        pool = _pool(
            _entry("Caitlyn", 80, 5.0),
            _entry("Jinx",    60, 8.0),
            _entry("Ezreal",  10, 2.0),
        )
        cap = self.W.champ_alpha * tier_width_at_pv(self.RANK_PV)
        b2_residual = (60 * (8.0 - 5.0) + 10 * (2.0 - 5.0)) / 70
        b1_residual = 0.0  # 5.0 - 5.0
        raw_delta = 1.0 * b1_residual + 0.8 * b2_residual
        expected = cap * math.tanh(self.W.champ_scale_factor * raw_delta / cap)
        result = compute_champion_modifier(pool, self.RANK_PV, SPLIT, self.W)
        assert result == pytest.approx(expected, abs=0.001)


# ------------------------------------------------------------------
# compute_pv integration — F5/F6 wired into formula
# ------------------------------------------------------------------

class TestComputePvChampIntegration:
    W = PVWeights()

    def _pv(self, solo_pool=None, flex_pool=None, **kwargs):
        profile = _profile_with_champ(solo_pool=solo_pool, flex_pool=flex_pool, **kwargs)
        return compute_pv(profile, self.W, N_threshold=50, tournament_round=ROUND, current_lol_split=SPLIT)

    def test_no_champion_data_sets_missing_flag(self):
        result = self._pv()
        assert result.features.champ_data_missing is True
        assert result.features.solo_champ_modifier == 0.0
        assert result.features.flex_champ_modifier == 0.0

    def test_strong_solo_pool_lowers_pv(self):
        """Above-average solo pool → positive modifier → PV decreases."""
        base   = self._pv()
        strong = self._pv(solo_pool=_pool(*[_entry(f"C{i}", 50, 8.0) for i in range(5)]))
        assert strong.point_value < base.point_value
        assert strong.features.champ_data_missing is False
        assert strong.features.solo_champ_modifier > 0.0

    def test_weak_solo_pool_raises_pv(self):
        """Below-average solo pool → negative modifier → PV increases."""
        base = self._pv()
        weak = self._pv(solo_pool=_pool(*[_entry(f"C{i}", 50, 2.0) for i in range(5)]))
        assert weak.point_value > base.point_value
        assert weak.features.solo_champ_modifier < 0.0

    def test_weak_flex_pool_does_not_raise_pv(self):
        """F6 is benefit-only — weak flex pool must not penalize the player."""
        base = self._pv()
        weak_flex = self._pv(flex_pool=_pool(*[_entry(f"C{i}", 50, 2.0) for i in range(5)]))
        assert weak_flex.point_value == pytest.approx(base.point_value, abs=0.1)
        assert weak_flex.features.flex_champ_modifier < 0.0  # raw value is negative
        # but the actual PV impact is zero (clamped before subtracting)

    def test_strong_flex_pool_lowers_pv(self):
        """Strong flex pool → positive raw modifier → clamped to positive → PV decreases."""
        base   = self._pv()
        strong = self._pv(flex_pool=_pool(*[_entry(f"C{i}", 50, 8.0) for i in range(5)]))
        assert strong.point_value < base.point_value

    def test_solo_modifier_stored_on_features(self):
        pool = _pool(_entry("Caitlyn", 80, 7.0), _entry("Jinx", 40, 6.0))
        result = self._pv(solo_pool=pool)
        assert result.features.solo_champ_modifier > 0.0
        assert result.features.champ_data_missing is False

    def test_archived_account_skipped(self):
        """Archived accounts should not contribute champion data."""
        champ_data = AccountChampionData(
            solo=_pool(*[_entry(f"C{i}", 80, 9.0) for i in range(5)]),
        )
        account = Account(riot_id="Archived#NA1", archived=True, champion_data=champ_data)
        solo_splits = [
            AggregatedSplitRank(season=SPLIT, split_rank="Gold 1", peak_rank="Gold 1", wins=100, losses=100),
            AggregatedSplitRank(season="S2025", peak_rank="Gold 1"),
        ]
        profile = PlayerProfile(
            discord_id="testplayer",
            accounts=[account],
            season_data=[SeasonData(season=ROUND)],
            stats=PlayerStats(
                rank_data=AggregatedRankData(solo_splits=solo_splits),
                current_rank="Gold 1",
                all_time_peak_rank="Gold 1",
            ),
            created_at=datetime.now(timezone.utc),
            last_updated_at=datetime.now(timezone.utc),
        )
        result = compute_pv(profile, self.W, N_threshold=50, tournament_round=ROUND, current_lol_split=SPLIT)
        assert result.features.champ_data_missing is True
        assert result.features.solo_champ_modifier == 0.0
