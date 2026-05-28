"""
Champion name normalization — reconciles DPM.lol internal keys with display names.

DPM returns Riot's internal champion keys (CamelCase, no spaces or apostrophes).
OP.GG returns the official display names (spaces, apostrophes, periods).

Two utilities:
  normalize_champion_name(name) — convert a DPM key to display name for storage.
  champion_key(name)            — collapse to a lowercase alphanumeric key for comparison,
                                   so "MissFortune" and "Miss Fortune" resolve to the same entry.

Unknown multi-word names are written to data/raw/champion_name_review.json.
Any quartz command startup warns if that file has pending entries.
"""

import json
import re
from pathlib import Path

# Champions whose display names cannot be derived by simple CamelCase splitting.
# Key = DPM internal name, Value = official display name.
# Add new entries here when the startup warning flags an unmapped name.
_OVERRIDES: dict[str, str] = {
    "AurelionSol":    "Aurelion Sol",
    "Belveth":        "Bel'Veth",
    "Chogath":        "Cho'Gath",
    "DrMundo":        "Dr. Mundo",
    "FiddleSticks":   "Fiddlesticks",
    "JarvanIV":       "Jarvan IV",
    "Khazix":         "Kha'Zix",
    "KogMaw":         "Kog'Maw",
    "Kogmaw":         "Kog'Maw",
    "Leblanc":        "LeBlanc",
    "LeeSin":         "Lee Sin",
    "MasterYi":       "Master Yi",
    "MissFortune":    "Miss Fortune",
    "NunuWillump":    "Nunu & Willump",
    "RekSai":         "Rek'Sai",
    "TahmKench":      "Tahm Kench",
    "TwistedFate":    "Twisted Fate",
    "Velkoz":         "Vel'Koz",
    "VelKoz":         "Vel'Koz",
    "MonkeyKing":     "Wukong",
    "XinZhao":        "Xin Zhao",
}

_REVIEW_PATH = Path("data/raw/champion_name_review.json")  # NOSONAR


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize_champion_name(name: str) -> str:
    """Return the canonical display name for a champion.

    Handles DPM internal keys (CamelCase) and already-correct display names.
    Unknown multi-word names are flagged to the review file for manual confirmation.
    """
    if name in _OVERRIDES:
        _clear_from_review(name)
        return _OVERRIDES[name]

    normalized = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
    if normalized != name:
        # CamelCase transformation happened — flag it: may be missing apostrophe/period
        _add_to_review(name, guessed=normalized)

    return normalized


def champion_key(name: str) -> str:
    """Lowercase alphanumeric key for champion name comparison.

    "Miss Fortune", "MissFortune", "miss fortune" all → "missfortune".
    Used by get_champion() so merges work even for unresolved display names.
    """
    return re.sub(r"[^a-z0-9]", "", name.lower())


def check_champion_name_warnings() -> None:
    """Print a startup warning if any unmapped champion names need review.

    Called once at CLI startup. Clears entries that are now covered by _OVERRIDES.
    """
    pending = _load_review()
    if not pending:
        return

    # Auto-clear anything now covered by _OVERRIDES
    still_pending = {k: v for k, v in pending.items() if k not in _OVERRIDES}
    if len(still_pending) != len(pending):
        _save_review(still_pending)
        pending = still_pending

    if not pending:
        return

    print("\n  ┌─ CHAMPION NAME REVIEW NEEDED " + "─" * 30)
    print(f"  │  {len(pending)} DPM champion name(s) could not be auto-resolved.")
    print("  │  They may be missing apostrophes, periods, or other characters.")
    print("  │")
    for dpm_name, info in sorted(pending.items()):
        print(f"  │  DPM key : {dpm_name}")
        print(f"  │  Guessed : {info['guessed']}  (first seen {info['first_seen']})")
        print("  │")
    print("  │  Fix: open quartz/utils/champion_names.py and add the correct")
    print("  │  mapping to _OVERRIDES, then re-run your scrape.")
    print("  │  Example:  \"MissFortune\": \"Miss Fortune\",")
    print("  └" + "─" * 50)
    print()


# ---------------------------------------------------------------------------
# Internal — review file helpers
# ---------------------------------------------------------------------------

def _load_review() -> dict:
    if not _REVIEW_PATH.exists():
        return {}
    try:
        return json.loads(_REVIEW_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_review(data: dict) -> None:
    _REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REVIEW_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _add_to_review(dpm_name: str, guessed: str) -> None:
    from datetime import date
    pending = _load_review()
    if dpm_name not in pending:
        pending[dpm_name] = {"guessed": guessed, "first_seen": str(date.today())}
        _save_review(pending)


def _clear_from_review(dpm_name: str) -> None:
    pending = _load_review()
    if dpm_name in pending:
        del pending[dpm_name]
        _save_review(pending)
