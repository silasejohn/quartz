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
Once every player has their per-champ residuals, Quartz aggregates them into bracket scores and applies the tanh-scaled formula. No cross-player normalization is needed — the zero point is already fixed at 5.0 (MVP) or the regional baseline (post-MVP), so all players are on the same scale without a second pass.

**On the ±rank-neighborhood bell curve:**
A Gaussian-weighted rank comparison group (e.g., ±4 divisions, bell-weighted) is the right long-term approach for computing per-stat deltas against a noise-resistant baseline. Deferred to post-MVP when we compute our own deltas from raw stats. For MVP, trust DPM's internal baseline.

---

## Fearless Draft Context

Fearless Bo5: every champion played is unavailable for the rest of the series. Worst-case game 5: ~14 champions unavailable (bans + previously played by both teams). Practical depth target: **12–15 unique champions** to survive a full series without forced bad picks.

Champion pool features are designed to capture this: a player with elite performance across many champions is genuinely more valuable in fearless than a one-trick, even at the same rank.

---

## Bracket Model — Marginal Brackets

Champions are sorted by **games played (descending)** using the ALL-role DPM aggregate for the current split. No role filtering — all champions count regardless of role (fearless format, multi-role depth has real value). Only champions meeting the `games_min` threshold (default: 5 games) qualify.

The pool is divided into **marginal brackets** — each bracket covers only the *new* champions added at that depth level, so your best champion does not inflate every bracket:

| Bracket | Champs | Fearless context |
|---|---|---|
| B1 | #1 (most played) | Safest pick — almost always played in game 1 |
| B2 | #2–3 | Games 1–2 fallback |
| B3 | #4–5 | Games 3–4 depth |
| B4 | #6–8 | Game 5 + situational picks |
| B5 | #9–13 | Worst-case fearless depth |

**Bracket residual** = games-weighted average of `(dpm_score − 5.0)` for champions in that bracket.
- `5.0` is the global average DPM Score (MVP baseline). Post-MVP: replaced by `regional_avg_dpm_score_for_champ_at_player_rank_range` per champion.
- Games-weighted: within a bracket, a champion with 80 games pulls harder than one with 12. Prevents low-sample outliers from inflating the bracket score.
- Positive residual = above average performance on those champions → lowers PV (stronger).
- Negative residual = below average → raises PV (weaker).

**Empty brackets**: zero-filled. If a player has only 2 qualifying champions, B3–B5 contribute 0 residual. Thin pools naturally produce near-zero modifiers.

A one-trick maxes B1 but contributes 0 on B2–B5 (no qualifying champs). A 13-champ generalist earns positive or negative contribution across all five brackets.

---

## Formula

```
raw_delta     = Σ bracket_weight_i × bracket_residual_i          # DPM Score units
cap           = champ_alpha × tier_width(rank_pv)                 # PV units
modifier      = cap × tanh(champ_scale_factor × raw_delta / cap)  # PV units, smooth saturation
```

`tier_width(rank_pv)` — the PV span of one full tier (4 divisions) at the player's current rank position, derived via finite difference on `rank_score()` at the F1+F2 blended PV. Automatically adapts to any rank model shape (piecewise linear, sqrt, constant segments).

`tanh` saturation: at small `raw_delta`, modifier ≈ `champ_scale_factor × raw_delta` (linear). As `raw_delta` grows, modifier asymptotically approaches `±cap` — no hard wall, no discontinuity.

**F5 — Solo modifier**: bidirectional. Applied directly.
**F6 — Flex modifier**: unidirectional. `flex_contribution = max(flex_modifier, 0)` — strong flex lowers PV, weak flex is ignored. Flex signals teamplay ability; it should never penalize a player for casual flex play.

## PV Pipeline

```
rank_pv   = weighted(F1, F2)
after_F5  = rank_pv  − solo_modifier          # F5: bidirectional champion modifier
after_F6  = after_F5 − max(flex_modifier, 0)  # F6: unidirectional flex modifier
final_pv  = after_F6 + baseline − inhouse_modifier − manual_adj_total
```

`tier_width` for both F5 and F6 is derived from `rank_pv` (pre-modification), not the post-F5 value. No dependency chain.

## Tunable Weight Inventory

All parameters live in `PVWeights` (`quartz/models/pv_model.py`). A snapshot is stored in `ComputedPV.weights_used` for full audit trail.

| Parameter | Field in PVWeights | Default | Notes |
|---|---|---|---|
| `games_min` | `champ_games_min` | 5 | Hard floor to qualify a champ for any bracket |
| B1–B5 bracket weights | `champ_bracket_weights` | `[1.0, 0.8, 0.6, 0.4, 0.2]` | Mild taper — game-5 depth earns real credit |
| Scale factor | `champ_scale_factor` | 1.0 | Sensitivity: PV points per unit of `raw_delta` in the linear regime. Tune by checking P50 player modifier — should be meaningful but not saturated. |
| Cap fraction | `champ_alpha` | 0.3 | Max modifier = `champ_alpha × tier_width`. Tune relative to F1/F2 spread — champion pool should influence but not dominate. |
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

**MVP**:
- Bracket assignment: sort by games played (ALL-role DPM aggregate, current split)
- Residual per champion: `dpm_score − 5.0` (5.0 = global average DPM Score)
- Aggregation: games-weighted mean within each bracket → bracket residuals
- Formula: `cap × tanh(champ_scale_factor × raw_delta / cap)` where `cap = champ_alpha × tier_width(rank_pv)`
- Solo (F5) bidirectional; Flex (F6) benefit-only
- Missing data → modifier = 0, `champ_data_missing` flag

**Post-MVP (in order)**:
1. Replace 5.0 baseline with `regional_avg_dpm_score_for_champ_at_player_rank_range` scraped from DPM (see TODO — needs `_baseline` field on `ChampionSplitStats`)
2. Add `op_score` as secondary bracket signal, blended with DPM Score (weight TBD)
3. Build Quartz-native composite score from all collected fields (`dpm_score`, `op_score`, `op_laning_score`, `kda`, `cs_per_min`, `kill_participation_pct`, `gold_share_pct`, etc.)
4. Per-cluster raw stat deltas with role-specific cluster weights. Bell-curve rank-neighborhood weighting for baseline. Temporal features (trajectory per cluster).

---

## Future Features

- **Solo/flex delta signal**: difference between a player's stats on the same champion in solo vs. flex queue — signal for individual vs. team performance.
- **Consistency gap**: variance of DPM Score across splits for the same champion. High variance = boom-or-bust. Low variance = reliable floor. Valuable for fearless draft (you want the reliable floor in game 5).
- **Trajectory**: rank-normalized slope across last 3 splits, recency-weighted. Mirrors F1/F2 temporal structure.
