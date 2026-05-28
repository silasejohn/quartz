"""quartz pv-shadow — show ineligible players and their shadow PV scores (read-only)."""

import typer

from quartz.player_registry import PlayerRegistry
from quartz.tournament_config import load_tournament_config


def pv_shadow() -> None:
    """Show ineligible players with their shadow PV scores. Read-only; does not recompute."""
    config = load_tournament_config()
    registry = PlayerRegistry(config.abs_players_dir)
    profiles = registry.load_all()

    eligibility = config.eligibility
    rows = []

    for profile in profiles:
        season_entry = next((sd for sd in profile.season_data if sd.season == config.round_id), None)
        if not season_entry or season_entry.eligible is not False:
            continue

        pv = profile.stats.computed_pv if profile.stats else None
        shadow_pv = pv.shadow_pv if pv else None
        current_rank = profile.stats.current_rank if profile.stats else None

        # Build reason string — games per relevant split
        reason_parts = []
        if profile.stats and profile.stats.rank_data and eligibility:
            splits_by_season = {s.season: s for s in profile.stats.rank_data.solo_splits}
            for split_key in filter(None, [eligibility.primary_split, eligibility.backup_split]):
                agg = splits_by_season.get(split_key)
                games = ((agg.wins or 0) + (agg.losses or 0)) if agg else 0
                reason_parts.append(f"{split_key}: {games}g")

        rows.append((
            profile.effective_id,
            profile.player_type or "—",
            current_rank or "—",
            f"{round(shadow_pv)}" if shadow_pv is not None else "—",
            "  ".join(reason_parts) or "—",
        ))

    if not rows:
        typer.echo("No ineligible players found. Run 'quartz pv --recalculate' first.")
        return

    rows.sort(key=lambda r: float(r[3]) if r[3] != "—" else 9999)

    col_w = [max(len(r[i]) for r in rows + [("Player", "Type", "Current Rank", "Shadow PV", "Games")]) for i in range(5)]
    header = "  ".join(h.ljust(col_w[i]) for i, h in enumerate(("Player", "Type", "Current Rank", "Shadow PV", "Games")))
    typer.echo(f"\n{header}")
    typer.echo("-" * len(header))
    for row in rows:
        typer.echo("  ".join(row[i].ljust(col_w[i]) for i in range(5)))
    typer.echo(f"\n{len(rows)} ineligible player(s).")
