"""
Shared CLI prompt and profile-filtering helpers.

Functions:
  confirm_batch_force(command, config)  -> None   (loud double-confirm before batch --force)
  prompt_season(round_ids)              -> str | None   (composite key e.g. "GCS-S4")
  prompt_player_types()                 -> set[str] | None
  filter_profiles(profiles, season, types) -> (scoped, type_scoped, scope_label, type_label)
  prompt_existing_player(registry, allow_skip) -> PlayerProfile | None
  prompt_from_matches(matches)          -> PlayerProfile   (pick from a known ambiguous list)
  resolve_players(registry, terms)     -> list[PlayerProfile] | None  (disambiguate each term)
"""

from quartz.constants import PLAYER_TYPES


def confirm_batch_destructive(
    confirm_word: str,
    config,
    *,
    full_command: str | None = None,
    action: str = "permanently overwritten",
    safer_hint: str | None = None,
) -> None:
    """Show a loud warning and require double confirmation before any batch destructive operation.

    Call this whenever an operation with no players specified will touch the entire roster.
    Aborts via typer.Exit(0) if the user does not pass both prompts.

    [param] confirm_word:  the word the user must type in confirm #2, e.g. "opgg" or "rank"
    [param] config:        TournamentConfig — used to count profiles and accounts
    [param] full_command:  display string for the command line, e.g. "quartz scrape opgg --force"
                           (defaults to "quartz scrape {confirm_word} --force")
    [param] action:        verb phrase describing what happens, e.g. "permanently overwritten"
                           or "permanently deleted"
    [param] safer_hint:    optional single-player example shown as the safer alternative
    """
    import typer
    from rich.markup import escape

    from quartz.player_registry import PlayerRegistry
    from quartz.utils.logging import console

    registry = PlayerRegistry(config.abs_players_dir)
    all_profiles = registry.load_all()
    active_accounts = sum(1 for p in all_profiles for a in p.accounts if not a.archived)
    profile_count = len(all_profiles)

    display_cmd = full_command or f"quartz scrape {confirm_word} --force"
    default_hint = f"quartz scrape {confirm_word} PLAYER_NAME --force"

    console.print()
    console.print(f"  [bold red]{'!' * 62}[/bold red]")
    console.print("  [bold red]!!  BATCH OPERATION — THIS AFFECTS THE ENTIRE ROSTER  !![/bold red]")
    console.print(f"  [bold red]{'!' * 62}[/bold red]")
    console.print()
    console.print(f"  Command  : [bold]{escape(display_cmd)}[/bold]")
    console.print(f"  Scope    : [bold red]{profile_count} profiles · {active_accounts} active accounts[/bold red]")
    console.print()
    console.print(f"  Scraped data for [bold]every account[/bold] will be [bold red]{escape(action)}[/bold red].")
    console.print("  There is [bold red]no undo[/bold red].")
    console.print()
    console.print("  To target a single player instead (safer), run:")
    console.print(f"  [dim]  {escape(safer_hint or default_hint)}[/dim]")
    console.print()

    first = typer.prompt("  Confirm #1 — type 'yes' to continue")
    if first.strip().lower() != "yes":
        console.print("\n  [yellow]Aborted.[/yellow]\n")
        raise typer.Exit(0)

    second = typer.prompt(f"  Confirm #2 — type '{confirm_word}' to confirm")
    if second.strip().lower() != confirm_word.lower():
        console.print("\n  [yellow]Aborted.[/yellow]\n")
        raise typer.Exit(0)

    console.print()
    console.print(f"  [bold yellow]Confirmed. Proceeding on all {active_accounts} accounts...[/bold yellow]")
    console.print()


def confirm_batch_force(command: str, config) -> None:
    """Convenience wrapper for scrape --force batch confirmation."""
    confirm_batch_destructive(
        confirm_word=command,
        config=config,
        full_command=f"quartz scrape {command} --force",
        action="permanently overwritten",
        safer_hint=f"quartz scrape {command} PLAYER_NAME --force",
    )


def prompt_season(round_ids: list[str]) -> str | None:
    """
    Ask which tournament round to scope results to.
    Returns a composite round ID (e.g. "GCS-S4") or None for all rounds.
    """
    options = round_ids + ["All"]
    print("\n  Season filter:")
    for i, opt in enumerate(options, 1):
        print(f"    {i}. {opt}")
    while True:
        raw = input("  > ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            val = options[int(raw) - 1]
            return None if val == "All" else val
        if raw.lower() == "all":
            return None
        if raw in options:
            return None if raw == "All" else raw
        print(f"    Invalid — enter a number 1–{len(options)} or type the season.")


def prompt_player_types() -> set[str] | None:
    """
    Ask which player types to include.
    Returns a set of type strings, or None meaning all types.
    Accepts comma-separated numbers or names, e.g. "1,2" or "main,sub".
    """
    type_options = PLAYER_TYPES + ["All"]
    print("\n  Player type filter:")
    for i, opt in enumerate(type_options, 1):
        print(f"    {i}. {opt}")
    print("  Enter one or more (comma-separated), e.g. '2,3' or 'main,sub'")
    while True:
        raw = input("  > ").strip()
        if not raw:
            continue
        if raw.lower() == "all" or raw == str(len(type_options)):
            return None

        parts = [p.strip() for p in raw.split(",")]
        selected = set()
        valid = True
        for part in parts:
            if part.isdigit() and 1 <= int(part) <= len(type_options):
                val = type_options[int(part) - 1]
                if val == "All":
                    return None
                selected.add(val)
            elif part.lower() in [t.lower() for t in type_options]:
                val = next(t for t in type_options if t.lower() == part.lower())
                if val == "All":
                    return None
                selected.add(val)
            else:
                print(f"    Unrecognized: '{part}' — enter numbers or type names.")
                valid = False
                break
        if valid and selected:
            return selected


def filter_profiles(
    profiles: list,
    season_filter: str | None,
    type_filter: set[str] | None,
) -> tuple[list, list, str, str]:
    """
    Apply season and player-type filters to a list of PlayerProfile objects.

    Returns (scoped, type_scoped, scope_label, type_label):
      scoped       — profiles matching season_filter (all profiles if None)
      type_scoped  — scoped profiles also matching type_filter (same as scoped if None)
      scope_label  — display string e.g. "GCS-S4" or "All Seasons"
      type_label   — display string e.g. "main, sub" or "All"
    """
    if season_filter:
        scoped = [p for p in profiles if any(sd.season == season_filter for sd in p.season_data)]
        scope_label = season_filter
    else:
        scoped = list(profiles)
        scope_label = "All Seasons"

    type_label = ", ".join(sorted(type_filter)) if type_filter else "All"

    def _matches_type(profile) -> bool:
        if not type_filter:
            return True
        if season_filter:
            sd = next((s for s in profile.season_data if s.season == season_filter), None)
            return sd is not None and sd.player_type in type_filter
        return any(sd.player_type in type_filter for sd in profile.season_data)

    type_scoped = [p for p in scoped if _matches_type(p)]
    return scoped, type_scoped, scope_label, type_label


def prompt_existing_player(registry, allow_skip: bool = False):
    """
    Interactive player lookup: numbered list + partial match.

    [param] registry:    PlayerRegistry instance
    [param] allow_skip:  if True, blank input returns None (caller can create new player)
                         if False, blank re-prompts until a valid player is chosen

    Returns a PlayerProfile if found, or None if allow_skip=True and user pressed Enter.
    """
    ids = sorted(registry.player_ids())
    print("\n  Players:")
    for i, pid in enumerate(ids, 1):
        print(f"    {i:>3}. {pid}")

    skip_hint = " (Enter to add new player)" if allow_skip else ""
    print()

    while True:
        raw = input(f"  Enter player name or number{skip_hint}: ").strip()

        if not raw:
            if allow_skip:
                return None
            continue

        if raw.isdigit() and 1 <= int(raw) <= len(ids):
            return registry.load(ids[int(raw) - 1])

        matches = [pid for pid in ids if raw.lower() in pid.lower()]
        if len(matches) == 1:
            return registry.load(matches[0])
        if len(matches) > 1:
            print(f"  Multiple matches: {', '.join(matches)}")
            continue

        if allow_skip:
            print(f"  No player found matching '{raw}' — press Enter to create new, or try again.")
        else:
            print(f"  Not found: '{raw}'")


def prompt_from_matches(matches: list) -> object:
    """
    Disambiguate when a search term matched multiple profiles.
    Shows the matches as a numbered list and prompts until the user picks one.

    [param] matches: list of PlayerProfile objects (2+)
    Returns a single PlayerProfile.
    """
    print("\n  Multiple matches — pick one:")
    for i, p in enumerate(matches, 1):
        print(f"    {i}. {p.effective_id}")
    print()
    while True:
        raw = input("  > ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(matches):
            return matches[int(raw) - 1]
        hits = [p for p in matches if raw.lower() in p.effective_id.lower()]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            print(f"  Still ambiguous: {', '.join(p.effective_id for p in hits)}")
        else:
            print(f"  Not in list — enter a number 1–{len(matches)}.")


def resolve_player_arg(registry, player_arg: "str | None") -> "object | None":
    """
    Resolve an optional CLI player argument to a single PlayerProfile.

    - player_arg given: find_profiles match → Exit(1) if none, prompt if ambiguous.
    - player_arg None: falls back to interactive prompt_existing_player.

    Returns a PlayerProfile, or None if the interactive prompt was skipped.
    """
    import typer
    if player_arg:
        matches = registry.find_profiles([player_arg])
        if not matches:
            typer.echo(f"No player found matching '{player_arg}'")
            raise typer.Exit(1)
        if len(matches) > 1:
            return prompt_from_matches(matches)
        return matches[0]
    return prompt_existing_player(registry)


def resolve_players(registry, terms: list[str]) -> "list | None":
    """
    Resolve a list of search terms to a deduplicated list of PlayerProfile objects.
    When a single term matches multiple profiles, prompts the user to pick one.
    Returns None if any term matches zero profiles.

    [param] registry: PlayerRegistry
    [param] terms:    list of discord_usernames or partial names from CLI args
    """
    resolved = []
    seen_ids = set()
    for term in terms:
        matches = registry.find_profiles([term])
        if not matches:
            print(f"  No player found matching '{term}'")
            return None
        if len(matches) == 1:
            profile = matches[0]
        else:
            print(f"  '{term}' matches {len(matches)} players:")
            profile = prompt_from_matches(matches)
        if profile.effective_id not in seen_ids:
            resolved.append(profile)
            seen_ids.add(profile.effective_id)
    return resolved
