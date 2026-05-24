# Quartz — Open TODOs

Organized by area. Each item links to the relevant feature or system doc where applicable.

---

## PV Features

### F1 — Historical Peak ([docs](features/F1_historical_peak.md))
- [ ] **Confidence-weighted peak rank**: weight each split's peak_rank by a confidence factor derived from games played that split. A peak rank achieved in 5 games should count less than one earned over 200. Mirrors the F2 confidence curve, applied retroactively to historical splits.

### F3 — In-House Wilson Modifier ([docs](features/F3_inhouse_wilson.md))
- [ ] **Pool-relative manual adjustment scaling**: instead of hard-coding typical values (e.g. "+5 for previous winner"), scale adjustment values as a proportion of the pool's PV range (max_pv - min_pv). Makes adjustments portable across tournaments with different skill distributions.

---

## Data Ingest

### Historical Split Games (needed for F1 confidence weighting)
- [ ] Ensure `wins` + `losses` are reliably scraped for all historical splits, not just the current one. OP.GG sometimes omits game counts on older splits. Verify coverage and add fallback logic in `OPGGScraper._extract_season_history()`.
- [ ] Once games data is reliable for historical splits, wire up the F1 confidence weighting (see F1 TODO above).

### Champion Pool — DPM.lol (DPM_SCRAPE_CHAMP task)
- [ ] Build `DPMScraper` in `quartz/scrapers/dpm_scraper.py`
- [ ] Implement `DPMEnrichChamp` task in `quartz/tasks/dpm_enrich_champ.py`
- [ ] Populate `Account.champion_data.solo` and `.flex` from DPM data
- [ ] Add `CALCULATE_CHAMP_STATS` task to aggregate `AccountChampionData` → `PlayerStats.champion_pool`

### Champion Pool — OP.GG (OPGG_SCRAPE_CHAMP task)
- [ ] Implement `extract_champion_pool()` on `OPGGScraper` (currently raises `NotImplementedError`)
- [ ] Implement `OPGGEnrichChamp` task in `quartz/tasks/opgg_enrich_champ.py`

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

- [ ] Implement `EXPORT` task and `quartz export` CLI command (currently raises `NotImplementedError`)
- [ ] Include champion pool summary columns in export

---

## Scraper System

### Concurrency
- [ ] **Parallel scraping**: scrapers currently run sequentially (one account at a time). Investigate `ThreadPoolExecutor` with thread-local WebDriver instances (see Zephyr `ConcurrentManager` as reference). Note: OP.GG and LOG **cannot run headless** (hover tooltips required for rank data); Rewind.LOL and DPM.lol are candidates for headless + parallel mode.

### PUUID per Account
- [ ] Store `puuid` on `Account` in `PlayerProfile`. PUUID is stable across Riot ID name changes — using it resolves the `update_riot_id` flag problem permanently. Lookup: Riot Account API (`/riot/account/v1/accounts/by-riot-id/{gameName}/{tagLine}`). Investigate `riotwatcher` library (`pip install riotwatcher`) as a clean Riot API client; also see Zephyr `backend/modules/api_clients/riot_api/` for existing reference implementation.

---

## Project Config

- [ ] **SonarQube Python version**: set `sonar.python.version` in `sonar-project.properties` (create if absent) so analysis targets the actual interpreter version instead of defaulting to all-Python-3 compatibility. Use the version from `.python-version` or `pyproject.toml`.

---

## General

- [ ] Add integration test coverage for `OPGGScraper` against a recorded DOM fixture
- [ ] Add `quartz/scrapers/rewind_lol.py` stub when REWIND_LOL source is scoped
