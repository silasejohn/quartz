# Testing Guide

Three layers of testing: unit tests, diagnostic scripts, and CLI end-to-end tests.

---

## 1. Unit Tests

Pure-logic, no network, no browser. Run in CI or locally at any time.

```bash
pytest tests/unit/ -v          # verbose — shows each test name
pytest tests/unit/ -q          # summary only
pytest tests/unit/ --cov=quartz  # with coverage
```

### Test modules

| File | What it covers |
|------|---------------|
| `test_rank_score.py` | `rank_score()` scoring function — Challenger/Iron bounds, LP interpolation, apex tiers |
| `test_compute_enrichment.py` | `compute_enrichment()` — best rank across accounts, win aggregation, archived accounts |
| `test_champion_merge.py` | `ChampionSplitStats.merge_split()` — more-games rule, source exclusivity, `_strip_dpm_data`, `_strip_opgg_champ_data` |
| `test_player_profile_model.py` | `PlayerProfile` model — flag helpers, `touch()`, `last_modified`, JSON round-trip, backwards-compat loading |
| `test_player_profile.py` | Profile construction from CSV rows |
| `test_signup_sheet_adapter.py` | Signup sheet CSV → profile ingest adapter — column mapping, Riot ID parsing, smart skip |
| `test_scrape_state.py` | Skip-logic predicates — `is_complete()`, `dpm_complete()`, `opgg_complete()`, backwards-compat loading of profiles without scrape state fields |
| `test_scrape_result.py` | `ScrapeResult` — `errors`, `retryable`, `summary()`, `retry_hint()`, double-counting guards |
| `test_pv_compute.py` | PV formula — F1/F2 blend, confidence curve, ATP decay, F3/F4, eligibility |
| `test_pv_compute_pool.py` | `compute_N_threshold()`, `compute_realistic_max()`, pool-level helpers |
| `test_pv_compute_champ.py` | F5/F6 champion pool modifiers — `tier_width_at_pv()`, bracket model, bracket confidence, empty bracket penalty, `compute_champ_dpm_baseline()` |

### Fixtures

`tests/fixtures/` contains committed, stable snapshots used as test inputs — never auto-generated.

| Path | Purpose |
|------|---------|
| `fixtures/dpm/champions_response.json` | Full DPM `/v1/players/{id}/champions` payload (dont ever stop#NA1) |
| `fixtures/dpm/champions_response_pingspam.json` | Second DPM payload (PingSpam#NA1) |
| `fixtures/opgg/champ_new_format.html` | OP.GG champion page — current HTML format (S2026) |
| `fixtures/opgg/champ_old_format.html` | OP.GG champion page — legacy format (S2024 S1) |
| `fixtures/opgg/main_page.html` | OP.GG main profile page |

---

## 2. Diagnostic Scripts

Live network + real browser. Require Chrome + internet. Never run in CI.

```bash
python tests/diag/<script>.py
```

| Script | When to use |
|--------|-------------|
| `diag_dpm.py` | Capture a full DPM API response via CDP for a live player account |
| `diag_dpm_main_page.py` | Debug DPM main page loading and network capture |
| `diag_dpm_queue_lane.py` | Verify DPM queue+lane response structure for a specific account |
| `diag_opgg_champ.py` | Test `OPGGScraper.extract_all_champion_seasons()` against a live account |
| `diag_opgg_champ_cells.py` | Inspect individual OP.GG champion stat cells (CSS selector debugging) |
| `diag_opgg_champ_fixtures.py` | Re-capture OP.GG champion page HTML into test fixtures |
| `diag_network_inspector.py` | General-purpose CDP network inspector — dump all JSON API calls a page makes |
| `diag_network_analyze.py` | Compare captured network responses against what the scrapers actually capture |
| `diag_f1_f2_analysis.py` | F1/F2 PV feature analysis against live data |
| `diag_log_headless.py` | Test LOG.lol scraper in headless mode |
| `diag_log_undetected.py` | Test LOG.lol scraper with undetected-chromedriver |

**Workflow for fixing broken CSS selectors:**
1. Run `quartz debug opgg-dump PLAYER` to dump the live HTML
2. Compare against `fixtures/opgg/` to spot structural changes
3. Update `quartz/scrapers/configs/opgg_config.yaml`
4. Run `diag_opgg_champ.py` to verify the fix
5. Run `diag_opgg_champ_fixtures.py` to update the fixture HTML if needed

---

## 3. CLI End-to-End Tests (v4 test profiles)

Pre-seeded player profiles in `data/test/v4/players/` exercise every code path in the scrape
pipeline without needing to touch real player data.

### Setup

```bash
export QUARTZ_CONFIG=tournaments/test_v4.yaml
```

All `quartz` commands will now target the test tournament instead of the active one.
Unset with `unset QUARTZ_CONFIG` when done.

### Quick smoke test (no browser)

```bash
quartz scrape opgg --status
```

Expected output:
```
total active accounts        10
complete (rank + champ)       2
rank only                     2
champ only                    0
has scrape error              2
never attempted               4
needs riot_id update          0
```

### Full scrape test

```bash
quartz scrape opgg
```

### Test profile index

| Profile | Riot ID(s) | Pre-seeded state | Expected outcome |
|---------|-----------|-----------------|-----------------|
| `qt_fresh` | `SPP VoidSpawn#NA1` | No data | Scrapes rank + champ; flags low level (account level < 100) |
| `qt_skip_all` | `SPP VoidSpawn#NA1` | Rank complete + OPGG champ complete | `status: skipped` — no navigation |
| `qt_skip_rank` | `SPP VoidSpawn#NA1` | Rank complete, no champ | Navigates once, skips rank extraction, scrapes champ only |
| `qt_rank_retry` | `SPP VoidSpawn#NA1` | `rank_data.last_scrape_error` set | Retries rank despite having prior `scraped_at` |
| `qt_champ_retry` | `SPP VoidSpawn#NA1` | Rank complete, `opgg_last_scrape_error` set | Skips rank, retries champ |
| `qt_archived` | `SPP VoidSpawn#NA1` | `archived: true` | `status: skipped/archived` — no navigation |
| `qt_name_change` | `FakeTestPlayer#QT07` | No data, nonexistent Riot ID | `status: not_found`, `FLAG_NAME_CHANGED` added, `last_scrape_error` set |
| `qt_multi` | `SPP VoidSpawn#NA1` + `FakeTestPlayer#QT08` | Acct A complete; Acct B has rank error | Acct A skipped; Acct B retried → not_found |
| `qt_dpm_stale` | `SPP VoidSpawn#NA1` | `dpm_scraped_for_split: S2025` | Run with `quartz scrape dpm` — re-scrapes despite `dpm_scraped_at` being set |
| `qt_crash_test` | `SPP VoidSpawn#NA1` | No data | See browser crash procedure below |

### What to verify after a full run

After `quartz scrape opgg`:

1. `qt_fresh` — `rank_data.scraped_at` and `champion_data.solo.opgg_scraped_at` now set; `FLAG_LOW_LEVEL` present
2. `qt_skip_all` — JSON unchanged (no browser navigation happened)
3. `qt_skip_rank` — `champion_data.solo.opgg_scraped_at` now set; rank fields untouched
4. `qt_rank_retry` — `rank_data.last_scrape_error` now null (cleared on success); `scraped_at` refreshed
5. `qt_champ_retry` — `opgg_last_scrape_error` now null; `opgg_scraped_at` refreshed
6. `qt_archived` — JSON unchanged
7. `qt_name_change` — `FLAG_NAME_CHANGED` auto-flag present; `last_scrape_error` set on rank + champ
8. `qt_multi` — Acct A unchanged; Acct B has `FLAG_NAME_CHANGED` and `last_scrape_error`

Re-run `quartz scrape opgg --status` — should show most accounts complete, 2 under `needs riot_id update`.

### DPM stale season test

```bash
quartz scrape dpm qt_dpm_stale
```

Verify: `dpm_scraped_for_split` updated to `S2026`, `dpm_scraped_at` refreshed.

---

## 4. Browser Crash Recovery Test (manual)

Tests the outer exception handler that restarts the browser and saves partial state.

**Setup:** Use two profiles — one that succeeds before the crash, one that is the crash target.

```bash
# Run a sequence where qt_skip_all processes first (fast skip), then qt_crash_test navigates
quartz scrape opgg qt_skip_all qt_crash_test
```

**During execution:** Once you see the log line `Processing: qt_crash_test` and navigation has started,
kill Chrome in a second terminal:

```bash
kill $(pgrep -f "Google Chrome")   # macOS
# or force-kill: kill -9 $(pgrep -f chrome)
```

**Expected behavior:**
1. Console prints: `Browser crash on qt_crash_test: ... — attempting restart`
2. Scraper calls `scraper.close()` then `scraper.setup()` — a new browser window opens
3. `qt_crash_test.json` is saved with whatever partial state existed before the crash
   (`scrape_started_at` set, `scraped_at` null, `last_scrape_error` set to the exception message)
4. If more profiles follow in the queue, they continue processing in the restarted browser

**Restart failure path:** If `scraper.setup()` fails (e.g., Chrome won't start):
- Profile is saved with partial state
- Exception is re-raised, aborting the run
- Run `quartz scrape opgg qt_crash_test` to retry just that profile

---

## Resetting test profiles

After a full run, profiles in `data/test/v4/players/` will have been mutated by the scraper.
To restore them to their original pre-seeded state:

```bash
git checkout data/test/v4/players/
```

Or to reset a single profile:

```bash
git checkout data/test/v4/players/qt_fresh.json
```
