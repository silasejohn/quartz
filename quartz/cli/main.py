"""
quartz CLI — single entry point with subcommands.

Usage:
    quartz ingest               load local CSV into player profiles
    quartz ingest-sheets        load player profiles from Google Sheets (stub)
    quartz pv                   compute and display PV scores
    quartz pv --recalculate     run rank stats first, then PV
    quartz pv --tune            interactive weight editor
    quartz pv-shadow            show ineligible players and their shadow PV scores
    quartz scrape opgg          targeted OP.GG rank scrape
    quartz scrape opgg-batch    batch OP.GG with progress tracking
    quartz flags list           list account flags across all players
    quartz flags add            add a manual flag to an account
    quartz flags dismiss        dismiss a flag (mark as false positive)
    quartz manage               interactive player profile TUI
    quartz draft                draft simulator
    quartz export               export scouting CSV for Google Sheets
    quartz view PLAYER          full profile + PV breakdown for one player
    quartz stats                roster summary stats
    quartz resync               re-save all profiles after manual JSON edits
    quartz debug opgg-dump      dump OP.GG HTML for selector debugging
"""

import typer

from quartz.cli import draft, export, flags, ingest, manage, pv, pv_shadow, reset, scrape, stats, util, view

app = typer.Typer(
    name="quartz",
    help="Tournament scouting and draft analysis for amateur LoL tournaments.",
    no_args_is_help=True,
)


@app.callback()
def _startup(ctx: typer.Context) -> None:
    from quartz.utils.champion_names import check_champion_name_warnings
    check_champion_name_warnings()

app.add_typer(scrape.app, name="scrape", help="Scrape rank and champion data from external sources.")
app.add_typer(reset.app,  name="reset",  help="Wipe raw scraped data for a clean re-scrape.")
app.add_typer(flags.app,  name="flags",  help="View and manage account flags.")
app.add_typer(util.app,   name="debug",  help="Debugging and maintenance utilities.")

app.command("ingest")(ingest.ingest)
app.command("ingest-sheets")(ingest.ingest_sheets)
app.command("pv")(pv.pv)
app.command("pv-shadow")(pv_shadow.pv_shadow)
app.command("manage")(manage.manage)
app.command("draft")(draft.draft)
app.command("export")(export.export)
app.command("view")(view.view)
app.command("delete")(manage.delete)
app.command("stats")(stats.stats)
app.command("resync")(util.resync)


if __name__ == "__main__":
    app()
