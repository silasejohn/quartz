import typer
import subprocess
import sys
import os


def stats():
    """Roster summary stats — player types, roles, rank distributions."""
    script = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "pool_stats.py")
    subprocess.run([sys.executable, os.path.abspath(script)], check=True)
