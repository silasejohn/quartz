# F4 — Manual Adjustments

Admin-set per-player, per-round PV modifiers applied after all computed features.

## What it captures

Tournament-specific context that no scraper can derive: previous season wins, finals appearances, known smurfs, admin discretion. These are set explicitly by tournament organizers and stored on `SeasonData.manual_adjustments`.

## Formula

```
manual_adj_total = Σ adjustment.value for all adjustments in season_entry.manual_adjustments
point_value = base_pv + baseline - F3 - manual_adj_total
```

Positive `value` reduces PV (bonus — player is stronger than rank suggests).
Negative `value` increases PV (penalty — player is weaker or penalized for conduct).

## Schema

```python
ManualAdjustment(
    category="tournament_win",    # freeform label for display/audit
    value=5.0,                    # positive = bonus (reduces PV)
    note="Won GCS S3",            # optional context
)
```

## Common categories

| Category | Typical direction | Meaning |
|----------|------------------|---------|
| `previous_winner` | bonus (+) | Won a prior season |
| `finals_appearance` | bonus (+) | Reached finals |
| `admin_bonus` | bonus (+) | Organizer discretion |
| `admin_penalty` | penalty (−) | Conduct, sandbagging, etc. |
| `region_modifier` | either | EUW/KR account correction |

> **TODO**: Scale adjustment magnitudes as a proportion of the pool's PV range rather than hard-coded values. See [TODO.md](../TODO.md) — F3/F4 section.
