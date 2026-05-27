"""quartz manage — interactively add or update a player profile (TUI)."""

import re
from typing import Optional

import typer

from quartz.cli.filters import prompt_existing_player, resolve_player_arg
from quartz.signup_sheet_adapter import sanitize_riot_id
from quartz.constants import (
    PLAYER_TYPES,
    RANK_ALIASES,
    RANK_ORDER,
    ROLE_ALIASES,
    ROLES,
    SEASON_ORDER,
)
from quartz.models.player_profile import Account, AccountURL, ManualAdjustment, PlayerProfile, SeasonData
from quartz.models.rank_data import AccountRankData, SplitRankEntry
from quartz.pipeline_runner import PipelineRunner, Task
from quartz.player_registry import PlayerRegistry
from quartz.tournament_config import TournamentConfig, load_tournament_config
from quartz.utils.logging import info_print, success_print, warning_print

# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

def ask(label: str, required: bool = True) -> str:
    while True:
        val = input(f"  {label}: ").strip()
        if val:
            return val
        if not required:
            return ""
        print("    Required — please enter a value.")


def ask_choice(label: str, options: list[str]) -> str:
    print(f"\n  {label}:")
    for i, opt in enumerate(options, 1):
        print(f"    {i:>2}. {opt}")
    while True:
        raw = input("  > ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        if raw in options:
            return raw
        upper = raw.upper()
        if upper in ROLE_ALIASES:
            val = ROLE_ALIASES[upper]
            if val in options:
                return val
        print(f"    Invalid — enter a number 1-{len(options)} or type the value exactly.")


def ask_rank(label: str, required: bool = True) -> str | None:
    hint = "e.g. Gold 4 / G4 / Platinum 1 / P1 / Master / Unranked"
    while True:
        raw = input(f"  {label} ({hint}): ").strip()
        if not raw:
            if not required:
                return "Unranked"
            print("    Required.")
            continue

        if raw.lower() in ("unranked", "n/a", "none"):
            return "Unranked"

        aliased = RANK_ALIASES.get(raw) or RANK_ALIASES.get(raw.title())
        candidate = aliased if aliased else raw.title()
        if candidate in RANK_ORDER or candidate == "Unranked":
            return candidate

        print(f"    Unrecognized rank '{raw}'.")
        print("    Valid tiers: Iron / Bronze / Silver / Gold / Platinum / Emerald / Diamond / Master / Grandmaster / Challenger")
        print("    Divisions: 1-4 (e.g. 'Gold 4')  |  Short codes: G4, P1, E2, D1, M, GM, C")


def ask_rank_full(label: str, required: bool = False) -> str | None:
    """Like ask_rank() but also accepts LP inline — e.g. 'E4 98 LP'."""
    hint = "e.g. Gold 4 / G4 / E4 98 LP / Master 120 LP / blank to skip"
    while True:
        raw = input(f"  {label} ({hint}): ").strip()
        if not raw:
            if not required:
                return None
            print("    Required.")
            continue

        if raw.lower() in ("unranked", "n/a", "none", "skip", "-"):
            return None

        lp = None
        lp_match = re.search(r'\b(\d+)\s*(?:LP|lp)?\s*$', raw)
        rank_part = raw
        if lp_match:
            potential_lp = int(lp_match.group(1))
            candidate_rank = raw[:lp_match.start()].strip()
            aliased = RANK_ALIASES.get(candidate_rank) or RANK_ALIASES.get(candidate_rank.title())
            resolved = aliased if aliased else candidate_rank.title()
            if resolved in RANK_ORDER or resolved == "Unranked":
                lp = potential_lp
                rank_part = candidate_rank

        aliased = RANK_ALIASES.get(rank_part) or RANK_ALIASES.get(rank_part.title())
        candidate = aliased if aliased else rank_part.title()

        if candidate in RANK_ORDER or candidate == "Unranked":
            if lp is not None:
                return f"{candidate} {lp} LP"
            return candidate

        print(f"    Unrecognized rank '{rank_part}'.")
        print("    Valid tiers: Iron / Bronze / Silver / Gold / Platinum / Emerald / Diamond / Master / Grandmaster / Challenger")
        print("    Short codes: G4, P1, E2, D1, M, GM, C  |  Add LP: 'E4 98 LP'")


def ask_riot_id() -> tuple[str, str]:
    print("\n  Riot ID format: GameName#Tag   or   (EUW)GameName#Tag for non-NA")
    while True:
        raw = input("  Riot ID: ").strip()
        if not raw:
            print("    Required.")
            continue

        region = "NA"
        entry  = raw
        if entry.startswith("("):
            close = entry.find(")")
            if close != -1:
                region = entry[1:close].upper()
                entry  = entry[close + 1:].strip()

        if "#" not in entry:
            print("    Invalid — Riot ID must include '#' (e.g. PlayerName#NA1).")
            continue

        return sanitize_riot_id(entry), region


def ask_accounts() -> list[dict]:
    accounts = []
    print("\n  Riot ID(s) — one per line, blank when done.")
    print("  Format: GameName#Tag   or   (EUW)GameName#Tag for non-NA")
    while True:
        raw = input(f"  Account {len(accounts) + 1}: ").strip()
        if not raw:
            if not accounts:
                print("    At least one account required.")
                continue
            break

        region = "NA"
        entry  = raw
        if entry.startswith("("):
            close = entry.find(")")
            if close != -1:
                region = entry[1:close].upper()
                entry  = entry[close + 1:].strip()

        if "#" not in entry:
            print("    Invalid — Riot ID must include '#' (e.g. PlayerName#NA1).")
            continue

        accounts.append({"riot_id": entry, "player_region": region})
        info_print(f"    Added: {entry} ({region})")

    return accounts


# ---------------------------------------------------------------------------
# Core entry + save
# ---------------------------------------------------------------------------

def collect_row() -> dict:
    print()
    discord = ask("Discord Username")

    player_type = ask_choice("Player type", options=PLAYER_TYPES)

    peak_rank    = ask_rank("Stated Peak Rank   ", required=False)
    current_rank = ask_rank("Stated Current Rank", required=False)

    primary_role   = ask_choice("Primary Role",   options=ROLES)
    secondary_role = ask_choice("Secondary Role", options=ROLES)

    accounts = ask_accounts()

    return {
        "discord_username":     discord,
        "player_type_override": player_type if player_type != "main" else None,
        "accounts":             accounts,
        "stated_peak_rank":     peak_rank,
        "stated_current_rank":  current_rank,
        "primary_role":         primary_role,
        "secondary_role":       secondary_role,
    }


def apply_row(registry: PlayerRegistry, row: dict, season: str) -> None:
    discord = row["discord_username"]

    if registry.exists(discord):
        profile = registry.load(discord)
        changed = False

        new_season = SeasonData(
            season=season,
            player_type=row.get("player_type_override") or "main",
            primary_pos=row.get("primary_role"),
            secondary_pos=row.get("secondary_role"),
            stated_current_rank=row.get("stated_current_rank"),
            stated_peak_rank=row.get("stated_peak_rank"),
        )
        existing_season = next((sd for sd in profile.season_data if sd.season == season), None)
        if existing_season is None or existing_season.model_dump() != new_season.model_dump():
            profile.upsert_season(new_season)
            changed = True

        existing_by_id = {a.riot_id: a for a in profile.accounts}
        csv_riot_ids   = {a["riot_id"] for a in row.get("accounts", []) if a.get("riot_id")}

        for acc_data in row.get("accounts", []):
            rid = acc_data.get("riot_id")
            if not rid:
                continue
            if rid in existing_by_id:
                acc = existing_by_id[rid]
                if acc.archived or acc.player_region != acc_data["player_region"]:
                    acc.archived = False
                    acc.player_region = acc_data["player_region"]
                    changed = True
            else:
                profile.accounts.append(Account(riot_id=rid, player_region=acc_data["player_region"]))
                changed = True

        for acc in profile.accounts:
            if acc.riot_id not in csv_riot_ids and not acc.archived:
                acc.archived = True
                changed = True

        if changed:
            profile.touch()
            registry.save(profile)
            success_print(f"  Updated: {profile.effective_id}")
        else:
            info_print(f"  No changes: {profile.effective_id}")
    else:
        profile = PlayerProfile.from_csv_row(row, season)
        registry.save(profile)
        success_print(f"  Created: {profile.effective_id}")


# ---------------------------------------------------------------------------
# Action 1 — Add new account
# ---------------------------------------------------------------------------

def _ask_splits_loop() -> list[SplitRankEntry]:
    splits: list[SplitRankEntry] = []
    added_seasons: set[str] = set()

    while True:
        print("\n  Seasons — enter number to add split data, blank when done:")
        for i, s in enumerate(SEASON_ORDER, 1):
            tag = "  (added)" if s in added_seasons else ""
            print(f"    {i:>3}. {s}{tag}")

        raw = input("  > ").strip()
        if not raw or raw.lower() == "done":
            break

        if raw.isdigit() and 1 <= int(raw) <= len(SEASON_ORDER):
            season_key = SEASON_ORDER[int(raw) - 1]
        elif raw in SEASON_ORDER:
            season_key = raw
        else:
            print(f"    Invalid — enter a number 1-{len(SEASON_ORDER)} or the season key.")
            continue

        print(f"\n  Adding data for {season_key}:")
        peak_rank  = ask_rank_full("  Peak Rank      ")
        split_rank = ask_rank_full("  Split/End Rank ")

        wins_raw   = input("  Wins   (blank to skip): ").strip()
        losses_raw = input("  Losses (blank to skip): ").strip()
        wins   = int(wins_raw)   if wins_raw.isdigit()   else None
        losses = int(losses_raw) if losses_raw.isdigit() else None
        win_rate = round(wins / (wins + losses) * 100, 1) if wins and losses else None

        entry = SplitRankEntry(
            season=season_key,
            peak_rank=peak_rank,
            split_rank=split_rank,
            wins=wins,
            losses=losses,
            win_rate=win_rate,
        )
        splits = [s for s in splits if s.season != season_key]
        splits.append(entry)
        added_seasons.add(season_key)
        info_print(f"    {season_key}  peak={peak_rank or '—'}  end={split_rank or '—'}")

    return splits


def add_account_manual(profile, registry: PlayerRegistry) -> None:
    riot_id, region = ask_riot_id()
    archived_raw = input("  Archived (banned/inactive)? [y/N]: ").strip().lower()
    archived = archived_raw == "y"

    splits = _ask_splits_loop()

    rank_data = AccountRankData(splits=splits, source="manual") if splits else None
    new_account = Account(
        riot_id=riot_id,
        player_region=region,
        archived=archived,
        rank_data=rank_data,
    )

    print()
    info_print(f"  Riot ID:   {riot_id} ({region})")
    info_print(f"  Archived:  {archived}")
    info_print(f"  Splits:    {len(splits)} entered")
    for s in splits:
        info_print(f"    {s.season:<14}  peak={s.peak_rank or '—':<24}  end={s.split_rank or '—'}")

    confirm = input("\n  Save account? [y/N]: ").strip().lower()
    if confirm != "y":
        info_print("  Skipped.")
        return

    profile.accounts.append(new_account)
    profile.touch()
    registry.save(profile)
    success_print(f"  Account added to {profile.effective_id}")


def add_account_automated(profile, registry: PlayerRegistry, config: TournamentConfig) -> None:
    riot_id, region = ask_riot_id()
    archived_raw = input("  Archived (banned/inactive)? [y/N]: ").strip().lower()
    archived = archived_raw == "y"
    opgg_url = input("  OP.GG URL (blank to skip): ").strip() or None

    new_account = Account(
        riot_id=riot_id,
        player_region=region,
        archived=archived,
        urls=AccountURL(opgg_url=opgg_url),
    )

    print()
    info_print(f"  Riot ID:   {riot_id} ({region})")
    info_print(f"  Archived:  {archived}")
    if opgg_url:
        info_print(f"  OP.GG URL: {opgg_url}")

    confirm = input("\n  Save account and run OP.GG scraper? [y/N]: ").strip().lower()
    if confirm != "y":
        info_print("  Skipped.")
        return

    profile.accounts.append(new_account)
    profile.touch()
    registry.save(profile)
    success_print(f"  Account added to {profile.effective_id}")

    if not archived:
        info_print("  Running OP.GG scraper...")
        runner = PipelineRunner(config)
        runner.run_task(Task.OPGG_SCRAPE_RANK, players=[profile.effective_id])
    else:
        info_print("  Account is archived — skipping scraper.")


def replace_account_riot_id(profile, registry: PlayerRegistry, config: TournamentConfig) -> None:
    accounts = profile.accounts
    if not accounts:
        warning_print("  No accounts on this profile.")
        return

    print(f"\n  Accounts on {profile.effective_id}:")
    for i, a in enumerate(accounts, 1):
        status = "[archived] " if a.archived else ""
        flag_note = "  [name_changed]" if any(f.flag_type == "name_changed" and not f.dismissed for f in a.flags) else ""
        print(f"    {i:>2}. {status}{a.riot_id} ({a.player_region}){flag_note}")

    while True:
        raw = input("\n  Select account number to rename (or q to cancel): ").strip()
        if raw.lower() == "q":
            info_print("  Cancelled.")
            return
        if raw.isdigit() and 1 <= int(raw) <= len(accounts):
            break
        print(f"    Enter a number 1-{len(accounts)}.")

    account = accounts[int(raw) - 1]
    old_riot_id = account.riot_id
    old_region  = account.player_region

    print(f"\n  Current:  {old_riot_id} ({old_region})")
    new_riot_id, new_region = ask_riot_id()

    old_opgg = account.urls.opgg_url if account.urls else None
    print(f"\n  Current OP.GG URL: {old_opgg or '(none)'}")
    new_opgg_raw = input("  New OP.GG URL (blank to keep current, 'clear' to remove): ").strip()
    if new_opgg_raw.lower() == "clear":
        new_opgg = None
    elif new_opgg_raw:
        new_opgg = new_opgg_raw
    else:
        new_opgg = old_opgg

    print()
    info_print(f"  Old Riot ID:  {old_riot_id} ({old_region})")
    info_print(f"  New Riot ID:  {new_riot_id} ({new_region})")
    if new_opgg != old_opgg:
        info_print(f"  OP.GG URL:    {new_opgg or '(cleared)'}")

    confirm = input("\n  Save rename? [y/N]: ").strip().lower()
    if confirm != "y":
        info_print("  Cancelled.")
        return

    account.riot_id       = new_riot_id
    account.player_region = new_region
    if account.urls is None:
        from quartz.models.player_profile import AccountURL as _AccountURL
        account.urls = _AccountURL()
    account.urls.opgg_url = new_opgg

    # Dismiss any existing name_changed flags — the rename resolves them
    for f in account.flags:
        if f.flag_type == "name_changed" and not f.dismissed:
            f.dismissed = True

    profile.touch()
    registry.save(profile)
    success_print(f"  Renamed {old_riot_id} → {new_riot_id} on {profile.effective_id}")

    if not account.archived:
        run_scrape = input("\n  Run OP.GG scraper for the renamed account? [y/N]: ").strip().lower()
        if run_scrape == "y":
            info_print("  Running OP.GG scraper...")
            runner = PipelineRunner(config)
            runner.run_task(Task.OPGG_SCRAPE_RANK, players=[profile.effective_id])


def update_existing_accounts_automated(profile, registry: PlayerRegistry, config: TournamentConfig) -> None:
    active   = [a for a in profile.accounts if not a.archived]
    archived = [a for a in profile.accounts if a.archived]

    if not active:
        warning_print("  No active accounts on this profile — nothing to scrape.")
        if archived:
            warning_print(f"  ({len(archived)} archived account(s) skipped.)")
        return

    print()
    info_print(f"  Accounts to scrape ({len(active)}):")
    for a in active:
        info_print(f"    {a.riot_id} ({a.player_region})")
    if archived:
        info_print(f"  Skipping {len(archived)} archived account(s).")

    confirm = input("\n  Run OP.GG scraper for all active accounts? [y/N]: ").strip().lower()
    if confirm != "y":
        info_print("  Skipped.")
        return

    info_print("  Running OP.GG scraper...")
    runner = PipelineRunner(config)
    runner.run_task(Task.OPGG_SCRAPE_RANK, players=[profile.effective_id])
    success_print(f"  OP.GG scrape complete for {profile.effective_id}")


# ---------------------------------------------------------------------------
# Action 2 — Add new tournament season
# ---------------------------------------------------------------------------

def add_tournament_season(profile, registry: PlayerRegistry, config: TournamentConfig) -> None:
    season = ask_choice("Tournament season", options=config.tournament_rounds)

    existing = next((sd for sd in profile.season_data if sd.season == season), None)
    if existing:
        warning_print(f"  Season {season} already exists on this profile.")
        overwrite = input("  Overwrite? [y/N]: ").strip().lower()
        if overwrite != "y":
            info_print("  Cancelled.")
            return

    player_type    = ask_choice("Player type",    options=PLAYER_TYPES)
    primary_role   = ask_choice("Primary Role",   options=ROLES)
    secondary_role = ask_choice("Secondary Role", options=ROLES)
    peak_rank      = ask_rank("Stated Peak Rank   ", required=False)
    current_rank   = ask_rank("Stated Current Rank", required=False)

    new_season = SeasonData(
        season=season,
        player_type=player_type,
        primary_pos=primary_role,
        secondary_pos=secondary_role,
        stated_peak_rank=peak_rank,
        stated_current_rank=current_rank,
    )

    print()
    info_print(f"  Season:       {season}")
    info_print(f"  Player type:  {player_type}")
    info_print(f"  Roles:        {primary_role} / {secondary_role}")
    info_print(f"  Peak rank:    {peak_rank}")
    info_print(f"  Current rank: {current_rank}")

    confirm = input("\n  Save? [y/N]: ").strip().lower()
    if confirm != "y":
        info_print("  Skipped.")
        return

    profile.upsert_season(new_season)
    profile.touch()
    registry.save(profile)
    success_print(f"  Season {season} saved to {profile.effective_id}")


# ---------------------------------------------------------------------------
# Action 3 — Manage manual adjustments
# ---------------------------------------------------------------------------

_ADJUSTMENT_CATEGORIES = [
    ("inhouse_modifier",         "In-House performance bonus"),
    ("region_modifier",          "Region adjustment"),
    ("admin_modifier",           "Admin discretionary bonus"),
    ("previous_winner_modifier", "Previous tournament winner bonus"),
]


def _resolve_season_entry(profile, action_label: str, config: TournamentConfig):
    season = ask_choice(f"Tournament season for {action_label}?", options=config.tournament_rounds)
    entry = next((sd for sd in profile.season_data if sd.season == season), None)
    if entry is None:
        warning_print(f"  Season {season} not found on this profile.")
        warning_print("  Add it first via [3] Add new tournament season.")
    return entry


def manage_adjustments(profile, registry: PlayerRegistry, config: TournamentConfig) -> None:
    season_entry = _resolve_season_entry(profile, "adjustments", config)
    if season_entry is None:
        return
    season = season_entry.season

    values: dict[str, float]      = {cat: 0.0  for cat, _ in _ADJUSTMENT_CATEGORIES}
    notes:  dict[str, str | None] = {cat: None for cat, _ in _ADJUSTMENT_CATEGORIES}
    for adj in season_entry.manual_adjustments:
        if adj.category in values:
            values[adj.category] = adj.value
            notes[adj.category]  = adj.note

    original_values = dict(values)
    original_notes  = dict(notes)

    while True:
        print(f"\n  {profile.effective_id} / {season} — Manual Adjustments")
        print(f"  {'─'*58}")
        for i, (cat, desc) in enumerate(_ADJUSTMENT_CATEGORIES, 1):
            val = values[cat]
            note_str = f"  ({notes[cat]})" if notes[cat] else ""
            val_str = f"{val:.1f}" if val != 0.0 else "0.0"
            print(f"  {i}.  {cat:<28}  {val_str:<8}  {desc}{note_str}")
        print(f"  {'─'*58}")
        print("  s.  Save and exit")
        print("  q.  Quit without saving")

        raw = input("\n  > ").strip().lower()

        if raw == "q":
            print("  Cancelled — no changes saved.")
            return
        if raw == "s":
            break

        if not raw.isdigit() or not 1 <= int(raw) <= len(_ADJUSTMENT_CATEGORIES):
            print(f"  Enter a number 1-{len(_ADJUSTMENT_CATEGORIES)}, 's', or 'q'.")
            continue

        idx = int(raw) - 1
        cat, desc = _ADJUSTMENT_CATEGORIES[idx]
        print(f"\n  {cat}  (current: {values[cat]:.1f})")

        while True:
            val_raw = input("  new value (positive = reduces PV, 0 to clear) > ").strip()
            try:
                new_val = float(val_raw)
                break
            except ValueError:
                print("  Enter a number (e.g. 5.0 or 0 to clear).")

        if new_val != 0.0:
            note_raw = input("  Note (optional, blank to skip) > ").strip()
            notes[cat] = note_raw or None
        else:
            notes[cat] = None

        values[cat] = new_val
        note_str = f"  ({notes[cat]})" if notes[cat] else ""
        print(f"  {cat}  ->  {new_val:.1f}{note_str}")

    if values == original_values and notes == original_notes:
        info_print("  No changes.")
        return

    season_entry.manual_adjustments = [
        ManualAdjustment(category=cat, value=values[cat], note=notes[cat])
        for cat, _ in _ADJUSTMENT_CATEGORIES
        if values[cat] != 0.0
    ]
    profile.touch()
    registry.save(profile)
    total = sum(v for v in values.values() if v != 0.0)
    success_print(f"  Saved — total PV reduction: {total:.1f}")


# ---------------------------------------------------------------------------
# Action 4 — Enter in-house data
# ---------------------------------------------------------------------------

def enter_inhouse_data(profile, registry: PlayerRegistry, config: TournamentConfig) -> None:
    season_entry = _resolve_season_entry(profile, "in-house data", config)
    if season_entry is None:
        return
    season = season_entry.season

    if season_entry.inhouse_wins is not None and season_entry.inhouse_losses is not None:
        cur_w = season_entry.inhouse_wins
        cur_l = season_entry.inhouse_losses
        cur_n = cur_w + cur_l
        cur_wr = round(cur_w / cur_n * 100, 1) if cur_n > 0 else 0.0
        info_print(f"  Current record: {cur_w}W / {cur_l}L  ({cur_n} games, {cur_wr}% WR)")
    else:
        info_print("  Current record: (none)")

    while True:
        raw = input("  Wins: ").strip()
        if raw.isdigit():
            wins = int(raw)
            break
        print("    Enter a non-negative integer.")

    while True:
        raw = input("  Losses: ").strip()
        if raw.isdigit():
            losses = int(raw)
            break
        print("    Enter a non-negative integer.")

    total = wins + losses
    wr = round(wins / total * 100, 1) if total > 0 else 0.0

    from quartz.models.pv_model import PVWeights
    from quartz.pv_compute import _wilson_lower
    wlb = _wilson_lower(wins, total) if total > 0 else 0.0

    print()
    info_print(f"  {wins}W / {losses}L  ({total} games, {wr}% WR)")
    info_print(f"  Wilson LB (95%):  {wlb:.4f}  {'qualifies for modifier' if total >= PVWeights().min_games_threshold and wlb > 0.5 else '— no modifier (below threshold or <50% WLB)'}")

    confirm = input("\n  Save? [y/N]: ").strip().lower()
    if confirm != "y":
        info_print("  Skipped.")
        return

    season_entry.inhouse_wins   = wins
    season_entry.inhouse_losses = losses
    profile.touch()
    registry.save(profile)
    success_print(f"  In-house record saved: {wins}W / {losses}L for {profile.effective_id} / {season}")


# ---------------------------------------------------------------------------
# Typer entry point
# ---------------------------------------------------------------------------

def manage():
    """Interactively add or update a player profile (TUI)."""
    config   = load_tournament_config()
    registry = PlayerRegistry(config.abs_players_dir)
    season   = config.round_id

    print(f"\n=== Manual Player Entry  (season: {season}) ===")
    print("Ctrl+C at any time to quit.\n")

    while True:
        try:
            profile = prompt_existing_player(registry, allow_skip=True)

            if profile:
                action = ask_choice(
                    f"Player found: {profile.effective_id}. What would you like to do?",
                    ["Add new account", "Replace account Riot ID",
                     "Update existing accounts (OP.GG scraper)",
                     "Add new tournament season", "Manage adjustments",
                     "Enter in-house data", "New Player Profile"],
                )

                if action == "Update existing accounts (OP.GG scraper)":
                    update_existing_accounts_automated(profile, registry, config)

                elif action == "Replace account Riot ID":
                    replace_account_riot_id(profile, registry, config)

                elif action == "Add new account":
                    sub = ask_choice(
                        "Account entry method",
                        ["Manual entry", "Automated Info Retrieval (OP.GG scraper)"],
                    )
                    if sub == "Manual entry":
                        add_account_manual(profile, registry)
                    else:
                        add_account_automated(profile, registry, config)

                elif action == "Add new tournament season":
                    add_tournament_season(profile, registry, config)

                elif action == "Manage adjustments":
                    manage_adjustments(profile, registry, config)

                elif action == "Enter in-house data":
                    enter_inhouse_data(profile, registry, config)

                else:  # New Player Profile
                    row = collect_row()
                    print()
                    info_print(f"  Discord:      {row['discord_username']}")
                    info_print(f"  Player type:  {row['player_type_override'] or 'main'}")
                    info_print(f"  Peak rank:    {row['stated_peak_rank']}")
                    info_print(f"  Current rank: {row['stated_current_rank']}")
                    info_print(f"  Roles:        {row['primary_role']} / {row['secondary_role']}")
                    for a in row["accounts"]:
                        info_print(f"  Account:      {a['riot_id']} ({a['player_region']})")
                    confirm = input("\n  Save? [y/N]: ").strip().lower()
                    if confirm == "y":
                        apply_row(registry, row, season)
                    else:
                        info_print("  Skipped.")

            else:
                row = collect_row()
                print()
                info_print(f"  Discord:      {row['discord_username']}")
                info_print(f"  Player type:  {row['player_type_override'] or 'main'}")
                info_print(f"  Peak rank:    {row['stated_peak_rank']}")
                info_print(f"  Current rank: {row['stated_current_rank']}")
                info_print(f"  Roles:        {row['primary_role']} / {row['secondary_role']}")
                for a in row["accounts"]:
                    info_print(f"  Account:      {a['riot_id']} ({a['player_region']})")
                confirm = input("\n  Save? [y/N]: ").strip().lower()
                if confirm == "y":
                    apply_row(registry, row, season)
                else:
                    info_print("  Skipped.")

        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            break

        try:
            another = input("\n  Continue? [y/N]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            break
        if another != "y":
            break

    print("\nDone.")


def delete(
    player: Optional[str] = typer.Argument(None, help="Player ID or partial name to delete"),
):
    """Permanently delete a player profile from the registry."""
    config   = load_tournament_config()
    registry = PlayerRegistry(config.abs_players_dir)

    profile = resolve_player_arg(registry, player)

    if not profile:
        typer.echo("No player selected.")
        raise typer.Exit(1)

    accounts_str = ", ".join(a.riot_id for a in profile.accounts) or "no accounts"
    print(f"\n  {profile.effective_id}  ({accounts_str})")
    confirmed = typer.confirm("\n  Delete this player? This cannot be undone.", default=False)
    if not confirmed:
        typer.echo("Aborted.")
        raise typer.Exit(0)

    registry.delete(profile)
    success_print(f"Deleted {profile.effective_id}")
