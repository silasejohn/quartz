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

from quartz.constants import METAL_RANKS, PAST_YEAR_SEASONS, RANK_POINTS, SEASON_ORDER, rank_score
from quartz.models.pv_model import (
    ComputedPV,
    ConfidenceThresholdStrategy,
    PVFeatures,
    PVWeights,
)

_FALLBACK_N = 50
_FALLBACK_REALISTIC_MAX = 0.75
_FALLBACK_ATP_MISS_SCALE = 25.0
_DPM_SCORE_BASELINE = 5.0  # global average DPM Score — MVP residual baseline

# Bracket structure: (start_index, end_index) into games-sorted champion list
_CHAMP_BRACKET_RANGES = [(0, 1), (1, 3), (3, 5), (5, 8), (8, 13)]


def tier_width_at_pv(pv: float) -> float:
    """
    PV span of one full tier (4 divisions) at the given PV position.
    Finds the nearest metal rank division by PV, then returns its tier's full span.
    Derived from RANK_POINTS so it adapts automatically to any rank model shape.
    Falls back to Bronze tier span for the Iron plateau (all divisions flat at 85).
    """
    nearest = min(METAL_RANKS, key=lambda r: abs(RANK_POINTS[r] - pv))
    tier = nearest.split(" ")[0]
    span = RANK_POINTS.get(f"{tier} 4", 0.0) - RANK_POINTS.get(f"{tier} 1", 0.0)
    if span <= 0:
        return RANK_POINTS["Bronze 4"] - RANK_POINTS["Bronze 1"]
    return span


def _collect_bracket_champs(pool, current_lol_split: str, games_min: int) -> list[tuple[int, float]]:
    """
    Collect (games, dpm_score) for ALL-role champion entries with DPM data in the current split.
    Sorted by games descending — this order determines bracket membership.
    Only entries meeting games_min threshold are included; empty brackets zero-fill.
    """
    qualifying: list[tuple[int, float]] = []
    for entry in pool.champions:
        if entry.role != "ALL":
            continue
        for split in entry.splits:
            if split.lol_season != current_lol_split or split.dpm_score is None:
                continue
            games = (split.wins or 0) + (split.losses or 0)
            if games >= games_min:
                qualifying.append((games, split.dpm_score))
            break
    qualifying.sort(key=lambda x: x[0], reverse=True)
    return qualifying


def compute_champion_modifier(
    pool,
    rank_pv: float,
    current_lol_split: str,
    weights: PVWeights,
) -> float:
    """
    Compute the champion pool PV modifier for one queue (solo or flex).

    Bracket assignment: champions sorted by games played (descending). Brackets B1–B5
    cover positions #1, #2-3, #4-5, #6-8, #9-13. Bracket residual = games-weighted
    average of (dpm_score − 5.0). Empty brackets contribute 0 (zero-fill).

    Formula: cap × tanh(scale_factor × raw_delta / cap)
      cap = champ_alpha × tier_width_at_pv(rank_pv)
      Positive return value = above-average pool → lowers PV (stronger player).

    Returns 0.0 if no qualifying champions exist.
    """
    qualifying = _collect_bracket_champs(pool, current_lol_split, weights.champ_games_min)
    if not qualifying:
        return 0.0

    raw_delta = 0.0
    for (start, end), bw in zip(_CHAMP_BRACKET_RANGES, weights.champ_bracket_weights):
        bracket = qualifying[start:end]
        if not bracket:
            continue
        total_games = sum(g for g, _ in bracket)
        if total_games == 0:
            continue
        bracket_residual = sum(g * (score - _DPM_SCORE_BASELINE) for g, score in bracket) / total_games
        raw_delta += bw * bracket_residual

    cap = weights.champ_alpha * tier_width_at_pv(rank_pv)
    if cap <= 0:
        return 0.0
    return cap * math.tanh(weights.champ_scale_factor * raw_delta / cap)


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


def compute_atp_miss_scale(profiles: list, weights: PVWeights) -> float:
    """
    Pool-derived normalization constant for ATP decay miss magnitude.
    Returns 2 × stdev(pool current rank scores). Override via weights.atp_max_miss_scale_override.

    [param] profiles: all PlayerProfile objects in the pool
    [param] weights:  PVWeights (reads atp_max_miss_scale_override)
    """
    if weights.atp_max_miss_scale_override is not None:
        return weights.atp_max_miss_scale_override
    scores = [rank_score(p.stats.current_rank) for p in profiles if p.stats and p.stats.current_rank]
    scores = [s for s in scores if s is not None]
    if len(scores) < 2:
        return _FALLBACK_ATP_MISS_SCALE
    return 2.0 * statistics.stdev(scores)


def compute_atp_season_min_games(profiles: list, weights: PVWeights, season: str) -> int:
    """
    P_k of games played in `season` across the pool. Used as the pool-relative gate
    in the per-season ATP staleness checkpoint.

    [param] profiles: all PlayerProfile objects in the pool
    [param] weights:  PVWeights (reads atp_season_pool_percentile, n_historical_floor)
    [param] season:   season key to compute the percentile for, e.g. "S2025"
    """
    games_list = []
    for profile in profiles:
        if not profile.stats or not profile.stats.rank_data:
            continue
        agg = next((s for s in profile.stats.rank_data.solo_splits if s.season == season), None)
        if agg:
            g = (agg.wins or 0) + (agg.losses or 0)
            if g > 0:
                games_list.append(g)
    if not games_list:
        return weights.n_historical_floor
    games_list.sort()
    idx = max(0, int(len(games_list) * weights.atp_season_pool_percentile) - 1)
    return max(weights.n_historical_floor, games_list[idx])


def _compute_atp_decay(
    atp_rs: float,
    current_rs: float,
    atp_split: str,
    splits_by_season: dict,
    weights: PVWeights,
    n_thresholds: "dict[str, int]",
    atp_season_min_games: "dict[str, int]",
    miss_scale: float,
) -> "tuple[float, float]":
    """
    Compute ATP staleness decay factor and effective ATP rank score for F2 regression.

    For each season after atp_split, checks whether it qualifies as evidence of decline
    (enough games, WR < threshold) and accumulates a decay factor. Returns
    (atp_decay_factor, effective_atp_rs).

    Raises ValueError if a qualifying season has win_rate=None (data integrity issue).
    """
    if atp_split not in SEASON_ORDER:
        return 0.0, atp_rs

    atp_idx = SEASON_ORDER.index(atp_split)
    # SEASON_ORDER is newest-first; post-ATP seasons have lower indices (more recent).
    # Iterate chronologically oldest→newest so evidence accumulates in natural order.
    post_atp_seasons = list(reversed(SEASON_ORDER[:atp_idx]))
    no_decay_prob = 1.0

    for s_key in post_atp_seasons:
        agg = splits_by_season.get(s_key)
        if not agg or not agg.peak_rank:
            continue

        games = (agg.wins or 0) + (agg.losses or 0)
        if games == 0:
            continue

        # Effective minimum games = max of all three volume gates
        # Prior seasons = older than s_key = higher indices in SEASON_ORDER (newest-first)
        s_idx = SEASON_ORDER.index(s_key)
        prior_seasons = SEASON_ORDER[s_idx + 1:]
        prior_games = [
            ((splits_by_season[s].wins or 0) + (splits_by_season[s].losses or 0))
            for s in prior_seasons
            if s in splits_by_season and ((splits_by_season[s].wins or 0) + (splits_by_season[s].losses or 0)) > 0
        ]
        player_avg = statistics.mean(prior_games) if prior_games else 0.0
        personal_min = int(weights.atp_personal_volume_pct * player_avg)
        pool_min = atp_season_min_games.get(s_key, weights.atp_hard_floor_games)
        effective_min = max(weights.atp_hard_floor_games, personal_min, pool_min)

        if games < effective_min:
            continue

        # WR gate — skip seasons where the player is still actively climbing
        win_rate = agg.win_rate
        if win_rate is None:
            raise ValueError(
                f"win_rate is None for season {s_key} with {games} games — "
                f"re-run AGGREGATE_RANK_STATS to recompute win_rate"
            )
        if win_rate >= weights.atp_climbing_wr_threshold:
            continue

        # Season qualifies — compute decay contribution
        season_peak_rs = rank_score(agg.peak_rank)
        if season_peak_rs is None:
            continue

        if season_peak_rs <= atp_rs:
            # ATP re-confirmed this season — reset and stop checking
            no_decay_prob = 1.0
            break

        miss = season_peak_rs - atp_rs
        miss_frac = min(1.0, miss / miss_scale) if miss_scale > 0 else 1.0
        n_s = n_thresholds.get(s_key, weights.n_historical_floor)
        season_conf = (1.0 - math.exp(-games / n_s)) if n_s > 0 else 0.0
        no_decay_prob *= (1.0 - season_conf * miss_frac)

    atp_decay_factor = round(1.0 - no_decay_prob, 4)
    effective_atp_rs = atp_rs * (1.0 - atp_decay_factor) + current_rs * atp_decay_factor
    return atp_decay_factor, effective_atp_rs


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
    atp_season_min_games: "dict[str, int] | None" = None,
    atp_miss_scale: float = _FALLBACK_ATP_MISS_SCALE,
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
    [param] n_historical_thresholds:  per-split N for F1 and ATP decay confidence — compute via compute_n_historical_thresholds()
    [param] atp_season_min_games:     pool P_k games per season for ATP decay gate — compute via compute_atp_season_min_games()
    [param] atp_miss_scale:           miss normalization scale — compute via compute_atp_miss_scale()

    Returns ComputedPV. point_value is None when flag_reason is set (no usable rank data).
    """
    features = PVFeatures()
    splits_by_season: dict = {}
    if profile.stats and profile.stats.rank_data:
        splits_by_season = {agg.season: agg for agg in profile.stats.rank_data.solo_splits}

    features.n_historical_thresholds_used = dict(n_historical_thresholds or {})

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
    # Regression target is the player's effective ATP (all-time peak with staleness decay applied).
    F2: Optional[float] = None
    default_rank_str: Optional[str] = None
    atp_rs: Optional[float] = None
    if profile.stats and profile.stats.all_time_peak_rank:
        s = rank_score(profile.stats.all_time_peak_rank)
        if s is not None:
            default_rank_str = profile.stats.all_time_peak_rank
            atp_rs = s

    current_agg = splits_by_season.get(current_lol_split)
    games = (current_agg.wins or 0) + (current_agg.losses or 0) if current_agg else 0
    confidence = 1.0 - math.exp(-games / N_threshold) if N_threshold > 0 else 0.0

    rank_pts: Optional[float] = None
    if profile.stats and profile.stats.current_rank:
        rank_pts = rank_score(profile.stats.current_rank)

    # ATP staleness decay — find which split contains the ATP, then compute decay
    atp_decay_factor: float = 0.0
    effective_atp_rs: Optional[float] = atp_rs
    if atp_rs is not None and rank_pts is not None and splits_by_season:
        # Identify the split where the all-time peak was set
        best_rs: Optional[float] = None
        atp_split: Optional[str] = None
        for s_key, agg in splits_by_season.items():
            if not agg.peak_rank:
                continue
            rs = rank_score(agg.peak_rank)
            if rs is not None and (best_rs is None or rs < best_rs):
                best_rs = rs
                atp_split = s_key
        if atp_split is not None:
            n_thresh_all = dict(n_historical_thresholds or {})
            n_thresh_all.setdefault(current_lol_split, N_threshold)
            atp_decay_factor, effective_atp_rs = _compute_atp_decay(
                atp_rs=atp_rs,
                current_rs=rank_pts,
                atp_split=atp_split,
                splits_by_season=splits_by_season,
                weights=weights,
                n_thresholds=n_thresh_all,
                atp_season_min_games=atp_season_min_games or {},
                miss_scale=atp_miss_scale,
            )

    if rank_pts is not None:
        if effective_atp_rs is not None:
            F2 = confidence * rank_pts + (1.0 - confidence) * effective_atp_rs
        else:
            F2 = rank_pts
            confidence = 1.0

    features.current_rank_pts    = round(rank_pts, 3) if rank_pts is not None else None
    features.games_played         = games
    features.confidence           = round(confidence, 4)
    features.default_rank_used    = default_rank_str
    features.adjusted_current_pts = round(F2, 3) if F2 is not None else None
    features.n_threshold_used     = N_threshold
    features.atp_decay_factor     = round(atp_decay_factor, 4)
    features.effective_atp_rs     = round(effective_atp_rs, 3) if effective_atp_rs is not None else None

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

    # Combine F1 + F2 → rank PV
    valid: list[tuple[float, float]] = []
    if F1 is not None:
        valid.append((weights.w_historical, F1))
    if F2 is not None:
        valid.append((weights.w_current, F2))

    if not valid:
        return ComputedPV(features=features, weights_used=weights, pv_rank_only=None, point_value=None, flag_reason="no_data")

    total_w = sum(w for w, _ in valid)
    rank_pv = sum((w / total_w) * s for w, s in valid)

    # F5/F6 — Champion Pool Modifiers
    # Account selection: rank-anchored — best-ranked account with ≥ champ_account_min_games;
    # falls back to most-games if no account clears the floor.
    # Solo (F5) is bidirectional; Flex (F6) is benefit-only (only lowers PV).
    solo_champ_modifier = 0.0
    flex_champ_modifier = 0.0
    champ_data_missing = True

    if hasattr(profile, "accounts"):
        # Collect (q_games, rank_score, pool) per account per queue.
        # Rank-anchor: prefer the account with best current rank that meets champ_account_min_games.
        # Fall back to most-games account if none clear the floor.
        solo_candidates: list[tuple[int, float, object]] = []  # (q_games, rscore, pool)
        flex_candidates: list[tuple[int, float, object]] = []

        for account in profile.accounts:
            if getattr(account, "archived", False) or not account.champion_data:
                continue
            acct_rank = None
            if account.rank_data:
                split = account.rank_data.get_split(current_lol_split)
                if split:
                    acct_rank = rank_score(split.split_rank)
            rscore = acct_rank if acct_rank is not None else float("inf")

            for queue_attr in ("solo", "flex"):
                q_pool = getattr(account.champion_data, queue_attr)
                q_games = sum(
                    (s.wins or 0) + (s.losses or 0)
                    for e in q_pool.champions
                    if e.role == "ALL"
                    for s in e.splits
                    if s.lol_season == current_lol_split and s.dpm_score is not None
                )
                if queue_attr == "solo":
                    solo_candidates.append((q_games, rscore, q_pool))
                else:
                    flex_candidates.append((q_games, rscore, q_pool))

        def _pick_pool(candidates: list) -> tuple:
            """Return (pool, games) using rank-anchored selection with game floor fallback."""
            if not candidates:
                return None, -1
            qualifying = [(g, r, p) for g, r, p in candidates if g >= weights.champ_account_min_games]
            if qualifying:
                # best rank = lowest rank_score
                best = min(qualifying, key=lambda x: x[1])
            else:
                # fallback: most games
                best = max(candidates, key=lambda x: x[0])
            return best[2], best[0]

        best_solo_pool, best_solo_games = _pick_pool(solo_candidates)
        best_flex_pool, best_flex_games = _pick_pool(flex_candidates)

        if best_solo_pool is not None and best_solo_games >= weights.champ_games_min:
            solo_champ_modifier = compute_champion_modifier(best_solo_pool, rank_pv, current_lol_split, weights)
            champ_data_missing = False
        if best_flex_pool is not None and best_flex_games >= weights.champ_games_min:
            flex_champ_modifier = compute_champion_modifier(best_flex_pool, rank_pv, current_lol_split, weights)
            champ_data_missing = False

    features.solo_champ_modifier = round(solo_champ_modifier, 3)
    features.flex_champ_modifier  = round(flex_champ_modifier, 3)
    features.champ_data_missing   = champ_data_missing

    # Pipeline: rank_pv → F5 (solo, bidirectional) → F6 (flex, benefit-only) → flat adjustments
    after_F5 = rank_pv - solo_champ_modifier
    after_F6 = after_F5 - max(flex_champ_modifier, 0.0)
    point_value = round(after_F6 + weights.baseline - features.inhouse_modifier - manual_adj_total, 1)

    return ComputedPV(
        features=features,
        weights_used=weights,
        pv_rank_only=round(rank_pv, 3),
        point_value=point_value,
    )
