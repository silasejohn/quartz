"""
compute_pv.py
Run PV_COMPUTE (and optionally AGGREGATE_RANK_STATS) for all players.
Prints a summary table sorted by PV ascending (strongest players first).

Usage:
    python3 compute_pv.py               # PV_COMPUTE with active weights
    python3 compute_pv.py --recalculate  # AGGREGATE_RANK_STATS then PV_COMPUTE
    python3 compute_pv.py --tune         # interactive weight editor (no PV compute)
"""

import argparse

from quartz.tournament_config import load_tournament_config
from quartz.pipeline_runner import PipelineRunner, Task
from quartz.player_registry import PlayerRegistry
from quartz.models.pv_model import PVWeights, ConfidenceThresholdStrategy
from quartz.pv_weights_io import load_weights, save_weights
from quartz.utils.logging import info_print, success_print, warning_print, console
from cli_shared_filters import prompt_season, prompt_player_types, filter_profiles



# ---------------------------------------------------------------------------
# Weight tuning CLI
# ---------------------------------------------------------------------------

_TUNABLE_FIELDS = [
    ("w_historical",           "float",       "Feature 1 blend weight"),
    ("w_current",              "float",       "Feature 2 blend weight"),
    ("historical_base_weights","floatlist",   "Decay curve weights [split_1..split_4]"),
    ("history_splits",         "int14",       "Max past splits to include (1-4)"),
    ("confidence_strategy",    "strategy",    "Games threshold strategy (median/p25/mean_1sd)"),
    ("n_override",             "int_none",    "Override N directly (integer or 'none')"),
    ("baseline",               "float_signed","Baseline added to every player's PV (can be negative)"),
    ("max_bonus_points",       "float",       "F3: in-house modifier ceiling (pts)"),
    ("min_games_threshold",    "int_pos",     "F3: min in-house games to activate modifier"),
    ("wilson_z",               "wilson_z",    "F3: CI z-score — 1.28=80% (lenient), 1.645=90%, 1.96=95% (strict)"),
    ("realistic_max_override", "float_none",  "F3: override pool Wilson LB ceiling (float or 'none')"),
]


def _fmt(val) -> str:
    if isinstance(val, list):
        return "[" + ", ".join(str(v) for v in val) + "]"
    return str(val) if val is not None else "none"


def _parse_field(field_type: str, raw: str):
    """Parse and validate user input for a given field type. Raises ValueError on bad input."""
    raw = raw.strip()
    if field_type == "float":
        v = float(raw)
        if v < 0:
            raise ValueError("must be >= 0")
        return v
    elif field_type == "float_signed":
        return float(raw)
    elif field_type == "floatlist":
        parts = [p.strip() for p in raw.strip("[]").split(",")]
        if not 2 <= len(parts) <= 4:
            raise ValueError("enter 2-4 comma-separated values")
        vals = [float(p) for p in parts]
        if any(v <= 0 for v in vals):
            raise ValueError("all weights must be > 0")
        return vals
    elif field_type == "int14":
        v = int(raw)
        if not 1 <= v <= 4:
            raise ValueError("must be 1-4")
        return v
    elif field_type == "strategy":
        valid = [e.value for e in ConfidenceThresholdStrategy]
        if raw not in valid:
            raise ValueError(f"must be one of: {', '.join(valid)}")
        return ConfidenceThresholdStrategy(raw)
    elif field_type == "int_none":
        if raw.lower() == "none":
            return None
        v = int(raw)
        if v < 1:
            raise ValueError("must be a positive integer or 'none'")
        return v
    elif field_type == "int_pos":
        v = int(raw)
        if v < 1:
            raise ValueError("must be a positive integer")
        return v
    elif field_type == "wilson_z":
        v = float(raw)
        if not 0.5 <= v <= 3.0:
            raise ValueError("must be between 0.5 and 3.0  (common: 1.28=80%, 1.645=90%, 1.96=95%)")
        return v
    elif field_type == "float_none":
        if raw.lower() == "none":
            return None
        v = float(raw)
        if not 0.0 < v <= 1.0:
            raise ValueError("must be a float in (0.0, 1.0] or 'none'")
        return v
    raise ValueError(f"unknown field type: {field_type}")


def run_tune_mode(base_data_dir: str) -> None:
    weights, from_file = load_weights(base_data_dir)
    source = "pv_weights.json" if from_file else "defaults (no pv_weights.json yet)"
    print(f"\n  Weight tuning mode  —  current values from: {source}")

    while True:
        print(f"\n  {'─'*52}")
        for i, (field, _, desc) in enumerate(_TUNABLE_FIELDS, 1):
            val = getattr(weights, field)
            print(f"  {i}.  {field:<28}  {_fmt(val):<20}  {desc}")
        print(f"  {'─'*52}")
        print(f"  s.  Save and exit")
        print(f"  q.  Quit without saving")

        raw = input("\n  > ").strip().lower()

        if raw == "q":
            print("  Cancelled — no changes saved.")
            return
        if raw == "s":
            path = save_weights(weights, base_data_dir)
            success_print(f"  Saved to {path}")
            return

        if not raw.isdigit() or not 1 <= int(raw) <= len(_TUNABLE_FIELDS):
            print(f"  Enter a number 1-{len(_TUNABLE_FIELDS)}, 's', or 'q'.")
            continue

        idx = int(raw) - 1
        field, field_type, desc = _TUNABLE_FIELDS[idx]
        current = getattr(weights, field)
        print(f"\n  {field}  (current: {_fmt(current)})")

        while True:
            new_raw = input("  new value > ").strip()
            try:
                new_val = _parse_field(field_type, new_raw)
                weights = weights.model_copy(update={field: new_val})
                print(f"  {field}  ->  {_fmt(new_val)}")
                break
            except (ValueError, TypeError) as e:
                print(f"  Invalid: {e}")


# ---------------------------------------------------------------------------
# PV table
# ---------------------------------------------------------------------------

def print_pv_table(
    players_dir: str,
    tournament: str,
    season_filter: str | None = None,
    type_filter: set[str] | None = None,
) -> None:
    registry = PlayerRegistry(players_dir)
    all_profiles = registry.load_all()

    _, type_scoped, scope_label, type_label = filter_profiles(
        all_profiles, season_filter, type_filter
    )

    rows = []
    for profile in type_scoped:
        pv = conf = splits = current_rank = peak_rank = None
        f1_contrib = f2_contrib = f3_mod = f4_adj = None

        player_type = None
        if season_filter:
            sd = next((s for s in profile.season_data if s.season == season_filter), None)
            if sd:
                player_type = sd.player_type
        elif profile.season_data:
            player_type = profile.season_data[-1].player_type

        if profile.stats:
            current_rank = profile.stats.current_rank
            if profile.stats.computed_pv:
                cpv = profile.stats.computed_pv
                f   = cpv.features
                w   = cpv.weights_used
                pv      = cpv.point_value
                conf    = f.confidence
                peak_rank = f.default_rank_used

                total_w = 0.0
                if f.historical_score is not None:
                    total_w += w.w_historical
                if f.adjusted_current_pts is not None:
                    total_w += w.w_current
                if total_w > 0:
                    if f.historical_score is not None:
                        f1_contrib = (w.w_historical / total_w) * f.historical_score
                    if f.adjusted_current_pts is not None:
                        f2_contrib = (w.w_current / total_w) * f.adjusted_current_pts
                f3_mod = f.inhouse_modifier
                f4_adj = f.manual_adjustment_total

        rows.append((profile.effective_id, pv, conf, current_rank, peak_rank,
                     f1_contrib, f2_contrib, f3_mod, f4_adj, player_type))

    rows.sort(key=lambda x: (x[1] is None, x[1] if x[1] is not None else float("inf")))

    CP = 24   # player col
    RK = 20   # rank cols
    print(f"\n{'='*106}")
    print(f"  {tournament} — Point Value  |  {scope_label}  |  Types: {type_label}  ({len(rows)} players)")
    print(f"{'='*106}")
    print(f"  {'Player':<{CP}}  {'PV':>6}  {'Cur Rank':<{RK}}  {'Peak Rank':<{RK}}  {'Conf':>5}  {'F1':>7}  {'F2':>7}  {'F3':>5}  {'F4':>5}")
    print(f"  {'─'*98}")

    def _fc(val, fmt=".1f"):
        return format(val, fmt) if val is not None else "—"

    for player_id, pv, conf, cur_rank, peak_rank, f1, f2, f3, f4, ptype in rows:
        conf_str  = f"{conf:.0%}" if conf is not None else "—"
        cur_str   = cur_rank  or "—"
        peak_str  = peak_rank or "—"
        is_cap    = ptype == "captain"
        if pv is None:
            line = f"  {player_id:<{CP}}  {'—':>6}  {cur_str:<{RK}}  {peak_str:<{RK}}  {'—':>5}  {'—':>7}  {'—':>7}  {'—':>5}  {'—':>5}  (not computed)"
        else:
            f3_str = f"{-f3:+.2f}" if f3 else "—"
            f4_str = f"{-f4:+.2f}" if f4 else "—"
            line = f"  {player_id:<{CP}}  {pv:>6.1f}  {cur_str:<{RK}}  {peak_str:<{RK}}  {conf_str:>5}  {_fc(f1):>7}  {_fc(f2):>7}  {f3_str:>5}  {f4_str:>5}"
        console.print(line, style="cyan", markup=False) if is_cap else console.print(line, markup=False)
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Compute player PV scores")
    parser.add_argument(
        "--recalculate", action="store_true",
        help="Run AGGREGATE_RANK_STATS before PV_COMPUTE"
    )
    parser.add_argument(
        "--tune", action="store_true",
        help="Interactive weight editor — edit and save weights, then exit without computing"
    )
    args = parser.parse_args()

    config = load_tournament_config()

    if args.tune:
        run_tune_mode(config.abs_data_dir)
        return

    season_filter = prompt_season(config.round_ids)
    type_filter   = prompt_player_types()

    runner = PipelineRunner(config)

    if args.recalculate:
        info_print("Running AGGREGATE_RANK_STATS...")
        runner.run_task(Task.AGGREGATE_RANK_STATS)

    info_print("Running PV_COMPUTE...")
    runner.run_task(Task.PV_COMPUTE)

    print_pv_table(config.abs_players_dir, config.tournament, season_filter, type_filter)


if __name__ == "__main__":
    main()
