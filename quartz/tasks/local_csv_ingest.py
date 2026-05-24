"""
Task: LOCAL_CSV_INGEST
Read the local form response CSV and create/update player JSONs.

Safe to re-run — existing profiles get their season entry upserted,
new players get a fresh JSON created.
"""

from quartz.local_csv_input import LocalCSVInput
from quartz.models.player_profile import Account, PlayerProfile, SeasonData
from quartz.player_registry import PlayerRegistry
from quartz.tournament_config import TournamentConfig
from quartz.utils.logging import info_print, success_print


def run(config: TournamentConfig, registry: PlayerRegistry, players: list[str] | None = None) -> None:
    """
    [param] config:   TournamentConfig — uses abs_raw_csv path and round_id
    [param] registry: PlayerRegistry — profiles are loaded and saved here
    [param] players:  optional list of discord_usernames to limit scope. None = all.
    """
    reader = LocalCSVInput(config.abs_raw_csv)
    rows = reader.load()

    if players:
        players_lower = {p.lower() for p in players}
        rows = [r for r in rows if r["discord_username"].lower() in players_lower]
        info_print(f"Filtered to {len(rows)} rows for players: {players}")

    tournament_round = config.round_id
    created = updated = unchanged = 0

    for row in rows:
        discord = row["discord_username"]

        if registry.exists(discord):
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

    success_print(
        f"LOCAL_CSV_INGEST: {created} created, {updated} updated, {unchanged} unchanged "
        f"({registry.count()} total players in registry)"
    )
