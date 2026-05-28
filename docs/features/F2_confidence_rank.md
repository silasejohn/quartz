# F2 — Confidence-Adjusted Current Rank Score

Current rank score blended with the player's **effective ATP** (all-time peak, adjusted for staleness), weighted by how many ranked games they've played this split.

## Why this exists

Early in a split, players may have played very few ranked games. Their current rank is noisy — a Diamond player 5 games in might be sitting Gold. Rather than penalizing them for low sample size, we regress their current rank toward their **own historical peak** as a prior. As games accumulate, confidence rises and current rank carries more weight.

The regression target is the player's **effective ATP** rather than the raw all-time peak. A raw ATP can be stale — a player who peaked Challenger two seasons ago but has since played 600 games without reaching Diamond 1 is not plausibly still Challenger. The effective ATP decays toward the player's current rank as post-peak evidence accumulates.

## Formula

```
confidence    = 1 - e^(-games / N)
F2            = confidence × rank_score(current_rank) + (1 - confidence) × effective_atp_rs
```

Where:
- `N` is computed from the pool via `compute_N_threshold()` (pool-relative games threshold)
- `effective_atp_rs` is the ATP rank score after staleness decay (see below)
- At `confidence = 0` (0 games): F2 = effective ATP score
- At `confidence = 1` (many games): F2 = current rank score

## ATP Staleness Decay

The all-time peak is treated as a prior, not a permanent anchor. For each season **after** the season where the ATP was set, the pipeline checks whether that season constitutes valid evidence that the player can no longer reach their ATP. If it does, the ATP is partially decayed toward the player's current rank.

### Per-season checkpoint model

For each post-ATP season `i`:

**Step 1 — Qualify the season as a valid test.** All four conditions must hold:

| Condition | Logic | Rationale |
|---|---|---|
| Hard floor | `games_i >= atp_hard_floor_games` (default 50) | Absolute minimum — a token appearance proves nothing |
| Personal volume | `games_i >= atp_personal_volume_pct × mean(player's prior season games)` | Player-relative — did *this* player give the season a real try? |
| Pool volume | `games_i >= P_k(pool games in season i)` | Pool-relative — is this enough effort relative to peers? |
| Not climbing | `win_rate_i < atp_climbing_wr_threshold` (default 55.0%) | A player still winning >55% hasn't peaked yet for this season |

The three volume conditions collapse into a single effective minimum:
```
effective_min_games = max(atp_hard_floor_games,
                          int(atp_personal_volume_pct × player_prior_mean_games),
                          pool_p_k_games_this_season)
season_qualifies = (games_i >= effective_min_games) AND (win_rate_i < atp_climbing_wr_threshold)
```

If the season does not qualify, it is skipped entirely — it provides neither evidence for nor against the ATP being stale.

**Step 2 — Compute the season's decay contribution** (only for qualifying seasons):

```
miss_i        = max(0, rank_score(season_peak_rank_i) - atp_rs)
miss_frac_i   = min(1.0, miss_i / atp_max_miss_scale)
decay_i       = season_confidence_i × miss_frac_i
```

Where:
- `miss_i` is how far below the ATP the player peaked that season (0 if they matched or exceeded it)
- `atp_max_miss_scale = 2 × stdev(pool current rank scores)` — pool-derived, auto-computed pre-pass
- `season_confidence_i = 1 - e^(-games_i / n_historical_i)` — confidence in that season's data

If `miss_i = 0` (the player reached their ATP that season), decay resets: `no_decay_prob = 1.0` and no further seasons are checked. The ATP is still valid.

**Step 3 — Accumulate evidence across seasons:**

```
no_decay_prob = Π (1 - decay_i)  for all qualifying seasons
atp_decay_factor = 1 - no_decay_prob
```

Each qualifying season where the player missed their ATP multiplies the evidence. Evidence compounds — two seasons of missing is stronger than one.

**Step 4 — Apply to regression target:**

```
effective_atp_rs = atp_rs × (1 - atp_decay_factor) + rank_score(current_rank) × atp_decay_factor
```

- `atp_decay_factor = 0.0`: ATP fully intact, regression target unchanged
- `atp_decay_factor = 1.0`: ATP fully decayed, regression target = current rank (F2 reduces to current rank regardless of confidence)

### Design properties

- **ATP is all-time, not windowed.** The ATP looks across all scraped splits — not just the `PAST_YEAR_SEASONS` window used by F1. A hard 2-year cutoff was considered but rejected: the decay model already handles staleness (a 3-year-old Master peak at 86% decay contributes less than 2 pts to the regression target). A cutoff would double-penalize old peaks that the decay has already neutralised, and would make a fresh current-split peak the ATP with 0 decay — not always desirable. Trust the decay; update `PAST_YEAR_SEASONS` instead if the F1 window needs adjusting.
- **Games-gated, not time-gated.** The staleness check is driven by games played, not calendar time. A player who barely played post-peak is not penalized — their ATP is preserved because we have no evidence it's stale.
- **Win rate gate.** A >55% win rate in a qualifying season means the player hasn't peaked yet. Skipping that season prevents decaying the ATP based on a still-active climb.
- **Player-relative threshold.** A player who typically plays 600 games per season must show meaningful volume relative to *themselves*, not just relative to the pool. A 100-game season from a 600-game-per-season player is weak evidence.
- **Compounding evidence.** One season of missing the ATP is a weak signal. Two or three seasons of solid volume and consistently falling short is strong evidence of true decline.
- **ATP confirmation resets decay.** If in any post-peak season the player reaches or exceeds their ATP, `no_decay_prob` resets to 1.0 — the ATP is re-confirmed as valid.

### Example

A player peaked Challenger in S2025 (739 games). In S2026 they have 32 games at Emerald 1.

- **Hard floor check**: 32 < 50 → season fails. ATP fully preserved.

A different player peaked Master in S2024 S2 (272 games). Subsequent seasons:
- S2024 S3: 54 games (below personal_min of 108). Skipped.
- S2025: 296 games, WR=46.6%, peaked Diamond 3. Qualifies. miss=10.8, decay_contrib≈0.21.
- S2026: 247 games, WR=49.4%, peaked near Diamond 1. Qualifies. miss=2.6, decay_contrib≈0.07.
- Total atp_decay_factor ≈ 0.26. Effective ATP shifts modestly toward current rank.

---

## N threshold strategies

N is derived from the pool so it scales with competition level:

| Strategy | N value | Bias |
|----------|---------|------|
| `MEDIAN` (default) | Median games across pool | Balanced |
| `P25` | 25th percentile | Softer on casual players |
| `MEAN_1SD` | Mean − 1 std dev | Harsher on low-game outliers |

Override with `n_override` for deterministic behavior.

## Relationship to F1

F1 does **not** use the all-time peak or the effective ATP. It reads `peak_rank` directly from each historical split's scraped data and weights those peaks by recency and confidence. The ATP regression — raw or decayed — only exists in F2. ATP staleness decay has no effect on F1.

## Shadow PV

When a player is **ineligible** (fails the tournament eligibility rule — see `docs/flags.md`), their PV is not computed and is marked `INF`. However, a **Shadow PV** is computed and stored separately: the PV they would receive if the eligibility check were bypassed. This uses the identical F1/F2/F3/F4 formula with no modifications, including ATP staleness decay.

Shadow PV is visible via `quartz pv-shadow` and stored on `SeasonData.shadow_point_value`.

## Parameters

All parameters live in `PVWeights`. Pool-derived values are computed at pipeline pre-pass time and stored in `ComputedPV.weights_used` for audit.

| Parameter | Default | Source | Effect |
|-----------|---------|--------|--------|
| `w_current` | 1.0 | hyperparameter | Blend weight relative to F1 at final combination |
| `confidence_strategy` | `median` | hyperparameter | How N is derived from pool (shared with F1 N_historical derivation) |
| `n_override` | `None` | override | Override N directly (bypasses pool derivation) |
| `atp_hard_floor_games` | `50` | hyperparameter | Absolute minimum games for a post-peak season to be a valid test |
| `atp_personal_volume_pct` | `0.40` | hyperparameter | Fraction of player's mean prior season games required (personal volume gate) |
| `atp_season_pool_percentile` | `0.25` | hyperparameter | Pool percentile (P_k) of games for the season volume gate |
| `atp_climbing_wr_threshold` | `55.0` | hyperparameter | Win rate (as %, stored 0–100) above which the season is skipped (player still climbing) |
| `atp_max_miss_scale_override` | `None` | override | Override the auto-computed miss scale; `None` = `2 × stdev(pool rank scores)` |

## Pool-level pre-pass computations

Two new pool-level helpers run before any per-player `compute_pv` calls:

```python
compute_atp_miss_scale(profiles, weights) -> float
# Returns 2 × stdev of pool current rank scores.
# Override via weights.atp_max_miss_scale_override.

compute_atp_season_min_games(profiles, weights, season) -> int
# Returns P_k of games played in `season` across the pool.
# k = weights.atp_season_pool_percentile (default P25).
# Floored at weights.n_historical_floor.
```

Both results are passed through to `compute_pv` alongside `N_threshold` and `n_historical_thresholds`.

## Stored fields (`PVFeatures`)

| Field | Description |
|-------|-------------|
| `current_rank_pts` | Raw `rank_score(current_rank)` before confidence blending |
| `games_played` | Games played in current split (drives confidence) |
| `confidence` | F2 confidence value (0–1) |
| `default_rank_used` | The rank string of the ATP used as regression target (before decay) |
| `adjusted_current_pts` | Final F2 value after confidence blending with effective ATP |
| `n_threshold_used` | N value used for this player's F2 computation |
| `atp_decay_factor` | Accumulated ATP staleness (0 = fully intact, 1 = fully decayed to current) |
| `effective_atp_rs` | Rank score of decayed regression target (what F2 actually regressed toward) |
