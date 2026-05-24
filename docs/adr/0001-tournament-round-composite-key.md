# Tournament Round Identifier Uses Composite Key

Tournament rounds are identified by a composite key of the form `{TOURNAMENT}-{ROUND}` (e.g. `GCS-S4`, `LEPL-S3`) rather than a bare round label like `S4`. This is stored as the `SeasonData.season` key on player profiles and derived via a `round_id` computed property on `TournamentConfig`.

The bare `S4` label collides with three other things in the codebase: the LoL ranked season "Season 4" (2014) in `SEASON_ORDER`, and the rank shorthand "Silver 4" in `RANK_ALIASES`. A future reader looking at a player profile with `"season": "S4"` cannot tell which tournament or even which kind of entity that refers to. The composite key is self-describing in all contexts.

## Considered Options

- **Bare round label** (`S4`) — shorter, already in use, but ambiguous in three different namespaces simultaneously.
- **Full composite in YAML** (`current_round: GCS-S4`) — redundant; the tournament name is already declared separately.
- **Composite derived in code** — `TournamentConfig` holds `tournament: GCS` and `current_round: S4` separately; `round_id` property composes them. YAML stays non-redundant, code produces the canonical key. ← chosen.
