"""
view_player.py
Detailed view of a single player's profile data — accounts, rank history, PV breakdown.

Usage:
    python3 view_player.py
    python3 view_player.py <player_id>
"""

import sys

from quartz.tournament_config import load_tournament_config
from quartz.player_registry import PlayerRegistry
from quartz.constants import SEASON_ORDER, PAST_YEAR_SEASONS, rank_score
from cli_shared_filters import prompt_existing_player

SEP_HEAVY = "=" * 60
SEP_LIGHT = "─" * 60
SEP_MID   = "·" * 60


def _r(val, fallback="—"):
    return val if val is not None else fallback


def _pct(val, fallback="—"):
    return f"{val:.0%}" if val is not None else fallback


def print_profile(profile) -> None:
    print(f"\n{SEP_HEAVY}")
    print(f"  {profile.effective_id}  (discord: {profile.discord_id})")
    print(SEP_HEAVY)

    # ------------------------------------------------------------------
    # Season data
    # ------------------------------------------------------------------
    print(f"\n  SEASON DATA")
    print(f"  {SEP_LIGHT}")
    for sd in profile.season_data:
        flagged = "  FLAGGED" if profile.profile_flagged else ""
        print(f"  Season      {sd.season}{flagged}")
        print(f"  Type        {sd.player_type}")
        print(f"  Role        {_r(sd.primary_pos)} / {_r(sd.secondary_pos)}")
        print(f"  Stated Cur  {_r(sd.stated_current_rank)}")
        print(f"  Stated Peak {_r(sd.stated_peak_rank)}")
        print(f"  Point Value {_r(sd.point_value)}")
        if sd.inhouse_wins is not None or sd.inhouse_losses is not None:
            ih_w = sd.inhouse_wins or 0
            ih_l = sd.inhouse_losses or 0
            print(f"  In-House    {ih_w}W / {ih_l}L  ({ih_w + ih_l} games)")
        if sd.manual_adjustments:
            print(f"  Adjustments {len(sd.manual_adjustments)} adjustment(s)")
        print()

    # ------------------------------------------------------------------
    # Accounts
    # ------------------------------------------------------------------
    print(f"  ACCOUNTS  ({len(profile.accounts)} total)")
    print(f"  {SEP_LIGHT}")
    for acc in profile.accounts:
        status_parts = []
        if acc.archived:
            status_parts.append("ARCHIVED")
        if acc.account_flagged:
            status_parts.append("FLAGGED")
        if acc.update_riot_id:
            status_parts.append("NAME CHANGED")
        status = "  [" + ", ".join(status_parts) + "]" if status_parts else ""

        print(f"  {acc.riot_id}  ({acc.player_region})  lv{_r(acc.account_level)}{status}")
        if acc.urls.opgg_url:
            print(f"    OP.GG  {acc.urls.opgg_url}")

        if acc.rank_data and acc.rank_data.solo_splits:
            print(f"    {'Season':<14}  {'Peak Rank':<22}  {'Split Rank':<22}  W/L")
            print(f"    {'·'*56}")
            for split in acc.rank_data.solo_splits:
                w = f"{split.wins}W" if split.wins is not None else "—"
                l = f"{split.losses}L" if split.losses is not None else "—"
                wl = f"{w}/{l}" if split.wins is not None or split.losses is not None else "—"
                print(
                    f"    {split.season:<14}  {_r(split.peak_rank):<22}  "
                    f"{_r(split.split_rank):<22}  {wl}"
                )
        else:
            print(f"    (no rank data scraped)")
        print()

    # ------------------------------------------------------------------
    # Enrichment
    # ------------------------------------------------------------------
    d = profile.stats
    if not d:
        print(f"  ENRICHMENT  (not computed — run AGGREGATE_RANK_STATS)")
        return

    print(f"  ENRICHMENT")
    print(f"  {SEP_LIGHT}")
    print(f"  All-Time Peak   {_r(d.all_time_peak_rank)}")
    print(f"  Current Rank    {_r(d.current_rank)}")

    if d.rank_data and d.rank_data.solo_splits:
        print(f"\n  Aggregated Split History (best across all accounts)")
        print(f"  {'Season':<14}  {'Peak Rank':<22}  {'Split Rank':<22}  W/L/WR")
        print(f"  {'·'*60}")
        for agg in d.rank_data.solo_splits:
            w   = f"{agg.wins}W"   if agg.wins   is not None else "—"
            l   = f"{agg.losses}L" if agg.losses is not None else "—"
            wr  = f"{agg.win_rate}%" if agg.win_rate is not None else "—"
            wl  = f"{w}/{l} ({wr})" if agg.wins is not None else "—"
            print(
                f"  {agg.season:<14}  {_r(agg.peak_rank):<22}  "
                f"{_r(agg.split_rank):<22}  {wl}"
            )

    # ------------------------------------------------------------------
    # PV breakdown
    # ------------------------------------------------------------------
    pv = d.computed_pv
    if not pv:
        print(f"\n  PV  (not computed — run PV_COMPUTE)")
        return

    f = pv.features
    w = pv.weights_used

    print(f"\n  PV BREAKDOWN")
    print(f"  {SEP_LIGHT}")

    # Feature 1
    print(f"  Feature 1 — Time-Decayed Historical Peak")
    print(f"    Score       {_r(f.historical_score)}  ({f.splits_used} splits used)")
    if d.rank_data:
        splits_by_season = {agg.season: agg for agg in d.rank_data.solo_splits}
        base_weights = w.historical_base_weights[:w.history_splits]
        past_seasons = PAST_YEAR_SEASONS[:w.history_splits]
        available_ws = [
            bw for s, bw in zip(past_seasons, base_weights)
            if splits_by_season.get(s) and splits_by_season[s].peak_rank
        ]
        total_w = sum(available_ws) if available_ws else 1
        for season_key, base_w in zip(past_seasons, base_weights):
            agg = splits_by_season.get(season_key)
            if agg and agg.peak_rank:
                norm_w = base_w / total_w
                pts = rank_score(agg.peak_rank)
                print(f"    {season_key:<14}  peak={_r(agg.peak_rank):<22}  pts={pts:<7.3f}  w={norm_w:.3f}")
            else:
                print(f"    {season_key:<14}  (no data)")

    # Feature 2
    print(f"\n  Feature 2 — Confidence-Adjusted Current Rank")
    print(f"    Current Rank    {_r(d.current_rank)}  ->  pts={_r(f.current_rank_pts)}")
    print(f"    Default Rank    {_r(f.default_rank_used)}  (all-time peak — regression target)")
    print(f"    Games Played    {_r(f.games_played)}  (N={_r(f.n_threshold_used)})")
    print(f"    Confidence      {_pct(f.confidence)}  ->  1 - e^(-{_r(f.games_played)}/{_r(f.n_threshold_used)})")
    print(f"    Adjusted Score  {_r(f.adjusted_current_pts)}")
    if f.stated_rank_diff is not None:
        direction = "understated" if f.stated_rank_diff > 0 else "overstated"
        print(f"    Stated Diff     {f.stated_rank_diff:+.3f}  ({direction})")

    # Feature 3
    if f.inhouse_total is not None:
        floor_str = f"  (floor: {w.min_games_threshold} games)"
        print(f"\n  Feature 3 — In-House Modifier")
        print(f"    Record      {_r(f.inhouse_wins)}W / {_r(f.inhouse_losses)}L  ({_r(f.inhouse_total)} games){floor_str}")
        if f.wilson_lower is not None:
            if f.inhouse_modifier == 0.0 and f.wilson_lower <= 0.5:
                wlb_note = "  — WLB <= 0.50, no upside confidence"
            else:
                wlb_note = ""
            print(f"    Wilson LB   {f.wilson_lower:.4f}{wlb_note}")
        elif f.inhouse_total < w.min_games_threshold:
            print(f"    Wilson LB   —  ({f.inhouse_total} < {w.min_games_threshold} games, below floor)")
        ceiling_str = f"{w.realistic_max_override:.4f} (override)" if w.realistic_max_override is not None else "derived from pool"
        print(f"    Ceiling     {ceiling_str}")
        print(f"    Modifier    {f.inhouse_modifier:+.2f}")

    # Feature 4 — Manual Adjustments
    seasons_with_adj = [sd for sd in profile.season_data if sd.manual_adjustments]
    if seasons_with_adj:
        print(f"\n  Feature 4 — Manual Adjustments")
        for sd in seasons_with_adj:
            print(f"    {sd.season}")
            for adj in sd.manual_adjustments:
                note_str = f"  ({adj.note})" if adj.note else ""
                print(f"      {adj.category:<28}  -{adj.value:.1f}{note_str}")
            season_total = sum(adj.value for adj in sd.manual_adjustments)
            print(f"      {'─'*36}")
            print(f"      Total reduction   {season_total:.1f}")
        if f.manual_adjustment_total > 0:
            print(f"    Applied this PV:  -{f.manual_adjustment_total:.1f}")

    # Final formula
    print(f"\n  {SEP_MID}")
    print(f"  F1 (historical)   {_r(f.historical_score):<10}  weight={w.w_historical}")
    print(f"  F2 (current adj)  {_r(f.adjusted_current_pts):<10}  weight={w.w_current}")
    print(f"  base_pv           {pv.pv_rank_only}")
    print(f"  + baseline        +{w.baseline}")
    print(f"  - inhouse mod     {-f.inhouse_modifier:+.2f}")
    print(f"  - manual adj      {-f.manual_adjustment_total:+.2f}")
    print(f"  {'─'*36}")
    flag_str = "  FLAGGED (no data)" if pv.flagged else ""
    print(f"  POINT VALUE       {pv.point_value}{flag_str}")
    print()


def main() -> None:
    config = load_tournament_config()
    registry = PlayerRegistry(config.abs_players_dir)

    if len(sys.argv) > 1:
        query = sys.argv[1]
        ids = registry.player_ids()
        matches = [pid for pid in ids if query.lower() in pid.lower()]
        if not matches:
            print(f"No player found matching '{query}'")
            sys.exit(1)
        if len(matches) > 1:
            print(f"Multiple matches: {', '.join(matches)}")
            sys.exit(1)
        profile = registry.load(matches[0])
    else:
        profile = prompt_existing_player(registry)

    if not profile:
        print("No player selected.")
        sys.exit(1)

    print_profile(profile)


if __name__ == "__main__":
    main()
