# F3 — In-House Wilson Modifier

An upward-only PV bonus for players who perform well in the tournament's own in-house games.

## What it captures

In-house performance is a direct signal of how a player competes in this specific tournament's environment — against the actual player pool, at the actual competition level. It corrects for players who are ranked higher than they perform in practice, and rewards players whose in-house record suggests they punch above their rank.

## Formula

```
wilson_lb = Wilson lower bound(inhouse_wins, inhouse_total, z=wilson_z)

if wilson_lb > 0.5:
    inhouse_raw        = wilson_lb - 0.5
    inhouse_normalized = inhouse_raw / (realistic_max - 0.5)
    F3 = min(inhouse_normalized, 1.0) × max_bonus_points
```

Where `realistic_max` is the **pool's maximum Wilson LB** — the best-performing player's lower bound. This makes the bonus relative to the pool, not absolute.

## Design decisions

- **Upward-only**: F3 only reduces PV (bonus). Poor in-house performance does not increase PV — rank data already handles that.
- **50% floor**: No bonus is applied unless `wilson_lb > 0.5`. A player below 50% win rate gets 0, not a penalty.
- **Minimum games gate**: `min_games_threshold` (default: 7) must be met before any modifier applies. Prevents noise from 1-2 game samples.
- **Pool-relative normalization**: `realistic_max` is computed each run from the full pool. The best in-house performer gets the full `max_bonus_points`; others are scaled proportionally.

## Parameters

| Parameter | Default | Effect |
|-----------|---------|--------|
| `max_bonus_points` | 5.0 | Maximum PV reduction from in-house performance |
| `min_games_threshold` | 7 | Minimum games before modifier activates |
| `wilson_z` | 1.28 | CI z-score — 1.28=80%, 1.645=90%, 1.96=95% (stricter = harder to earn bonus) |
| `realistic_max_override` | `None` | Bypass pool max — pin normalization ceiling manually |
