"""
export_csv.py
Export player scouting data as a CSV for Google Sheets.

Usage:
    python3 export_csv.py                        # outputs to data/{tournament}/{season}/processed/
    python3 export_csv.py --out custom.csv       # custom output filename
    python3 export_csv.py --season S4            # explicit season filter (default: current_round)
"""

import os
import csv
import argparse

from quartz.tournament_config import load_tournament_config
from quartz.player_registry import PlayerRegistry

FIELDNAMES = [
    "player_type",
    "team_name",
    "player_id",
    "discord_id",
    "riot_accounts",
    "pv",
    "pv_confidence",
    "current_rank",
    "all_time_peak_rank",
    "primary_role",
    "secondary_role",
]


def _fmt_accounts(profile) -> str:
    parts = []
    for acc in profile.accounts:
        if acc.archived:
            continue
        region = (acc.player_region or "NA").upper()
        tag = acc.riot_id or ""
        if region == "NA":
            parts.append(tag)
        else:
            parts.append(f"({region}) {tag}")
    return " | ".join(parts)


def build_rows(registry: PlayerRegistry, season: str) -> list[dict]:
    rows = []
    for profile in registry.load_all():
        sd = next((s for s in profile.season_data if s.season == season), None)
        if not sd:
            continue
        if sd.player_type not in ("captain", "main", "sub"):
            continue
        if not (profile.stats and profile.stats.computed_pv):
            continue
        pv = profile.stats.computed_pv.point_value
        if pv is None:
            continue

        conf = profile.stats.computed_pv.features.confidence
        conf_str = f"{conf:.0%}" if conf is not None else ""

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
            "pv_confidence":      conf_str,
        })

    rows.sort(key=lambda r: float(r["pv"]))
    return rows


def main() -> None:
    config = load_tournament_config()

    parser = argparse.ArgumentParser(description="Export scouting CSV")
    default_out = f"{config.tournament.lower()}_{config.current_round.lower()}_scouting.csv"
    parser.add_argument("--out",    default=default_out, help="Output CSV filename")
    parser.add_argument("--season", default=config.round_id, help="Season filter")
    args = parser.parse_args()

    registry = PlayerRegistry(config.abs_players_dir)
    rows = build_rows(registry, args.season)

    out_path = os.path.join(config.abs_processed_dir, args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"  Exported {len(rows)} players -> {out_path}")


if __name__ == "__main__":
    main()
