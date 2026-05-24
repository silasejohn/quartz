import typer
import subprocess
import sys
import os
from typing import Optional


def view(
    player: Optional[str] = typer.Argument(None, help="Player ID or Riot ID to inspect"),
):
    """Drill-down viewer — full profile, rank history, PV breakdown for one player."""
    script = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "view_player.py")
    args = [sys.executable, os.path.abspath(script)]
    if player:
        args.append(player)
    subprocess.run(args, check=True)
