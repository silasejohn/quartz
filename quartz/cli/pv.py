"""
quartz pv — compute and display PV scores.

    quartz pv                   compute PV with active weights
    quartz pv --recalculate     run AGGREGATE_RANK_STATS first, then PV_COMPUTE
    quartz pv --tune            interactive weight editor
"""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from quartz.models.pv_model import ConfidenceThresholdStrategy
from quartz.pipeline_runner import PipelineRunner, Task
from quartz.player_registry import PlayerRegistry
from quartz.pv_weights_io import load_weights, save_weights
from quartz.tournament_config import load_active_tournament
from quartz.utils.logging import info_print, success_print

console = Console()

_TUNABLE_FIELDS = [
    ("w_historical",            "float",       "Feature 1 blend weight"),
    ("w_current",               "float",       "Feature 2 blend weight"),
    ("historical_base_weights", "floatlist",   "Decay curve weights [split_1..split_4]"),
    ("history_splits",          "int14",       "Max past splits to include (1-4)"),
    ("confidence_strategy",     "strategy",    "Games threshold strategy (median/p25/mean_1sd)"),
    ("n_override",              "int_none",    "Override N directly (integer or 'none')"),
    ("baseline",                "float_signed","Baseline added to every player's PV"),
    ("max_bonus_points",        "float",       "F3: in-house modifier ceiling (pts)"),
    ("min_games_threshold",     "int_pos",     "F3: min in-house games to activate modifier"),
    ("wilson_z",                "wilson_z",    "F3: CI z-score — 1.28=80%, 1.645=90%, 1.96=95%"),
    ("realistic_max_override",  "float_none",  "F3: override pool Wilson LB ceiling (float or 'none')"),
]


def _fmt(val) -> str:
    if isinstance(val, list):
        return "[" + ", ".join(str(v) for v in val) + "]"
    return str(val) if val is not None else "none"


def _parse_field(field_type: str, raw: str):
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
            raise ValueError("must be between 0.5 and 3.0")
        return v
    elif field_type == "float_none":
        if raw.lower() == "none":
            return None
        v = float(raw)
        if not 0.0 < v <= 1.0:
            raise ValueError("must be a float in (0.0, 1.0] or 'none'")
        return v
    raise ValueError(f"unknown field type: {field_type}")


def _run_tune_mode(base_data_dir: str) -> None:
    weights, from_file = load_weights(base_data_dir)
    source = "pv_weights.json" if from_file else "defaults (no pv_weights.json yet)"
    typer.echo(f"\n  Weight tuning mode  —  current values from: {source}")

    while True:
        typer.echo(f"\n  {'─'*52}")
        for i, (field, _, desc) in enumerate(_TUNABLE_FIELDS, 1):
            val = getattr(weights, field)
            typer.echo(f"  {i}.  {field:<28}  {_fmt(val):<20}  {desc}")
        typer.echo(f"  {'─'*52}")
        typer.echo("  s.  Save and exit")
        typer.echo("  q.  Quit without saving")

        raw = typer.prompt("\n  >").strip().lower()
        if raw == "q":
            typer.echo("  Cancelled — no changes saved.")
            return
        if raw == "s":
            path = save_weights(weights, base_data_dir)
            success_print(f"  Saved to {path}")
            return
        if not raw.isdigit() or not 1 <= int(raw) <= len(_TUNABLE_FIELDS):
            typer.echo(f"  Enter a number 1-{len(_TUNABLE_FIELDS)}, 's', or 'q'.")
            continue
        idx = int(raw) - 1
        field, field_type, desc = _TUNABLE_FIELDS[idx]
        current = getattr(weights, field)
        typer.echo(f"\n  {field}  (current: {_fmt(current)})")
        while True:
            new_raw = typer.prompt("  new value >").strip()
            try:
                new_val = _parse_field(field_type, new_raw)
                weights = weights.model_copy(update={field: new_val})
                typer.echo(f"  {field}  ->  {_fmt(new_val)}")
                break
            except (ValueError, TypeError) as e:
                typer.echo(f"  Invalid: {e}")


def _print_pv_table(config, round_key: Optional[str], type_filter: Optional[set[str]]) -> None:
    registry = PlayerRegistry(config.abs_players_dir)
    all_profiles = registry.load_all()

    rows = []
    for profile in all_profiles:
        sd = next((s for s in profile.season_data if s.season == (round_key or config.round_id)), None)
        if not sd:
            continue
        if type_filter and sd.player_type not in type_filter:
            continue

        pv = conf = f1 = f2 = f3 = f4 = None
        current_rank = peak_rank = None

        if profile.stats:
            current_rank = profile.stats.current_rank
            if profile.stats.computed_pv:
                cpv = profile.stats.computed_pv
                feat = cpv.features
                w    = cpv.weights_used
                pv   = cpv.point_value
                conf = feat.confidence
                peak_rank = feat.default_rank_used
                total_w = 0.0
                if feat.historical_score is not None:
                    total_w += w.w_historical
                if feat.adjusted_current_pts is not None:
                    total_w += w.w_current
                if total_w > 0:
                    if feat.historical_score is not None:
                        f1 = (w.w_historical / total_w) * feat.historical_score
                    if feat.adjusted_current_pts is not None:
                        f2 = (w.w_current / total_w) * feat.adjusted_current_pts
                f3 = feat.inhouse_modifier
                f4 = feat.manual_adjustment_total

        rows.append((profile.effective_id, sd.player_type, pv, conf, current_rank, peak_rank, f1, f2, f3, f4))

    rows.sort(key=lambda x: (x[2] is None, x[2]))

    table = Table(title=f"{config.tournament} — Point Values ({round_key or config.round_id})")
    table.add_column("Player", style="cyan", no_wrap=True)
    table.add_column("Type", style="dim")
    table.add_column("PV", justify="right")
    table.add_column("Cur Rank")
    table.add_column("Peak Rank")
    table.add_column("Conf", justify="right")
    table.add_column("F1", justify="right")
    table.add_column("F2", justify="right")
    table.add_column("F3", justify="right")
    table.add_column("F4", justify="right")

    def fc(val, fmt=".1f"):
        return format(val, fmt) if val is not None else "—"

    for player_id, ptype, pv, conf, cur_rank, peak_rank, f1, f2, f3, f4 in rows:
        style = "bold" if ptype == "captain" else ""
        table.add_row(
            player_id, ptype,
            fc(pv) if pv is not None else "[red]no data[/red]",
            cur_rank or "—", peak_rank or "—",
            f"{conf:.0%}" if conf is not None else "—",
            fc(f1), fc(f2),
            f"{-f3:+.2f}" if f3 else "—",
            f"{-f4:+.2f}" if f4 else "—",
            style=style,
        )

    console.print(table)


def pv(
    recalculate: bool = typer.Option(False, "--recalculate", help="Run AGGREGATE_RANK_STATS before PV_COMPUTE"),
    tune: bool = typer.Option(False, "--tune", help="Interactive weight editor — edit and save, then exit"),
    round: Optional[str] = typer.Option(None, "--round", help="Tournament round filter (default: current round_id)"),
):
    """Compute PV scores for all players and display the ranking table."""
    config = load_active_tournament()

    if tune:
        _run_tune_mode(config.abs_data_dir)
        return

    runner = PipelineRunner(config)
    if recalculate:
        info_print("Running AGGREGATE_RANK_STATS...")
        runner.run_task(Task.AGGREGATE_RANK_STATS)

    info_print("Running PV_COMPUTE...")
    runner.run_task(Task.PV_COMPUTE)
    _print_pv_table(config, round, None)
