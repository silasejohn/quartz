"""quartz flags — view and manage account flags."""

from typing import Optional

import typer

from quartz.player_registry import PlayerRegistry
from quartz.tournament_config import load_tournament_config
from quartz.utils.logging import success_print, warning_print

app = typer.Typer(help="View and manage account flags.")


def _load_registry() -> tuple:
    config = load_tournament_config()
    registry = PlayerRegistry(config.abs_players_dir)
    return config, registry


def _resolve_account(registry: PlayerRegistry, player: str, riot_id: str):
    """Return (profile, account) or raise typer.Exit on failure."""
    matches = registry.find_profiles([player])
    if not matches:
        typer.echo(f"No player found matching '{player}'.")
        raise typer.Exit(1)
    if len(matches) > 1:
        typer.echo(f"Ambiguous player '{player}': {', '.join(p.effective_id for p in matches)}")
        raise typer.Exit(1)
    profile = matches[0]
    riot_id_lower = riot_id.lower()
    account = next(
        (a for a in profile.accounts if riot_id_lower in a.riot_id.lower()),
        None,
    )
    if account is None:
        ids = ", ".join(a.riot_id for a in profile.accounts)
        typer.echo(f"No account matching '{riot_id}' on {profile.effective_id}. Accounts: {ids}")
        raise typer.Exit(1)
    return profile, account


@app.command("list")
def flags_list(
    all_flags: bool = typer.Option(False, "--all", help="Include dismissed flags."),
) -> None:
    """List account flags across all players."""
    _, registry = _load_registry()
    profiles = registry.load_all()

    any_shown = False
    for profile in sorted(profiles, key=lambda p: p.effective_id.lower()):
        for account in profile.accounts:
            visible = account.flags if all_flags else [f for f in account.flags if not f.dismissed]
            if not visible:
                continue
            any_shown = True
            typer.echo(f"\n{profile.effective_id}  /  {account.riot_id}")
            for flag in visible:
                tag = f"[{flag.flag_type.upper()}]"
                if flag.dismissed:
                    tag += " [DISMISSED]"
                src = "auto" if flag.auto else "manual"
                detail = f"  {flag.detail}" if flag.detail else ""
                typer.echo(f"  {tag} ({src}){detail}")

    if not any_shown:
        typer.echo("No flags found." if all_flags else "No active flags. Use --all to include dismissed.")


@app.command("add")
def flags_add(
    player: str = typer.Argument(..., help="Player name (substring of discord ID)."),
    riot_id: str = typer.Argument(..., help="Account riot ID (substring match)."),
    flag_type: str = typer.Argument(..., help="Flag type, e.g. smurf_peak, low_level, name_changed."),
    detail: Optional[str] = typer.Option(None, "--detail", help="Optional detail text."),
) -> None:
    """Add a manual flag to a specific account."""
    _, registry = _load_registry()
    profile, account = _resolve_account(registry, player, riot_id)

    from quartz.models.player_profile import AccountFlag
    account.flags.append(AccountFlag(flag_type=flag_type, detail=detail, auto=False, dismissed=False))
    profile.touch()
    registry.save(profile)
    success_print(f"Added manual flag [{flag_type.upper()}] to {account.riot_id} ({profile.effective_id}).")


@app.command("dismiss")
def flags_dismiss(
    player: str = typer.Argument(..., help="Player name (substring of discord ID)."),
    riot_id: str = typer.Argument(..., help="Account riot ID (substring match)."),
    flag_type: str = typer.Argument(..., help="Flag type to dismiss."),
) -> None:
    """Dismiss a flag on a specific account (marks as false positive; keeps it visible)."""
    _, registry = _load_registry()
    profile, account = _resolve_account(registry, player, riot_id)

    target = account.get_flag(flag_type)
    if target is None:
        warning_print(f"No flag of type '{flag_type}' found on {account.riot_id}.")
        raise typer.Exit(1)

    target.dismissed = True
    profile.touch()
    registry.save(profile)
    success_print(f"Dismissed [{flag_type.upper()}] on {account.riot_id} ({profile.effective_id}).")
