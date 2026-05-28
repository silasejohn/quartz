# Champion Pool Features — F5 (Solo) and F6 (Flex)

Champion pool adjusts rank-derived PV after F1/F2 are combined. F5 is bidirectional (strong pool helps, weak pool hurts). F6 is unidirectional — good flex performance lowers PV, bad flex performance is ignored. Neither is a cross-rank booster: a Plat player with an elite champion pool does not reach Diamond-level PV from champion pool alone.

---

## Stat Clusters

Three feature clusters, role-weighted differently:

**Cluster 1 — Laning / Early Game**
CS/min, avg_cs_per_game, CS@15 (source: dpm), CSD@10 (source: riot_api), early deaths pre-14min (source: riot_api), first blood rate (source: dpm).
What it captures: champion mastery in isolated laning phase. Strongest signal for mid/top/ADC. Weaker for jungle/support.

**Cluster 2 — Combat / Carry Impact**
DPM, damage share %, KDA (K/D/A), solo kills, KP %.
What it captures: fight influence and kill pressure. Primary signal for carry roles. KP matters more for jungle/support. Solo kills are high-skill-expression regardless of role.

**Cluster 3 — Macro / Team Contribution**
GPM, avg_gold_per_game, gold share %, objective participation %, vision score/min (VSM), avg_vision_score.
What it captures: game understanding beyond mechanics. VSM and objective participation strongest for jungle/support. GPM and gold share matter across all roles, especially carries.

Note: `cs_at_15` (DPM source) and `csd_at_10` (Riot API source) are separate fields capturing different things — absolute farm volume at 15min vs. lane differential at 10min. Both belong in Cluster 1.

---

## Data Sources per Field

Fields on `ChampionSplitStats` are attributed to one or more sources. **Contested** means both DPM and OP.GG can populate the field; `merge_split()` applies a more-games-wins rule with source-exclusive fields protected from cross-source overwrite.

| Field | Source | Notes |
|---|---|---|
| `games`, `wins`, `losses`, `win_rate` | contested | Both sources provide; more-games-wins |
| `kda`, `kills_per_game`, `deaths_per_game`, `assists_per_game` | contested | Both DPM and OP.GG; more-games-wins |
| `cs_per_min` | contested | DPM: `csm`; OP.GG: line 1 of CS cell |
| `gpm` | contested | DPM: `gpm`; OP.GG: line 1 of gold cell |
| `dpm` | contested | DPM: damage per minute; OP.GG: cell[6] line 0 |
| `damage_share_pct` | contested | OP.GG: cell[6] line 1; DPM: team damage % |
| `dpm_score` | `dpm` | DPM's internally computed per-champ performance score |
| `cs_at_15` | `dpm` | Absolute CS at 15 min (stub — not yet parsed) |
| `first_blood_rate` | `dpm` | FB kill + assist participation % |
| `solo_kills_per_game` | `dpm` | |
| `kill_participation_pct` | `dpm` | KP % |
| `gold_share_pct` | `dpm` | % of team gold earned |
| `vision_score_per_min` | `dpm` | Vision score normalized per minute |
| `op_score` | `opgg` | OP.GG avg OP score per game this split |
| `expected_op_score` | `opgg` | Matchup-adjusted expected OP score |
| `op_laning_score` | `opgg` | Laning score, e.g. 51 from "51:49" |
| `expected_laning_pct` | `opgg` | Matchup-adjusted expected laning win % |
| `avg_vision_score` | `opgg` | Raw vision score per game (not per minute) |
| `avg_cs_per_game` | `opgg` | Average total CS per game |
| `avg_gold_per_game` | `opgg` | Average total gold per game |
| `csd_at_10` | `riot_api` | CS differential vs. opponent at 10 min |
| `early_deaths_per_game` | `riot_api` | Deaths before 14 min per game |
| `objective_participation_pct` | `riot_api` | |
| `mastery_points` | `opgg` | Cumulative Riot mastery points — lives on `ChampionEntry`, not per split |

`OPGG_EXCLUSIVE_FIELDS` and `DPM_EXCLUSIVE_FIELDS` frozensets in `champion_data.py` enumerate which fields belong exclusively to each source. These are used by the force-rescrape strip logic to preserve the other source's data when `--force` is passed.

---

## Source Attribution and Merge Logic

`ChampionSplitStats.source` tracks data provenance:
- `"dpm"` — populated only by DPM.lol
- `"opgg"` — populated only by OP.GG
- `"multi"` — both sources have contributed (DPM-exclusive and OPGG-exclusive fields both non-None)

`merge_split()` in `ChampionEntry` governs all merges:
- **More games** → incoming source wins all non-None fields (takes control)
- **Same/fewer games** → gap-fill only: write None fields, never overwrite
- **Source-exclusive fields** (`_SOURCE_EXCLUSIVE` map) are never overwritten by a different source regardless of game count

Force-rescraping one source (`--force`) only strips that source's fields from `"multi"` splits, preserving the other source's exclusive data intact.

---

## Normalization — Two-Layer Design

**Layer 1 — Global rank normalization (DPM handles this):**
DPM computes a regional average per champion per rank tier. We scrape both the player's stat and the regional average. Delta = `player_stat - dpm_regional_avg`. This is the raw signal — how far above or below the global rank-appropriate baseline a player performs on a given champion.

For MVP: DPM Score encapsulates this internally. Use it directly.

**Layer 2 — Within-champion normalization (post-MVP):**
Even after computing `player_stat - champ_rank_avg`, champion-specific variance remains. CS/min has a wider distribution on farming-heavy ADCs (e.g., Smolder) than on mages (e.g., Orianna). A raw delta of +1.0 CS/min on Smolder is a smaller achievement than +1.0 on Orianna.

Ideal solution: z-score per `(champion, role, rank)` using `std_dev`. However, DPM only exposes means, not standard deviations.

**Practical solution (mean-shifting):** use the mean-shifted delta `player_stat - mean[champ, role, rank]` as the input. This centres each stat at zero and removes champion-specific baseline bias, but does not equalize variance across champions or stats. Deltas across different stats (e.g., +0.4 CS/min vs. +50 DPM) are not directly on the same scale.

Compensation strategies (in order of complexity):
1. **DPM Score for MVP** — DPM's internal score is pre-normalized; use it directly and skip raw stat comparison entirely.
2. **Per-stat fixed scale factors** — hand-tune a divisor per stat (e.g., CS/min ÷ 1.5, DPM ÷ 100) to bring deltas onto comparable ranges. Requires empirical calibration on pool data.
3. **Pool-percentile ranking** — rank all pool players by their delta per `(stat, champ, role)` and convert to 0–1. Self-normalizing but fragile when pool is sparse on a given champion.

Store `mean[champ, role, rank]` per stat alongside player values so deltas can be recomputed without re-scraping if the baseline is updated.

**Layer 3 — Cross-player pool comparison (Quartz handles this):**
Once every player has their per-champ residuals, Quartz aggregates them into bracket scores and applies the tanh-scaled formula. No cross-player normalization is needed — the zero point is already fixed at `champ_dpm_baseline` (50.0 for MVP, or the regional baseline post-MVP), so all players are on the same scale without a second pass.

Note: DPM `averageScore` is on a **0-100 scale** (not 0-10). GCS S4 pool: mean=61.8, median=62.1, stddev=10.2, range 32.5–90.2. Baseline is computed at runtime from the pool median — not a fixed constant — so roughly half the pool earns positive residuals and half negative. Post-MVP: replace pool-median baseline with `regional_avg_dpm_score_for_champ_at_player_rank_range` scraped from DPM per champion×rank_tier.

**On the ±rank-neighborhood bell curve:**
A Gaussian-weighted rank comparison group (e.g., ±4 divisions, bell-weighted) is the right long-term approach for computing per-stat deltas against a noise-resistant baseline. Deferred to post-MVP when we compute our own deltas from raw stats. For MVP, trust DPM's internal baseline.

---

## Fearless Draft Context

Fearless Bo5: every champion played is unavailable for the rest of the series. Worst-case game 5: ~14 champions unavailable (bans + previously played by both teams). Practical depth target: **12–15 unique champions** to survive a full series without forced bad picks.

Champion pool features are designed to capture this: a player with elite performance across many champions is genuinely more valuable in fearless than a one-trick, even at the same rank.

---

## Bracket Model — Marginal Brackets

Champions are sorted by **games played (descending)** using the ALL-role DPM aggregate for the current split. No role filtering — all champions count regardless of role (fearless format, multi-role depth has real value). Only champions meeting the `games_min` threshold (default: **3 games**) qualify.

The pool is divided into **marginal brackets** — each bracket covers only the *new* champions added at that depth level, so your best champion does not inflate every bracket:

| Bracket | Champs | Fearless context |
|---|---|---|
| B1 | #1 (most played) | Safest pick — almost always played in game 1 |
| B2 | #2–3 | Games 1–2 fallback |
| B3 | #4–5 | Games 3–4 depth |
| B4 | #6–8 | Game 5 + situational picks |
| B5 | #9–13 | Worst-case fearless depth |

**Bracket contribution** is computed in three layers:

**Layer 1 — Hard floor**: `games_min = 3`. A champion with fewer than 3 games does not qualify for any bracket (insufficient data).

**Layer 2 — Within-bracket games-weighted residual**: `residual = Σ(games × (dpm_score − baseline)) / Σgames`. A champion with 80 games pulls harder than one with 12. Prevents low-sample outliers from inflating the bracket score.
- `baseline` = pool median DPM score, computed at runtime from all qualifying solo entries across the tournament pool. At GCS S4 (60 players): baseline ≈ 62.1, stddev ≈ 10.2.
- Positive residual = outperforming pool median on those champions → lowers PV (stronger).
- Negative residual = below pool median → raises PV (weaker).

**Layer 3 — Bracket confidence**: `conf = 1 − exp(−total_bracket_games / N_bracket)` where `N_bracket = 10` (default). At 30 total games in a bracket, confidence ≈ 95%.

| Games in bracket | Confidence |
|---|---|
| 3g | 26% |
| 6g | 45% |
| 10g | 63% |
| 15g | 78% |
| 30g | 95% |
| 50g | 99% |

This means a player with 4 total games this split cannot generate a large F5 signal in either direction — the amplitude is naturally near zero, matching the low evidence.

**Empty brackets — active penalty**: Empty brackets contribute `bw × P` where `P = −champ_penalty_sigma × pool_stddev` (default: `−0.5 × 10.2 ≈ −5.1`). This is pool-relative: a larger pool stddev means a larger penalty.

One-trick (only B1 qualifying): needs B1 DPM score > ~72 to generate any positive F5. A mediocre one-trick at pool median earns a net-negative modifier from the empty B2–B5 penalty.

---

## Formula

```
P = −champ_penalty_sigma × champ_dpm_pool_stddev     # empty bracket penalty (pool-relative)

For each bracket i:
  if empty:
    contribution_i = bw_i × P
  else:
    residual_i = Σ(games × (dpm_score − baseline)) / Σgames   # games-weighted avg
    conf_i     = 1 − exp(−total_bracket_games / champ_n_bracket)
    contribution_i = bw_i × residual_i × conf_i

raw_delta = Σ contribution_i                               # DPM Score units (pool-median-centred)
cap       = champ_alpha × tier_width(rank_pv)              # PV units
modifier  = cap × tanh(champ_scale_factor × raw_delta / cap)  # PV units, smooth saturation
```

`tier_width(rank_pv)` — the PV span of one full tier (4 divisions) at the player's current rank position, derived via finite difference on `rank_score()` at the F1+F2 blended PV. Automatically adapts to any rank model shape (piecewise linear, sqrt, constant segments).

**Apex tier handling:** Master, Grandmaster, and Challenger all use Diamond 1's tier_width (11.8 PV) as a proxy. Actual apex entry-point spans (Master=4.9, GM=6.0) were evaluated but rejected: they would shrink caps for Master-zone players (the majority of top-elo tournament participants) from 3.89 → 1.62 PV, reducing champion pool signal exactly where it matters most. `rank_pv` already captures the LP difference between apex players; the cap only needs to be a fair upper bound, not LP-granular. Iron ranks (all flat at PV=85) fall back to Bronze tier_width (5.9 PV).

`dpm_score` is DPM's `averageScore` on a **0-100 scale**. `baseline` is the pool median computed at runtime via `compute_champ_dpm_baseline()` — not a fixed constant. Residual = `dpm_score − baseline`, centred at 0 across the pool. Roughly half the pool gets positive residuals, half negative.

`tanh` saturation: at small `raw_delta`, modifier ≈ `champ_scale_factor × raw_delta` (linear). As `raw_delta` grows, modifier asymptotically approaches `±cap` — no hard wall, no discontinuity.

**F5 — Solo modifier**: bidirectional. `solo_modifier = cap × tanh(scale × solo_raw_delta / cap)`. Applied directly.

**F6 — Flex advantage**: benefit-only. Measures how much better the player's flex pool is compared to their own solo pool — not absolute flex quality.
```
flex_advantage = flex_raw_delta − solo_raw_delta
flex_modifier  = max(cap × tanh(scale × flex_advantage / cap), 0)
```
- Requires a solo pool reference. If no solo data exists, F6 = 0.
- Flex identical to solo → F6 = 0. Flex considerably better than solo → F6 > 0.
- Never negative — weak flex is simply ignored. Flex should never penalize a player for casual queue play.

## PV Pipeline

```
rank_pv        = weighted(F1, F2)
solo_raw_delta = Σ bw_i × solo_bracket_residual_i
flex_raw_delta = Σ bw_i × flex_bracket_residual_i
after_F5       = rank_pv − cap × tanh(scale × solo_raw_delta / cap)
flex_advantage = flex_raw_delta − solo_raw_delta
after_F6       = after_F5 − max(cap × tanh(scale × flex_advantage / cap), 0)
final_pv       = after_F6 + baseline − inhouse_modifier − manual_adj_total
```

`cap` and `tier_width` are derived from `rank_pv` (pre-modification) for both F5 and F6. No dependency chain.

## Tunable Weight Inventory

All parameters live in `PVWeights` (`quartz/models/pv_model.py`). A snapshot is stored in `ComputedPV.weights_used` for full audit trail. Fields marked **runtime** are overwritten before the per-player loop by pool-level helpers; the defaults serve as fallback when the pool has < 2 samples.

| Parameter | Field in PVWeights | Default | Notes |
|---|---|---|---|
| `games_min` | `champ_games_min` | **3** | Hard floor per champ; 3 = intentional exposure |
| Account min games | `champ_account_min_games` | 15 | Min qualifying games for rank-anchored account selection |
| B1–B5 bracket weights | `champ_bracket_weights` | `[1.0, 0.8, 0.6, 0.4, 0.2]` | Mild taper — game-5 depth earns real credit |
| DPM baseline | `champ_dpm_baseline` | 50.0 | **Runtime**: replaced by pool median of all qualifying solo DPM scores via `compute_champ_dpm_baseline()`. GCS S4 value ≈ 62.1 |
| Pool stddev | `champ_dpm_pool_stddev` | 10.2 | **Runtime**: replaced by pool stddev alongside baseline. Used to scale empty-bracket penalty. GCS S4 value ≈ 10.2 |
| Empty bracket penalty σ | `champ_penalty_sigma` | 0.5 | Penalty per empty bracket = `−sigma × pool_stddev` ≈ −5.1 at GCS S4 values |
| Bracket confidence N | `champ_n_bracket` | 10 | 30 bracket-games → 95% weight; 3 games → 26% |
| Scale factor | `champ_scale_factor` | 0.13 | Sensitivity — may need increase post-redesign (residuals now centred at 0, not +12 as with old 50.0 baseline) |
| Cap fraction | `champ_alpha` | 0.33 | Max modifier = `champ_alpha × tier_width`. GM cap ≈ 3.89 PV |
| `w_cluster1/2/3[role]` | *(not yet added)* | — | Post-MVP only. Deferred until raw stats replace DPM Score |

**Bracket weight rationale (mild taper):** In fearless Bo5, game-5 picks visibly decide series. A player solid across 13 champs should earn meaningfully more than a one-trick. `[1.0, 0.8, 0.6, 0.4, 0.2]` makes B5 worth 20% of B1 — present but not dominant.

**Tuning `champ_scale_factor` vs `champ_alpha` independently:**
- `champ_scale_factor` controls *sensitivity* — how quickly the modifier grows from zero as `raw_delta` increases. Raise it if most players' modifiers cluster near zero. Lower it if most players are already in saturation.
- `champ_alpha` controls the *ceiling* — the absolute max PV shift. Raise it to give champion pool more weight vs. rank. Lower it to keep it a minor differentiator.
- They are independent: adjusting `champ_alpha` changes the ceiling without affecting sensitivity in the linear regime.

## Missing Data

If a player has no DPM scrape or no champions above `champ_games_min`, both F5 and F6 modifiers default to 0. `PVFeatures.champ_data_missing` is set to `True` so `quartz view` can surface "champion features not computed — run `quartz scrape dpm`."

---

## MVP vs Post-MVP

**MVP** (current implementation):
- Bracket assignment: sort by games played (ALL-role DPM aggregate, current split); `games_min = 3`
- Account selection: rank-anchored — best-ranked account with ≥ `champ_account_min_games` qualifying games; falls back to most-games account if none clear the floor
- Baseline: pool median DPM score, computed at runtime via `compute_champ_dpm_baseline()` before the per-player loop; stddev also computed for penalty scaling
- Residual per champion: `dpm_score − pool_median`; centred at 0 across the pool
- Within-bracket aggregation: games-weighted mean residual
- Bracket confidence: `1 − exp(−bracket_total_games / champ_n_bracket)` applied per bracket (N=10)
- Empty bracket penalty: `bw × (−champ_penalty_sigma × pool_stddev)` per empty bracket (sigma=0.5)
- Formula: `cap × tanh(champ_scale_factor × raw_delta / cap)` where `cap = champ_alpha × tier_width(rank_pv)`
- Apex tier_width: Diamond 1 proxy (11.8 PV) for all apex ranks (see Formula section)
- Solo (F5) bidirectional
- Flex (F6) benefit-only: `max(cap × tanh(scale × (flex_raw_delta − solo_raw_delta) / cap), 0)`; requires solo reference, stays 0 if no solo pool
- Missing data (no qualifying champs at all) → modifier = 0, `champ_data_missing` flag

**Post-MVP (in order)**:
1. Replace pool-median baseline with `regional_avg_dpm_score_for_champ_at_player_rank_range` scraped from DPM per champion×rank_tier (needs `_baseline` field on `ChampionSplitStats`)
2. Add `op_score` as secondary bracket signal, blended with DPM Score (weight TBD)
3. Build Quartz-native composite score from all collected fields (`dpm_score`, `op_score`, `op_laning_score`, `kda`, `cs_per_min`, `kill_participation_pct`, `gold_share_pct`, etc.)
4. Per-cluster raw stat deltas with role-specific cluster weights. Bell-curve rank-neighborhood weighting for baseline. Temporal features (trajectory per cluster).

---

## Future Features

- **Solo/flex delta signal**: difference between a player's stats on the same champion in solo vs. flex queue — signal for individual vs. team performance.
- **Consistency gap**: variance of DPM Score across splits for the same champion. High variance = boom-or-bust. Low variance = reliable floor. Valuable for fearless draft (you want the reliable floor in game 5).
- **Trajectory**: rank-normalized slope across last 3 splits, recency-weighted. Mirrors F1/F2 temporal structure.
