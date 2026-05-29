# Draft Simulation — Design & Goals

Captures the design decisions, mechanics, and optimization goals behind `quartz draft`.

---

## Purpose

The draft simulator exists to answer two questions before the live draft:
1. **What thresholds are fair?** — Given the actual pool of players, what R2 and R4 floors produce the most balanced teams?
2. **What does a good pick look like?** — Given those thresholds, what should each captain target at each pick slot?

---

## Tournament Formats

Draft rules vary per tournament. The simulator is format-agnostic — all structural parameters live in `active_tournament.yaml` under a `draft_format:` block.

| Parameter | GCS S4 | LEPL S3 |
|---|---|---|
| Captains | 10 | 8 |
| Picks per captain | 4 | 6 |
| Snake phases | 1 (rounds 1–4) | 2 (rounds 1–4, reorder, rounds 5–6) |
| Mid-draft reorder | No | Yes — weakest team picks first in Phase 2 |
| Soft cap | Yes | No |
| Threshold checks | R2, R4 | R2, R4 |

---

## Snake Draft Mechanics

- Captains are assigned pick slots (1–N) in `active_tournament.yaml` under `captain_slots`.
- Odd rounds go forward (slot 1 → N), even rounds reverse (slot N → 1).
- If `randomize_captain_order: true` is set in the YAML, slot assignments are shuffled before the draft begins.
- Captain profiles are verified against the player registry at load time — a captain listed in `captain_slots` must have a profile with `player_type = "captain"`.

---

## Threshold System

### Global Floors

Two thresholds are configured per tournament draft:

- **R2 threshold** — minimum team PV (captain + 2 picks) a team must reach by end of round 2.
- **R4 threshold** — minimum team PV (captain + 4 picks) a team must reach by end of round 4.

Enforcement: on the constrained pick (round 2 or round 4), only players whose PV would bring the team to or above the floor are eligible. If no such player exists, the threshold is infeasible and the simulator raises an error.

### Soft Cap (GCS S4)

Purpose: prevent dominant two-man cores (e.g. Challenger captain + Challenger pick 1) from producing unbeatable teams.

Mechanics:
- Evaluated after each team completes round 1 (their first pick).
- If `captain_pv + pick1_pv < soft_cap_trigger`, the team has exceeded the soft cap.
- Their effective floors are raised:
  ```
  soft_cap_excess   = soft_cap_trigger - (captain_pv + pick1_pv)
  floor_raise       = soft_cap_excess × soft_cap_scale
  effective_r2      = r2_threshold + floor_raise
  effective_r4      = r4_threshold + floor_raise
  ```
- The same `floor_raise` is applied to both R2 and R4 (not escalating — one correction, not a double-punish).
- Scale is linear. `soft_cap_scale` is a tunable parameter calibrated against real pool data.

---

## Fairness Objective

**Goal: minimize average standard deviation of final team PV across N simulated drafts.**

A threshold pair `(r2, r4)` is better if teams end up closer together in total PV. The optimization procedure:

1. Define a grid of candidate `(r2, r4)` pairs.
2. For each pair, run 500 simulated drafts (randomized pick strategy).
3. Score each pair: `mean(std_dev(final_team_pvs))` across all simulations.
4. Select the `(r2, r4)` pair with the lowest score.

Soft cap parameters (`soft_cap_trigger`, `soft_cap_scale`) are tuned separately by targeting the specific scenario to prevent (e.g. two Challenger-tier players on one team) and finding the minimum trigger that raises their floor meaningfully without over-penalizing borderline cases.

---

## Pick Strategies (Simulation)

| Strategy | Description | Use case |
|---|---|---|
| `greedy_pv` | Always pick the lowest available PV | Worst-case ceiling — shows maximum advantage a team could accumulate |
| `role_greedy` | Pick lowest PV that fills an open role; fallback to greedy | Realistic best-play approximation |
| `random` | Random pick from available pool | Monte Carlo fairness analysis |

---

## CLI Reference

```bash
# Find fair thresholds — grid search over (r2, r4) pairs
quartz draft --optimize
quartz draft --optimize --sims 500 --top-k 10

# Diagnose a specific (r2, r4) pair — percentile stats per captain
quartz draft --analyze 500 --r2 85 --r4 160

# Generate pick sheet for a chosen threshold pair
quartz draft --recommend --r2 85 --r4 160

# Play-by-play walkthrough
quartz draft --simulate --r2 85 --r4 160
quartz draft --simulate --r2 85 --r4 160 --strategy greedy_pv

# All commands respect draft_format from active_tournament.yaml
```

## YAML Configuration

```yaml
draft_format:
  picks_per_captain: 4
  reorder_after_round: ~        # null = no reorder
  randomize_captain_order: false
  soft_cap_trigger: ~           # null = no soft cap; set to team PV ceiling after pick 1
  soft_cap_scale: 0.5           # linear multiplier on soft cap excess

captain_slots:
  - [1, "PlayerA"]
  - [2, "PlayerB"]
  # ...
```

Thresholds (`r2`, `r4`) are CLI flags — they are the *output* of `--optimize`, not tournament rules, so they are not stored in YAML.

---

## Open Questions / Future Work

- [ ] Tune `soft_cap_trigger` and `soft_cap_scale` against GCS S4 pool once all PVs are finalized.
- [ ] Implement `DraftFormat` config object in `active_tournament.yaml` to make phase/reorder rules fully data-driven (currently partially hardcoded in `draft_simulator.py`).
- [ ] Surface champion pool depth in pick recommendations — constrain picks by whether a player can fill a required champ role.
- [ ] Validate that threshold search converges cleanly on GCS S4 pool (10 captains × 4 picks = 50 players drafted; pool size matters for feasibility).
