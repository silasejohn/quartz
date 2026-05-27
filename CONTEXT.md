# Quartz — Domain Glossary

Terms used in code, config, and conversation. Canonical definitions only — no implementation details.

---

## Tournament Round

A labeled iteration of a specific tournament. Uniquely identified by a composite key of the form `{TOURNAMENT}-{ROUND}` (e.g. `GCS-S4`, `LEPL-S3`).

- `TOURNAMENT` — the league name (`GCS`, `LEPL`, etc.)
- `ROUND` — the sequential season label within that league (`S1`, `S2`, `S4`, etc.)

Used as the `SeasonData.season` key on a player's profile.

**Not to be confused with**: LoL Ranked Season (see below).

---

## LoL Ranked Season

A ranked ladder period defined by Riot Games. Used as keys in `SEASON_ORDER`. Follows Riot's own naming: `S2026`, `S2025`, `S2024 S3`, ..., `S4`, `S3`, `S2`, `S1`.

**Not to be confused with**: Tournament Round (see above). The `S4` in `SEASON_ORDER` is Riot Season 4 (2014). The `S4` in a tournament round is e.g. `GCS-S4`.

---

## PV (Point Value)

A numeric score representing a player's strength. **Lower = stronger.** Computed from ranked history, current rank, in-house performance, and admin adjustments. Challenger ≈ 10, Iron ≈ 85.

---

## Current LoL Split

The LoL ranked split/season that was active during a given Tournament Round. Stored explicitly as `current_lol_split` in the tournament YAML and `TournamentConfig`. Used by the PV pipeline to identify the "current split" for rank data and confidence curve computation.

**Not** derived from `SEASON_ORDER[0]` — that would always return today's split regardless of which historical tournament round is being processed.

---

## Champion Pool

Per-account, per-queue, per-champion collection of ranked stats across LoL splits. Stored as `AccountChampionData` on `Account`. Aggregated across accounts into `AggregatedChampionPool` on `PlayerStats`.

Stats are organized into three feature clusters (Laning, Combat, Macro) each tracked per LoL split to support peak/current/trajectory temporal features. Solo queue and flex queue are stored separately — the delta between them is a signal about team vs. individual performance.

Sources: `opgg`, `dpm`, `rewind`, `log`, `riot_api` — source tagged per `ChampionSplitStats` entry. Each source is authoritative for distinct fields; no field has two competing sources.

---

## Scrape Source

One of the external sites scraped by the pipeline. Each source is the sole authority for specific fields — overlap between sources is resolved at authoring time (one site is chosen per field), not at runtime.

| Source | Primary output | Notes |
|---|---|---|
| `opgg` | `AccountRankData` — rank history per split (solo + flex) | Cannot run headless — hover tooltips used for peak rank |
| `log` | `AccountRankData` supplement — fills gaps OPGG misses | Cannot run headless — hover tooltips |
| `dpm` | `AccountChampionData` — champion depth (per-split stats, three feature clusters) | Headless-capable |
| `rewind` | `AccountChampionData` — champion breadth (role-based stats, pool shape) | Headless-capable |
| `riot_api` | Laning cluster fields not available from scrapers (CSD@10, early deaths, first blood rate) | API, no browser |

---

## Scrape Mode

Controls how incoming scraped data is merged with existing profile data.

- **Additive (default):** fills `None` fields only — never overwrites a value already present.
- **Destructive (`--force`):** replaces existing values regardless of current state.

Applies to all scrape tasks. Rank data and champion data follow the same contract.

---

## Scrape Outcome

The result of scraping one account in one task run. Has a `status` string (`"ok"`, `"not_found"`, `"soft_error"`, `"timeout"`, `"parse_error"`, `"flagged"`) and an optional `detail` string carrying human-readable context. `soft_error` subtypes (e.g. `"soft_error_no_rank"`) are added post-integration-testing as real failure modes are observed — not pre-specified.

Aggregated into a `ScrapeResult` per task run, which exposes `retryable` and `flagged` views and generates a `retry_hint` CLI command.

---

## PlayerStats

The aggregated, derived section of a `PlayerProfile`. Populated incrementally by pipeline tasks. Contains: aggregated rank data across all accounts (`AggregatedRankData`), `all_time_peak_rank`, `current_rank`, `champion_pool`, and `computed_pv`.

Formerly named `PlayerEnrichment`. Accessed as `profile.stats` (formerly `profile.data`).

---

## CLI

The `quartz` command — a single entry point with subcommands (`quartz draft`, `quartz manage`, `quartz export`, etc.). Declared in `pyproject.toml [project.scripts]`. Built with `typer`. Lives in `quartz/cli/`.

Replaces the `scripts/` directory of standalone Python files.

---

## Tests

`tests/` directory at the project root, `pytest` wired into `pyproject.toml`. Covers pure-logic layers only: `rank_score()`, `compute_enrichment()`, `compute_pv()`, `merge_split_entries()`. Scrapers and full pipeline excluded (require live browser).

---

## Player Registry

The on-disk store of all player profiles for a given tournament round. One JSON file per player. Source of truth for all pipeline stages.

---

## Account Flag

A structured marker on an individual `Account` indicating a condition that warrants human review. Stored as `Account.flags: list[AccountFlag]`. Each flag has a `flag_type` (e.g. `low_level`, `smurf_peak`, `name_changed`), optional `detail` string, and a `dismissed` bool for admin acknowledgment of false positives.

Dismissed flags remain visible in `quartz view` but are excluded from `account_flagged` computation. See `docs/flags.md` for the full type catalogue and evaluation timing.

**Not to be confused with**: Player Eligibility (see below). Flags are signals for review; eligibility is a binary tournament rulebook determination.

---

## Player Eligibility

Whether a player meets the tournament's minimum ranked games requirement. Configured per tournament in `active_tournament.yaml` (e.g. GCS: 30 games in S2026, or 50+ in S2025 as backup). Stored as `SeasonData.eligible: Optional[bool]` — `None` means not yet evaluated.

Ineligible players receive `point_value = INF` — PV is not computed. A Shadow PV is computed and stored separately for admin reference.

**Not to be confused with**: Account Flags (see above). A flagged account does not make a player ineligible.

---

## Shadow PV

The PV score an ineligible player *would* receive if the eligibility check were bypassed. Computed using the identical F1/F2/F3/F4 formula. Stored on `SeasonData.shadow_point_value` and `ComputedPV.shadow_pv`. Visible via `quartz pv-shadow`. Does not feed into drafting or ranking — informational only.

---

## Flag Reason

Why a `ComputedPV` has no `point_value`. Two distinct values:

- `"no_data"` — no usable rank history at all; displayed as `FLAGGED`
- `"ineligible"` — has rank data but fails the tournament eligibility rule; displayed as `INF`

Stored on `ComputedPV.flag_reason: Optional[str]`. `None` means PV was computed successfully.
