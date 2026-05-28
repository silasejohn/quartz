# F5 Champion Pool Redesign — Pool-Median Baseline, Bracket Confidence, Empty Bracket Penalty

Implemented 2026-05-27. Applies to GCS S4 and all subsequent tournament rounds.

## Why the Old Formula Was Broken

The original F5 used a fixed `champ_dpm_baseline = 50.0` against DPM `averageScore` (0-100 scale).
Three compounding problems:

1. **Baseline too low.** GCS S4 pool: mean=61.8, median=62.1. 87% of qualifying entries were above 50.0 → F5 was always positive. No player was ever penalized for a weak pool.
2. **One-tricks not penalized.** Empty brackets contributed 0. An elite one-trick with a B1 score of 80 could outscore a generalist with good depth across 5 brackets.
3. **`games_min=5` cut real breadth.** At games_min=5: only 48% of players had all 5 brackets filled, median 7 qualifying champs. Many players with genuine champ depth showed as "thin pool."

## Decisions

### 1. Baseline → Pool Median (runtime, not fixed)

`compute_champ_dpm_baseline()` collects all qualifying solo DPM scores across the tournament pool and returns `(median, stddev)`. This is applied to `weights` before the per-player loop — same pattern as `compute_N_threshold()`.

Considered: pool mean (pulled by outliers), fixed 62.1 (non-self-calibrating), P75 (too aggressive — would penalize 75% of players). Chose **median** because it centers F5 at zero for the actual pool without hand-tuning per tournament.

### 2. games_min 5 → 3

3 games = intentional exposure. At games_min=3: 63% of players fill all brackets (vs. 48%), median 12 qualifying champs (vs. 7). Noise from 3-game samples is handled by bracket confidence (decision 4) rather than exclusion.

### 3. Empty Bracket Penalty (not zero-fill)

Empty brackets contribute `bw × P` where `P = −champ_penalty_sigma × pool_stddev` (default: sigma=0.5 → P≈−5.1 at GCS S4 values).

Considered: zero-fill (one-tricks keep all their positive B1 signal with no downside — not appropriate for fearless draft), proportional confidence scaling (complex, no meaningful downside for one-tricks). Chose **active penalty** because fearless draft genuinely disadvantages one-tricks in game 5+, and the penalty magnitude should be pool-relative rather than a fixed constant.

With sigma=0.5: a one-trick needs B1 DPM score > ~72 to generate any positive F5. Tunable via `champ_penalty_sigma`.

### 4. Bracket Confidence Layer

Each filled bracket's contribution is scaled by `conf = 1 − exp(−total_bracket_games / champ_n_bracket)` with `N_bracket = 10`.

At 30 bracket-games: conf ≈ 95%. At 3 games: conf ≈ 26%. This means low-volume players (20 total games this split → ~3-4g per bracket → ~26-39% confidence) produce naturally muted F5 — positive or negative — matching the low evidence. High-volume players (200 games → 30-80g per bracket) earn full amplitude.

The direction is always preserved; only amplitude scales with evidence. No separate account-level confidence multiplier is needed — bracket confidence captures it.

## Calibration (GCS S4)

| Parameter | Old | New |
|---|---|---|
| `champ_games_min` | 5 | 3 |
| `champ_dpm_baseline` | 50.0 (fixed) | 62.1 (runtime pool median) |
| `champ_dpm_pool_stddev` | — | 10.2 (runtime) |
| `champ_penalty_sigma` | — | 0.5 |
| `champ_n_bracket` | — | 10 |
| `champ_scale_factor` | 0.13 | 0.13 (needs recalibration — residuals now centred at 0) |

Pool stats: 60 players with solo DPM data, P25=54.8, P50=62.1, P75=69.0.
