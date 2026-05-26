# Implementation Plan: F1 Confidence Weighting + Eligibility + Account Flags

Branch: refactor-scraper-system (or new branch)
Context: grilling session resolved all design decisions. This doc is the authoritative task list.

---

## Design Summary (for context after compaction)

### F1 change
Each historical split's base_weight is multiplied by a confidence factor before normalization:
```
confidence_i  = 1 - e^(-games_i / N_historical_i)
effective_w_i = base_weight_i × confidence_i
F1            = Σ (effective_w_i / Σ effective_w) × rank_score(peak_rank_i)
```
- `N_historical_i = max(n_historical_floor=30, pool_stat_for_that_split)` using same `confidence_strategy` as F2
- games=0 or None → confidence=0 → split excluded (sparse normalization, same as missing peak_rank)
- New `PVWeights` param: `n_historical_floor: int = 30`

### ComputedPV model change
- `flagged: bool` → `flag_reason: Optional[str]` (`None` | `"no_data"` | `"ineligible"`)
- New field: `shadow_pv: Optional[float]` (PV an ineligible player would have if eligible)

### Eligibility
- Config lives in `active_tournament.yaml` under `eligibility:` block (EligibilityConfig model)
- GCS rule: 30 games in S2026 OR 50+ games in S2025
- Ineligible → `flag_reason="ineligible"`, `point_value=None`, shadow PV computed and stored
- `SeasonData` gets: `eligible: Optional[bool]`, `shadow_point_value: Optional[int]`
- Evaluated during `PV_COMPUTE` (pre-check) AND during `quartz resync`

### Account flags
- `account_flagged: bool` + `update_riot_id: bool` → `flags: list[AccountFlag]`
- `AccountFlag`: `flag_type`, `detail`, `auto`, `dismissed`
- `account_flagged` becomes a `@computed_field`: `any(f for f in flags if not f.dismissed)`
- Types: `low_level` (<100), `low_volume` (all PAST_YEAR <50g), `smurf_peak` (level<200 + Emerald+ any split), `smurf_jump` (rank_score delta >20pts between consecutive splits, level<200), `name_changed`
- Dismissed flags stay visible in view, marked [DISMISSED], excluded from account_flagged

### Shadow PV
- Stored on `ComputedPV.shadow_pv` and `SeasonData.shadow_point_value`
- `quartz pv-shadow` shows ineligible players + their shadow scores (read-only, does NOT write)

---

## What is DONE ✅

| File | Change |
|------|--------|
| `quartz/models/player_profile.py` | `AccountFlag` model; `Account.flags` list; `account_flagged` computed_field; migration validator; `add_auto_flag / clear_auto_flag / get_flag` helpers; `SeasonData.eligible` + `shadow_point_value` |
| `quartz/models/pv_model.py` | `ComputedPV.flag_reason` (replaces `flagged`); `ComputedPV.shadow_pv`; `PVWeights.n_historical_floor=30`; `PVWeights.smurf_jump_threshold=20.0` |
| `quartz/tournament_config.py` | `EligibilityConfig` model; `TournamentConfig.eligibility: Optional[EligibilityConfig]` |
| `quartz/account_flags.py` | New module — `evaluate_account_flags(account, weights)` with all 4 auto checks |
| `docs/features/F1_historical_peak.md` | Full rewrite with confidence weighting formula |
| `docs/features/F2_confidence_rank.md` | Added shadow PV section, F1 relationship |
| `docs/flags.md` | New — full flag type catalogue, CLI reference, evaluation timing |
| `CONTEXT.md` | Added: Account Flag, Player Eligibility, Shadow PV, Flag Reason |
| `quartz/pv_compute.py` | Docstring updated (partial — rest is TODO below) |

---

## What is TODO ❌

### 1. `quartz/pv_compute.py` — core compute logic
Add after `compute_N_threshold()`:

```python
def compute_N_historical_thresholds(
    profiles: list,
    weights: PVWeights,
    past_seasons: list[str],
) -> dict[str, int]:
    """Per-split N for F1 confidence curve. max(n_historical_floor, pool_stat_for_split)."""
    result = {}
    for season in past_seasons:
        games_list = []
        for profile in profiles:
            if not profile.stats or not profile.stats.rank_data:
                continue
            agg = next((s for s in profile.stats.rank_data.solo_splits if s.season == season), None)
            if not agg:
                continue
            g = (agg.wins or 0) + (agg.losses or 0)
            if g > 0:
                games_list.append(g)
        if not games_list:
            result[season] = weights.n_historical_floor
            continue
        strategy = weights.confidence_strategy
        if strategy == ConfidenceThresholdStrategy.MEDIAN:
            pool_stat = int(statistics.median(games_list))
        elif strategy == ConfidenceThresholdStrategy.P25:
            idx = max(0, int(len(sorted(games_list)) * 0.25) - 1)
            pool_stat = sorted(games_list)[idx]
        elif strategy == ConfidenceThresholdStrategy.MEAN_1SD:
            mean = statistics.mean(games_list)
            std = statistics.stdev(games_list) if len(games_list) >= 2 else 0.0
            pool_stat = int(mean - std)
        else:
            pool_stat = _FALLBACK_N
        result[season] = max(weights.n_historical_floor, pool_stat)
    return result


def evaluate_eligibility(profile, eligibility_config) -> bool:
    """Returns True if player meets tournament eligibility requirements."""
    if eligibility_config is None:
        return True
    if not profile.stats or not profile.stats.rank_data:
        return False
    splits_by_season = {s.season: s for s in profile.stats.rank_data.solo_splits}
    primary = splits_by_season.get(eligibility_config.primary_split)
    primary_games = ((primary.wins or 0) + (primary.losses or 0)) if primary else 0
    if primary_games >= eligibility_config.primary_min_games:
        return True
    if eligibility_config.backup_split and eligibility_config.backup_min_games:
        backup = splits_by_season.get(eligibility_config.backup_split)
        backup_games = ((backup.wins or 0) + (backup.losses or 0)) if backup else 0
        if backup_games >= eligibility_config.backup_min_games:
            return True
    return False
```

Update `compute_pv()` signature — add parameter:
```python
n_historical_thresholds: dict[str, int] | None = None,
```

Replace F1 block (currently lines ~125–143) with confidence-weighted version:
```python
# F1 — Time-Decayed Historical Peak with confidence weighting
F1: Optional[float] = None
if splits_by_season:
    past_seasons = PAST_YEAR_SEASONS[:weights.history_splits]
    base_weights = weights.historical_base_weights[:weights.history_splits]
    available: list[tuple[float, float]] = []
    for season_key, base_w in zip(past_seasons, base_weights):
        agg = splits_by_season.get(season_key)
        if not agg or not agg.peak_rank:
            continue
        score = rank_score(agg.peak_rank)
        if score is None:
            continue
        games = (agg.wins or 0) + (agg.losses or 0)
        n_hist = (n_historical_thresholds or {}).get(season_key, weights.n_historical_floor)
        confidence = (1.0 - math.exp(-games / n_hist)) if n_hist > 0 and games > 0 else 0.0
        eff_w = base_w * confidence
        if eff_w > 0:
            available.append((eff_w, score))
    if available:
        total_w = sum(w for w, _ in available)
        F1 = sum((w / total_w) * s for w, s in available)
        features.historical_score = round(F1, 3)
        features.splits_used = len(available)
```

Replace final return (flagged case) — change `flagged=True` → `flag_reason="no_data"`:
```python
return ComputedPV(..., flag_reason="no_data")
```

---

### 2. `quartz/tasks/pv_compute.py` — task orchestration

Replace the whole `run()` body. Key changes:
- Compute `n_hist_thresholds = compute_N_historical_thresholds(all_profiles, weights, PAST_YEAR_SEASONS[:weights.history_splits])`
- Before each player's PV: call `evaluate_eligibility(profile, config.eligibility)` → write to `season_entry.eligible`
- If ineligible: compute shadow PV (call compute_pv normally), then build ineligible ComputedPV with `flag_reason="ineligible"`, `shadow_pv=shadow_result.point_value`; write `season_entry.shadow_point_value`
- If eligible: normal compute_pv, `season_entry.shadow_point_value = None`
- Also call `evaluate_account_flags(account, weights)` for each account (flag refresh)
- Change `pv_result.flagged` checks → `pv_result.flag_reason`

```python
from quartz.pv_compute import (
    compute_N_threshold, compute_N_historical_thresholds,
    compute_pv, compute_realistic_max, evaluate_eligibility,
)
from quartz.account_flags import evaluate_account_flags
from quartz.constants import PAST_YEAR_SEASONS
from quartz.models.pv_model import ComputedPV

# ... inside run():
n_hist_thresholds = compute_N_historical_thresholds(
    all_profiles, weights, PAST_YEAR_SEASONS[:weights.history_splits]
)

for profile in target_profiles:
    # refresh account flags
    for account in profile.accounts:
        if not account.archived:
            evaluate_account_flags(account, weights)

    season_entry = next((sd for sd in profile.season_data if sd.season == config.round_id), None)

    # eligibility check
    eligible = evaluate_eligibility(profile, config.eligibility)
    if season_entry:
        season_entry.eligible = eligible

    if not eligible:
        # compute shadow PV (bypasses eligibility gate)
        shadow = compute_pv(profile, weights, N, config.round_id,
                            config.current_lol_split, realistic_max, n_hist_thresholds)
        pv_result = ComputedPV(
            features=shadow.features,
            weights_used=weights,
            pv_rank_only=None,
            point_value=None,
            flag_reason="ineligible",
            shadow_pv=shadow.point_value,
        )
        if season_entry:
            season_entry.point_value = None
            season_entry.shadow_point_value = (
                round(shadow.point_value) if shadow.point_value is not None else None
            )
    else:
        pv_result = compute_pv(profile, weights, N, config.round_id,
                               config.current_lol_split, realistic_max, n_hist_thresholds)
        if season_entry:
            season_entry.point_value = (
                None if pv_result.point_value is None else round(pv_result.point_value)
            )
            season_entry.shadow_point_value = None

    profile.stats.computed_pv = pv_result
    profile.touch()
    registry.save(profile)
```

---

### 3. `quartz/tasks/opgg_scrape_rank.py` — replace legacy flag writes

Replace all `account.account_flagged = True/False` and `account.update_riot_id = True/False` with:

```python
# not found (name changed):
account.add_auto_flag('name_changed', detail='OP.GG profile not found — name change likely')

# found (clear name_changed):
account.clear_auto_flag('name_changed')

# level < 100:
account.add_auto_flag('low_level', detail=f'account level {level} < 100')

# level >= 100 (clear low_level):
account.clear_auto_flag('low_level')
```

Note: full flag evaluation (`smurf_peak`, `smurf_jump`, `low_volume`) happens in `evaluate_account_flags()` during PV_COMPUTE or resync — rank scraper only handles `low_level` and `name_changed` since it has that data at scrape time.

---

### 4. `quartz/cli/flags.py` — new file

```
quartz flags list [--all]
quartz flags add  PLAYER RIOT_ID TYPE [--detail TEXT]
quartz flags dismiss PLAYER RIOT_ID TYPE
```

- `list`: load all profiles, iterate all accounts, collect flags. Default: show non-dismissed. `--all`: include dismissed (marked [DISMISSED]).
- `add`: find profile+account, append `AccountFlag(flag_type=TYPE, detail=detail, auto=False, dismissed=False)`, save.
- `dismiss`: find flag by type on that account, set `dismissed=True`, save.

Register in `main.py`:
```python
from quartz.cli import flags as flags_cli
app.add_typer(flags_cli.app, name="flags", help="View and manage account flags.")
```

---

### 5. `quartz/cli/pv_shadow.py` — new file (or add to pv.py)

`quartz pv-shadow` — read-only, no writes.
- Load all profiles for current round
- Find those with `season_entry.eligible == False`
- Display table: player | type | current_rank | shadow_pv | reason (games in primary/backup split)

Register in `main.py`:
```python
from quartz.cli.pv_shadow import pv_shadow
app.command("pv-shadow")(pv_shadow)
```

---

### 6. `quartz/cli/view.py` — update flag/PV display

In the accounts block, replace:
```python
if acc.account_flagged:
    status_parts.append("FLAGGED")
if acc.update_riot_id:
    status_parts.append("NAME CHANGED")
```
With:
```python
for flag in acc.flags:
    label = flag.flag_type.upper().replace("_", " ")
    if flag.dismissed:
        label += " [DISMISSED]"
    status_parts.append(label)
```

In the PV breakdown footer, replace:
```python
flag_str = "  FLAGGED (no data)" if pv.flagged else ""
```
With:
```python
if pv.flag_reason == "no_data":
    flag_str = "  FLAGGED (no data)"
elif pv.flag_reason == "ineligible":
    shadow_str = f"  shadow={pv.shadow_pv}" if pv.shadow_pv is not None else ""
    flag_str = f"  INF (ineligible){shadow_str}"
else:
    flag_str = ""
```

---

### 7. `quartz/cli/util.py` — resync adds flag + eligibility eval

In `resync()`, after `profile.stats = compute_enrichment(...)`:
```python
from quartz.account_flags import evaluate_account_flags
from quartz.pv_compute import evaluate_eligibility
from quartz.pv_weights_io import load_weights

weights, _ = load_weights(config.abs_data_dir)
for account in profile.accounts:
    if not account.archived:
        evaluate_account_flags(account, weights)

season_entry = next((sd for sd in profile.season_data if sd.season == config.round_id), None)
if season_entry:
    season_entry.eligible = evaluate_eligibility(profile, config.eligibility)
```

---

### 8. `active_tournament.yaml` — add eligibility block

```yaml
eligibility:
  primary_split: S2026
  primary_min_games: 30
  backup_split: S2025
  backup_min_games: 50
```

---

### 9. `quartz/cli/pv.py` — update flagged display

In the PV table, `pv` is `cpv.point_value`. When `None`, currently shows `[red]no data[/red]`.
Need to distinguish `flag_reason="no_data"` vs `flag_reason="ineligible"`:
- `"no_data"` → `[red]FLAGGED[/red]`
- `"ineligible"` → `[yellow]INF[/yellow]`
- `None` (clean) → normal PV number

---

### 10. Before/after PV comparison

After everything is implemented and `quartz pv --recalculate` is run:
- Run `quartz pv` on the full pool
- Compare `SeasonData.point_value` before vs after for each player
- Look especially at players with thin historical splits (S2024 S1/S2 with few games)

The view command shows the PV breakdown per player — use `quartz view PLAYER` to inspect F1 splits_used and historical_score for specific players.

---

## Implementation order

1. `quartz/pv_compute.py` — compute_N_historical_thresholds, evaluate_eligibility, updated compute_pv F1 + flag_reason return
2. `quartz/tasks/pv_compute.py` — full rewrite of run() body
3. `quartz/tasks/opgg_scrape_rank.py` — legacy flag writes → add_auto_flag/clear_auto_flag
4. `quartz/cli/flags.py` — new flags subcommand group
5. `quartz/cli/pv_shadow.py` — new pv-shadow command
6. `quartz/cli/main.py` — register flags + pv-shadow
7. `quartz/cli/view.py` — flag display + INF display
8. `quartz/cli/util.py` — resync integration
9. `quartz/cli/pv.py` — table display update
10. `active_tournament.yaml` — add eligibility block
11. Run `quartz pv --recalculate` + before/after comparison
