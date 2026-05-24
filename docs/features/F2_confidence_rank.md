# F2 — Confidence-Adjusted Current Rank Score

Current rank score blended with the player's all-time peak rank, weighted by how many ranked games they've played this split.

## Why this exists

Early in a split, players may have played very few ranked games. Their current rank is noisy — a Diamond player 5 games in might be sitting Gold. Rather than penalizing them for low sample size, we regress their current rank toward their **own historical peak** (not a global average). As games accumulate, confidence rises and current rank carries more weight.

## Formula

```
confidence = 1 - e^(-games / N)
F2 = confidence × rank_score(current_rank) + (1 - confidence) × rank_score(all_time_peak_rank)
```

Where:
- `N` is computed from the pool via `compute_N_threshold()` (pool-relative games threshold)
- `all_time_peak_rank` is the best peak rank across all of a player's accounts across all splits
- At `confidence = 0` (0 games): F2 = all-time peak score (player assumed at their ceiling)
- At `confidence = 1` (many games): F2 = current rank score

## Per-player regression target

The regression target is the player's **own** all-time peak, not a pool-wide default. This prevents penalizing strong players who haven't played yet this split — they're assumed to be at their ceiling until proven otherwise.

## N threshold strategies

N is derived from the pool so it scales with competition level:

| Strategy | N value | Bias |
|----------|---------|------|
| `MEDIAN` (default) | Median games across pool | Balanced |
| `P25` | 25th percentile | Softer on casual players |
| `MEAN_1SD` | Mean − 1 std dev | Harsher on low-game outliers |

Override with `n_override` for deterministic behavior.

## Parameters

| Parameter | Default | Effect |
|-----------|---------|--------|
| `w_current` | 1.0 | Blend weight relative to F1 at final combination |
| `confidence_strategy` | `median` | How N is derived from pool |
| `n_override` | `None` | Override N directly |
