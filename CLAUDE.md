# Quartz

Tournament scouting and draft analysis pipeline for amateur League of Legends tournaments.

## Project Structure

```
quartz/                  Core library package
  cli/                   Typer CLI subcommands (main.py wires everything together)
  models/                Pydantic data models (player_profile, rank_data, champion_data, pv_model, ...)
  scrapers/              Web scrapers (OP.GG, DPM.lol; TODO: Rewind.LOL, LOG)
    configs/             YAML selector configs per scraper (dpm_config.yaml, opgg_config.yaml)
  tasks/                 Pipeline task implementations (one module per task)
  utils/                 logging.py — rich console + Python logging setup
  account_flags.py       Auto-evaluates low_level, low_volume, smurf_peak, smurf_jump flags
  pipeline_runner.py     Thin orchestrator — dispatches to quartz/tasks/
  pv_compute.py          PV formula (math)
  tournament_config.py   Loads active_tournament.yaml
config/                  API keys and secrets (api.env is gitignored)
  api.env                RIOT_API_KEY and other credentials (gitignored)
  config.py              Loader: get_riot_api_config("KEY")
data/                    Tournament data — gitignored, structure committed via .gitkeep
  samples/               Raw API/DOM dumps for human reference (gitignored)
    dpm/                 champions_response.json — full DPM /v1/players/{id}/champions payload
tournaments/             Saved tournament config snapshots (one YAML per tournament)
tests/
  unit/                  pytest unit tests for pure-logic modules (no network, no browser)
  fixtures/              Curated, committed snapshots used as stable test inputs
    dpm/                 champions_response.json — reference DPM API response (dont ever stop#NA1)
    opgg/                champion page HTML — new format (S2026) and old format (S2024 S1)
  diag/                  Live diagnostic scripts — require real network, never run in CI
docs/
  features/              Design docs per PV feature (F1–F4, champion pool)
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
quartz pv --tune
quartz pv-shadow
quartz manage
quartz draft
quartz export
quartz view PLAYER
quartz delete PLAYER
quartz stats
quartz set-type PLAYER TYPE
quartz resync

# Scraping (subcommands under `quartz scrape`)
quartz scrape opgg [PLAYER]         # OP.GG rank + champ in one session (smart-skip per component)
quartz scrape opgg --status         # scrape coverage summary across all accounts
quartz scrape opgg-rank [PLAYER]    # OP.GG rank history only
quartz scrape opgg-champ [PLAYER]   # OP.GG champion stats — all historical seasons
quartz scrape dpm [PLAYER]          # DPM.lol champion stats — current split, per role
quartz scrape champ [PLAYER]        # combined: DPM + OP.GG champion scrape
quartz scrape riot-puuid [PLAYER]   # Riot API PUUID lookup

# Reset (wipe scraped data for clean re-scrape)
quartz reset rank [PLAYER]          # clear rank history
quartz reset champ [PLAYER]         # clear champion pool data

# Flags (view and manage account flags)
quartz flags list                   # show all active flags across roster
quartz flags list --all             # include dismissed flags
quartz flags add PLAYER RIOT_ID TYPE
quartz flags dismiss PLAYER RIOT_ID TYPE

# Debug / maintenance
quartz debug opgg-dump PLAYER       # dump OP.GG HTML to fix opgg_config.yaml selectors
quartz debug fixture                # interactive CDP inspector — capture API responses as fixtures
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
from quartz.models.champion_data import ChampionSplitStats, OPGG_EXCLUSIVE_FIELDS, DPM_EXCLUSIVE_FIELDS
from quartz.constants import RANK_ORDER, rank_score
from quartz.utils.logging import get_logger, info_print, success_print
```

## Key Concepts

- **PV (Point Value)** — lower = stronger player. Challenger ~10, Iron ~85.
- **Tournament round key** — composite `{TOURNAMENT}-{ROUND}` e.g. `GCS-S4`. Used as `SeasonData.season` and in all pipeline calls. Derived via `config.round_id`.
- **LoL split key** — e.g. `S2026`, `S2025 S3`. Separate from tournament rounds. Set via `current_lol_split` in YAML.
- **Player registry** — one JSON file per player in `data/{tournament}/{round}/players/`
- **Pipeline tasks** — `LOCAL_CSV_INGEST` → `OPGG_SCRAPE_RANK` → `AGGREGATE_RANK_STATS` → `PV_COMPUTE` → `EXPORT`
- **Champion tasks** — `DPM_SCRAPE_CHAMP` (current split, per-role), `OPGG_SCRAPE_CHAMP` (historical seasons, all-roles aggregate)
- **Task modules** — each task in `quartz/tasks/` exposes `run(config, registry, players=None)` and is callable independently of `PipelineRunner`
- **Champion data merge** — `ChampionSplitStats.source` tracks provenance: `"dpm"`, `"opgg"`, `"multi"` (both). Force-rescraping one source preserves the other source's exclusive fields. See `OPGG_EXCLUSIVE_FIELDS` / `DPM_EXCLUSIVE_FIELDS` in `champion_data.py`.

---

## E2E Workflows

### Workflow 1 — Season Bootstrap from CSV

```bash
# 1. Load raw form response CSV into player profiles
quartz ingest

# 2. Scrape OP.GG rank + champion data (smart-skip: resumes where it left off)
quartz scrape opgg

# 3. Scrape DPM champion data (current split, per role)
quartz scrape dpm

# 4. Compute rank stats then PV scores
quartz pv --recalculate

# 5. Export draft pool to CSV for Google Sheets
quartz export
quartz export --out custom.csv
quartz export --season GCS-S4
```

---

### Workflow 2 — Mid-Season Player Additions & Quick Profile Edits

```bash
# 1. Add or update the player profile (interactive TUI)
quartz manage

# 2. Scrape OP.GG for a specific player (rank + champ in one session)
quartz scrape opgg PlayerName

# 3. Scrape DPM champion data for that player
quartz scrape dpm PlayerName

# 4. Recompute PV after profile changes
quartz pv

# 5. Re-export if the Google Sheet needs refreshing
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
| `quartz delete PLAYER` | Permanently remove a player profile from the registry |
| `quartz set-type PLAYER TYPE` | Promote a sub to main, designate a captain |
| `quartz resync` | After directly editing player JSON files |
| `quartz reset rank [PLAYER]` | Wipe rank history for a clean re-scrape |
| `quartz reset champ [PLAYER]` | Wipe champion pool data for a clean re-scrape |
| `quartz flags list` | Review all active account flags across the roster |
| `quartz scrape opgg --status` | Show scrape coverage summary (complete/errors/never-attempted) |
| `quartz scrape opgg --force` | Re-scrape OP.GG rank + champ for all accounts unconditionally |
| `quartz scrape opgg-rank --force` | Re-scrape OP.GG rank only |
| `quartz scrape dpm --force` | Re-scrape DPM champion data even if already scraped |
| `quartz scrape opgg-champ --force` | Re-scrape OP.GG champion data even if already scraped |
| `quartz debug opgg-dump` | OP.GG CSS selectors broke — dump DOM to fix `opgg_config.yaml` |
| `quartz debug fixture` | Interactive CDP inspector — capture API responses from DPM/OP.GG/any site and save as JSON fixtures. Run `python tests/diag/diag_network_analyze.py` afterward to compare against what the scrapers capture. |

## Tests

```bash
pytest tests/ -v          # run all
pytest tests/ -q          # summary only
pytest --cov=quartz       # with coverage
```

Tests cover pure-logic modules: rank scoring, PV compute, enrichment, champion pool merge logic. Scrapers and browser code are not tested — use `tests/diag/` scripts with a live browser for those.
