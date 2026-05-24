"""
PV computation for the Quartz pipeline.

Public API:
  compute_N_threshold(profiles, weights, current_lol_season) -> int
      Derive the confidence-curve N parameter from the player pool's games distribution.

  compute_pv(profile, weights, N_threshold, tournament_season) -> ComputedPV
      Compute PV for a single PlayerProfile.
      Requires profile.data (PlayerEnrichment) to be populated — run CALCULATE_RANK_STATS first.

Formula:
  F1 = time-decayed weighted avg of peak_rank across PAST_YEAR_SEASONS
  F2 = confidence-blended current rank (regressed toward player's all_time_peak_rank)
  base_pv = (w_historical × F1 + w_current × F2) / (w_historical + w_current)
  point_value = round(base_pv + baseline - inhouse_modifier - manual_adjustment_total, 1)

Lower PV = stronger player.
"""

import math
import statistics
from typing import Optional

from quartz.constants import SEASON_ORDER, PAST_YEAR_SEASONS, rank_score
from quartz.models.pv_model import (
    PVWeights, PVFeatures, ComputedPV, ConfidenceThresholdStrategy,
)

# Sentinel for missing/unusable data
PV_SENTINEL = 9999.0

# Fallback N when pool has zero game data (should never happen in practice)
_FALLBACK_N = 50

# Fallback realistic_max when no player in the pool has sufficient in-house data
_FALLBACK_REALISTIC_MAX = 0.75


def _wilson_lower(wins: int, total: int, z: float = 1.96) -> float:
    """95% confidence Wilson lower bound on win rate."""
    if total == 0:
        return 0.0
    p_hat = wins / total
    z2 = z * z
    return (p_hat + z2 / (2 * total) - z * math.sqrt((p_hat * (1 - p_hat) + z2 / (4 * total)) / total)) \
           / (1 + z2 / total)


# ------------------------------------------------------------------
# Pool-level helpers
# ------------------------------------------------------------------

def compute_N_threshold(profiles: list, weights: PVWeights, current_lol_season: str) -> int:
    """
    Derive N (games played threshold for Feature 2 confidence curve) from the pool.

    N is computed from wins+losses in current_lol_season across all profiles that
    have enrichment data. Uses the strategy specified in weights.confidence_strategy,
    unless weights.n_override is set (which bypasses strategy entirely).

    [param] profiles: all PlayerProfile objects in the pool
    [param] weights: PVWeights (reads confidence_strategy and n_override)
    [param] current_lol_season: e.g. "S2026"

    Returns N (int), minimum 1.
    """
    if weights.n_override is not None:
        return max(1, weights.n_override)

    games_list: list[int] = []
    for profile in profiles:
        if not profile.data or not profile.data.rank_data:
            continue
        splits_by_season = {agg.season: agg for agg in profile.data.rank_data.splits}
        agg = splits_by_season.get(current_lol_season)
        if agg is None:
            continue
        games = (agg.wins or 0) + (agg.losses or 0)
        if games > 0:
            games_list.append(games)

    if not games_list:
        return _FALLBACK_N

    strategy = weights.confidence_strategy
    if strategy == ConfidenceThresholdStrategy.MEDIAN:
        return max(1, int(statistics.median(games_list)))
    elif strategy == ConfidenceThresholdStrategy.P25:
        sorted_games = sorted(games_list)
        idx = max(0, int(len(sorted_games) * 0.25) - 1)
        return max(1, sorted_games[idx])
    elif strategy == ConfidenceThresholdStrategy.MEAN_1SD:
        mean = statistics.mean(games_list)
        std = statistics.stdev(games_list) if len(games_list) >= 2 else 0.0
        return max(1, int(mean - std))

    return _FALLBACK_N


def compute_realistic_max(profiles: list, weights: PVWeights, tournament_season: str) -> float:
    """
    Derive the realistic Wilson lower bound ceiling from the pool (two-pass normalization).

    Scans all profiles for in-house W/L on tournament_season, computes Wilson LB for each
    player that meets min_games_threshold, and returns the maximum observed value.

    If weights.realistic_max_override is set, that value is returned directly.
    Falls back to _FALLBACK_REALISTIC_MAX if no player has sufficient in-house data.

    [param] profiles:          all PlayerProfile objects in the pool
    [param] weights:           PVWeights (reads min_games_threshold, realistic_max_override)
    [param] tournament_season: tournament round string e.g. "S4"

    Returns realistic_max (float), used to normalize InHouse_Modifier.
    """
    if weights.realistic_max_override is not None:
        return weights.realistic_max_override

    wilson_lbs: list[float] = []
    for profile in profiles:
        season_entry = next((sd for sd in profile.season_data if sd.season == tournament_season), None)
        if not season_entry:
            continue
        if season_entry.inhouse_wins is None or season_entry.inhouse_losses is None:
            continue
        total = season_entry.inhouse_wins + season_entry.inhouse_losses
        if total < weights.min_games_threshold:
            continue
        wlb = _wilson_lower(season_entry.inhouse_wins, total, z=weights.wilson_z)
        wilson_lbs.append(wlb)

    if not wilson_lbs:
        return _FALLBACK_REALISTIC_MAX

    return max(wilson_lbs)


# ------------------------------------------------------------------
# Single-profile computation
# ------------------------------------------------------------------

def compute_pv(
    profile,
    weights: PVWeights,
    N_threshold: int,
    tournament_season: str,
    realistic_max: float = _FALLBACK_REALISTIC_MAX,
) -> "ComputedPV":
    """
    Compute PV for a single PlayerProfile.

    [param] profile:           PlayerProfile — must have profile.data populated (CALCULATE_RANK_STATS)
    [param] weights:           PVWeights with all tunable parameters
    [param] N_threshold:       games played threshold — compute via compute_N_threshold()
    [param] tournament_season: tournament round string e.g. "S4"
    [param] realistic_max:     max Wilson LB observed across pool — compute via compute_realistic_max()
    """
    current_lol_season = SEASON_ORDER[0]  # "S2026"
    features = PVFeatures()

    splits_by_season: dict = {}
    if profile.data and profile.data.rank_data:
        splits_by_season = {agg.season: agg for agg in profile.data.rank_data.splits}

    # ------------------------------------------------------------------
    # Feature 1 — Time-Decayed Historical Peak Score
    # ------------------------------------------------------------------
    F1: Optional[float] = None

    if splits_by_season:
        past_seasons = PAST_YEAR_SEASONS[:weights.history_splits]
        base_weights = weights.historical_base_weights[:weights.history_splits]

        available: list[tuple[float, float]] = []  # (base_weight, rank_score_value)
        for season_key, base_w in zip(past_seasons, base_weights):
            agg = splits_by_season.get(season_key)
            if not agg or not agg.peak_rank:
                continue
            score = rank_score(agg.peak_rank)
            if score is None or score >= PV_SENTINEL:
                continue
            available.append((base_w, score))

        if available:
            total_w = sum(w for w, _ in available)
            F1 = sum((w / total_w) * s for w, s in available)
            features.historical_score = round(F1, 3)
            features.splits_used = len(available)

    # ------------------------------------------------------------------
    # Feature 2 — Confidence-Adjusted Current Rank Score
    # ------------------------------------------------------------------
    F2: Optional[float] = None

    # Per-player regression target: all-time peak rank across all accounts + all splits.
    # A player with 0 games this season is assumed to be at their ceiling, not penalized
    # to a fixed global default. The confidence curve then blends current rank toward
    # this peak as games accumulate.
    default_rank_str: Optional[str] = None
    if profile.data and profile.data.all_time_peak_rank:
        s = rank_score(profile.data.all_time_peak_rank)
        if s is not None and s < PV_SENTINEL:
            default_rank_str = profile.data.all_time_peak_rank

    # Games played this season
    current_agg = splits_by_season.get(current_lol_season)
    games = 0
    if current_agg:
        games = (current_agg.wins or 0) + (current_agg.losses or 0)

    confidence = 1.0 - math.exp(-games / N_threshold) if N_threshold > 0 else 0.0

    # Current rank score
    rank_pts: Optional[float] = None
    if profile.data and profile.data.current_rank:
        rank_pts = rank_score(profile.data.current_rank)
        if rank_pts is not None and rank_pts >= PV_SENTINEL:
            rank_pts = None

    if rank_pts is not None:
        if default_rank_str is not None:
            # Blend: at confidence=0 → default (last split); at confidence=1 → current rank
            default_pts = rank_score(default_rank_str)
            F2 = confidence * rank_pts + (1.0 - confidence) * default_pts
        else:
            # No history to regress toward — use current rank directly
            F2 = rank_pts
            confidence = 1.0   # treat as fully trusted (no regression needed)

    features.current_rank_pts     = round(rank_pts, 3) if rank_pts is not None else None
    features.games_played          = games
    features.confidence            = round(confidence, 4)
    features.default_rank_used     = default_rank_str
    features.adjusted_current_pts  = round(F2, 3) if F2 is not None else None
    features.n_threshold_used      = N_threshold

    # Transparency: stated vs actual rank diff
    season_entry = next((sd for sd in profile.season_data if sd.season == tournament_season), None)
    if season_entry and season_entry.stated_current_rank and rank_pts is not None:
        stated_pts = rank_score(season_entry.stated_current_rank)
        if stated_pts is not None and stated_pts < PV_SENTINEL:
            features.stated_rank_diff = round(stated_pts - rank_pts, 3)

    # ------------------------------------------------------------------
    # Feature 3 — In-House Wilson Modifier
    # ------------------------------------------------------------------
    if season_entry and season_entry.inhouse_wins is not None and season_entry.inhouse_losses is not None:
        ih_wins   = season_entry.inhouse_wins
        ih_losses = season_entry.inhouse_losses
        ih_total  = ih_wins + ih_losses
        features.inhouse_wins   = ih_wins
        features.inhouse_losses = ih_losses
        features.inhouse_total  = ih_total

        if ih_total >= weights.min_games_threshold:
            wlb = _wilson_lower(ih_wins, ih_total, z=weights.wilson_z)
            features.wilson_lower = round(wlb, 4)
            if wlb > 0.5 and realistic_max > 0.5:
                inhouse_raw        = max(0.0, wlb - 0.5)
                inhouse_normalized = inhouse_raw / (realistic_max - 0.5)
                features.inhouse_modifier = round(min(inhouse_normalized, 1.0) * weights.max_bonus_points, 3)

    # ------------------------------------------------------------------
    # Feature 4 — Manual Adjustments (admin-set per-season bonuses)
    # ------------------------------------------------------------------
    manual_adj_total = 0.0
    if season_entry:
        manual_adj_total = sum(adj.value for adj in season_entry.manual_adjustments)
    features.manual_adjustment_total = round(manual_adj_total, 3)

    # ------------------------------------------------------------------
    # Combine → final PV
    # ------------------------------------------------------------------
    valid: list[tuple[float, float]] = []  # (weight, score)
    if F1 is not None:
        valid.append((weights.w_historical, F1))
    if F2 is not None:
        valid.append((weights.w_current, F2))

    if not valid:
        return ComputedPV(
            features=features,
            weights_used=weights,
            pv_rank_only=PV_SENTINEL,
            point_value=PV_SENTINEL,
            flagged=True,
        )

    total_w = sum(w for w, _ in valid)
    base_pv = sum((w / total_w) * s for w, s in valid)
    point_value = round(base_pv + weights.baseline - features.inhouse_modifier - manual_adj_total, 1)

    return ComputedPV(
        features=features,
        weights_used=weights,
        pv_rank_only=round(base_pv, 3),
        point_value=point_value,
        flagged=False,
    )
