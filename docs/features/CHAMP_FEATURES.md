# Champion Pool Features

Champion pool is an additive PV modifier — it adjusts rank-derived PV up or down, same as F1–F4. It is a *differentiator between players at similar rank*, not a cross-rank booster. A Plat player with elite champion mastery does not reach Diamond-level PV from champion pool alone.

---

## Stat Clusters

Three feature clusters, role-weighted differently:

**Cluster 1 — Laning / Early Game**
CS/min, CS@15 (source: dpm), CSD@10 (source: riot_api), early deaths pre-14min (source: riot_api), first blood rate.
What it captures: champion mastery in isolated laning phase. Strongest signal for mid/top/ADC. Weaker for jungle/support.

**Cluster 2 — Combat / Carry Impact**
DPM, damage share %, KDA, solo kills, KP %.
What it captures: fight influence and kill pressure. Primary signal for carry roles. KP matters more for jungle/support. Solo kills are high-skill-expression regardless of role.

**Cluster 3 — Macro / Team Contribution**
GPM, gold share %, objective participation %, vision score/min (VSM).
What it captures: game understanding beyond mechanics. VSM and objective participation strongest for jungle/support. GPM and gold share matter across all roles, especially carries.

Note: `cs_at_15` (DPM source) and `csd_at_10` (Riot API source) are separate fields capturing different things — absolute farm volume at 15min vs. lane differential at 10min. Both belong in Cluster 1.

---

## Data Sources per Field

| Field | Source | Notes |
|---|---|---|
| CS/min, CS@15, GPM, DPM, VSM, KP, Solo Kills, Team DMG%, First Blood | `dpm` | DPM.lol per-champ per-rank stats |
| DPM Score | `dpm` | DPM's internally computed per-champ performance score. MVP champion feature — avoids manual cluster weighting |
| OP Score | `opgg` | OP.GG's internally computed per-champ performance score |
| CSD@10, early deaths | `riot_api` | Match timeline data, not available from scrapers |
| Mastery points | `opgg` | Cumulative, not split-specific. Lives on ChampionEntry, not ChampionSplitStats |

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
Once every player has their per-champ z-scores (or DPM Scores), Quartz compares them across the pool to determine relative PV contribution. This does NOT require matching roles or champions across players — you're ranking normalized scores, not normalizing within the pool.

The zero point for PV contribution = pool average DPM Score (MVP) or pool average z-score (post-MVP) for each bracket.

**On the ±rank-neighborhood bell curve:**
A Gaussian-weighted rank comparison group (e.g., ±4 divisions, bell-weighted) is the right long-term approach for computing per-stat deltas against a noise-resistant baseline. Deferred to post-MVP when we compute our own deltas from raw stats. For MVP, trust DPM's internal baseline.

---

## Fearless Draft Context

Fearless Bo5: every champion played is unavailable for the rest of the series. Worst-case game 5: ~14 champions unavailable (bans + previously played by both teams). Practical depth target: **12–15 unique champions** to survive a full series without forced bad picks.

Champion pool features are designed to capture this: a player with elite performance across many champions is genuinely more valuable in fearless than a one-trick, even at the same rank.

---

## Bracket Model — Marginal Brackets

Champions are sorted by DPM Score (descending). Only champs meeting the `games_min` threshold (default: 5 games) qualify. The pool is divided into **marginal brackets** — each bracket covers only the *new* champions added, so your best champion does not inflate every bracket:

| Bracket | Champs | Fearless context |
|---|---|---|
| B1 | #1 | Safest pick — almost always played |
| B2 | #2–3 | Games 1–2 fallback |
| B3 | #4–5 | Games 3–4 depth |
| B4 | #6–8 | Game 5 + situational picks |
| B5 | #9–13 | Worst-case fearless depth |

**Bracket score** = average DPM Score of champs in *that bracket only*.
**Bracket delta** = bracket score − pool average DPM Score for that bracket position.
**Direction**: positive delta (above pool avg) → lowers PV (stronger). Negative delta → raises PV (weaker).

A one-trick maxes B1 but earns near-zero on B2–B5 (no qualifying champs, or low-score bench). A 13-champ generalist earns positive or negative contribution across all five brackets.

---

## Tunable Weight Inventory

All parameters live in `PVWeights` (`quartz/models/pv_model.py`) — the single source of truth for every tunable parameter. A snapshot is stored in `ComputedPV.weights_used` for full audit trail.

| Parameter | Field in PVWeights | Default | Notes |
|---|---|---|---|
| `games_min` | `champ_games_min` | 5 | Hard floor to qualify a champ for any bracket |
| B1–B5 bracket weights | `champ_bracket_weights` | `[1.0, 0.8, 0.6, 0.4, 0.2]` | Mild taper — game-5 depth earns real credit |
| `max_champ_delta` | *(computed at runtime)* | proportional to pool PV spread | NOT a flat constant — dynamic like F3's cap |
| `w_cluster1/2/3[role]` | *(not yet added)* | — | Post-MVP only. Deferred until raw stats replace DPM Score |

**Bracket weight rationale (mild taper):** In fearless Bo5, game-5 picks visibly decide series. A player solid across 13 champs should earn meaningfully more than a one-trick. `[1.0, 0.8, 0.6, 0.4, 0.2]` makes B5 worth 20% of B1 — present but not dominant. All values are tunable post-launch from `PVWeights`.

**Known design debt**: `max_champ_delta` must be dynamic (proportional to pool PV spread), not a flat constant. Same issue as F3's `max_bonus_points`. Both should be resolved together when the pool-relative scaling system is built.

---

## MVP vs Post-MVP

**MVP**: Use DPM Score per champion as the single input. Compute bracket deltas vs. pool average. Apply bracket weights and cap. Total champion pool modifier = one additive PV delta.

**Post-MVP**: Replace DPM Score with per-cluster raw stat deltas (each stat vs. DPM regional baseline). Apply role-specific cluster weights. Apply bell-curve rank-neighborhood weighting to baseline computation. Add temporal features (peak/current/trajectory per cluster).

---

## Future Features

- **Solo/flex delta signal**: difference between a player's stats on the same champion in solo vs. flex queue — signal for individual vs. team performance.
- **Consistency gap**: variance of DPM Score across splits for the same champion. High variance = boom-or-bust. Low variance = reliable floor. Valuable for fearless draft (you want the reliable floor in game 5).
- **Trajectory**: rank-normalized slope across last 3 splits, recency-weighted. Mirrors F1/F2 temporal structure.
