"""
F1/F2 feature analysis — compute PV for every pool player and inspect how
the historical (F1) and current (F2) features interact.

Run: python tests/diag/diag_f1_f2_analysis.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from quartz.constants import PAST_YEAR_SEASONS, rank_score
from quartz.models.player_profile import PlayerProfile
from quartz.models.pv_model import PVWeights
from quartz.pv_compute import (
    compute_N_historical_thresholds,
    compute_N_threshold,
    compute_pv,
    compute_realistic_max,
)
from quartz.tournament_config import load_tournament_config

# ── Load ─────────────────────────────────────────────────────────────────────
config  = load_tournament_config()
weights = PVWeights()

players = []
for fname in os.listdir(config.abs_players_dir):
    if not fname.endswith(".json") or fname.startswith("_"):
        continue
    with open(os.path.join(config.abs_players_dir, fname)) as fp:
        data = json.load(fp)
    try:
        players.append(PlayerProfile.model_validate(data))
    except Exception:
        pass

# ── Pool-level params ────────────────────────────────────────────────────────
N        = compute_N_threshold(players, weights, config.current_lol_split)
n_hist   = compute_N_historical_thresholds(players, weights, PAST_YEAR_SEASONS[:weights.history_splits])
real_max = compute_realistic_max(players, weights, config.round_id)

print(f"Pool: {len(players)} players  |  N_threshold={N}  |  n_historical={n_hist}  |  realistic_max={real_max:.3f}")
print(f"Config: split={config.current_lol_split}  round={config.round_id}")
print()

# ── Per-player breakdown ─────────────────────────────────────────────────────
rows = []
for p in players:
    cpv = compute_pv(p, weights, N, config.round_id, config.current_lol_split, real_max, n_hist)
    f   = cpv.features

    stats = p.stats
    cur   = stats.current_rank if stats else None
    atp   = stats.all_time_peak_rank if stats else None

    splits = {}
    if stats and stats.rank_data:
        splits = {s.season: s for s in stats.rank_data.solo_splits}

    rows.append({
        "player":      p.effective_id,
        "cur":         cur or "?",
        "atp":         atp or "?",
        "cur_rs":      rank_score(cur) if cur else None,
        "atp_rs":      rank_score(atp) if atp else None,
        "games":       f.games_played,
        "f2_conf":     f.confidence,
        "f1":          f.historical_score,
        "f2":          f.adjusted_current_pts,
        "f1_conf":     f.f1_confidence,
        "nsplits":     f.splits_used or 0,
        "pv":          cpv.point_value,
        "flag":        cpv.flag_reason,
        "splits_raw":  splits,
    })

rows.sort(key=lambda r: (r["pv"] or 999))

# Header
print(f"{'Player':<18} {'Current':>22} {'ATP':>22} {'F1':>6} {'F1c':>4} {'F2':>6} {'F2c':>4} {'Games':>5} {'PV':>6}")
print("─" * 100)
for r in rows:
    f1s  = f"{r['f1']:6.1f}" if r["f1"] is not None else "     ?"
    f2s  = f"{r['f2']:6.1f}" if r["f2"] is not None else "     ?"
    f1cs = f"{r['f1_conf']:4.2f}" if r["f1_conf"] is not None else "   ?"
    f2cs = f"{r['f2_conf']:4.2f}" if r["f2_conf"] is not None else "   ?"
    pvs  = f"{r['pv']:6.1f}" if r["pv"] is not None else "  flag"
    print(f"{r['player']:<18} {r['cur']:>22} {r['atp']:>22} {f1s} {f1cs} {f2s} {f2cs} {r['games']:>5} {pvs}")

print()
print("  F1 = time-decayed weighted historical peak (lower = stronger)")
print("  F2 = confidence-adjusted current rank regressed toward ATP (lower = stronger)")
print("  F1c/F2c = confidence 0–1 (higher = more data, less regression)")
print()

# ── Case 1: Low F2 confidence — high regression to ATP ───────────────────────
low_conf = [r for r in rows if r["f2_conf"] is not None and r["f2_conf"] < 0.35]
if low_conf:
    print("=== LOW F2 CONFIDENCE (<0.35) — heavy regression toward ATP ===")
    for r in sorted(low_conf, key=lambda x: x["f2_conf"]):
        if r["f1"] is None or r["f2"] is None or r["cur_rs"] is None or r["atp_rs"] is None:
            continue
        raw_curr = r["cur_rs"]
        atp_pull = raw_curr - r["f2"]   # how much ATP regression pulled F2 below raw current
        print(f"  {r['player']:<18}  cur_rs={raw_curr:5.1f}  atp_rs={r['atp_rs']:5.1f}  "
              f"F2_conf={r['f2_conf']:.2f}  F2={r['f2']:5.1f}  ATP_pull={atp_pull:+5.1f}  games={r['games']}")
    print()

# ── Case 2: Large F1/F2 divergence — history vs. current disagree ────────────
diverg = [r for r in rows if r["f1"] is not None and r["f2"] is not None]
diverg.sort(key=lambda r: abs(r["f1"] - r["f2"]), reverse=True)
print("=== LARGEST F1/F2 DIVERGENCE (top 6) ===")
for r in diverg[:6]:
    delta = r["f1"] - r["f2"]
    label = "hist < curr (player improving)" if delta < 0 else "hist > curr (player declining / was stronger)"
    print(f"  {r['player']:<18}  F1={r['f1']:5.1f}  F2={r['f2']:5.1f}  Δ={delta:+5.1f}  ({label})")
print()

# ── Case 3: ATP much stronger than current ───────────────────────────────────
gap_players = [r for r in rows if r["cur_rs"] is not None and r["atp_rs"] is not None
               and (r["cur_rs"] - r["atp_rs"]) > 8]
if gap_players:
    print("=== SIGNIFICANT ATP→CURRENT DROP (gap > 8 pts, e.g. Challenger→Emerald) ===")
    for r in sorted(gap_players, key=lambda x: x["cur_rs"] - x["atp_rs"], reverse=True):
        gap = r["cur_rs"] - r["atp_rs"]
        print(f"  {r['player']:<18}  {r['atp']:>22} → {r['cur']:<22}  gap={gap:.1f}  F2={r['f2']:.1f}  F2c={r['f2_conf']:.2f}")
    print()

# ── Case 4: Sensitivity to N_threshold (brezzy / gumbee edge cases) ──────────
print("=== N_THRESHOLD SENSITIVITY — how F2 changes with different N values ===")
test_N = [50, 100, 150, 190, 250, 400]
interesting = [r["player"] for r in rows if r["f2_conf"] is not None and r["f2_conf"] < 0.5][:4]
print(f"  Players: {interesting}")
print(f"  {'Player':<18}", end="")
for n in test_N:
    print(f"  N={n:<3}", end="")
print()
print(f"  {'':18}", end="")
for n in test_N:
    lbl = "←cur" if n == N else ""
    print(f"  {'F2':>5}{lbl:<2}", end="")
print()

for pname in interesting:
    p = next((pl for pl in players if pl.effective_id == pname), None)
    if not p:
        continue
    print(f"  {pname:<18}", end="")
    for n in test_N:
        cpv_n = compute_pv(p, weights, n, config.round_id, config.current_lol_split, real_max, n_hist)
        f2    = cpv_n.features.adjusted_current_pts
        marker = "*" if n == N else " "
        print(f"  {f2:5.1f}{marker} ", end="")
    print()
print()

# ── Case 5: What if F2 regressed toward F1 instead of ATP? ───────────────────
print("=== F2 REGRESSION TARGET: ATP vs. F1 (current formula vs. alternative) ===")
print("  Current: F2 regresses toward player's all-time peak rank when confidence is low")
print("  Alt:     F2 regresses toward F1 (their weighted historical average)")
print()
print(f"  {'Player':<18} {'F2_vs_ATP':>9} {'F2_vs_F1':>9} {'delta_PV':>9}  note")
for r in sorted(rows, key=lambda x: abs((x["f1"] or 0) - (x["atp_rs"] or 0)), reverse=True)[:8]:
    if r["f1"] is None or r["atp_rs"] is None or r["cur_rs"] is None:
        continue
    conf     = r["f2_conf"] or 0.0
    f2_vs_atp = r["f2"]  # current formula
    f2_vs_f1  = conf * r["cur_rs"] + (1.0 - conf) * r["f1"]  # alt: regress toward F1
    if r["f1"] is None or f2_vs_atp is None:
        continue
    pv_curr   = r["pv"] or 0
    # Approximate alt PV (same weights, just swap F2)
    pv_alt    = round((r["f1"] + f2_vs_f1) / 2 + 10, 1)
    delta_pv  = pv_alt - pv_curr
    atp_vs_f1_gap = (r["atp_rs"] - r["f1"])  # negative = ATP stronger than F1 (ATP more optimistic)
    note      = "ATP >> F1 (ATP very generous)" if atp_vs_f1_gap < -5 else ("ATP ≈ F1" if abs(atp_vs_f1_gap) < 2 else "F1 >> ATP (F1 harsher)")
    print(f"  {r['player']:<18} {f2_vs_atp:9.2f} {f2_vs_f1:9.2f} {delta_pv:+9.1f}  {note}  (ATP_rs={r['atp_rs']:.1f} F1={r['f1']:.1f})")
print()
print("  Positive delta_PV = Alt PV is higher (weaker) — F1-regression is more conservative")
print("  Negative delta_PV = Alt PV is lower (stronger) — F1-regression is more generous")
