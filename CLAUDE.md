# Quartz

Tournament scouting and draft analysis pipeline for amateur League of Legends tournaments.

## Project Structure

```
quartz/                  Core library package
  cli/                   Typer CLI subcommands (quartz ingest, quartz pv, ...)
  models/                Pydantic data models (player_profile, rank_data, pv_model, ...)
  scrapers/              Web scrapers (OP.GG; TODO: DPM, Rewind.LOL, LOG)
  tasks/                 Pipeline task implementations (one module per task)
  utils/                 logging.py — rich console + Python logging setup
  pipeline_runner.py     Thin orchestrator — dispatches to quartz/tasks/
  pv_compute.py          PV formula (math)
  tournament_config.py   Loads active_tournament.yaml
scripts/                 Legacy CLI entry points — use quartz CLI instead where possible
data/                    Tournament data — gitignored, structure committed via .gitkeep
tournaments/             Saved tournament config snapshots (one YAML per tournament)
tests/                   pytest unit tests for pure-logic modules
docs/
  features/              Design docs per PV feature (F1–F4)
  adr/                   Architecture Decision Records
  TODO.md                Organized backlog
active_tournament.yaml   Currently active tournament — edit to switch context
```

## Setup

```bash
brew install uv                  # if not already installed
uv venv                          # creates .venv/
source .venv/bin/activate
uv pip install -e .              # installs quartz package + CLI entry point
```

## Running the CLI

After setup, `quartz` is available as a command:

```bash
quartz --help
quartz ingest
quartz pv
quartz pv --recalculate
quartz scrape opgg
quartz scrape opgg-batch
quartz export
quartz view PLAYER
quartz stats
quartz set-type PLAYER TYPE
quartz resync
```

For commands with complex TUI (manage, draft), delegate to the legacy scripts while full migration is pending:

```bash
python3 scripts/manage_player.py
python3 scripts/draft_sim.py --analyze 500
```

## Switching Tournaments

Edit `active_tournament.yaml` — all scripts and CLI read from it automatically.

```yaml
tournament: GCS
current_lol_split: S2026   # LoL ranked split key — used for current rank aggregation
tournament_rounds:
  - S4
current_round: S4
data_dir: data/gcs/s4
raw_csv: data/gcs/s4/raw/gcs_draft_info_s4.csv
```

`config.round_id` returns the composite key `GCS-S4` (used everywhere season data is keyed).

## Imports

```python
from quartz.tournament_config import load_tournament_config
from quartz.pipeline_runner import PipelineRunner, Task   # Task re-exported from quartz.tasks
from quartz.tasks import Task                             # canonical import
from quartz.models.player_profile import PlayerProfile
from quartz.constants import RANK_ORDER, rank_score
from quartz.utils.logging import get_logger, info_print, success_print
```

## Key Concepts

- **PV (Point Value)** — lower = stronger player. Challenger ~10, Iron ~85.
- **Tournament round key** — composite `{TOURNAMENT}-{ROUND}` e.g. `GCS-S4`. Used as `SeasonData.season` and in all pipeline calls. Derived via `config.round_id`.
- **LoL split key** — e.g. `S2026`, `S2025 S3`. Separate from tournament rounds. Set via `current_lol_split` in YAML.
- **Player registry** — one JSON file per player in `data/{tournament}/{round}/players/`
- **Pipeline tasks** — `LOCAL_CSV_INGEST` → `OPGG_SCRAPE_RANK` → `AGGREGATE_RANK_STATS` → `PV_COMPUTE` → `EXPORT`
- **Task modules** — each task in `quartz/tasks/` exposes `run(config, registry, players=None)` and is callable independently of `PipelineRunner`

---

## E2E Workflows

### Workflow 1 — Season Bootstrap from CSV

```bash
# 1. Load raw form response CSV into player profiles
quartz ingest

# 2. Scrape OP.GG rank history for all players
python3 scripts/opgg_batch_update.py           # run all remaining
python3 scripts/opgg_batch_update.py --status  # check progress
python3 scripts/opgg_batch_update.py --reset   # start fresh if needed

# 3. Compute rank stats then PV scores
quartz pv --recalculate

# 4. Export draft pool to CSV for Google Sheets
quartz export
quartz export --out custom.csv
quartz export --season GCS-S4
```

---

### Workflow 2 — Mid-Season Player Additions & Quick Profile Edits

```bash
# 1. Add or update the player profile (TUI)
python3 scripts/manage_player.py
```

Action menu for existing players:
- **Add new account** — manual entry or automated OP.GG scrape
- **Add new tournament season** — add `SeasonData` entry for a new round
- **Manage adjustments** — edit per-season PV modifiers
- **Enter in-house data** — log W/L (feeds Wilson modifier)
- **New Player Profile** — full re-entry

```bash
# 2. Scrape OP.GG for a specific player
quartz scrape opgg PlayerName                  # targeted
python3 scripts/opgg_update.py donny,Komi     # legacy alternative

# 3. Recompute PV after profile changes
quartz pv

# 4. Re-export if the Google Sheet needs refreshing
quartz export
```

---

### Workflow 3 — Draft Threshold Analysis & Simulation

**Before running:** update `CAPTAIN_SLOTS` at the top of `scripts/draft_sim.py`.

**What are thresholds?** R2 = minimum team PV (captain + 2 picks) after round 2. R4 = same after round 4.

```bash
# Discover thresholds via Monte Carlo
python3 scripts/draft_sim.py --analyze 500
python3 scripts/draft_sim.py --analyze 500 --strategy greedy_pv

# Stress-test a threshold
python3 scripts/draft_sim.py --analyze 500 --r2 85.0 --r4 160.0

# Generate the pick sheet
python3 scripts/draft_sim.py --recommend 85.0 --r4 160.0

# Play-by-play walkthrough
python3 scripts/draft_sim.py --simulate --r2 85.0 --r4 160.0

# Retune PV weights first
quartz pv --tune
quartz pv
```

---

## One-Time Utilities

| Command | When to use |
|---------|------------|
| `quartz stats` | Sanity-check roster composition before draft |
| `quartz view PLAYER` | Inspect a single player's full data and PV feature breakdown |
| `quartz set-type PLAYER TYPE` | Promote a sub to main, designate a captain |
| `quartz resync` | After directly editing player JSON files |
| `quartz debug opgg-dump` | OP.GG CSS selectors broke — dump DOM to fix `opgg_config.yaml` |

## Tests

```bash
pytest tests/ -v          # run all
pytest tests/ -q          # summary only
pytest --cov=quartz       # with coverage
```

Tests cover pure-logic modules only (rank_score, compute_enrichment, compute_pv). Scrapers and browser code are not tested.
