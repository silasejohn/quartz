"""
quartz CLI — single entry point with subcommands.

Usage:
    quartz ingest               load local CSV into player profiles
    quartz ingest-sheets        load player profiles from Google Sheets (stub)
    quartz pv                   compute and display PV scores
    quartz pv --recalculate     run rank stats first, then PV
    quartz pv --tune            interactive weight editor
    quartz scrape opgg          targeted OP.GG rank scrape
    quartz scrape opgg-batch    batch OP.GG with progress tracking
    quartz manage               interactive player profile TUI
    quartz draft                draft simulator
    quartz export               export scouting CSV for Google Sheets
    quartz view PLAYER          full profile + PV breakdown for one player
    quartz stats                roster summary stats
    quartz set-type PLAYER TYPE change a player's tournament role
    quartz resync               re-save all profiles after manual JSON edits
    quartz debug opgg-dump      dump OP.GG HTML for selector debugging
"""

from pathlib import Path

import typer

from quartz.cli import draft, export, ingest, manage, pv, scrape, stats, tournament, util, view
from quartz.tournament_config import set_active_tournament_override

app = typer.Typer(
    name="quartz",
    help="Tournament scouting and draft analysis for amateur LoL tournaments.",
    no_args_is_help=True,
)


def _print_migration_reminder() -> None:
    cwd = Path.cwd()
    active_config = cwd / "active_tournament.yaml"
    tournament_files = sorted((cwd / "tournaments").glob("*.yaml")) if (cwd / "tournaments").is_dir() else []
    if active_config.exists():
        typer.echo(
            "Detected legacy ./active_tournament.yaml. Import it with:\n"
            "  quartz tournament import ./active_tournament.yaml --use\n"
            "Legacy auto-loading is no longer supported.",
            err=True,
        )
    if tournament_files:
        typer.echo(
            "Detected legacy ./tournaments/*.yaml files. Import them with:\n"
            "  quartz tournament import ./tournaments/<file>.yaml\n"
            "Legacy repo-root tournament snapshots are no longer loaded automatically.",
            err=True,
        )


@app.callback()
def main(
    tournament_name: str | None = typer.Option(
        None,
        "--tournament",
        help="Run this command against a registered tournament without changing the active selection.",
    ),
):
    _print_migration_reminder()
    set_active_tournament_override(tournament_name)

app.add_typer(scrape.app, name="scrape", help="Scrape rank and champion data from external sources.")
app.add_typer(tournament.app, name="tournament", help="Create, list, and select Quartz tournaments.")
app.add_typer(util.app,   name="debug",  help="Debugging and maintenance utilities.")

app.command("ingest")(ingest.ingest)
app.command("ingest-sheets")(ingest.ingest_sheets)
app.command("pv")(pv.pv)
app.command("manage")(manage.manage)
app.command("draft")(draft.draft)
app.command("export")(export.export)
app.command("view")(view.view)
app.command("stats")(stats.stats)
app.command("set-type")(util.set_type)
app.command("resync")(util.resync)


if __name__ == "__main__":
    app()
