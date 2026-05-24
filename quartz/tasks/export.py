"""Task: EXPORT — write enriched scouting data to CSV for Google Sheets."""

import csv
import os

from quartz.tournament_config import TournamentConfig
from quartz.player_registry import PlayerRegistry
from quartz.utils.logging import success_print

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


def run(
    config: TournamentConfig,
    registry: PlayerRegistry,
    players: list[str] | None = None,
    out_filename: str | None = None,
    round_key: str | None = None,
) -> tuple[set[str], set[str]]:
    """
    [param] config:       TournamentConfig
    [param] registry:     PlayerRegistry
    [param] players:      unused — export always covers the full pool
    [param] out_filename: CSV filename written into processed/. Defaults to auto-named.
    [param] round_key:    season filter (default: config.round_id)
    """
    season = round_key or config.round_id
    filename = out_filename or f"{config.tournament.lower()}_{config.current_round.lower()}_scouting.csv"

    rows = []
    for profile in registry.load_all():
        sd = next((s for s in profile.season_data if s.season == season), None)
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

    out_path = os.path.join(config.abs_processed_dir, filename)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    success_print(f"EXPORT: {len(rows)} players -> {out_path}")
    return set(), set()
