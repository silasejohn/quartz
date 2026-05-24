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

## LoL Season (active)

The LoL ranked season that was current during a given Tournament Round. Stored explicitly as `lol_season` in the tournament YAML and `TournamentConfig`. Used by the PV pipeline to identify the "current split" for rank data and confidence curve computation.

**Not** derived from `SEASON_ORDER[0]` — that would always return today's season regardless of which historical round is being processed.

---

## Player Registry

The on-disk store of all player profiles for a given tournament round. One JSON file per player. Source of truth for all pipeline stages.
