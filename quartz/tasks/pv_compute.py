"""
Task: PV_COMPUTE
Compute Point Value for each player and write to profile.stats.computed_pv.

Also writes round(point_value) to SeasonData.point_value for the current
tournament round for easy downstream access.

N threshold and realistic_max are derived from the full pool regardless of
any player filter — per-player PV must be comparable across the whole pool.

Requires AGGREGATE_RANK_STATS to have run first (profile.stats must be populated).
"""

from quartz.player_registry import PlayerRegistry
from quartz.tournament_config import TournamentConfig
from quartz.utils.logging import info_print, success_print, warning_print


def run(
    config: TournamentConfig,
    registry: PlayerRegistry,
    players: list[str] | None = None,
    weights=None,
) -> None:
    """
    [param] config:   TournamentConfig — uses round_id, current_lol_split, and eligibility
    [param] registry: PlayerRegistry — profiles are loaded and saved here
    [param] players:  optional list of discord_usernames to limit scope. None = all.
    [param] weights:  PVWeights instance. If None, loads from pv_weights.json in
                      config.abs_data_dir, falling back to PVWeights() defaults.
    """
    from quartz.account_flags import evaluate_account_flags
    from quartz.constants import PAST_YEAR_SEASONS
    from quartz.models.pv_model import ComputedPV
    from quartz.pv_compute import (
        compute_atp_miss_scale,
        compute_atp_season_min_games,
        compute_champ_dpm_baseline,
        compute_n_historical_thresholds,
        compute_N_threshold,
        compute_pv,
        compute_realistic_max,
        evaluate_eligibility,
    )
    from quartz.pv_weights_io import load_weights

    if weights is None:
        weights, from_file = load_weights(config.abs_data_dir)
        info_print(f"PV_COMPUTE: using weights from {'pv_weights.json' if from_file else 'defaults'}")

    all_profiles = registry.load_all()
    players_lower = {p.lower() for p in players} if players else None

    # "other" = tracked players not in the tournament — never compute PV for them
    def _is_other(profile) -> bool:
        sd = next((s for s in profile.season_data if s.season == config.round_id), None)
        return sd is not None and sd.player_type == "other"

    other_profiles = [p for p in all_profiles if _is_other(p)]
    tournament_profiles = [p for p in all_profiles if not _is_other(p)]
    if other_profiles:
        warning_print(
            f"PV_COMPUTE: skipping {len(other_profiles)} player(s) with type='other' "
            f"(not in tournament): {', '.join(p.effective_id for p in other_profiles)}"
        )
    target_profiles = (
        [p for p in tournament_profiles if p.effective_id.lower() in players_lower]
        if players_lower else tournament_profiles
    )

    N = compute_N_threshold(tournament_profiles, weights, config.current_lol_split)
    info_print(f"PV_COMPUTE: N threshold = {N} games (strategy={weights.confidence_strategy}, pool={len(tournament_profiles)} players)")
    realistic_max = compute_realistic_max(tournament_profiles, weights, config.round_id)
    info_print(f"PV_COMPUTE: in-house realistic_max Wilson LB = {realistic_max:.4f}")

    past_seasons = PAST_YEAR_SEASONS[:weights.history_splits]
    n_hist_thresholds = compute_n_historical_thresholds(tournament_profiles, weights, past_seasons)
    info_print(f"PV_COMPUTE: N_historical thresholds = {n_hist_thresholds}")

    champ_median, champ_stddev = compute_champ_dpm_baseline(tournament_profiles, weights, config.current_lol_split)
    info_print(f"PV_COMPUTE: champ DPM baseline = {champ_median:.1f} (stddev={champ_stddev:.1f}, pool={len(tournament_profiles)} players)")
    weights = weights.model_copy(update={"champ_dpm_baseline": champ_median, "champ_dpm_pool_stddev": champ_stddev})

    from quartz.constants import SEASON_ORDER
    atp_miss_scale = compute_atp_miss_scale(tournament_profiles, weights)
    atp_season_min_games = {
        season: compute_atp_season_min_games(tournament_profiles, weights, season)
        for season in SEASON_ORDER
    }
    info_print(f"PV_COMPUTE: ATP miss scale = {atp_miss_scale:.2f}, season min games = {atp_season_min_games}")

    computed = flagged = ineligible = 0
    for profile in target_profiles:
        if not profile.stats:
            warning_print(f"  Skipping {profile.effective_id} — no enrichment data (run AGGREGATE_RANK_STATS first)")
            continue

        # refresh account flags for all active accounts
        for account in profile.accounts:
            if not account.archived:
                evaluate_account_flags(account, weights)

        season_entry = next((sd for sd in profile.season_data if sd.season == config.round_id), None)

        eligible = evaluate_eligibility(profile, config.eligibility)
        if season_entry:
            season_entry.eligible = eligible

        if not eligible:
            shadow = compute_pv(
                profile, weights, N, config.round_id,
                config.current_lol_split, realistic_max, n_hist_thresholds,
                atp_season_min_games, atp_miss_scale,
            )
            pv_result = ComputedPV(
                features=shadow.features,
                weights_used=weights,
                pv_rank_only=None,
                point_value=None,
                flag_reason="ineligible",
                shadow_pv=shadow.point_value,
            )
            if season_entry:
                season_entry.point_value = None
                season_entry.shadow_point_value = (
                    round(shadow.point_value) if shadow.point_value is not None else None
                )
            ineligible += 1
            warning_print(f"  {profile.effective_id}: INF (ineligible) — shadow PV = {shadow.point_value}")
        else:
            pv_result = compute_pv(
                profile, weights, N, config.round_id,
                config.current_lol_split, realistic_max, n_hist_thresholds,
                atp_season_min_games, atp_miss_scale,
            )
            if season_entry:
                season_entry.point_value = (
                    None if pv_result.point_value is None else round(pv_result.point_value)
                )
                season_entry.shadow_point_value = None

            if pv_result.flag_reason == "no_data":
                flagged += 1
                warning_print(f"  {profile.effective_id}: PV = None (no usable rank data)")
            else:
                info_print(f"  {profile.effective_id}: PV = {pv_result.point_value}")

        profile.stats.computed_pv = pv_result
        profile.touch()
        registry.save(profile)
        computed += 1

    success_print(
        f"PV_COMPUTE: {computed} profiles processed, "
        f"{flagged} no-data, {ineligible} ineligible"
    )
