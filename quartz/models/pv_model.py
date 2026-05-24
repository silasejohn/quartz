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

    # Feature 3 — in-house Wilson modifier
    min_games_threshold:    int            = 7
    max_bonus_points:       float          = 5.0
    realistic_max_override: Optional[float] = None
    wilson_z:               float          = 1.28

    # Global
    baseline: float = 10.0


class PVFeatures(BaseModel):
    """
    Intermediate values computed for one player — every component stored for transparency.
    Inspect profile.data.computed_pv.features to see exactly how a score was derived.
    """

    # Feature 1
    historical_score: Optional[float] = None
    splits_used:      int              = 0

    # Feature 2
    current_rank_pts:      Optional[float] = None
    games_played:          Optional[int]   = None
    confidence:            Optional[float] = None
    default_rank_used:     Optional[str]   = None
    adjusted_current_pts:  Optional[float] = None
    n_threshold_used:      Optional[int]   = None

    # Feature 3
    inhouse_wins:     Optional[int]   = None
    inhouse_losses:   Optional[int]   = None
    inhouse_total:    Optional[int]   = None
    wilson_lower:     Optional[float] = None
    inhouse_modifier: float           = 0.0

    # Feature 4
    manual_adjustment_total: float = 0.0

    # Transparency
    stated_rank_diff: Optional[float] = None


class ComputedPV(BaseModel):
    """
    Final PV output for one player. Stored on PlayerEnrichment.computed_pv.
    SeasonData.point_value receives round(point_value) for easy downstream access.
    """
    features:     PVFeatures
    weights_used: PVWeights
    pv_rank_only: float
    point_value:  float
    flagged:      bool     = False
    computed_at:  datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
