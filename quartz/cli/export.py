import os
import csv
from typing import Optional

import typer

from quartz.tournament_config import load_tournament_config
from quartz.player_registry import PlayerRegistry

FIELDNAMES = [
    "player_type", "team_name", "player_id", "discord_id", "riot_accounts",
    "pv", "pv_confidence", "current_rank", "all_time_peak_rank",
    "primary_role", "secondary_role",
]


def _fmt_accounts(profile) -> str:
    parts = []
    for acc in profile.accounts:
        if acc.archived:
            continue
        region = (acc.player_region or "NA").upper()
        parts.append(acc.riot_id if region == "NA" else f"({region}) {acc.riot_id}")
    return " | ".join(parts)


def export(
    out: Optional[str] = typer.Option(None, help="Output CSV filename (default: auto-named in processed/)"),
    round: Optional[str] = typer.Option(None, help="Tournament round filter (default: current round_id)"),
):
    """Export enriched scouting data to CSV for Google Sheets."""
    config = load_tournament_config()
    round_key = round or config.round_id
    default_name = f"{config.tournament.lower()}_{config.current_round.lower()}_scouting.csv"
    out_filename = out or default_name

    registry = PlayerRegistry(config.abs_players_dir)
    rows = []
    for profile in registry.load_all():
        sd = next((s for s in profile.season_data if s.season == round_key), None)
        if not sd or sd.player_type not in ("captain", "main", "sub"):
            continue
        if not (profile.stats and profile.stats.computed_pv):
            continue
        pv = profile.stats.computed_pv.point_value
        if pv is None:
            continue

        conf = profile.stats.computed_pv.features.confidence
        rows.append({
            "player_id":          profile.effective_id,
            "discord_id":         profile.discord_id,
            "riot_accounts":      _fmt_accounts(profile),
            "current_rank":       profile.stats.current_rank or "",
            "all_time_peak_rank": profile.stats.all_time_peak_rank or "",
            "primary_role":       sd.primary_pos or "",
            "secondary_role":     sd.secondary_pos or "",
            "player_type":        sd.player_type,
            "pv":                 f"{pv:.1f}",
            "team_name":          sd.team_name or "",
            "pv_confidence":      f"{conf:.0%}" if conf is not None else "",
        })

    rows.sort(key=lambda r: float(r["pv"]))
    out_path = os.path.join(config.abs_processed_dir, out_filename)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    typer.echo(f"Exported {len(rows)} players -> {out_path}")
