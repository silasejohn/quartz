"""
PV computation for the Quartz pipeline.

Public API:
  compute_N_threshold(profiles, weights, current_lol_split) -> int
  compute_n_historical_thresholds(profiles, weights, past_seasons) -> dict[str, int]
  compute_realistic_max(profiles, weights, tournament_round) -> float
  evaluate_eligibility(profile, eligibility_config) -> bool
  compute_pv(profile, weights, N_threshold, tournament_round, current_lol_split,
             realistic_max, n_historical_thresholds) -> ComputedPV

Feature docs: docs/features/F1_historical_peak.md through F4_manual_adjustments.md
Lower PV = stronger player. point_value is None when flag_reason is set.
"""

import math
import statistics
from typing import Optional

from quartz.constants import PAST_YEAR_SEASONS, rank_score
from quartz.models.pv_model import (
    ComputedPV,
    ConfidenceThresholdStrategy,
    PVFeatures,
    PVWeights,
)

_FALLBACK_N = 50
_FALLBACK_REALISTIC_MAX = 0.75


def _wilson_lower(wins: int, total: int, z: float = 1.96) -> float:
    if total == 0:
        return 0.0
    p_hat = wins / total
    z2 = z * z
    return (p_hat + z2 / (2 * total) - z * math.sqrt((p_hat * (1 - p_hat) + z2 / (4 * total)) / total)) \
           / (1 + z2 / total)


# ------------------------------------------------------------------
# Pool-level helpers
# ------------------------------------------------------------------

def compute_N_threshold(profiles: list, weights: PVWeights, current_lol_split: str) -> int:
    """
    Derive N (games threshold for F2 confidence curve) from solo queue games in current_lol_split.
    See docs/features/F2_confidence_rank.md for strategy details.

    [param] profiles:          all PlayerProfile objects in the pool
    [param] weights:           PVWeights (reads confidence_strategy and n_override)
    [param] current_lol_split: active LoL split key e.g. "S2026" — from TournamentConfig.current_lol_split

    Returns N (int), minimum 1.
    """
    if weights.n_override is not None:
        return max(1, weights.n_override)

    games_list: list[int] = []
    for profile in profiles:
        if not profile.stats or not profile.stats.rank_data:
            continue
        agg = next((s for s in profile.stats.rank_data.solo_splits if s.season == current_lol_split), None)
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


def compute_n_historical_thresholds(
    profiles: list,
    weights: PVWeights,
    past_seasons: list[str],
) -> dict[str, int]:
    """
    Per-split N for F1 confidence curve. max(n_historical_floor, pool_stat_for_split).
    Uses same confidence_strategy as compute_N_threshold (F2).

    [param] profiles:     all PlayerProfile objects in the pool
    [param] weights:      PVWeights (reads confidence_strategy and n_historical_floor)
    [param] past_seasons: historical split keys to compute N for, e.g. ["S2025", "S2024 S3"]

    Returns dict mapping season key → N (int, >= n_historical_floor).
    """
    result: dict[str, int] = {}
    for season in past_seasons:
        games_list: list[int] = []
        for profile in profiles:
            if not profile.stats or not profile.stats.rank_data:
                continue
            agg = next((s for s in profile.stats.rank_data.solo_splits if s.season == season), None)
            if not agg:
                continue
            g = (agg.wins or 0) + (agg.losses or 0)
            if g > 0:
                games_list.append(g)
        if not games_list:
            result[season] = weights.n_historical_floor
            continue
        strategy = weights.confidence_strategy
        if strategy == ConfidenceThresholdStrategy.MEDIAN:
            pool_stat = int(statistics.median(games_list))
        elif strategy == ConfidenceThresholdStrategy.P25:
            sorted_games = sorted(games_list)
            idx = max(0, int(len(sorted_games) * 0.25) - 1)
            pool_stat = sorted_games[idx]
        elif strategy == ConfidenceThresholdStrategy.MEAN_1SD:
            mean = statistics.mean(games_list)
            std = statistics.stdev(games_list) if len(games_list) >= 2 else 0.0
            pool_stat = int(mean - std)
        else:
            pool_stat = _FALLBACK_N
        result[season] = max(weights.n_historical_floor, pool_stat)
    return result


def evaluate_eligibility(profile, eligibility_config) -> bool:
    """
    Returns True if the player meets tournament eligibility requirements.
    Returns True when eligibility_config is None (no rule configured).

    [param] profile:            PlayerProfile — must have profile.stats.rank_data populated
    [param] eligibility_config: EligibilityConfig from TournamentConfig, or None
    """
    if eligibility_config is None:
        return True
    if not profile.stats or not profile.stats.rank_data:
        return False
    splits_by_season = {s.season: s for s in profile.stats.rank_data.solo_splits}
    primary = splits_by_season.get(eligibility_config.primary_split)
    primary_games = ((primary.wins or 0) + (primary.losses or 0)) if primary else 0
    if primary_games >= eligibility_config.primary_min_games:
        return True
    if eligibility_config.backup_split and eligibility_config.backup_min_games:
        backup = splits_by_season.get(eligibility_config.backup_split)
        backup_games = ((backup.wins or 0) + (backup.losses or 0)) if backup else 0
        if backup_games >= eligibility_config.backup_min_games:
            return True
    return False


def compute_realistic_max(profiles: list, weights: PVWeights, tournament_round: str) -> float:
    """
    Derive the pool's maximum Wilson LB from in-house records. Used to normalize F3.
    See docs/features/F3_inhouse_wilson.md for formula details.

    [param] profiles:         all PlayerProfile objects in the pool
    [param] weights:          PVWeights (reads min_games_threshold, wilson_z, realistic_max_override)
    [param] tournament_round: composite round key e.g. "GCS-S4" — from TournamentConfig.round_id

    Returns realistic_max (float). Falls back to _FALLBACK_REALISTIC_MAX if pool has no in-house data.
    """
    if weights.realistic_max_override is not None:
        return weights.realistic_max_override

    wilson_lbs: list[float] = []
    for profile in profiles:
        season_entry = next((sd for sd in profile.season_data if sd.season == tournament_round), None)
        if not season_entry:
            continue
        if season_entry.inhouse_wins is None or season_entry.inhouse_losses is None:
            continue
        total = season_entry.inhouse_wins + season_entry.inhouse_losses
        if total < weights.min_games_threshold:
            continue
        wilson_lbs.append(_wilson_lower(season_entry.inhouse_wins, total, z=weights.wilson_z))

    return max(wilson_lbs) if wilson_lbs else _FALLBACK_REALISTIC_MAX


# ------------------------------------------------------------------
# Single-profile computation
# ------------------------------------------------------------------

def compute_pv(
    profile,
    weights: PVWeights,
    N_threshold: int,
    tournament_round: str,
    current_lol_split: str,
    realistic_max: float = _FALLBACK_REALISTIC_MAX,
    n_historical_thresholds: "dict[str, int] | None" = None,
) -> "ComputedPV":
    """
    Compute PV for a single PlayerProfile.
    Feature docs: docs/features/F1_historical_peak.md through F4_manual_adjustments.md

    [param] profile:                  PlayerProfile — must have profile.stats populated (run AGGREGATE_RANK_STATS first)
    [param] weights:                  PVWeights with all tunable parameters
    [param] N_threshold:              games threshold for F2 confidence curve — compute via compute_N_threshold()
    [param] tournament_round:         composite round key e.g. "GCS-S4" — from TournamentConfig.round_id
    [param] current_lol_split:        active LoL split e.g. "S2026" — from TournamentConfig.current_lol_split
    [param] realistic_max:            pool's max Wilson LB for F3 normalization — compute via compute_realistic_max()
    [param] n_historical_thresholds:  per-split N for F1 confidence — compute via compute_n_historical_thresholds()

    Returns ComputedPV. point_value is None when flag_reason is set (no usable rank data).
    """
    features = PVFeatures()
    splits_by_season: dict = {}
    if profile.stats and profile.stats.rank_data:
        splits_by_season = {agg.season: agg for agg in profile.stats.rank_data.solo_splits}

    # F1 — Time-Decayed Historical Peak with confidence weighting (see docs/features/F1_historical_peak.md)
    F1: Optional[float] = None
    if splits_by_season:
        past_seasons = PAST_YEAR_SEASONS[:weights.history_splits]
        base_weights = weights.historical_base_weights[:weights.history_splits]
        available: list[tuple[float, float]] = []
        scoreable_base_w = 0.0  # sum of base_w for splits with valid peak_rank (f1_confidence denominator)
        for season_key, base_w in zip(past_seasons, base_weights):
            agg = splits_by_season.get(season_key)
            if not agg or not agg.peak_rank:
                continue
            score = rank_score(agg.peak_rank)
            if score is None:
                continue
            scoreable_base_w += base_w
            games = (agg.wins or 0) + (agg.losses or 0)
            n_hist = (n_historical_thresholds or {}).get(season_key, weights.n_historical_floor)
            confidence = (1.0 - math.exp(-games / n_hist)) if n_hist > 0 and games > 0 else 0.0
            eff_w = base_w * confidence
            if eff_w > 0:
                available.append((eff_w, score))
        if available:
            total_w = sum(w for w, _ in available)
            F1 = sum((w / total_w) * s for w, s in available)
            features.historical_score = round(F1, 3)
            features.splits_used = len(available)
            if scoreable_base_w > 0:
                features.f1_confidence = round(total_w / scoreable_base_w, 4)

    # F2 — Confidence-Adjusted Current Rank (see docs/features/F2_confidence_rank.md)
    # Regression target is the player's own all-time peak — not a global default.
    F2: Optional[float] = None
    default_rank_str: Optional[str] = None
    if profile.stats and profile.stats.all_time_peak_rank:
        s = rank_score(profile.stats.all_time_peak_rank)
        if s is not None:
            default_rank_str = profile.stats.all_time_peak_rank

    current_agg = splits_by_season.get(current_lol_split)
    games = (current_agg.wins or 0) + (current_agg.losses or 0) if current_agg else 0
    confidence = 1.0 - math.exp(-games / N_threshold) if N_threshold > 0 else 0.0

    rank_pts: Optional[float] = None
    if profile.stats and profile.stats.current_rank:
        rank_pts = rank_score(profile.stats.current_rank)

    if rank_pts is not None:
        if default_rank_str is not None:
            default_pts = rank_score(default_rank_str)
            F2 = confidence * rank_pts + (1.0 - confidence) * default_pts
        else:
            F2 = rank_pts
            confidence = 1.0

    features.current_rank_pts    = round(rank_pts, 3) if rank_pts is not None else None
    features.games_played         = games
    features.confidence           = round(confidence, 4)
    features.default_rank_used    = default_rank_str
    features.adjusted_current_pts = round(F2, 3) if F2 is not None else None
    features.n_threshold_used     = N_threshold

    season_entry = next((sd for sd in profile.season_data if sd.season == tournament_round), None)
    if season_entry and season_entry.stated_current_rank and rank_pts is not None:
        stated_pts = rank_score(season_entry.stated_current_rank)
        if stated_pts is not None:
            features.stated_rank_diff = round(stated_pts - rank_pts, 3)

    # F3 — In-House Wilson Modifier (see docs/features/F3_inhouse_wilson.md)
    if season_entry and season_entry.inhouse_wins is not None and season_entry.inhouse_losses is not None:
        ih_wins, ih_losses = season_entry.inhouse_wins, season_entry.inhouse_losses
        ih_total = ih_wins + ih_losses
        features.inhouse_wins   = ih_wins
        features.inhouse_losses = ih_losses
        features.inhouse_total  = ih_total
        if ih_total >= weights.min_games_threshold:
            wlb = _wilson_lower(ih_wins, ih_total, z=weights.wilson_z)
            features.wilson_lower = round(wlb, 4)
            if wlb > 0.5 and realistic_max > 0.5:
                inhouse_normalized = max(0.0, wlb - 0.5) / (realistic_max - 0.5)
                features.inhouse_modifier = round(min(inhouse_normalized, 1.0) * weights.max_bonus_points, 3)

    # F4 — Manual Adjustments (see docs/features/F4_manual_adjustments.md)
    manual_adj_total = sum(adj.value for adj in season_entry.manual_adjustments) if season_entry else 0.0
    features.manual_adjustment_total = round(manual_adj_total, 3)

    # Combine → final PV
    valid: list[tuple[float, float]] = []
    if F1 is not None:
        valid.append((weights.w_historical, F1))
    if F2 is not None:
        valid.append((weights.w_current, F2))

    if not valid:
        return ComputedPV(features=features, weights_used=weights, pv_rank_only=None, point_value=None, flag_reason="no_data")

    total_w = sum(w for w, _ in valid)
    base_pv = sum((w / total_w) * s for w, s in valid)
    point_value = round(base_pv + weights.baseline - features.inhouse_modifier - manual_adj_total, 1)

    return ComputedPV(
        features=features,
        weights_used=weights,
        pv_rank_only=round(base_pv, 3),
        point_value=point_value,
    )
