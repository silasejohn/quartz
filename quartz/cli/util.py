import typer
import subprocess
import sys
import os
from typing import Optional

from quartz.tournament_config import load_tournament_config
from quartz.player_registry import PlayerRegistry
from quartz.constants import PLAYER_TYPES
from quartz.utils.logging import success_print, warning_print

app = typer.Typer(no_args_is_help=True)


def set_type(
    player: str = typer.Argument(..., help="Player ID or RiotID#Tag"),
    player_type: str = typer.Argument(..., help=f"New type: {', '.join(PLAYER_TYPES)}"),
):
    """Change a player's tournament role (captain / main / sub / other)."""
    script = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "set_player_type.py")
    subprocess.run([sys.executable, os.path.abspath(script), player, player_type], check=True)


def resync():
    """Re-save all profiles through the registry after manual JSON edits."""
    script = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "resync_profiles.py")
    subprocess.run([sys.executable, os.path.abspath(script)], check=True)


@app.command("opgg-dump")
def opgg_dump(
    player: str = typer.Argument(..., help="Player ID or Riot ID"),
    out: Optional[str] = typer.Option(None, "--out", help="Output HTML file path"),
):
    """Dump OP.GG page HTML for inspecting/updating CSS selectors."""
    script = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "util_opgg_dump.py")
    args = [sys.executable, os.path.abspath(script), player]
    if out:
        args += ["--out", out]
    subprocess.run(args, check=True)
