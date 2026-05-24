"""
opgg_update.py
Runs the OPGG_SCRAPE_RANK pipeline task for specific players.

To run with interactive player selection:
    python3 opgg_update.py

To run on specific players via command line (comma-separated effective_id slugs):
    python3 opgg_update.py donny,Komi,player3
"""

import sys

from quartz.tournament_config import load_tournament_config
from quartz.pipeline_runner import PipelineRunner, Task
from quartz.player_registry import PlayerRegistry
from cli_shared_filters import prompt_existing_player

config = load_tournament_config()
runner = PipelineRunner(config)

if len(sys.argv) > 1:
    players = [p.strip() for p in sys.argv[1].split(",") if p.strip()]
else:
    registry = PlayerRegistry(config.abs_players_dir)
    players = []
    print("\nSelect players to update (Enter with no selection when done):")
    while True:
        profile = prompt_existing_player(registry, allow_skip=True)
        if profile is None:
            break
        if profile.effective_id not in players:
            players.append(profile.effective_id)
            print(f"  Added: {profile.effective_id}  ({len(players)} selected)")
        else:
            print(f"  Already added: {profile.effective_id}")

    if not players:
        print("No players selected — exiting.")
        sys.exit(0)

    print(f"\nRunning for: {', '.join(players)}")

runner.run_task(Task.OPGG_SCRAPE_RANK, players=players)
