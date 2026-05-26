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
  tournament_config.py   Loads active tournament from the registry
  tournament_registry.py CLI-managed tournament definitions and active state
  paths.py               Platform config/data/state/cache locations
scripts/                 Legacy CLI entry points — use quartz CLI instead where possible
data/                    Tournament data — gitignored, structure committed via .gitkeep
tests/                   pytest unit tests for pure-logic modules
docs/
  features/              Design docs per PV feature (F1–F4)
  adr/                   Architecture Decision Records
  TODO.md                Organized backlog
```

## Setup

```bash
brew install uv                  # if not already installed
uv sync --extra dev              # installs project + dev tools into uv's managed env
```

## Running the CLI

After setup, run commands through uv:

```bash
uv run quartz --help
uv run quartz ingest
uv run quartz pv
uv run quartz pv --recalculate
uv run quartz scrape opgg
uv run quartz scrape opgg-batch
uv run quartz export
uv run quartz view PLAYER
uv run quartz stats
uv run quartz set-type PLAYER TYPE
uv run quartz resync
```

For commands with complex TUI (manage, draft), delegate to the legacy scripts while full migration is pending:

```bash
python3 scripts/manage_player.py
python3 scripts/draft_sim.py --analyze 500
```

## Switching Tournaments

Quartz stores tournament definitions in the platform config directory and active selection in the platform state directory. Use the CLI to create, import, list, and select tournaments.

```bash
uv run quartz tournament create gcs-s4
uv run quartz tournament import ./legacy_tournament.yaml --use
uv run quartz tournament list
uv run quartz tournament use gcs-s4
uv run quartz tournament show
uv run quartz tournament path --data
```

Use `uv run quartz --tournament gcs-s4 pv` to run one command against a tournament without changing the active selection.

Legacy `active_tournament.yaml` and repo-root `tournaments/*.yaml` files are no longer loaded automatically. If detected, Quartz prints a migration reminder until those files are removed or renamed.

Default Linux locations are `$XDG_CONFIG_HOME/quartz`, `$XDG_DATA_HOME/quartz`, `$XDG_STATE_HOME/quartz`, and `$XDG_CACHE_HOME/quartz`, with normal XDG fallbacks under `~/.config`, `~/.local/share`, `~/.local/state`, and `~/.cache`. Run `uv run quartz tournament locations` to see the resolved paths.

`config.round_id` returns the composite key `GCS-S4` (used everywhere season data is keyed).

## Imports

```python
from quartz.tournament_config import load_active_tournament
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
- **Player registry** — one JSON file per player under the active tournament's data directory
- **Pipeline tasks** — `LOCAL_CSV_INGEST` → `OPGG_SCRAPE_RANK` → `AGGREGATE_RANK_STATS` → `PV_COMPUTE` → `EXPORT`
- **Task modules** — each task in `quartz/tasks/` exposes `run(config, registry, players=None)` and is callable independently of `PipelineRunner`

---

## E2E Workflows

### Workflow 1 — Season Bootstrap from CSV

```bash
# 1. Load raw form response CSV into player profiles
uv run quartz ingest

# 2. Scrape OP.GG rank history for all players
python3 scripts/opgg_batch_update.py           # run all remaining
python3 scripts/opgg_batch_update.py --status  # check progress
python3 scripts/opgg_batch_update.py --reset   # start fresh if needed

# 3. Compute rank stats then PV scores
uv run quartz pv --recalculate

# 4. Export draft pool to CSV for Google Sheets
uv run quartz export
uv run quartz export --out custom.csv
uv run quartz export --round GCS-S4
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
uv run quartz scrape opgg PlayerName           # targeted
python3 scripts/opgg_update.py donny,Komi     # legacy alternative

# 3. Recompute PV after profile changes
uv run quartz pv

# 4. Re-export if the Google Sheet needs refreshing
uv run quartz export
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
uv run quartz pv --tune
uv run quartz pv
```

---

## One-Time Utilities

| Command | When to use |
|---------|------------|
| `uv run quartz stats` | Sanity-check roster composition before draft |
| `uv run quartz view PLAYER` | Inspect a single player's full data and PV feature breakdown |
| `uv run quartz set-type PLAYER TYPE` | Promote a sub to main, designate a captain |
| `uv run quartz resync` | After directly editing player JSON files |
| `uv run quartz debug opgg-dump` | OP.GG CSS selectors broke — dump DOM to fix `opgg_config.yaml` |

## Tests

```bash
uv run pytest tests/ -v          # run all
uv run pytest tests/ -q          # summary only
uv run pytest --cov=quartz       # with coverage
```

Tests cover pure-logic modules only (rank_score, compute_enrichment, compute_pv). Scrapers and browser code are not tested.
