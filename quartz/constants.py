"""
Quartz — Shared Constants
Single source of truth for all standardized LoL values used across the pipeline.
Import from here, never redefine elsewhere.

Note on naming:
  LOL_RANKED_SEASONS / SEASON_ORDER  — LoL ranked season labels (S2026, S2025, etc.)
  Tournament rounds (S1, S4, etc.)   — defined per-tournament in active_tournament.yaml,
                                       NOT here. Use quartz.tournament_config.load_tournament_config().
"""

import re
from typing import Optional

# ============================================================
# ROLES
# ============================================================

ROLES = ["TOP", "JGL", "MID", "BOT", "SUP"]

ROLE_ALIASES = {
    "TOP": "TOP", "TOPLANE": "TOP", "TOP LANE": "TOP",
    "TOPLANER": "TOP", "BARON": "TOP", "1": "TOP",
    "JGL": "JGL", "JG": "JGL", "JNG": "JGL", "JUNGLE": "JGL",
    "JUNGLER": "JGL", "JUNG": "JGL", "2": "JGL",
    "MID": "MID", "MIDDLE": "MID", "MID LANE": "MID",
    "MIDLANE": "MID", "MIDLANER": "MID", "3": "MID",
    "BOT": "BOT", "BOTTOM": "BOT", "BOT LANE": "BOT",
    "BOTLANE": "BOT", "ADC": "BOT", "CARRY": "BOT", "4": "BOT",
    "SUP": "SUP", "SUPPORT": "SUP", "SUPP": "SUP",
    "UTILITY": "SUP", "UTIL": "SUP", "5": "SUP",
}

# ============================================================
# RANKS
# ============================================================

RANK_ORDER = [
    "Iron 4",     "Iron 3",     "Iron 2",     "Iron 1",
    "Bronze 4",   "Bronze 3",   "Bronze 2",   "Bronze 1",
    "Silver 4",   "Silver 3",   "Silver 2",   "Silver 1",
    "Gold 4",     "Gold 3",     "Gold 2",     "Gold 1",
    "Platinum 4", "Platinum 3", "Platinum 2", "Platinum 1",
    "Emerald 4",  "Emerald 3",  "Emerald 2",  "Emerald 1",
    "Diamond 4",  "Diamond 3",  "Diamond 2",  "Diamond 1",
    "Master",     "Grandmaster", "Challenger",
]

APEX_RANKS = ["Master", "Grandmaster", "Challenger"]

METAL_RANKS = [r for r in RANK_ORDER if r.split(" ")[0] not in APEX_RANKS]

RANK_TIERS = [
    "Iron", "Bronze", "Silver", "Gold", "Platinum",
    "Emerald", "Diamond", "Master", "Grandmaster", "Challenger",
]

RANK_POINTS = {
    "Iron 4": 85,       "Iron 3": 85,       "Iron 2": 85,       "Iron 1": 85,
    "Bronze 4": 83.1,   "Bronze 3": 81.2,   "Bronze 2": 79.2,   "Bronze 1": 77.2,
    "Silver 4": 75.2,   "Silver 3": 73.1,   "Silver 2": 71,     "Silver 1": 68.1,
    "Gold 4": 66.6,     "Gold 3": 64.4,     "Gold 2": 62.1,     "Gold 1": 59.7,
    "Platinum 4": 57.3, "Platinum 3": 54.8, "Platinum 2": 52.3, "Platinum 1": 49.6,
    "Emerald 4": 46.8,  "Emerald 3": 44,    "Emerald 2": 41,    "Emerald 1": 37.8,
    "Diamond 4": 34.5,  "Diamond 3": 30.9,  "Diamond 2": 27,    "Diamond 1": 22.7,
    "Master": 17.8,     "Grandmaster": 11.8, "Challenger": 0,
    # Tier-only averages (when only tier is known, no division)
    "Iron": 85,     "Bronze": 80.2,  "Silver": 72.05, "Gold": 63.25,
    "Platinum": 53.55, "Emerald": 42.5, "Diamond": 28.95,
}

RANK_ALIASES = {
    "I4": "Iron 4",     "I3": "Iron 3",     "I2": "Iron 2",     "I1": "Iron 1",
    "B4": "Bronze 4",   "B3": "Bronze 3",   "B2": "Bronze 2",   "B1": "Bronze 1",
    "S4": "Silver 4",   "S3": "Silver 3",   "S2": "Silver 2",   "S1": "Silver 1",
    "G4": "Gold 4",     "G3": "Gold 3",     "G2": "Gold 2",     "G1": "Gold 1",
    "P4": "Platinum 4", "P3": "Platinum 3", "P2": "Platinum 2", "P1": "Platinum 1",
    "E4": "Emerald 4",  "E3": "Emerald 3",  "E2": "Emerald 2",  "E1": "Emerald 1",
    "D4": "Diamond 4",  "D3": "Diamond 3",  "D2": "Diamond 2",  "D1": "Diamond 1",
    "M":  "Master",     "GM": "Grandmaster", "C": "Challenger",
    "Plat 4": "Platinum 4", "Plat 3": "Platinum 3",
    "Plat 2": "Platinum 2", "Plat 1": "Platinum 1",
    "Plat": "Platinum",
    "Masters": "Master",
    "GrandMaster": "Grandmaster",
    "Unranked": "Unranked", "UNRANKED": "Unranked", "N/A": "Unranked", "": "Unranked",
    "IV": "4", "III": "3", "II": "2",
}

# ============================================================
# LOL RANKED SEASONS
# ============================================================

# Ordered most-recent-first — used for current rank lookup and PV decay weighting
SEASON_ORDER = [
    "S2026",
    "S2025",
    "S2024 S3", "S2024 S2", "S2024 S1",
    "S2023 S2", "S2023 S1",
    "S2022", "S2021", "S2020",
    "S8", "S7", "S6", "S5", "S4", "S3", "S2", "S1",
]

# Splits that count as "past year" for Feature 1 historical decay
PAST_YEAR_SEASONS = ["S2025", "S2024 S3", "S2024 S2", "S2024 S1"]

# Maps OP.GG season label strings to our SEASON_ORDER keys
SEASON_LABEL_MAP = {
    "S2026": "S2026", "S2025": "S2025",
    "S2024 S3": "S2024 S3", "S2024 S2": "S2024 S2", "S2024 S1": "S2024 S1",
    "S2023 S2": "S2023 S2", "S2023 S1": "S2023 S1",
    "S2022": "S2022", "S2021": "S2021", "S2020": "S2020",
    "Season 8": "S8",  "S8": "S8",
    "Season 7": "S7",  "S7": "S7",
    "Season 6": "S6",  "S6": "S6",
    "Season 5": "S5",  "S5": "S5",
    "Season 4": "S4",  "S4": "S4",
    "Season 3": "S3",  "S3": "S3",
    "Season 2": "S2",  "S2": "S2",
    "Season 1": "S1",  "S1": "S1",
    "2026 S1": "S2026", "2025 S1": "S2025",
    "2024 S3": "S2024 S3", "2024 S2": "S2024 S2", "2024 S1": "S2024 S1",
    "2023 S2": "S2023 S2", "2023 S1": "S2023 S1",
    "2022": "S2022", "2021": "S2021", "2020": "S2020",
    "Split 1 2026": "S2026", "Split 1 2025": "S2025",
    "Split 3 2024": "S2024 S3", "Split 2 2024": "S2024 S2", "Split 1 2024": "S2024 S1",
    "Split 2 2023": "S2023 S2", "Split 1 2023": "S2023 S1",
    "Season 2026 Split 1": "S2026", "Season 2025 Split 1": "S2025",
    "Season 2024 Split 3": "S2024 S3", "Season 2024 Split 2": "S2024 S2",
    "Season 2024 Split 1": "S2024 S1",
    "Season 2023 Split 2": "S2023 S2", "Season 2023 Split 1": "S2023 S1",
}

# Backwards-compat alias
OPGG_SEASON_LABEL_MAP = SEASON_LABEL_MAP

PAST_2_YEARS_SEASONS = SEASON_ORDER

# Splits from S2024 S3 onward have a distinct peak rank on OP.GG
PEAK_RANK_EXPECTED_FROM = "S2024 S3"
PEAK_RANK_SEASONS = SEASON_ORDER[:SEASON_ORDER.index(PEAK_RANK_EXPECTED_FROM) + 1]

# ============================================================
# RANK SCORING
# ============================================================

def rank_score(rank_str: Optional[str]) -> Optional[float]:
    """
    Numeric score for a canonical rank string. Lower score = better rank.

    Non-apex ranks: LP is interpolated between this rank and the next better rank.
    Apex ranks: LP is unbounded, use lp / 100.

    Returns None for unrecognized or empty strings.
    """
    if not rank_str:
        return None
    lp_match = re.search(r'(\d+)\s*LP', rank_str)
    lp = int(lp_match.group(1)) if lp_match else 0
    rank_only = re.sub(r'\s*\d+\s*LP', '', rank_str).strip()
    if rank_only not in RANK_POINTS:
        return None
    base = RANK_POINTS[rank_only]
    if rank_only in APEX_RANKS:
        return base - lp / 100
    if rank_only in RANK_ORDER:
        idx = RANK_ORDER.index(rank_only)
        if idx + 1 < len(RANK_ORDER):
            next_better = RANK_ORDER[idx + 1]
            range_pts = base - RANK_POINTS[next_better]
            return base - lp * (range_pts / 100)
    return base

# ============================================================
# PLAYER TYPES
# ============================================================

PLAYER_TYPES = ["captain", "main", "sub", "other"]

# ============================================================
# DATA SOURCES
# ============================================================

SOURCES = {
    "CSV_LOCAL":  "csv_local",
    "CSV_REMOTE": "csv_remote",
    "OPGG":       "opgg",
    "DPM":        "dpm",
    "RIOT_API":   "riot_api",
    "LOG":        "log",
    "REWIND_LOL": "rewind_lol",
}
