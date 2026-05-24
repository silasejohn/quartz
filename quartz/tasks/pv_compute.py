"""
Task: PV_COMPUTE
Compute Point Value for each player and write to profile.stats.computed_pv.

Also writes round(point_value) to SeasonData.point_value for the current
tournament round for easy downstream access.

N threshold and realistic_max are derived from the full pool regardless of
any player filter — per-player PV must be comparable across the whole pool.

Requires AGGREGATE_RANK_STATS to have run first (profile.stats must be populated).
"""

from quartz.tournament_config import TournamentConfig
from quartz.player_registry import PlayerRegistry
from quartz.utils.color_utils import info_print, warning_print, success_print


def run(
    config: TournamentConfig,
    registry: PlayerRegistry,
    players: list[str] | None = None,
    weights=None,
) -> None:
    """
    [param] config:   TournamentConfig — uses round_id and current_lol_split
    [param] registry: PlayerRegistry — profiles are loaded and saved here
    [param] players:  optional list of discord_usernames to limit scope. None = all.
    [param] weights:  PVWeights instance. If None, loads from pv_weights.json in
                      config.abs_data_dir, falling back to PVWeights() defaults.
    """
    from quartz.pv_compute import compute_N_threshold, compute_realistic_max, compute_pv
    from quartz.pv_weights_io import load_weights

    if weights is None:
        weights, from_file = load_weights(config.abs_data_dir)
        info_print(f"PV_COMPUTE: using weights from {'pv_weights.json' if from_file else 'defaults'}")

    all_profiles = registry.load_all()
    players_lower = {p.lower() for p in players} if players else None
    target_profiles = (
        [p for p in all_profiles if p.effective_id.lower() in players_lower]
        if players_lower else all_profiles
    )

    N = compute_N_threshold(all_profiles, weights, config.current_lol_split)
    info_print(f"PV_COMPUTE: N threshold = {N} games (strategy={weights.confidence_strategy}, pool={len(all_profiles)} players)")
    realistic_max = compute_realistic_max(all_profiles, weights, config.round_id)
    info_print(f"PV_COMPUTE: in-house realistic_max Wilson LB = {realistic_max:.4f}")

    computed = flagged = 0
    for profile in target_profiles:
        if not profile.stats:
            warning_print(f"  Skipping {profile.effective_id} — no enrichment data (run AGGREGATE_RANK_STATS first)")
            continue

        pv_result = compute_pv(profile, weights, N, config.round_id, config.current_lol_split, realistic_max)
        profile.stats.computed_pv = pv_result

        season_entry = next((sd for sd in profile.season_data if sd.season == config.round_id), None)
        if season_entry:
            season_entry.point_value = (
                None if pv_result.point_value is None else round(pv_result.point_value)
            )

        profile.touch()
        registry.save(profile)

        if pv_result.flagged:
            flagged += 1
            warning_print(f"  {profile.effective_id}: PV = None (no usable rank data)")
        else:
            info_print(f"  {profile.effective_id}: PV = {pv_result.point_value}")
        computed += 1

    success_print(f"PV_COMPUTE: {computed} profiles processed, {flagged} flagged (no data)")
