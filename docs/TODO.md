# Quartz — Open TODOs

Organized by area. Each item links to the relevant feature or system doc where applicable.

---

## PV Features

### F1 — Historical Peak ([docs](features/F1_historical_peak.md))
- [x] **Confidence-weighted peak rank** — each split's base weight is scaled by `1 - e^(-games/N_historical)` before normalization. `f1_confidence` stored on `PVFeatures` and shown in `quartz view`. ✅

### F2 — Confidence-Adjusted Current Rank
- No open items.

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
- [x] `DPMScraper` in `quartz/scrapers/dpm_scraper.py` ✅
- [x] `dpm_scrape_champ` task — scrapes per-role + ALL aggregate, merges into `Account.champion_data` ✅
- [x] `dpm_score` field on `ChampionSplitStats` ✅
- [x] Per-role champion data (`TOP/JGL/MID/BOT/SUP`) with `role="ALL"` aggregate ✅
- [ ] **DPM scraper: pass config `api_response` timeout** — task hardcodes default 10s; config says 15s. Pass `scraper.config.get("timeouts.api_response", 10)` to `extract_champion_data()`.
- [ ] **Store PUUID on Account** — `extract_champion_data()` returns puuid but the task discards it (`_`). Store on `account.puuid` if currently `None`.
- [ ] **Regional baseline stats** — DPM shows player avg and per-champ/per-rank regional baseline. Store both so pipeline can compute normalized delta without re-scraping. Needs parallel `_baseline` field on `ChampionSplitStats`.
- [ ] **`cs_at_15`** — absolute CS at 15 min (different from `csd_at_10` which is lane differential). DPM exposes this; add to `ChampionSplitStats` (source: `"dpm"`).

### Champion Pool — OP.GG
- [x] `opgg_scrape_champ` task — scrapes all historical seasons, wins/losses/WR/op_score per champion ✅
- [x] `op_score` field on `ChampionSplitStats` ✅
- [x] `mastery_points` on `ChampionEntry` ✅
- [x] Historical W/L backfill into rank splits ✅

### Riot API
- [ ] Build `RiotAPIClient` in `quartz/scrapers/riot_api.py`
- [ ] Prioritize: CSD@10, early deaths, first blood rate (Cluster 1 laning stats not available from DPM/OPGG)
- [ ] Add `RIOT_ENRICH_MATCH` task

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
- [ ] Store `puuid` on `Account` in `PlayerProfile`. PUUID is stable across Riot ID name changes — using it resolves the `name_changed` flag problem permanently. DPM scraper already extracts it but it's discarded. Lookup via Riot Account API if not available from DPM.

---

## Project Config

- [ ] **SonarQube Python version**: set `sonar.python.version` in `sonar-project.properties` so analysis targets the actual interpreter version.

---

## General

- [ ] Add integration test coverage for `OPGGScraper` against a recorded DOM fixture
- [ ] Add `quartz/scrapers/rewind_lol.py` stub when Rewind.LOL source is scoped
