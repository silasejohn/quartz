# F1 — Time-Decayed Historical Peak Score

Time-decayed weighted average of a player's peak rank across the past year of LoL splits.

## What it captures

A player's peak performance across recent splits, weighted toward the most recent. Accounts for players who peaked one or two splits ago but may have dropped off, or players climbing steadily.

## Formula

```
F1 = Σ (base_weight_i / total_active_weight) × rank_score(peak_rank_i)
```

Where:
- `base_weight_i` comes from `PVWeights.historical_base_weights` (default: `[0.40, 0.25, 0.15, 0.12]`)
- Weights are re-normalized over only the splits that actually have data (so a player with 2 splits isn't penalized vs one with 4)
- `rank_score()` maps rank strings to numeric scores — lower score = stronger player

## Parameters

| Parameter | Default | Effect |
|-----------|---------|--------|
| `historical_base_weights` | `[0.40, 0.25, 0.15, 0.12]` | Decay curve — how much each past split counts |
| `history_splits` | 4 | How many past splits to include (1–4) |
| `w_historical` | 1.0 | Blend weight relative to F2 at final combination |

## Splits used

`PAST_YEAR_SEASONS` in `constants.py` defines which LoL splits are considered "recent history" (currently S2025, S2024 S3, S2024 S2, S2024 S1). Updated annually.

## Edge cases

- If a player has no data for any past split, F1 is `None`. The final PV formula renormalizes — F2 carries full weight if F1 is missing.
- Unranked or missing peak_rank entries are skipped (not treated as Unranked = 0-skill).
