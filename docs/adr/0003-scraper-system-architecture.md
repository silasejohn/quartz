# Scraper System Architecture

The scraper system is built around four sources (OP.GG, LOG, DPM.lol, Rewind.LOL) plus the Riot API. Several non-obvious decisions were made about source ownership, the scraper interface, the visible-browser constraint, error reporting, and CLI structure.

## Decisions

### 1. One source owns each field — no runtime field-level merge

Each scraper source is authoritative for a distinct set of fields. Where two sites could provide the same data, one is chosen at authoring time and the other is not used for that field. No code path exists to merge competing values from two live sources at runtime.

**Why:** Field-level runtime merge requires a conflict-resolution policy (last-write-wins, rank-score-wins, source-priority-order). Every such policy is a hidden assumption that breaks silently when a site changes its data. Authoring-time ownership is explicit, testable, and requires no merge logic.

**How to apply:** When adding a new field to `ChampionSplitStats` or `SplitRankEntry`, document which source owns it. If a better source is found later, migrate the field ownership and remove the old extraction code — don't add a second source.

---

### 2. Explicit typed methods per scraper — no abstract interface on BaseScraper

Each scraper class defines its own typed public methods (`extract_solo_rank_data → AccountRankData`, `extract_champion_stats → AccountChampionData`). `BaseScraper` provides browser management only — it does not declare abstract scraping methods.

**Why:** All four scrapers produce different output types. A uniform `scrape_account(account) → T` abstract method would require a generic return type, losing Pydantic model specificity. With four scrapers and a single author, the ergonomics of generics cost more than they save. Consistency is enforced by convention and documentation, not by the type system.

**How to apply:** When adding a new scraper, name extraction methods `extract_<data_type>()` and have them return the canonical Pydantic model for that data. The corresponding task module is the caller — it knows what to call by name.

---

### 3. requires_visible_browser is a class-level constraint, enforced at setup

Scrapers that rely on hover tooltips to surface data (currently OP.GG and LOG — peak rank is only visible via hover) declare `requires_visible_browser: bool = True`. `BaseScraper.setup()` raises a clear error if `browser_headless=True` is passed to such a scraper.

**Why:** Calling an OP.GG or LOG scraper in headless mode silently produces incomplete rank data — no error, no warning, just `None` for peak rank fields. The failure is invisible until PV computation produces wrong scores. Encoding the constraint on the class makes it impossible to misuse without a loud failure at startup.

**How to apply:** Any scraper that uses hover/tooltip interactions must set `requires_visible_browser = True`. DPM and Rewind are headless-capable (`False`). Verify this constraint empirically during integration testing before committing the value.

---

### 4. ScrapeResult replaces raw tuple returns on all scrape tasks

All scrape tasks return a `ScrapeResult` dataclass (not a raw `(soft_errors, not_found)` tuple). `ScrapeResult` holds a list of `AccountScrapeOutcome` objects, each with a `status: str` and `detail: Optional[str]`. Exposes `retryable`, `flagged` views, and a `retry_hint(cli_verb)` method.

**Why:** The existing tuple return on `OPGG_SCRAPE_RANK` conflates two error categories and provides no per-account detail. As the scraper count grows, callers would need to handle four different tuple shapes. A shared result contract means the CLI output, logging, and retry logic are written once and apply to all tasks. `soft_error` subtypes (e.g. `"soft_error_no_rank"`) are added post-integration-testing — not pre-specified — to avoid specifying failure modes before they've been observed.

**How to apply:** `OPGG_SCRAPE_RANK` is retrofitted to return `ScrapeResult`. All new scrape tasks use it from the start. `ScrapeResult` lives in `quartz/scrapers/core/scrape_result.py`.

---

### 5. CLI: unified flags command + interactive wizard per scraper

Each scraper has two CLI entry points:
- `quartz scrape <source>` — accepts `--players`, `--type`, `--team`, `--season`, `--force` flags. No prompts.
- `quartz scrape <source>-batch` — interactive Typer wizard that builds the same filter interactively, shows the resolved player list for confirmation, then runs.

**Why:** Flags are ergonomic for scripting and targeted re-runs but hard to recall during ad-hoc scouting sessions. An interactive wizard prevents flag-recall errors without removing the flags for power use. Both entry points call the same underlying filter-and-run logic — no duplicated scraping code.

**How to apply:** Filter construction (flags → list of matching accounts) lives in a shared helper, not in either CLI handler. The wizard calls that helper after prompting for each parameter. `--force` in the wizard is a confirmation step ("This will overwrite existing data. Confirm? [y/N]"), not just a silent flag.
