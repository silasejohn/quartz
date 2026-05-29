"""
Task: EXPORT_STATS — write pool overview stats to CSV and optionally push to Google Sheets.

Two-section layout:
  Section 1 — Captains + Mains
  Section 2 — Subs

Side-by-side column layout (A–L, 12 columns):
  A–B  Player Types (Type | Count)
  C    spacer
  D–F  Role Distribution (Role | Primary | Secondary)
  G    spacer
  H–I  Current Ranks (Tier | Count)
  J    spacer
  K–L  Peak Ranks (Tier | Count)
"""

import csv
import os
import re
from collections import defaultdict

from quartz.constants import APEX_RANKS, RANK_TIERS, ROLES
from quartz.player_registry import PlayerRegistry
from quartz.tournament_config import TournamentConfig
from quartz.utils.logging import error_print, success_print

_ROLE_ORDER = [r.upper() for r in ROLES]
_TIER_ORDER = list(reversed(RANK_TIERS))
_N_COLS     = 12
_GAP_ROWS   = 2


def _parse_rank(rank_str: str | None) -> tuple[str | None, int | None]:
    if not rank_str or rank_str.lower() == "unranked":
        return None, None
    m = re.match(r"^([A-Za-z]+)\s*(\d)?", rank_str.strip())
    if not m:
        return None, None
    tier = m.group(1).capitalize()
    if tier not in RANK_TIERS:
        return None, None
    div_str = m.group(2)
    return tier, int(div_str) if div_str else None


def _compute_section(profiles, season: str, type_filter: set[str]) -> dict:
    type_counts:      dict[str, int] = defaultdict(int)
    primary_counts:   dict[str, int] = defaultdict(int)
    secondary_counts: dict[str, int] = defaultdict(int)
    current_ranks: list[str | None] = []
    peak_ranks:    list[str | None] = []

    for profile in profiles:
        sd = next((s for s in profile.season_data if s.season == season), None)
        if sd is None or sd.player_type not in type_filter:
            continue
        type_counts[sd.player_type] += 1
        if sd.primary_pos:
            primary_counts[sd.primary_pos.upper()] += 1
        if sd.secondary_pos:
            secondary_counts[sd.secondary_pos.upper()] += 1
        if profile.stats:
            current_ranks.append(profile.stats.current_rank)
            peak_ranks.append(profile.stats.all_time_peak_rank)

    return {
        "type_counts":      dict(type_counts),
        "primary_counts":   dict(primary_counts),
        "secondary_counts": dict(secondary_counts),
        "current_ranks":    current_ranks,
        "peak_ranks":       peak_ranks,
        "n_players":        sum(type_counts.values()),
    }


def _type_col(type_counts: dict, type_filter: set[str]) -> list[list]:
    rows = [[pt, type_counts.get(pt, 0)] for pt in ["captain", "main", "sub"] if pt in type_filter]
    rows.append(["Total", sum(type_counts.values())])
    return rows


def _role_col(primary: dict, secondary: dict) -> list[list]:
    rows = [[role, primary.get(role, 0), secondary.get(role, 0)] for role in _ROLE_ORDER]
    rows.append(["Total", sum(primary.values()), sum(secondary.values())])
    return rows


def _rank_col(rank_list: list) -> list[list]:
    tier_counts: dict[str, int] = defaultdict(int)
    unranked = no_data = 0
    for r in rank_list:
        tier, _ = _parse_rank(r)
        if tier is None:
            if r and r.lower() != "unranked":
                no_data += 1
            else:
                unranked += 1
        else:
            tier_counts[tier] += 1
    rows = [[tier, tier_counts[tier]] for tier in _TIER_ORDER if tier in tier_counts]
    if unranked:
        rows.append(["Unranked", unranked])
    if no_data:
        rows.append(["No data", no_data])
    return rows


def build_section_rows(data: dict, label: str, type_filter: set[str]) -> list[list]:
    """Build the 12-column side-by-side row list for one pool section."""
    type_col = _type_col(data["type_counts"], type_filter)
    role_col = _role_col(data["primary_counts"], data["secondary_counts"])
    curr_col = _rank_col(data["current_ranks"])
    peak_col = _rank_col(data["peak_ranks"])

    n = max(len(type_col), len(role_col), len(curr_col), len(peak_col))

    header    = [f"{label}  ({data['n_players']} players)"] + [""] * (_N_COLS - 1)
    subheader = ["Type", "Count", "", "Role", "Primary", "Secondary", "",
                 "Current Rank", "Count", "", "Peak Rank", "Count"]
    rows = [header, subheader]

    for i in range(n):
        row = [""] * _N_COLS
        if i < len(type_col):
            row[0], row[1] = str(type_col[i][0]), type_col[i][1]
        if i < len(role_col):
            row[3], row[4], row[5] = str(role_col[i][0]), role_col[i][1], role_col[i][2]
        if i < len(curr_col):
            row[7], row[8] = str(curr_col[i][0]), curr_col[i][1]
        if i < len(peak_col):
            row[10], row[11] = str(peak_col[i][0]), peak_col[i][1]
        rows.append(row)

    return rows


def run(
    config: TournamentConfig,
    registry: PlayerRegistry,
    players: list[str] | None = None,
    push: bool = False,
) -> tuple[set[str], set[str]]:
    """
    [param] config:   TournamentConfig
    [param] registry: PlayerRegistry
    [param] players:  unused — always covers the full pool
    [param] push:     if True, push to sheets.stats_sheet_name in active_tournament.yaml
    """
    season   = config.round_id
    profiles = registry.load_all()

    data1 = _compute_section(profiles, season, {"captain", "main"})
    data2 = _compute_section(profiles, season, {"sub"})

    label1 = f"Captains + Mains — {config.tournament} {config.current_round}"
    label2 = f"Subs — {config.tournament} {config.current_round}"

    section1_rows = build_section_rows(data1, label1, {"captain", "main"})
    section2_rows = build_section_rows(data2, label2, {"sub"})

    filename = f"{config.tournament.lower()}_{config.current_round.lower()}_pool_stats.csv"
    out_path = os.path.join(config.abs_processed_dir, filename)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    all_rows = section1_rows + [[""] * _N_COLS] * _GAP_ROWS + section2_rows
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(all_rows)
    success_print(
        f"EXPORT_STATS: {data1['n_players']} captains/mains + {data2['n_players']} subs -> {out_path}"
    )

    if push:
        if not config.sheets or not config.sheets.stats_sheet_name:
            error_print("EXPORT_STATS --push: no 'sheets.stats_sheet_name' in active_tournament.yaml — skipping push")
        else:
            from quartz.utils.sheets_writer import SheetsWriter
            stats_writer = SheetsWriter(
                spreadsheet_id=config.sheets.spreadsheet_id,
                sheet_name=config.sheets.stats_sheet_name,
                credentials_path=config.sheets.credentials_path,
                token_path=config.sheets.token_path,
            )
            stats_writer.push_stats(section1_rows, section2_rows)

    return set(), set()
