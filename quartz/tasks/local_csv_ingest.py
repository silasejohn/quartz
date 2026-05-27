"""
Task: LOCAL_CSV_INGEST
Read the local form response CSV and create/update player JSONs.

Default (no --force): only new players are created — existing profiles are skipped.
With --force: full upsert for all rows (existing behavior; safe to re-run).
"""

import csv
import os

from quartz.local_csv_input import LocalCSVInput
from quartz.models.player_profile import Account, PlayerProfile, SeasonData
from quartz.player_registry import PlayerRegistry
from quartz.tournament_config import TournamentConfig
from quartz.utils.logging import info_print, success_print


def run(
    config: TournamentConfig,
    registry: PlayerRegistry,
    players: list[str] | None = None,
    force: bool = False,
    limit: int | None = None,
) -> None:
    """
    [param] config:   TournamentConfig — uses abs_raw_csv path and round_id
    [param] registry: PlayerRegistry — profiles are loaded and saved here
    [param] players:  optional list of discord_usernames to limit scope. None = all.
    [param] force:    if True, upsert all rows; if False, skip players already in registry
    [param] limit:    if set, process only the first N rows (for testing)
    """
    if config.signup_sheet:
        from quartz.signup_sheet_adapter import SignupSheetAdapter
        adapter = SignupSheetAdapter(config.signup_sheet, config.abs_raw_csv)
        rows = adapter.load()
        _save_processed_csv(rows, config)
    else:
        reader = LocalCSVInput(config.abs_raw_csv)
        rows = reader.load()

    if limit is not None:
        rows = rows[:limit]
        info_print(f"Limiting to first {limit} rows")

    if players:
        players_lower = {p.lower() for p in players}
        rows = [r for r in rows if r["discord_username"].lower() in players_lower]
        info_print(f"Filtered to {len(rows)} rows for players: {players}")

    tournament_round = config.round_id
    created = updated = unchanged = skipped = 0

    for row in rows:
        discord = row["discord_username"]

        if registry.exists(discord):
            if not force:
                info_print(f"  Skipped: {discord} (already in registry — use --force to update)")
                skipped += 1
                continue

            profile = registry.load(discord)
            changed = False

            new_season = SeasonData(
                season=tournament_round,
                player_type=row.get("player_type_override") or "main",
                primary_pos=row.get("primary_role"),
                secondary_pos=row.get("secondary_role"),
                stated_current_rank=row.get("stated_current_rank"),
                stated_peak_rank=row.get("stated_peak_rank"),
            )
            existing_season = next((sd for sd in profile.season_data if sd.season == tournament_round), None)
            if existing_season is None or existing_season.model_dump() != new_season.model_dump():
                profile.upsert_season(new_season)
                changed = True

            existing_by_id = {a.riot_id: a for a in profile.accounts}
            csv_riot_ids = {a["riot_id"] for a in row.get("accounts", []) if a.get("riot_id")}

            for acc_data in row.get("accounts", []):
                rid = acc_data.get("riot_id")
                if not rid:
                    continue
                if rid in existing_by_id:
                    acc = existing_by_id[rid]
                    if acc.archived or acc.player_region != acc_data["player_region"]:
                        acc.archived = False
                        acc.player_region = acc_data["player_region"]
                        changed = True
                else:
                    profile.accounts.append(Account(riot_id=rid, player_region=acc_data["player_region"]))
                    changed = True

            for acc in profile.accounts:
                if acc.riot_id not in csv_riot_ids and not acc.archived:
                    acc.archived = True
                    changed = True

            if changed:
                profile.touch()
                registry.save(profile)
                info_print(f"  Updated: {profile.effective_id}")
                updated += 1
            else:
                info_print(f"  Unchanged: {profile.effective_id}")
                unchanged += 1
        else:
            profile = PlayerProfile.from_csv_row(row, tournament_round)
            registry.save(profile)
            info_print(f"  Created: {profile.effective_id}")
            created += 1

    parts = [f"{created} created", f"{updated} updated", f"{unchanged} unchanged"]
    if skipped:
        parts.append(f"{skipped} skipped (use --force to update)")
    success_print(
        f"LOCAL_CSV_INGEST: {', '.join(parts)} "
        f"({registry.count()} total players in registry)"
    )


def _save_processed_csv(rows: list[dict], config: TournamentConfig) -> None:
    """Serialize normalized SignupSheetAdapter rows to CSV for audit trail."""
    os.makedirs(config.abs_processed_dir, exist_ok=True)
    out_path = os.path.join(config.abs_processed_dir, "signup_sheet_processed.csv")

    fieldnames = ["discord_username", "riot_ids", "player_region", "stated_current_rank", "primary_role", "secondary_role"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            accounts = row.get("accounts", [])
            riot_ids = "|".join(a["riot_id"] for a in accounts)
            regions = {a.get("player_region", "") for a in accounts}
            region = next(iter(regions)) if len(regions) == 1 else "|".join(sorted(regions))
            writer.writerow({
                "discord_username": row["discord_username"],
                "riot_ids": riot_ids,
                "player_region": region,
                "stated_current_rank": row.get("stated_current_rank") or "",
                "primary_role": row.get("primary_role") or "",
                "secondary_role": row.get("secondary_role") or "",
            })

    info_print(f"SignupSheetAdapter: processed CSV saved to {out_path}")
