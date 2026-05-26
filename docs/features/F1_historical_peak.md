# F1 — Time-Decayed Historical Peak Score

Time-decayed, confidence-weighted average of a player's peak rank across the past year of LoL splits.

## What it captures

A player's peak performance across recent splits, weighted toward the most recent. Accounts for players who peaked one or two splits ago but may have dropped off, or players climbing steadily. Also accounts for splits where the player barely played — a peak established in 5 games is treated with less confidence than one established in 100.

## Formula

```
confidence_i  = 1 - e^(-games_i / N_historical_i)
effective_w_i = base_weight_i × confidence_i
F1            = Σ (effective_w_i / Σ effective_w) × rank_score(peak_rank_i)
```

Where:
- `base_weight_i` comes from `PVWeights.historical_base_weights` (default: `[0.40, 0.25, 0.15, 0.12]`)
- `confidence_i` scales each split's base weight by how many games were played that split
- `N_historical_i` is the games threshold for split `i` — see below
- Weights are re-normalized over splits with effective weight > 0 (sparse normalization)
- `rank_score()` maps rank strings to numeric scores — lower score = stronger player

### Before this change (legacy)

```
F1 = Σ (base_weight_i / total_active_weight) × rank_score(peak_rank_i)
```

Games played had no effect — a 3-game Master peak scored identically to a 150-game Master peak.

## N_historical — per-split confidence threshold

`N_historical` is derived independently for each historical split from the pool's games distribution for that split, with a hard floor:

```
N_historical_i = max(n_historical_floor, pool_stat(games_i across all players))
```

Where `pool_stat` uses the same `confidence_strategy` as F2 (MEDIAN / P25 / MEAN_1SD). This means N self-calibrates: if the pool largely skipped a particular split, N floors at 30 rather than collapsing to a tiny number. If the pool played heavily that split, N rises to reflect the real competition level.

## Sparse normalization and missing data

A split is excluded from F1 (weight = 0) in two cases:
1. No `peak_rank` data — not scraped at all (same as before)
2. `games = 0 or None` — confidence = 0, effective weight = 0

The remaining splits renormalize over their effective weights. A player with 2 high-confidence splits is not penalized vs. one with 4 low-confidence splits.

If a split has `peak_rank` but `games = None` (not yet scraped), it is treated conservatively as excluded rather than assumed fully trusted. Re-run `quartz scrape champ` to populate games data for historical splits via the OPGG champion season backfill.

## Parameters

| Parameter | Default | Effect |
|-----------|---------|--------|
| `historical_base_weights` | `[0.40, 0.25, 0.15, 0.12]` | Time-decay curve — how much each past split counts before confidence scaling |
| `history_splits` | 4 | How many past splits to include (1–4) |
| `n_historical_floor` | 30 | Minimum N for any historical split's confidence curve |
| `confidence_strategy` | `median` | How N_historical is derived from pool (shared with F2) |
| `w_historical` | 1.0 | Blend weight relative to F2 at final combination |

## Splits used

`PAST_YEAR_SEASONS` in `constants.py` defines which LoL splits are "recent history" (currently S2025, S2024 S3, S2024 S2, S2024 S1). Updated annually.

## Edge cases

- If a player has no splits with both `peak_rank` and `games > 0`, F1 is `None`. The final PV formula renormalizes — F2 carries full weight if F1 is missing.
- Unranked or missing `peak_rank` entries are skipped (not treated as Unranked = 0-skill).
- For very old splits where few pool members played (e.g. S2024 S1), N floors at `n_historical_floor = 30` so confidence doesn't artificially spike.
