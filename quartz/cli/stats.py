"""quartz stats — roster summary stats."""

import re
from collections import defaultdict

from quartz.cli.filters import filter_profiles, prompt_player_types, prompt_season
from quartz.constants import APEX_RANKS, PLAYER_TYPES, RANK_TIERS, ROLES
from quartz.player_registry import PlayerRegistry
from quartz.tournament_config import load_active_tournament


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


_TIER_ORDER = list(reversed(RANK_TIERS))


def _rank_section(title: str, rank_list: list[str | None]) -> None:
    print(f"\n  {title}")
    print(f"  {'─' * 50}")
    tier_div: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    unranked_count = no_data_count = 0

    for r in rank_list:
        tier, div = _parse_rank(r)
        if tier is None:
            if r and r.lower() != "unranked":
                no_data_count += 1
            else:
                unranked_count += 1
        else:
            tier_div[tier][div] += 1

    for tier in _TIER_ORDER:
        if tier not in tier_div:
            continue
        divs  = tier_div[tier]
        total = sum(divs.values())
        if tier in APEX_RANKS:
            print(f"  {tier:<12} ({total:>2})")
        else:
            detail = "  ".join(
                f"{tier[0]}{div}:{divs[div]}"
                for div in sorted(divs.keys())
                if divs[div] > 0
            )
            print(f"  {tier:<12} ({total:>2}):  {detail}")

    if unranked_count:
        print(f"  {'Unranked':<12} ({unranked_count:>2})")
    if no_data_count:
        print(f"  {'No data':<12} ({no_data_count:>2})")


def stats():
    """Roster summary stats — player types, roles, rank distributions."""
    config   = load_active_tournament()
    registry = PlayerRegistry(config.abs_players_dir)
    profiles = registry.load_all()

    season_filter = prompt_season(config.round_ids)
    type_filter   = prompt_player_types()
    scoped, rank_scoped, scope_label, type_label = filter_profiles(profiles, season_filter, type_filter)

    print(f"\n{'=' * 56}")
    print(f"  {config.tournament} Player Stats — {scope_label}  ({len(scoped)} players)")
    print(f"  Type filter: {type_label}  ({len(rank_scoped)} players)")
    print(f"{'=' * 56}")

    # Section 1 — Player Types
    type_counts: dict[str, int] = defaultdict(int)
    for p in scoped:
        sd = (
            next((s for s in p.season_data if s.season == season_filter), None)
            if season_filter
            else (p.season_data[-1] if p.season_data else None)
        )
        if sd:
            type_counts[sd.player_type] += 1

    print("\n  Player Types")
    print(f"  {'─' * 30}")
    for pt in PLAYER_TYPES:
        count = type_counts.get(pt, 0)
        print(f"  {pt:<10}  {count:>3}  {'#' * count}")
    print(f"  {'─' * 30}")
    print(f"  {'Total':<10}  {sum(type_counts.values()):>3}")

    # Section 2 — Positions
    primary_counts:   dict[str, int] = defaultdict(int)
    secondary_counts: dict[str, int] = defaultdict(int)
    for p in rank_scoped:
        sd = (
            next((s for s in p.season_data if s.season == season_filter), None)
            if season_filter
            else (p.season_data[-1] if p.season_data else None)
        )
        if sd:
            if sd.primary_pos:
                primary_counts[sd.primary_pos.upper()] += 1
            if sd.secondary_pos:
                secondary_counts[sd.secondary_pos.upper()] += 1

    roles  = [r.upper() for r in ROLES]
    col_w  = 8
    print("\n  Positions")
    print(f"  {'─' * 38}")
    print(f"  {'Role':<8}  {'Primary':>{col_w}}  {'Secondary':>{col_w}}")
    print(f"  {'─' * 38}")
    for role in roles:
        print(f"  {role:<8}  {primary_counts.get(role, 0):>{col_w}}  {secondary_counts.get(role, 0):>{col_w}}")
    print(f"  {'─' * 38}")
    print(f"  {'Total':<8}  {sum(primary_counts.values()):>{col_w}}  {sum(secondary_counts.values()):>{col_w}}")

    # Enrichment coverage
    no_peak    = [p for p in rank_scoped if not (p.stats and p.stats.all_time_peak_rank)]
    no_current = [p for p in rank_scoped if not (p.stats and p.stats.current_rank)]
    print(f"\n  Enrichment Coverage  ({len(rank_scoped)} players in rank filter)")
    print(f"  {'─' * 40}")
    print(f"  Missing peak rank:    {len(no_peak):>3}  —  {', '.join(p.effective_id for p in no_peak) or 'none'}")
    print(f"  Missing current rank: {len(no_current):>3}  —  {', '.join(p.effective_id for p in no_current) or 'none'}")

    # Section 3 — Peak Ranks
    peak_ranks = [
        p.stats.all_time_peak_rank if (p.stats and p.stats.all_time_peak_rank) else None
        for p in rank_scoped
    ]
    _rank_section("Peak Ranks (all-time, enriched only)", peak_ranks)

    # Section 4 — Current Ranks
    current_ranks = [
        p.stats.current_rank if (p.stats and p.stats.current_rank) else None
        for p in rank_scoped
    ]
    _rank_section("Current Ranks (current LoL season, enriched only)", current_ranks)
    print()
