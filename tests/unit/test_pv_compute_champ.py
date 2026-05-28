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
from quartz.pv_compute import compute_champion_modifier, compute_champ_dpm_baseline, compute_pv, tier_width_at_pv


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
        pool = _pool(_entry("Caitlyn", games=2, dpm_score=7.0))  # 2 < games_min=3
        assert compute_champion_modifier(pool, self.RANK_PV, SPLIT, self.W) == 0.0

    def test_all_brackets_at_baseline_returns_zero(self):
        """All 5 brackets filled with dpm_score = baseline → residuals = 0 → modifier = 0."""
        pool = _pool(*[_entry(f"C{i}", 100, 50.0) for i in range(13)])
        result = compute_champion_modifier(pool, self.RANK_PV, SPLIT, self.W)
        assert result == pytest.approx(0.0, abs=1e-9)

    def test_partial_pool_at_baseline_penalized(self):
        """Filled brackets at baseline contribute 0, but empty brackets still apply penalty."""
        pool = _pool(_entry("Caitlyn", 80, 50.0))  # only B1 filled, B2-B5 empty
        result = compute_champion_modifier(pool, self.RANK_PV, SPLIT, self.W)
        assert result < 0.0

    def test_above_average_pool_positive(self):
        """Above-baseline dpm_scores → positive modifier (lowers PV = stronger)."""
        pool = _pool(
            _entry("Caitlyn", 80, 57.0),
            _entry("Jinx",    40, 56.5),
        )
        assert compute_champion_modifier(pool, self.RANK_PV, SPLIT, self.W) > 0.0

    def test_below_average_pool_negative(self):
        """Below-baseline dpm_scores → negative modifier (raises PV = weaker)."""
        pool = _pool(
            _entry("Caitlyn", 80, 43.0),
            _entry("Jinx",    40, 43.5),
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
        pool = _pool(*[_entry(f"Champ{i}", 100, 90.0) for i in range(13)])
        cap = self.W.champ_alpha * tier_width_at_pv(self.RANK_PV)
        result = compute_champion_modifier(pool, self.RANK_PV, SPLIT, self.W)
        assert result <= cap + 1e-9   # tanh saturates at 1.0 in floating point — never exceeds cap
        assert result > cap * 0.9     # should be very close to cap with extreme scores

    def test_games_weighting_within_bracket(self):
        """
        B1 = Caitlyn (80g, score 58.0). B2 = Jinx (10g, score 60.0). B3-B5 empty → penalty.
        Bracket confidence attenuates each filled bracket by 1 − exp(−games / champ_n_bracket).
        """
        pool = _pool(
            _entry("Caitlyn", 80, 58.0),
            _entry("Jinx",    10, 60.0),
        )
        cap = self.W.champ_alpha * tier_width_at_pv(self.RANK_PV)
        P = -self.W.champ_penalty_sigma * self.W.champ_dpm_pool_stddev
        conf_B1 = 1.0 - math.exp(-80 / self.W.champ_n_bracket)
        conf_B2 = 1.0 - math.exp(-10 / self.W.champ_n_bracket)
        expected_raw = (
            1.0 * (58.0 - self.W.champ_dpm_baseline) * conf_B1
            + 0.8 * (60.0 - self.W.champ_dpm_baseline) * conf_B2
            + 0.6 * P  # B3 empty
            + 0.4 * P  # B4 empty
            + 0.2 * P  # B5 empty
        )
        expected = cap * math.tanh(self.W.champ_scale_factor * expected_raw / cap)
        result = compute_champion_modifier(pool, self.RANK_PV, SPLIT, self.W)
        assert result == pytest.approx(expected, abs=0.001)

    def test_sparse_pool_only_b1_populated(self):
        """Only one qualifying champ → B2–B5 zero-fill → smaller modifier than full pool."""
        sparse = _pool(_entry("Caitlyn", 80, 58.0))
        full = _pool(*[_entry(f"C{i}", 80, 58.0) for i in range(13)])
        sparse_mod = compute_champion_modifier(sparse, self.RANK_PV, SPLIT, self.W)
        full_mod   = compute_champion_modifier(full,   self.RANK_PV, SPLIT, self.W)
        assert sparse_mod < full_mod

    def test_games_weighted_residual_in_bracket(self):
        """Within B2 (two champs), the higher-games champ pulls the residual harder."""
        # B1: Caitlyn 80g score 50.0 (neutral)
        # B2: Jinx 60g score 58.0, Ezreal 10g score 42.0
        # games-weighted B2 residual = (60*(58-50) + 10*(42-50)) / 70 = (480-80)/70 ≈ 5.71
        # B3-B5: empty → penalty P each
        pool = _pool(
            _entry("Caitlyn", 80, 50.0),
            _entry("Jinx",    60, 58.0),
            _entry("Ezreal",  10, 42.0),
        )
        cap = self.W.champ_alpha * tier_width_at_pv(self.RANK_PV)
        P = -self.W.champ_penalty_sigma * self.W.champ_dpm_pool_stddev
        conf_B1 = 1.0 - math.exp(-80 / self.W.champ_n_bracket)
        conf_B2 = 1.0 - math.exp(-70 / self.W.champ_n_bracket)  # 60 + 10 = 70
        b2_residual = (60 * (58.0 - self.W.champ_dpm_baseline) + 10 * (42.0 - self.W.champ_dpm_baseline)) / 70
        b1_residual = 0.0  # 50.0 - 50.0
        raw_delta = (
            1.0 * b1_residual * conf_B1
            + 0.8 * b2_residual * conf_B2
            + 0.6 * P  # B3 empty
            + 0.4 * P  # B4 empty
            + 0.2 * P  # B5 empty
        )
        expected = cap * math.tanh(self.W.champ_scale_factor * raw_delta / cap)
        result = compute_champion_modifier(pool, self.RANK_PV, SPLIT, self.W)
        assert result == pytest.approx(expected, abs=0.001)


# ------------------------------------------------------------------
# New formula — empty bracket penalty & bracket confidence
# ------------------------------------------------------------------

class TestBracketConfidenceAndPenalty:
    W = PVWeights()
    RANK_PV = 62.1

    def test_empty_bracket_contributes_penalty(self):
        """B2-B5 empty → each contributes bw × P where P = −sigma × stddev."""
        pool = _pool(_entry("Caitlyn", 80, 50.0))  # only B1, at baseline
        cap = self.W.champ_alpha * tier_width_at_pv(self.RANK_PV)
        P = -self.W.champ_penalty_sigma * self.W.champ_dpm_pool_stddev
        conf_B1 = 1.0 - math.exp(-80 / self.W.champ_n_bracket)
        expected_raw = 1.0 * 0.0 * conf_B1 + 0.8 * P + 0.6 * P + 0.4 * P + 0.2 * P
        expected = cap * math.tanh(self.W.champ_scale_factor * expected_raw / cap)
        assert compute_champion_modifier(pool, self.RANK_PV, SPLIT, self.W) == pytest.approx(expected, abs=0.001)

    def test_bracket_confidence_scales_with_games(self):
        """3-game bracket has lower confidence weight than 30-game bracket."""
        # 3-game bracket: conf = 1 − exp(−3/10) ≈ 0.26
        # 30-game bracket: conf = 1 − exp(−30/10) = 1 − exp(−3) ≈ 0.95
        # Both at the same above-baseline score → 30g bracket should dominate
        pool_low  = _pool(_entry("Caitlyn", 3,  70.0))
        pool_high = _pool(_entry("Caitlyn", 30, 70.0))
        mod_low  = compute_champion_modifier(pool_low,  self.RANK_PV, SPLIT, self.W)
        mod_high = compute_champion_modifier(pool_high, self.RANK_PV, SPLIT, self.W)
        # Both may be negative overall (B2-B5 penalty dominates) but high-games should be larger
        assert mod_high > mod_low

    def test_one_trick_penalized_by_empty_brackets(self):
        """One-trick needs elite B1 DPM to overcome B2-B5 empty-bracket penalties."""
        W = PVWeights()
        # Mediocre B1 (score at baseline) → penalties drag result negative
        mediocre = _pool(_entry("Caitlyn", 200, 50.0))
        mod = compute_champion_modifier(mediocre, self.RANK_PV, SPLIT, W)
        assert mod < 0.0  # empty B2-B5 penalty wins

        # Elite B1 (sigma > 1 above pool_stddev) → should overcome penalties
        elite = _pool(_entry("Caitlyn", 200, 85.0))
        mod_elite = compute_champion_modifier(elite, self.RANK_PV, SPLIT, W)
        assert mod_elite > mod  # elite one-trick does better, but still penalized vs full pool

    def test_high_games_amplifies_penalty(self):
        """200g with below-baseline score penalizes more than 3g with same score."""
        low_g  = _pool(_entry("Caitlyn", 3,  40.0))
        high_g = _pool(_entry("Caitlyn", 200, 40.0))
        mod_low  = compute_champion_modifier(low_g,  self.RANK_PV, SPLIT, self.W)
        mod_high = compute_champion_modifier(high_g, self.RANK_PV, SPLIT, self.W)
        assert mod_high < mod_low  # more games → more confident → penalty grows


# ------------------------------------------------------------------
# compute_champ_dpm_baseline
# ------------------------------------------------------------------

class TestComputeChampDpmBaseline:
    W = PVWeights()

    def _make_profile(self, scores_and_games: list[tuple[float, int]]) -> "PlayerProfile":
        entries = [_entry(f"C{i}", g, s) for i, (s, g) in enumerate(scores_and_games)]
        return _profile_with_champ(solo_pool=_pool(*entries))

    def test_returns_median_and_stddev(self):
        profiles = [self._make_profile([(60.0, 10), (70.0, 10)]) for _ in range(3)]
        # All champs: six entries with scores 60.0 and 70.0 alternating → median = 65.0
        median, stddev = compute_champ_dpm_baseline(profiles, self.W, SPLIT)
        assert median == pytest.approx(65.0, abs=0.1)
        assert stddev > 0.0

    def test_fallback_when_too_few_samples(self):
        profile = _profile_with_champ()  # no champion data
        median, stddev = compute_champ_dpm_baseline([profile], self.W, SPLIT)
        assert median == self.W.champ_dpm_baseline
        assert stddev == self.W.champ_dpm_pool_stddev

    def test_below_games_min_excluded(self):
        # games=2 is below champ_games_min=3 — should not contribute
        entries = [_entry("C0", 2, 90.0), _entry("C1", 10, 50.0), _entry("C2", 10, 50.0)]
        profiles = [_profile_with_champ(solo_pool=_pool(*entries))]
        median, _ = compute_champ_dpm_baseline(profiles, self.W, SPLIT)
        # Only the two 50.0 champs qualify → median = 50.0 (not pulled up by 90.0)
        assert median == pytest.approx(50.0, abs=0.1)

    def test_archived_accounts_excluded(self):
        from quartz.models.champion_data import AccountChampionData
        from quartz.models.player_profile import Account
        champ_data = AccountChampionData(solo=_pool(_entry("C0", 20, 90.0)))
        archived_account = Account(riot_id="Arch#NA1", archived=True, champion_data=champ_data)
        normal_account   = Account(riot_id="Norm#NA1", champion_data=AccountChampionData(
            solo=_pool(_entry("C0", 20, 50.0), _entry("C1", 20, 50.0))
        ))
        from quartz.models.player_profile import PlayerProfile, SeasonData
        from datetime import datetime, timezone
        from quartz.models.rank_data import PlayerStats
        profile = PlayerProfile(
            discord_id="test",
            accounts=[archived_account, normal_account],
            season_data=[SeasonData(season=ROUND)],
            stats=PlayerStats(),
            created_at=datetime.now(timezone.utc),
            last_updated_at=datetime.now(timezone.utc),
        )
        median, _ = compute_champ_dpm_baseline([profile], self.W, SPLIT)
        assert median == pytest.approx(50.0, abs=0.1)  # archived 90.0 not included


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
        strong = self._pv(solo_pool=_pool(*[_entry(f"C{i}", 50, 58.0) for i in range(5)]))
        assert strong.point_value < base.point_value
        assert strong.features.champ_data_missing is False
        assert strong.features.solo_champ_modifier > 0.0

    def test_weak_solo_pool_raises_pv(self):
        """Below-average solo pool → negative modifier → PV increases."""
        base = self._pv()
        weak = self._pv(solo_pool=_pool(*[_entry(f"C{i}", 50, 42.0) for i in range(5)]))
        assert weak.point_value > base.point_value
        assert weak.features.solo_champ_modifier < 0.0

    def test_weak_flex_pool_does_not_raise_pv(self):
        """F6 is benefit-only — flex pool weaker than solo must not penalize."""
        strong_solo = _pool(*[_entry(f"C{i}", 50, 65.0) for i in range(5)])
        base      = self._pv(solo_pool=strong_solo)
        weak_flex = self._pv(
            solo_pool=strong_solo,
            flex_pool=_pool(*[_entry(f"C{i}", 50, 42.0) for i in range(5)]),
        )
        assert weak_flex.point_value == pytest.approx(base.point_value, abs=0.1)
        assert weak_flex.features.flex_champ_modifier == 0.0  # clamped — never negative

    def test_strong_flex_pool_lowers_pv(self):
        """Flex pool that outperforms solo → positive advantage → PV decreases."""
        mediocre_solo = _pool(*[_entry(f"C{i}", 50, 55.0) for i in range(5)])
        base   = self._pv(solo_pool=mediocre_solo)
        strong = self._pv(
            solo_pool=mediocre_solo,
            flex_pool=_pool(*[_entry(f"C{i}", 50, 70.0) for i in range(5)]),
        )
        assert strong.point_value < base.point_value
        assert strong.features.flex_champ_modifier > 0.0

    def test_flex_without_solo_reference_gives_no_f6(self):
        """Without a solo pool, F6 stays 0 — can't compute advantage without reference."""
        result = self._pv(flex_pool=_pool(*[_entry(f"C{i}", 50, 70.0) for i in range(5)]))
        assert result.features.flex_champ_modifier == 0.0

    def test_solo_modifier_stored_on_features(self):
        pool = _pool(_entry("Caitlyn", 80, 57.0), _entry("Jinx", 40, 56.0))
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
