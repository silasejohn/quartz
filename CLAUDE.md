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
current_round: S4
data_dir: data/gcs/s4
...
```

## Imports

With `pip install -e .` done once, imports are clean everywhere — no sys.path hacks:

```python
from quartz.tournament_config import load_tournament_config
from quartz.pipeline_runner import PipelineRunner, Task
from quartz.models.player_profile import PlayerProfile
from quartz.constants import RANK_ORDER, rank_score
```

## Key Concepts

- **PV (Point Value)** — lower = stronger player. Challenger ~10, Iron ~85.
- **Tournament rounds** — labels like S1, S4 etc., separate from LoL ranked seasons (S2026 etc.). Defined in `active_tournament.yaml`.
- **Player registry** — one JSON file per player in `data/{tournament}/{season}/players/`
- **Pipeline tasks** — LOCAL_CSV_INGEST → OPGG_SCRAPE_RANK → AGGREGATE_RANK_STATS → PV_COMPUTE → EXPORT

---

## Script Index

| Script | Purpose |
|--------|---------|
| `ingest_csv.py` | Load initial player roster from raw CSV into player profiles |
| `opgg_batch_update.py` | Batch-scrape OP.GG rank history for all player accounts |
| `opgg_update.py` | Targeted OP.GG rank scrape for specific player(s) |
| `manage_player.py` | Interactive TUI — add/update player profiles, accounts, adjustments, in-house data |
| `compute_pv.py` | Compute PV scores for all players; includes weight tuning mode |
| `export_csv.py` | Export enriched scouting data to CSV for Google Sheets |
| `draft_sim.py` | Draft simulator — threshold analysis, pick sheet, play-by-play |
| `pool_stats.py` | Roster summary stats (player types, roles, rank distributions) |
| `view_player.py` | Drill-down viewer — full profile, rank history, PV breakdown for one player |
| `set_player_type.py` | Change a player's tournament role (captain / main / sub / other) |
| `resync_profiles.py` | Re-save all profiles through registry after manual JSON edits |
| `util_opgg_dump.py` | Dump OP.GG page HTML to file for inspecting/updating CSS selectors |
| `cli_shared_filters.py` | Shared CLI helpers (season filter, player type filter, player lookup) |

---

## E2E Workflows

### Workflow 1 — Season Bootstrap from CSV

Use at the start of a new season after form responses are collected.

```bash
# 1. Load raw form response CSV into player profiles
python3 scripts/ingest_csv.py

# 2. Scrape OP.GG rank history for all players (tracks 4-state progress, safe to re-run)
python3 scripts/opgg_batch_update.py           # run all remaining
python3 scripts/opgg_batch_update.py --status  # check progress
python3 scripts/opgg_batch_update.py --reset   # start fresh if needed

# 3. Compute rank stats then PV scores for all players
python3 scripts/compute_pv.py --recalculate

# 4. Export draft pool to CSV for Google Sheets
python3 scripts/export_csv.py
python3 scripts/export_csv.py --out custom.csv        # custom path
python3 scripts/export_csv.py --season S4             # explicit season
```

---

### Workflow 2 — Mid-Season Player Additions & Quick Profile Edits

Use when a new player joins after the bulk bootstrap, or when existing player data needs updating (new account, rank correction, in-house results, PV adjustment).

```bash
# 1. Add or update the player profile
python3 scripts/manage_player.py
```

Action menu for existing players:
- **Add new account** — two sub-modes:
  - `Manual entry` — enter Riot ID, region, archived flag, then optionally add rank history split by split
  - `Automated (OP.GG scraper)` — enter Riot ID and OP.GG URL, triggers scrape immediately
- **Add new tournament season** — add a `SeasonData` entry (player type, roles, stated ranks) for a new season
- **Manage adjustments** — edit per-season PV modifiers: `inhouse_modifier`, `region_modifier`, `admin_modifier`, `previous_winner_modifier`
- **Enter in-house data** — log W/L record for the season (feeds Wilson modifier; previews eligibility before saving)
- **New Player Profile** — full re-entry of all profile fields

```bash
# 2. If OP.GG rank data is needed for a specific player (skip if used auto-scrape above)
python3 scripts/opgg_update.py                      # interactive player select
python3 scripts/opgg_update.py donny,Komi,player3  # via CLI args

# 3. Recompute PV after profile changes
python3 scripts/compute_pv.py

# 4. Re-export if the Google Sheet needs refreshing
python3 scripts/export_csv.py
```

---

### Workflow 3 — Draft Threshold Analysis & Simulation

Use to determine R2/R4 captain pick thresholds and validate draft strategy before the live draft.

**Before running:** update `CAPTAIN_SLOTS` at the top of `scripts/draft_sim.py` with your tournament's captains and pick order.

**What are thresholds?**
R2 = minimum team PV (captain + 2 picks) a captain must reach after round 2. R4 = same after round 4.

#### Step 1 — Discover thresholds with Monte Carlo analysis

```bash
# Default: 200 sims, role_greedy strategy
python3 scripts/draft_sim.py --analyze 500

# Compare against pure greedy baseline (no role balancing)
python3 scripts/draft_sim.py --analyze 500 --strategy greedy_pv

# Control pick variance
python3 scripts/draft_sim.py --analyze 500 --top-n 1   # deterministic
python3 scripts/draft_sim.py --analyze 500 --top-n 5   # default: random from top 5 per role
python3 scripts/draft_sim.py --analyze 500 --top-n 10  # high variance
```

Output per captain: Min / P25 / Median / P75 / Max team PV after 2 and 4 picks.
Also prints a **suggested threshold** = avg P25 across all captains.

#### Step 2 — Stress-test a candidate threshold

```bash
python3 scripts/draft_sim.py --analyze 500 --r2 85.0
python3 scripts/draft_sim.py --analyze 500 --r2 85.0 --r4 160.0
```

#### Step 3 — Generate the pick sheet

```bash
python3 scripts/draft_sim.py --recommend 85.0 --r4 160.0
```

Output: per-captain optimal pick sequence with running PV totals; flags picks constrained by thresholds.

#### Step 4 — Validate with play-by-play walkthrough

```bash
python3 scripts/draft_sim.py --simulate                          # prompts for R2/R4
python3 scripts/draft_sim.py --simulate --r2 85.0 --r4 160.0
python3 scripts/draft_sim.py --simulate --r2 85.0 --seed 42     # reproducible
```

#### Optional — Retune PV weights before simulating

```bash
python3 scripts/compute_pv.py --tune      # interactive weight editor
python3 scripts/compute_pv.py             # recompute and review PV table
python3 scripts/draft_sim.py --analyze 500
```

---

## One-Time Utilities

| Script | When to use |
|--------|------------|
| `pool_stats.py` | Sanity-check roster composition before draft (type counts, role/rank distributions) |
| `view_player.py` | Inspect a single player's full data and PV feature breakdown |
| `set_player_type.py` | Promote a sub to main, designate a captain — accepts player_id or RiotID#Tag |
| `resync_profiles.py` | After directly editing player JSON files — applies renames and recomputes enrichment |
| `util_opgg_dump.py` | OP.GG CSS selectors broke after a site update — dump DOM to fix `opgg_config.yaml` |
