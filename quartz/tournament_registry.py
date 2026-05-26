"""CLI-managed tournament registry stored in platform config/state dirs."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from quartz import paths

STATE_SCHEMA_VERSION = 1


class TournamentRegistryError(RuntimeError):
    """Raised when tournament registry operations cannot be completed."""


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if not slug:
        raise TournamentRegistryError("Tournament name must contain at least one letter or number.")
    return slug


class TournamentRegistry:
    def __init__(self) -> None:
        self.tournaments_dir = paths.tournaments_dir()
        self.state_file = paths.state_file()

    def list(self) -> list[str]:
        return sorted(path.stem for path in self.tournaments_dir.glob("*.yaml"))

    def tournament_path(self, name: str) -> Path:
        return self.tournaments_dir / f"{slugify(name)}.yaml"

    def state(self) -> dict[str, Any]:
        if not self.state_file.exists():
            return {"schema_version": STATE_SCHEMA_VERSION, "active": None}

        with open(self.state_file, "r") as f:
            data = yaml.safe_load(f) or {}

        return {"schema_version": data.get("schema_version", STATE_SCHEMA_VERSION), "active": data.get("active")}

    def write_state(self, state: dict[str, Any]) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": STATE_SCHEMA_VERSION, "active": state.get("active")}
        with open(self.state_file, "w") as f:
            yaml.safe_dump(payload, f, sort_keys=False)

    def active_name(self) -> str | None:
        active = self.state().get("active")
        return str(active) if active else None

    def use(self, name: str) -> None:
        name = slugify(name)
        if not self.tournament_path(name).exists():
            raise TournamentRegistryError(f"Unknown tournament '{name}'. Run 'quartz tournament list'.")
        self.write_state({"active": name})

    def read_yaml(self, name: str) -> dict[str, Any]:
        path = self.tournament_path(name)
        if not path.exists():
            raise TournamentRegistryError(
                f"Unknown tournament '{slugify(name)}'. Run 'quartz tournament list' or import one first."
            )

        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise TournamentRegistryError(f"Tournament file must contain a mapping: {path}")
        data["name"] = slugify(str(data.get("name") or path.stem))
        return data

    def write_yaml(self, name: str, data: dict[str, Any]) -> Path:
        name = slugify(name)
        payload = dict(data)
        payload["name"] = name
        path = self.tournament_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.safe_dump(payload, f, sort_keys=False)
        return path

    def create(self, name: str, *, from_file: str | Path | None = None, data_dir: str | Path | None = None) -> Path:
        name = slugify(name)
        path = self.tournament_path(name)
        if path.exists():
            raise TournamentRegistryError(f"Tournament '{name}' already exists at {path}.")

        if from_file:
            with open(Path(from_file).expanduser().resolve(), "r") as f:
                payload = yaml.safe_load(f) or {}
            if not isinstance(payload, dict):
                raise TournamentRegistryError("Imported tournament file must contain a mapping.")
        else:
            display = name.replace("-", " ").title()
            payload = {
                "name": name,
                "display_name": display,
                "tournament": display,
                "current_lol_split": "S2026",
                "tournament_rounds": ["S1"],
                "current_round": "S1",
                "raw_csv": "raw/players.csv",
                "captain_slots": [],
            }

        if data_dir is not None:
            payload["data_dir"] = str(Path(data_dir).expanduser())

        return self.write_yaml(name, payload)

    def import_yaml(self, source: str | Path, *, use: bool = False) -> Path:
        source_path = Path(source).expanduser().resolve()
        with open(source_path, "r") as f:
            payload = yaml.safe_load(f) or {}
        if not isinstance(payload, dict):
            raise TournamentRegistryError("Imported tournament file must contain a mapping.")

        name = slugify(str(payload.get("name") or payload.get("display_name") or payload.get("tournament") or source_path.stem))
        path = self.write_yaml(name, payload)
        if use:
            self.use(name)
        return path

    def export_yaml(self, name: str, dest: str | Path) -> Path:
        source = self.tournament_path(name)
        if not source.exists():
            raise TournamentRegistryError(f"Unknown tournament '{slugify(name)}'.")
        dest_path = Path(dest).expanduser().resolve()
        if dest_path.is_dir():
            dest_path = dest_path / source.name
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest_path)
        return dest_path

    def rename(self, old: str, new: str) -> Path:
        old = slugify(old)
        new = slugify(new)
        old_path = self.tournament_path(old)
        new_path = self.tournament_path(new)
        if not old_path.exists():
            raise TournamentRegistryError(f"Unknown tournament '{old}'.")
        if new_path.exists():
            raise TournamentRegistryError(f"Tournament '{new}' already exists.")

        with open(old_path, "r") as f:
            payload = yaml.safe_load(f) or {}
        payload["name"] = new
        with open(new_path, "w") as f:
            yaml.safe_dump(payload, f, sort_keys=False)
        old_path.unlink()

        if self.active_name() == old:
            self.use(new)
        return new_path

    def remove(self, name: str, *, purge_data: bool = False) -> None:
        name = slugify(name)
        path = self.tournament_path(name)
        if not path.exists():
            raise TournamentRegistryError(f"Unknown tournament '{name}'.")
        data_dir = self.data_dir_for(name)
        path.unlink()
        if self.active_name() == name:
            self.write_state({"active": None})
        if purge_data and data_dir.exists():
            shutil.rmtree(data_dir)

    def data_dir_for(self, name: str) -> Path:
        data = self.read_yaml(name)
        configured = data.get("data_dir")
        if configured:
            path = Path(str(configured)).expanduser()
            if path.is_absolute():
                path.mkdir(parents=True, exist_ok=True)
                return path
            path = paths.data_dir() / path
            path.mkdir(parents=True, exist_ok=True)
            return path
        return paths.tournament_data_dir(slugify(name))
