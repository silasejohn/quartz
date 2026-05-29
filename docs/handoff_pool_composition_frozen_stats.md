# Handoff: Pool Composition + Frozen Pool Stats

Two related features. Implement them together since they share a `pool_profiles` split.

---

## Background

`quartz pv` computes a set of pool-level hyperparameters before the per-player loop — these
are statistics derived from the tournament roster that calibrate the PV formula for the pool:

| Hyperparam | Helper | What it calibrates |
|---|---|---|
| `N` | `compute_N_threshold` | F2 confidence curve games threshold |
| `champ_dpm_baseline`, `champ_dpm_pool_stddev` | `compute_champ_dpm_baseline` | F5 pool-median and spread |
| `realistic_max` | `compute_realistic_max` | F3 in-house Wilson LB ceiling |
| `atp_miss_scale` | `compute_atp_miss_scale` | ATP decay miss normalization |
| `atp_season_min_games` | `compute_atp_season_min_games` | ATP decay per-season game floor |

Currently all of these are computed from `tournament_profiles` which includes `captain`,
`main`, and `sub` player types. Two changes are needed:

1. **Pool Composition** — only `captain` + `main` should define the pool baseline; subs are
   evaluated against it, not part of defining it.
2. **Frozen Pool Stats** — once the roster is final, the organizer can lock these values into
   the tournament YAML so future `quartz pv` runs produce identical results regardless of
   any roster drift.

---

## Feature 1 — Pool Composition

### What changes

Introduce a `pool_profiles` list (captain + main only) alongside `tournament_profiles`
(captain + main + sub). Pass `pool_profiles` to all five pool-level helper functions.
`tournament_profiles` continues to define who gets PV computed.

`other` players are already excluded from `tournament_profiles` — do not touch that logic.

### File: `quartz/tasks/pv_compute.py`

After the existing `other_profiles` / `tournament_profiles` split (around line 59), add:

```python
def _is_pool_player(profile) -> bool:
    sd = next((s for s in profile.season_data if s.season == config.round_id), None)
    return sd is not None and sd.player_type in ("captain", "main")

pool_profiles = [p for p in tournament_profiles if _is_pool_player(p)]
info_print(
    f"PV_COMPUTE: pool = {len(pool_profiles)} players (captain+main), "
    f"scoring = {len(tournament_profiles)} players (incl. subs)"
)
```

Then replace every occurrence of `tournament_profiles` in the five helper calls with
`pool_profiles`:

```python
N = compute_N_threshold(pool_profiles, weights, config.current_lol_split)
realistic_max = compute_realistic_max(pool_profiles, weights, config.round_id)
n_hist_thresholds = compute_n_historical_thresholds(pool_profiles, weights, past_seasons)
champ_median, champ_stddev = compute_champ_dpm_baseline(pool_profiles, weights, config.current_lol_split)
atp_miss_scale = compute_atp_miss_scale(pool_profiles, weights)
atp_season_min_games = {
    season: compute_atp_season_min_games(pool_profiles, weights, season)
    for season in SEASON_ORDER
}
```

`target_profiles` (the loop that actually computes PV) still uses `tournament_profiles` —
do not change that.

### No changes needed in `quartz/pv_compute.py`

The helper functions are already agnostic to which list they receive. No signature changes.

---

## Feature 2 — Frozen Pool Stats

### Data model: `quartz/tournament_config.py`

Add a new Pydantic model and an optional field on `TournamentConfig`:

```python
class FrozenPoolStats(BaseModel):
    """Pool-level hyperparameters locked by `quartz pv --freeze`.

    When present on TournamentConfig, PV_COMPUTE uses these values directly
    instead of recomputing from live roster data. Clear with `quartz pv --clear`.
    """
    N: int
    champ_dpm_baseline: float
    champ_dpm_pool_stddev: float
    realistic_max: float
    atp_miss_scale: float
    atp_season_min_games: dict[str, int]   # SEASON_ORDER key → min games
```

On `TournamentConfig`, add:

```python
frozen_pool_stats: Optional[FrozenPoolStats] = None
```

Also add a `config_path` field so the write-back commands know which YAML to update:

```python
from pydantic import Field

config_path: Optional[str] = Field(default=None, exclude=True)
```

`exclude=True` keeps it out of `.model_dump()` so it never appears in serialization.

In `load_tournament_config`, set it after construction. The function currently does:

```python
return TournamentConfig(**data)
```

Change to:

```python
config = TournamentConfig(**data)
config.config_path = str(path)
return config
```

(`path` is already the resolved path at this point — the `source:` pointer is already
followed earlier in the function.)

### YAML write-back helper: `quartz/tournament_config.py`

Add this function (can be private, called only by pv.py):

```python
import re

def write_frozen_pool_stats(config: TournamentConfig, stats: "FrozenPoolStats | None") -> None:
    """Write (or clear) the frozen_pool_stats block in the tournament YAML.

    Preserves all other content including comments.
    """
    if not config.config_path:
        raise RuntimeError("config_path not set — cannot write back to YAML")

    yaml_path = Path(config.config_path)
    content = yaml_path.read_text(encoding="utf-8")

    if stats is None:
        replacement = "frozen_pool_stats: ~"
    else:
        season_lines = "".join(
            f"    {k}: {v}\n" for k, v in stats.atp_season_min_games.items()
        )
        replacement = (
            f"frozen_pool_stats:\n"
            f"  N: {stats.N}\n"
            f"  champ_dpm_baseline: {round(stats.champ_dpm_baseline, 4)}\n"
            f"  champ_dpm_pool_stddev: {round(stats.champ_dpm_pool_stddev, 4)}\n"
            f"  realistic_max: {round(stats.realistic_max, 6)}\n"
            f"  atp_miss_scale: {round(stats.atp_miss_scale, 4)}\n"
            f"  atp_season_min_games:\n"
            f"{season_lines}"
        ).rstrip("\n")

    # Replace existing block (null or multi-line) — matches from line start to next
    # top-level key or EOF, preserving all surrounding content.
    pattern = re.compile(
        r'^frozen_pool_stats:.*?(?=\n[^\s#\n]|\Z)',
        re.MULTILINE | re.DOTALL,
    )
    if pattern.search(content):
        content = pattern.sub(replacement, content)
    else:
        # Block not present — append it
        content = content.rstrip("\n") + "\n\n" + replacement + "\n"

    yaml_path.write_text(content, encoding="utf-8")
```

### Use frozen values in `quartz/tasks/pv_compute.py`

At the top of the pool-stats block (before any compute calls), add:

```python
frozen = config.frozen_pool_stats

if frozen:
    info_print("PV_COMPUTE: using FROZEN pool stats from tournament YAML")
    N             = frozen.N
    realistic_max = frozen.realistic_max
    n_hist_thresholds = frozen.n_hist_thresholds  # ← see note below
    champ_median  = frozen.champ_dpm_baseline
    champ_stddev  = frozen.champ_dpm_pool_stddev
    atp_miss_scale      = frozen.atp_miss_scale
    atp_season_min_games = frozen.atp_season_min_games
else:
    N = compute_N_threshold(pool_profiles, weights, config.current_lol_split)
    # ... rest of existing compute calls ...
```

**Note on `n_hist_thresholds`:** `compute_n_historical_thresholds` returns a `dict[str, int]`
(one N per past split). You have two options:

- **Option A (simpler):** Add `n_hist_thresholds: dict[str, int]` to `FrozenPoolStats` and
  freeze it alongside the others. Recommended.
- **Option B:** Always recompute `n_hist_thresholds` even when frozen (it's cheap and
  historical data doesn't change mid-tournament).

Recommend **Option A** for consistency — freeze everything together.

After the frozen/dynamic block, the `weights.model_copy(...)` line stays as-is since it
just injects `champ_median`/`champ_stddev` into weights for use downstream.

### CLI flags: `quartz/cli/pv.py`

Add two new flags to the `pv()` function signature:

```python
def pv(
    recalculate: bool = typer.Option(False, "--recalculate", ...),
    tune:        bool = typer.Option(False, "--tune", ...),
    freeze:      bool = typer.Option(False, "--freeze",
                     help="Compute and lock pool stats into the tournament YAML, then run PV"),
    clear:       bool = typer.Option(False, "--clear",
                     help="Clear frozen pool stats from the tournament YAML (revert to dynamic)"),
    round:       Optional[str] = typer.Option(None, "--round", ...),
):
```

Handle them before the existing `tune` block:

```python
if clear:
    from quartz.tournament_config import write_frozen_pool_stats
    write_frozen_pool_stats(config, None)
    success_print("Cleared frozen_pool_stats — pool stats will be recomputed dynamically.")
    return

if freeze:
    # Compute pool stats, write to YAML, then run PV (all in one shot)
    from quartz.tournament_config import FrozenPoolStats, write_frozen_pool_stats
    from quartz.models.pv_model import PVWeights
    from quartz.pv_weights_io import load_weights
    from quartz.pv_compute import (
        compute_N_threshold, compute_realistic_max,
        compute_n_historical_thresholds, compute_champ_dpm_baseline,
        compute_atp_miss_scale, compute_atp_season_min_games,
    )
    from quartz.constants import PAST_YEAR_SEASONS, SEASON_ORDER
    from quartz.player_registry import PlayerRegistry

    registry = PlayerRegistry(config.abs_players_dir)
    weights, _ = load_weights(config.abs_data_dir)

    all_profiles = registry.load_all()
    def _is_pool_player(p):
        sd = next((s for s in p.season_data if s.season == config.round_id), None)
        return sd is not None and sd.player_type in ("captain", "main")
    pool_profiles = [p for p in all_profiles if _is_pool_player(p)]

    past_seasons = PAST_YEAR_SEASONS[:weights.history_splits]

    frozen = FrozenPoolStats(
        N=compute_N_threshold(pool_profiles, weights, config.current_lol_split),
        realistic_max=compute_realistic_max(pool_profiles, weights, config.round_id),
        n_hist_thresholds=compute_n_historical_thresholds(pool_profiles, weights, past_seasons),
        champ_dpm_baseline=compute_champ_dpm_baseline(pool_profiles, weights, config.current_lol_split)[0],
        champ_dpm_pool_stddev=compute_champ_dpm_baseline(pool_profiles, weights, config.current_lol_split)[1],
        atp_miss_scale=compute_atp_miss_scale(pool_profiles, weights),
        atp_season_min_games={
            s: compute_atp_season_min_games(pool_profiles, weights, s) for s in SEASON_ORDER
        },
    )
    write_frozen_pool_stats(config, frozen)
    success_print(
        f"Frozen pool stats written to {config.config_path}\n"
        f"  N={frozen.N}, champ_baseline={frozen.champ_dpm_baseline:.1f}, "
        f"realistic_max={frozen.realistic_max:.4f}"
    )
    # Fall through to normal PV compute — which will now read the frozen values
    # (need to reload config so it picks up the just-written YAML)
    config = load_tournament_config()

# Existing logic continues:
if tune:
    ...
```

**Note:** Call `compute_champ_dpm_baseline` once and unpack — the double call above is
illustrative; in real code unpack to `(champ_median, champ_stddev)` first.

### Tournament YAML: add `frozen_pool_stats: ~` to all configs

Add to `tournaments/gcs_s4.yaml` and `tournaments/test_v4.yaml` (and any future ones):

```yaml
# Frozen pool stats — written by `quartz pv --freeze`, cleared by `quartz pv --clear`.
# Null = dynamic (recomputed each run from captain+main pool).
frozen_pool_stats: ~
```

Place this at the end of the file, or near the bottom with other computed/output fields.
The `write_frozen_pool_stats` regex will find and replace it regardless of position.

---

## Workflow summary (for organizer)

```bash
# 1. Tune with live data — dynamic, nothing locked
quartz pv --recalculate

# 2. Happy with the pool? Lock it.
quartz pv --freeze
# → writes frozen_pool_stats: block to gcs_s4.yaml
# → immediately runs PV compute using the now-frozen values
# → profiles are guaranteed to match the locked hyperparams

# 3. Future runs use frozen values — fast and reproducible
quartz pv

# 4. Want to re-tune? Clear and repeat.
quartz pv --clear
quartz pv --recalculate
quartz pv --freeze
```

---

## Gotchas

- **`config_path` requires the source pointer to be followed first.** `load_tournament_config`
  already follows the `source:` key — by the time it reaches `TournamentConfig(**data)`, `path`
  is already pointing at `tournaments/gcs_s4.yaml`. Set `config.config_path = str(path)` there.

- **Don't pass `active_tournament.yaml` to `write_frozen_pool_stats`.** Always write to the
  resolved tournament file (`tournaments/gcs_s4.yaml`), not the pointer file.

- **`_is_pool_player` is duplicated** between `pv_compute.py` (task) and `pv.py` (CLI freeze
  path). Either extract it to a shared helper in `pv_compute.py` or accept the duplication
  (it's two lines).

- **`--freeze` reloads config after writing** so the subsequent PV compute reads the frozen
  values from disk rather than the stale in-memory config. This is the simplest correct
  approach; alternatively, inject the frozen stats directly into the in-memory config before
  running the task.

- **Test with `test_v4.yaml`** — set `QUARTZ_CONFIG=tournaments/test_v4.yaml`, run
  `quartz pv --freeze`, confirm `frozen_pool_stats:` block appears in `test_v4.yaml`, run
  `quartz pv` again to confirm frozen values are used (look for the "using FROZEN" log line),
  then `quartz pv --clear` and confirm it reverts to `~`.
