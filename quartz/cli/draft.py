import typer
import subprocess
import sys
import os
from typing import Optional


def draft(
    analyze: Optional[int] = typer.Option(None, "--analyze", help="Run N Monte Carlo simulations"),
    simulate: bool = typer.Option(False, "--simulate", help="Play-by-play draft walkthrough"),
    recommend: Optional[float] = typer.Option(None, "--recommend", help="Generate pick sheet for given R2 threshold"),
    r2: Optional[float] = typer.Option(None, "--r2", help="R2 threshold"),
    r4: Optional[float] = typer.Option(None, "--r4", help="R4 threshold"),
    strategy: Optional[str] = typer.Option(None, "--strategy", help="Draft strategy (role_greedy / greedy_pv)"),
    top_n: Optional[int] = typer.Option(None, "--top-n", help="Pick variance — random from top N per role"),
    seed: Optional[int] = typer.Option(None, "--seed", help="Random seed for reproducible simulation"),
):
    """Draft simulator — threshold analysis, pick sheet, play-by-play."""
    script = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "draft_sim.py")
    args = [sys.executable, os.path.abspath(script)]
    if analyze is not None:
        args += ["--analyze", str(analyze)]
    if simulate:
        args += ["--simulate"]
    if recommend is not None:
        args += ["--recommend", str(recommend)]
    if r2 is not None:
        args += ["--r2", str(r2)]
    if r4 is not None:
        args += ["--r4", str(r4)]
    if strategy is not None:
        args += ["--strategy", strategy]
    if top_n is not None:
        args += ["--top-n", str(top_n)]
    if seed is not None:
        args += ["--seed", str(seed)]
    subprocess.run(args, check=True)
