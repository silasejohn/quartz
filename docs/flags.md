# Account Flags

Account flags are structured markers attached to individual accounts within a player profile. They identify conditions that warrant human review — suspected smurfs, under-leveled accounts, thin rank histories, or name changes.

Flags are stored as `Account.flags: list[AccountFlag]` on the account model. Each flag has a type, optional detail string, and a `dismissed` state for admin acknowledgment of false positives. An account is considered flagged if it has any non-dismissed flags.

`profile_flagged` fires when **every** active (non-archived) account on the profile has at least one non-dismissed flag.

---

## Flag Types

### `low_level`
**Trigger:** `account.account_level < 100`
**Auto-generated:** Yes — evaluated during `quartz resync` and rank scraping
**Meaning:** The account has very few total games played across all modes. Either a new account, or a smurf account that has only played ranked.

---

### `low_volume`
**Trigger:** Every split in `PAST_YEAR_SEASONS` (S2025, S2024 S3, S2024 S2, S2024 S1) has fewer than 50 total ranked games (wins + losses)
**Auto-generated:** Yes — evaluated during `quartz resync`
**Meaning:** The account has a thin solo queue history across the past year. Rank peaks from low-volume splits receive reduced weight in F1 automatically, but this flag surfaces the pattern explicitly for review.

---

### `smurf_peak`
**Trigger:** `account.account_level < 200` AND `peak_rank` in **any tracked split** is Emerald or above (rank_score ≤ 46.8, i.e. Emerald 4 0 LP or better)
**Auto-generated:** Yes — evaluated during `quartz resync`
**Meaning:** The account reached a high rank while still having low total game volume (implied by level < 200). Emerald+ in early account life is a common smurf pattern — experienced players leveling a new account will climb quickly.

*Note: level < 200 as the threshold reflects "low overall game experience." A legitimate player who has played since Season 2013 will almost certainly exceed level 200 regardless of ranked performance.*

---

### `smurf_jump`
**Trigger:** The rank_score difference between `split_rank` at end of split N−1 and `peak_rank` in split N exceeds `smurf_jump_threshold` (default: 20.0 rank_score points, tunable in `PVWeights`), AND `account.account_level < 200`
**Auto-generated:** Yes — evaluated during `quartz resync`, requires consecutive split data
**Meaning:** The account climbed more than ~2 full tiers in a single split while still having low account level. A 20-point rank_score jump corresponds roughly to Gold 4 → Emerald 4 or Platinum 1 → Diamond 4.

*Note: rank_score is used rather than raw division count because the LP gap between consecutive divisions is not uniform across tiers. 20 rank_score points is approximately "two full tiers" regardless of starting rank.*

| Starting rank (score) | +20 pts lands at | Example |
|---|---|---|
| Silver 4 (75.2) | ~55 → Platinum 3 | Silver → Platinum |
| Gold 4 (66.6) | ~47 → Emerald 4 | Gold → Emerald |
| Platinum 1 (49.6) | ~30 → Diamond 4 | Platinum → Diamond |
| Emerald 2 (41.0) | ~21 → Master | Emerald → Master |

---

### `name_changed`
**Trigger:** OP.GG cannot find the stored `riot_id` — likely a name or tag change
**Auto-generated:** Yes — set by the rank scraper when profile lookup fails
**Meaning:** The account's Riot ID has changed and needs to be updated. The account's data is stale until the correct riot_id is set via `quartz manage`.

---

## Manual Flags

Any `flag_type` string not in the list above can be set manually via `quartz flags add`. Use this for edge cases that don't fit automated detection: admin notes, manual smurf confirmation, player disputes, etc.

---

## CLI Reference

```
quartz flags list                              # show all accounts with active (non-dismissed) flags
quartz flags list --all                        # include dismissed flags
quartz flags add PLAYER RIOT_ID TYPE           # manually add a flag
quartz flags add PLAYER RIOT_ID TYPE \
  --detail "peaked E2 in S2024 S1"            # with context note
quartz flags dismiss PLAYER RIOT_ID TYPE       # dismiss a specific flag (marks as acknowledged)
```

Dismissed flags remain visible in `quartz view` and `quartz flags list --all`, marked `[DISMISSED]`. They are excluded from `account_flagged` computation but retained for audit trail.

---

## Evaluation Timing

Automated flags are evaluated in two places:

1. **`quartz resync`** — re-evaluates all auto flags on every profile after any data change
2. **`PV_COMPUTE`** — evaluates eligibility (which depends on flag state) immediately before computing each player's PV

Manual flags are only modified by explicit `quartz flags add / dismiss` commands.

---

## Eligibility vs. Flags

Flags and eligibility are related but distinct:

- **Flags** are account-level signals for human review. They do not directly affect PV.
- **Eligibility** is a player-level tournament rule (e.g. GCS: 30 games in S2026, or 50+ in S2025). Configured per tournament in `active_tournament.yaml`. Ineligible players receive `point_value = INF` and a **Shadow PV** instead — see `docs/features/F2_confidence_rank.md`.

A flagged account does not automatically make a player ineligible. Eligibility is determined solely by games-played thresholds from the tournament rulebook.
