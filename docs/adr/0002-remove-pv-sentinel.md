# PV Sentinel Value Replaced with Optional

`PV_SENTINEL = 9999.0` is removed. `ComputedPV.point_value` becomes `Optional[float]` — `None` when the player has no usable rank data. `rank_score("Unranked")` returns `None` instead of `9999`. The `ComputedPV.flagged` boolean remains as the authoritative signal for "no usable data."

The sentinel was a magic number that leaked into every downstream consumer: exports, display scripts, and the draft simulator all had to remember to check `>= 9999` rather than checking `flagged` or `None`. It created a silent correctness hazard — any math on a flagged player's PV would produce a nonsense result rather than a loud error. `Optional[float]` forces callers to handle the missing-data case explicitly.
