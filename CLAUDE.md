# Quartz

Tournament scouting and draft analysis pipeline for amateur League of Legends tournaments.

## Project Structure

```
quartz/                  Core library package — models, scrapers, pipeline logic
scripts/                 CLI entry points (thin wrappers that call into quartz/)
data/                    Tournament data — gitignored, structure committed via .gitkeep
tournaments/             Saved tournament config snapshots (one YAML per tournament)
active_tournament.yaml   Currently active tournament — edit to switch context
```

## Setup

```bash
brew install uv                  # if not already installed
uv venv                          # creates .venv/
source .venv/bin/activate
uv pip install -e .              # installs quartz package (enables clean imports)
```

## Running Scripts

Always activate the venv first, then run from the project root:

```bash
source .venv/bin/activate
python3 scripts/ingest_csv.py
python3 scripts/compute_pv.py
python3 scripts/draft_sim.py --analyze 500
```

Note: inside an active venv, `python` and `python3` are equivalent. `python3` is preferred for clarity.

## Switching Tournaments

Edit `active_tournament.yaml` — all scripts read from it automatically. No other files need to change.

```yaml
tournament: GCS
season: S4
data_dir: data/gcs/s4
...
```

## Imports

With `pip install -e .` done once, imports are clean everywhere — no sys.path hacks:

```python
from quartz.pipeline_runner import PipelineRunner
from quartz.models.player_profile import PlayerProfile
from quartz.constants import RANK_ORDER, rank_score
```

## Key Concepts

- **PV (Point Value)** — lower = stronger player. Challenger ~10, Iron ~85.
- **Tournament rounds** — GCS/LEPL season labels (S1, S4 etc.), separate from LoL ranked seasons (S2026 etc.)
- **Player registry** — one JSON file per player in `data/{tournament}/{season}/players/`
- **Pipeline tasks** — LOCAL_CSV_INGEST → OPGG_ENRICH_RANK → CALCULATE_RANK_STATS → PV_COMPUTE → EXPORT
