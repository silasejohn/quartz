import os
import subprocess
from pathlib import Path

import typer
import yaml

from quartz import paths
from quartz.tournament_registry import TournamentRegistry, TournamentRegistryError, slugify

app = typer.Typer(help="Create, list, and select Quartz tournaments.", no_args_is_help=True)


def _registry() -> TournamentRegistry:
    return TournamentRegistry()


def _handle_error(exc: TournamentRegistryError) -> None:
    raise typer.BadParameter(str(exc)) from exc


@app.command("create")
def create(
    name: str,
    from_file: Path | None = typer.Option(None, "--from", help="Create from an existing tournament YAML."),
    data_dir: Path | None = typer.Option(None, help="Absolute or XDG-data-relative tournament data directory."),
):
    """Create a tournament definition stub."""
    try:
        path = _registry().create(name, from_file=from_file, data_dir=data_dir)
    except TournamentRegistryError as exc:
        _handle_error(exc)
    typer.echo(f"Created tournament '{slugify(name)}' at {path}")


@app.command("list")
def list_tournaments():
    """List registered tournaments."""
    registry = _registry()
    active = registry.active_name()
    names = registry.list()
    if not names:
        typer.echo("No tournaments registered. Run 'quartz tournament create NAME'.")
        return

    for name in names:
        marker = "*" if name == active else " "
        typer.echo(f"{marker} {name}")


@app.command("show")
def show(name: str | None = None):
    """Show a tournament YAML definition."""
    registry = _registry()
    selected = name or registry.active_name()
    if not selected:
        raise typer.BadParameter("No active tournament. Run 'quartz tournament use NAME'.")
    try:
        data = registry.read_yaml(selected)
    except TournamentRegistryError as exc:
        _handle_error(exc)
    typer.echo(yaml.safe_dump(data, sort_keys=False))


@app.command("use")
def use(name: str):
    """Select the active tournament."""
    try:
        _registry().use(name)
    except TournamentRegistryError as exc:
        _handle_error(exc)
    typer.echo(f"Active tournament: {slugify(name)}")


@app.command("edit")
def edit(name: str | None = None):
    """Open a tournament YAML file in $EDITOR, or print the path if unset."""
    registry = _registry()
    selected = name or registry.active_name()
    if not selected:
        raise typer.BadParameter("No active tournament. Run 'quartz tournament use NAME'.")
    path = registry.tournament_path(selected)
    if not path.exists():
        raise typer.BadParameter(f"Unknown tournament '{slugify(selected)}'.")

    editor = os.environ.get("EDITOR")
    if not editor:
        typer.echo(str(path))
        return
    subprocess.run([editor, str(path)], check=True)


@app.command("rename")
def rename(old: str, new: str):
    """Rename a registered tournament."""
    try:
        path = _registry().rename(old, new)
    except TournamentRegistryError as exc:
        _handle_error(exc)
    typer.echo(f"Renamed tournament to '{slugify(new)}' at {path}")


@app.command("remove")
def remove(name: str, purge_data: bool = typer.Option(False, help="Also delete this tournament's data directory.")):
    """Remove a tournament from the registry."""
    try:
        _registry().remove(name, purge_data=purge_data)
    except TournamentRegistryError as exc:
        _handle_error(exc)
    typer.echo(f"Removed tournament '{slugify(name)}'")


@app.command("import")
def import_tournament(path: Path, use: bool = typer.Option(False, "--use", help="Select the imported tournament.")):
    """Import an existing tournament YAML file."""
    try:
        target = _registry().import_yaml(path, use=use)
    except TournamentRegistryError as exc:
        _handle_error(exc)
    typer.echo(f"Imported tournament at {target}")


@app.command("export")
def export_tournament(name: str, dest: Path):
    """Export a registered tournament YAML file."""
    try:
        target = _registry().export_yaml(name, dest)
    except TournamentRegistryError as exc:
        _handle_error(exc)
    typer.echo(f"Exported tournament to {target}")


@app.command("path")
def path(
    name: str | None = None,
    data: bool = typer.Option(False, "--data", help="Print the tournament data directory."),
    config: bool = typer.Option(False, "--config", help="Print the tournament config file."),
):
    """Print config or data paths for scripting."""
    registry = _registry()
    selected = name or registry.active_name()
    if not selected:
        raise typer.BadParameter("No active tournament. Run 'quartz tournament use NAME'.")
    if data and config:
        raise typer.BadParameter("Choose only one of --data or --config.")
    if config:
        typer.echo(registry.tournament_path(selected))
        return
    if data or not config:
        try:
            typer.echo(registry.data_dir_for(selected))
        except TournamentRegistryError as exc:
            _handle_error(exc)


@app.command("locations")
def locations():
    """Print Quartz's platform-specific storage locations."""
    typer.echo(f"config: {paths.config_dir()}")
    typer.echo(f"data:   {paths.data_dir()}")
    typer.echo(f"state:  {paths.state_dir()}")
    typer.echo(f"cache:  {paths.cache_dir()}")
