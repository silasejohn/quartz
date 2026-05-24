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

import typer

from quartz.cli import ingest, pv, scrape, manage, draft, export, view, stats, util

app = typer.Typer(
    name="quartz",
    help="Tournament scouting and draft analysis for amateur LoL tournaments.",
    no_args_is_help=True,
)

app.add_typer(scrape.app, name="scrape", help="Scrape rank and champion data from external sources.")
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
