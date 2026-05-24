import typer
import subprocess
import sys
import os


def manage():
    """Interactively add or update a player profile (TUI)."""
    script = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "manage_player.py")
    subprocess.run([sys.executable, os.path.abspath(script)], check=True)
