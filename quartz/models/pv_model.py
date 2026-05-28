"""
PV (Point Value) data models for the Quartz pipeline.

PVWeights       — tunable parameters for all features
PVFeatures      — intermediate computed values (stored for full audit trail)
ComputedPV      — final output stored on PlayerEnrichment.computed_pv

Lower PV = stronger player (Challenger ~10, Iron ~85+).
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ConfidenceThresholdStrategy(str, Enum):
    """Strategy for computing N (games threshold) in Feature 2's confidence curve."""
    MEDIAN   = "median"    # N = median(games_played across all players) ← default
    P25      = "p25"       # N = 25th percentile — softer on casual players
    MEAN_1SD = "mean_1sd"  # N = mean - stdev — harsher on low-game outliers


class PVWeights(BaseModel):
    """
    All tunable parameters for the PV model.

    Pass a custom instance to compute_pv() to experiment with weighting schemes.
    A snapshot is stored in ComputedPV.weights_used so every score is reproducible.

    Feature 1 (historical_base_weights):
      Base decay weights for past 4 splits [split_1, split_2, split_3, split_4].
      split_1 = most recently COMPLETED season. Renormalized when fewer than 4 splits exist.

    Feature 2 (confidence curve):
      confidence = 1 - e^(-games / N)
      Regression target is the player's own all-time peak rank.

    Feature 3 (in-house Wilson modifier):
      Upward-only boost. Hard floor at min_games_threshold.
      Wilson lower bound must exceed 50% before any bonus is applied.
    """

    # Feature blend weights (ratio is what matters — normalized at compute time)
    w_historical: float = 1.0
    w_current:    float = 1.0

    # Feature 1 — time-decayed historical peak
    historical_base_weights: list[float] = [0.40, 0.25, 0.15, 0.12]
    history_splits:          int         = 4

    # Feature 2 — confidence-adjusted current rank
    confidence_strategy: ConfidenceThresholdStrategy = ConfidenceThresholdStrategy.MEDIAN
    n_override:          Optional[int] = None

    # Feature 2 — ATP staleness decay (see docs/features/F2_confidence_rank.md)
    atp_hard_floor_games:        int            = 50    # absolute min games for a post-peak season to count as evidence
    atp_personal_volume_pct:     float          = 0.40  # fraction of player's mean prior season games required
    atp_season_pool_percentile:  float          = 0.25  # pool percentile (P_k) for season volume gate
    atp_climbing_wr_threshold:   float          = 55.0  # WR% above which season is skipped (player still climbing)
    atp_max_miss_scale_override: Optional[float] = None  # None = auto: 2 × stdev(pool current rank scores)

    # Feature 1 — historical confidence (games-based weight scaling)
    n_historical_floor: int = 30   # minimum N for any historical split's confidence curve

    # Account flag thresholds
    smurf_jump_threshold: float = 20.0  # rank_score delta triggering smurf_jump flag (~2 full tiers)

    # Feature 3 — in-house Wilson modifier
    min_games_threshold:    int            = 7
    max_bonus_points:       float          = 5.0
    realistic_max_override: Optional[float] = None
    wilson_z:               float          = 1.28

    # Global
    baseline: float = 10.0

    # F5/F6 — Champion pool modifier (see docs/features/CHAMP_FEATURES.md)
    # Bracket assignment: sort by games played (ALL-role DPM aggregate, current split).
    # B1 = champ #1, B2 = champs #2-3, B3 = champs #4-5, B4 = champs #6-8, B5 = champs #9-13.
    # Mild taper default — game-5 depth earns real credit, breadth meaningfully beats depth.
    #
    # Layers:
    #   1. games_min=3 hard floor per champ
    #   2. Within-bracket games-weighted residual vs pool-median baseline
    #   3. Bracket confidence: 1 − exp(−bracket_total_games / champ_n_bracket)
    #      (30 games in bracket ≈ 95% trust at N=10; 3 games ≈ 26%)
    #   Empty brackets contribute penalty P = −champ_penalty_sigma × pool_stddev instead of 0.
    champ_bracket_weights:   list[float]    = [1.0, 0.8, 0.6, 0.4, 0.2]
    champ_games_min:         int            = 3      # minimum games on a champ to qualify for any bracket
    champ_account_min_games: int            = 15     # minimum qualifying games an account must have to be rank-anchored
    champ_dpm_baseline:      float          = 50.0   # pool-median DPM averageScore (0-100 scale); filled at runtime by compute_champ_dpm_baseline()
    champ_dpm_pool_stddev:   float          = 10.2   # pool stddev; filled at runtime; used to scale empty-bracket penalty
    champ_penalty_sigma:     float          = 0.5    # empty bracket penalty = −sigma × pool_stddev (≈ −5.1 at GCS S4 values)
    champ_n_bracket:         int            = 10     # N for bracket confidence: 30 bracket-games ≈ 95% weight
    champ_scale_factor:      float          = 0.13   # sensitivity: may need increase post-redesign (residuals now near 0 not +12)
    champ_alpha:             float          = 0.33   # cap fraction: max modifier = champ_alpha × tier_width(rank_pv)


class PVFeatures(BaseModel):
    """
    Intermediate values computed for one player — every component stored for transparency.
    Inspect profile.data.computed_pv.features to see exactly how a score was derived.
    """

    # Feature 1
    historical_score: Optional[float] = None
    splits_used:      int              = 0
    f1_confidence:    Optional[float]  = None  # sum(eff_w) / sum(base_w for scoreable splits)

    # Feature 2
    current_rank_pts:      Optional[float] = None
    games_played:          Optional[int]   = None
    confidence:            Optional[float] = None
    default_rank_used:     Optional[str]   = None  # ATP rank string before decay
    adjusted_current_pts:  Optional[float] = None
    n_threshold_used:      Optional[int]   = None
    atp_decay_factor:      Optional[float] = None  # 0=ATP intact, 1=fully decayed to current
    effective_atp_rs:      Optional[float] = None  # rank score of decayed regression target
    n_historical_thresholds_used: dict[str, int] = {}  # per-split N for F1 confidence curve

    # Feature 3
    inhouse_wins:     Optional[int]   = None
    inhouse_losses:   Optional[int]   = None
    inhouse_total:    Optional[int]   = None
    wilson_lower:     Optional[float] = None
    inhouse_modifier: float           = 0.0

    # Feature 4
    manual_adjustment_total: float = 0.0

    # F5 — Solo champion modifier (bidirectional)
    solo_champ_modifier:  float = 0.0
    # F6 — Flex champion modifier (benefit-only: only lowers PV if positive)
    flex_champ_modifier:  float = 0.0
    # Set when player has no DPM scrape or no champs above games_min — both modifiers default to 0
    champ_data_missing:   bool  = False

    # Transparency
    stated_rank_diff: Optional[float] = None


class ComputedPV(BaseModel):
    """
    Final PV output for one player. Stored on PlayerStats.computed_pv.
    SeasonData.point_value receives round(point_value) for easy downstream access.

    point_value is None when flag_reason is set:
      "no_data"    — no usable rank history; displayed as FLAGGED
      "ineligible" — fails tournament games requirement; displayed as INF

    shadow_pv holds the score an ineligible player would receive if eligible.
    Stored on SeasonData.shadow_point_value for downstream access.
    """
    features:     PVFeatures
    weights_used: PVWeights
    pv_rank_only: Optional[float]
    point_value:  Optional[float]
    flag_reason:  Optional[str]  = None    # None | "no_data" | "ineligible"
    shadow_pv:    Optional[float] = None   # set for ineligible players; None for everyone else
    computed_at:  datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
