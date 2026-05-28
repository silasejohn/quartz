# Quartz — Open TODOs

Organized by area. Each item links to the relevant feature or system doc where applicable.

---

## PV Features

### F1 — Historical Peak ([docs](features/F1_historical_peak.md))
- [x] **Confidence-weighted peak rank** — each split's base weight is scaled by `1 - e^(-games/N_historical)` before normalization. `f1_confidence` stored on `PVFeatures` and shown in `quartz view`. ✅

### F2 — Confidence-Adjusted Current Rank ([docs](features/F2_confidence_rank.md))
- [ ] **ATP staleness decay** — per-season checkpoint model decays `all_time_peak_rank` toward current rank as post-peak evidence accumulates. Multi-condition season gate (hard floor 50g, 40% personal avg, P25 pool, WR<55%). Compounds across seasons. `atp_decay_factor` + `effective_atp_rs` stored on `PVFeatures`. New pool-level helpers: `compute_atp_miss_scale()`, `compute_atp_season_min_games()`. See feature doc.
- [ ] **`win_rate` model validator** — `AggregatedSplitRank`: raise `ValueError` if `wins + losses > 0` and `win_rate is None`. Catches bad data at ingest rather than silently skipping seasons at PV compute time.
- [ ] **New `PVWeights` fields**: `atp_hard_floor_games=50`, `atp_personal_volume_pct=0.40`, `atp_season_pool_percentile=0.25`, `atp_climbing_wr_threshold=55.0`, `atp_max_miss_scale_override=None`.

### Champion Pool Features ([docs](features/CHAMP_FEATURES.md))
- [x] **Pool-median baseline + bracket confidence + empty bracket penalty** — F5 redesigned: runtime pool-median baseline (not fixed 50.0), `games_min=3`, bracket confidence layer (`1 − exp(−games / N_bracket)`), and empty brackets penalized at `−sigma × pool_stddev` per bracket. See ADR `docs/adr/0004-f5-pool-median-redesign.md`. ✅
- [ ] **Recalibrate `champ_scale_factor`** — with residuals now centred at 0 (not +12 as with old 50.0 baseline), typical raw_delta is much smaller. Scale factor likely needs to increase from 0.13 to maintain ~2-4 PV spread. Requires running against real pool data and comparing distributions.
- [ ] **Upgrade champion residuals to regional baseline** — current MVP uses pool-median DPM score as baseline. Once `ChampionSplitStats._baseline` is populated by the DPM scraper (see Data Ingest TODO below), update `_compute_raw_delta()` to use `dpm_score - regional_avg_for_champ_at_rank_range` instead. Formula shape is identical — one-line swap.
- [ ] **Add OP Score as a champion bracket input** — currently MVP uses DPM Score only. Add `op_score` as a secondary signal once the bracket design is validated. Blend weight TBD (e.g. 70/30 DPM/OP or equal weight).
- [ ] **Build a custom composite score** — eventually replace raw DPM Score with a weighted composite across all collected fields: `dpm_score`, `op_score`, `op_laning_score`, `kda`, `cs_per_min`, `kill_participation_pct`, `gold_share_pct`, etc. Treat this as the Quartz-native champion quality signal once enough data has been collected to calibrate weights.

### F3 — In-House Wilson Modifier ([docs](features/F3_inhouse_wilson.md))
- [ ] **Pool-relative manual adjustment scaling**: scale adjustment values as a proportion of the pool's PV range (`max_pv - min_pv`). Makes adjustments portable across tournaments with different skill distributions.
- [ ] **Dynamic cap on `max_bonus_points`**: flat `5.0` PV ceiling should scale with pool rank spread so the bonus magnitude is self-calibrating. Same principle applies to the future champion pool PV modifier cap.

---

## Eligibility & Flags
- [x] **Player eligibility rule** — `EligibilityConfig` in `active_tournament.yaml`; evaluated in `PV_COMPUTE` and `resync`. Ineligible players get `flag_reason="ineligible"`, shadow PV computed and stored. ✅
- [x] **Account flags system** — `AccountFlag` model replacing boolean fields; `flags.py` CLI; `evaluate_account_flags()` auto-evaluates `low_level`, `low_volume`, `smurf_peak`, `smurf_jump`; `name_changed` set by rank scraper. ✅
- [x] **Shadow PV** — `quartz pv-shadow` shows ineligible players and what their PV would be if eligible. ✅

---

## Data Ingest

### Historical Split Games
- [x] **Backfill historical W/L from OPGG champion scraper** — `_backfill_rank_wl()` in `opgg_scrape_champ.py` fills `SplitRankEntry.wins/losses` from season totals summed across champion rows. ✅
- [ ] **Verify OPGG historical op_score coverage** — OP.GG sometimes omits op_score on older splits (pre-S2024 S3). Confirm which seasons reliably have it and add a note to the scraper if fallback logic is needed.

### Champion Pool — DPM.lol
- [x] `DPMScraper` — CDP-based network interception, undetected_chromedriver for Cloudflare bypass ✅
- [x] `dpm_scrape_champ` task — scrapes per-role (TOP/JGL/MID/BOT/SUP) + ALL aggregate, merges into `Account.champion_data` ✅
- [x] Profile update button triggered before scraping begins ✅
- [x] `api_response` timeout read from `dpm_config.yaml` and passed to `extract_champion_data()` ✅
- [x] PUUID extracted from first API URL and stored on `account.puuid` if not already set ✅
- [x] DPM-exclusive fields: `dpm_score`, `cs_at_15` (stub), `first_blood_rate`, `solo_kills_per_game`, `kill_participation_pct`, `gold_share_pct`, `vision_score_per_min` ✅
- [ ] **Regional baseline stats** — DPM shows player avg and per-champ/per-rank regional baseline. Store both so pipeline can compute normalized delta without re-scraping. Needs parallel `_baseline` field on `ChampionSplitStats`.
- [ ] **`cs_at_15`** — DPM exposes this field; not yet parsed from the API response. Add to `_add_to_pool()` in `dpm_scraper.py`.

### Champion Pool — OP.GG
- [x] `opgg_scrape_champ` task — scrapes all historical seasons via direct URL navigation, Solo/Duo + Flex ✅
- [x] Two table formats handled: new format (S2024 S3+, ~15 cells) and old format (S2024 S2−, ~12 cells) ✅
- [x] OPGG-exclusive fields: `op_score`, `expected_op_score`, `op_laning_score`, `expected_laning_pct`, `avg_vision_score`, `avg_cs_per_game`, `avg_gold_per_game` ✅
- [x] Contested fields from OPGG: `kda`, `kills/deaths/assists_per_game`, `dpm`, `damage_share_pct`, `cs_per_min`, `gpm` ✅
- [x] Historical W/L backfill into rank splits via `_backfill_rank_wl()` ✅
- [x] `mastery_points` on `ChampionEntry` ✅
- [x] HTML fixtures saved to `tests/fixtures/opgg/` for offline parsing validation ✅

### Champion Pool — Merge & Source Attribution
- [x] `ChampionSplitStats.source` — `"dpm"`, `"opgg"`, `"multi"` (both sources contributed) ✅
- [x] `_SOURCE_EXCLUSIVE` map — 18 fields, prevents cross-source overwrite regardless of game count ✅
- [x] `OPGG_EXCLUSIVE_FIELDS` / `DPM_EXCLUSIVE_FIELDS` — module-level frozensets used by strip logic ✅
- [x] `_strip_dpm_data` / `_strip_opgg_champ_data` — force re-scrape of one source preserves the other's exclusive fields on `"multi"` splits ✅

### Riot API
- [ ] Build `RiotAPIClient` in `quartz/scrapers/riot_api.py`
- [ ] Prioritize: CSD@10, early deaths, first blood rate (Cluster 1 laning stats not available from DPM/OPGG)
- [ ] Add `RIOT_ENRICH_MATCH` task

### Signup Sheet Adapter
- [x] Build integrated adapter inside `quartz ingest` — converts raw Signup Sheet CSV → player profiles in one command, no intermediate file required ✅
- [x] Save transformed output to `data/{tournament}/{round}/processed/` as an audit trail CSV (not used by pipeline) ✅
- [x] Smart skip: default run only creates profiles for new Player IDs (not yet in registry); `--force` re-runs upsert logic for all rows ✅
- [x] Support configurable column mapping per tournament in `active_tournament.yaml` (`signup_sheet:` block) ✅
- [x] Parse Riot IDs from OP.GG single-profile and multisearch URLs; U.GG as fallback ✅
- [x] **Manual supplemental accounts**: use `quartz manage` → select player → "Add new account" (manual entry or automated OP.GG scrape). ✅

### Remote CSV Ingest
- [ ] Build `RemoteCSVInput` (Google Sheets reader) and implement `REMOTE_CSV_INGEST` task

---

## Draft Simulator

- [ ] Surface champion pool data in draft recommendations (pick constraints by champ pool depth)
- [ ] Add champion-based pick score modifier once `PlayerStats.champion_pool` is populated

---

## Export

- [ ] Include champion pool summary columns in export CSV

---

## Scraper System

### Concurrency
- [ ] **Parallel scraping**: scrapers currently run sequentially. Investigate `ThreadPoolExecutor` with thread-local WebDriver instances. DPM and Rewind.LOL are candidates for headless + parallel mode; OP.GG and LOG require visible browser (hover tooltips).

### PUUID per Account
- [x] `puuid` stored on `Account` — `dpm_scrape_champ` stores it from the first intercepted API URL. ✅
- [x] `RIOT_ENRICH_PUUID` task runs automatically at the start of `quartz resync` and `quartz pv --recalculate` — fills any remaining gaps via Riot Account API. ✅

---

## Project Config

- [ ] **SonarQube Python version**: set `sonar.python.version` in `sonar-project.properties` so analysis targets the actual interpreter version.

---

## General

- [ ] Add integration test coverage for `OPGGScraper` against a recorded DOM fixture (HTML files now in `tests/fixtures/opgg/`)
- [ ] Add `quartz/scrapers/rewind_lol.py` stub when Rewind.LOL source is scoped
