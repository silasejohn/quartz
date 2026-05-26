"""Filesystem locations for Quartz config, data, state, and cache.

Quartz follows platform conventions instead of storing mutable files in the
repository root. On Linux, XDG environment variables are honored:

- XDG_CONFIG_HOME, defaulting to ~/.config
- XDG_DATA_HOME, defaulting to ~/.local/share
- XDG_STATE_HOME, defaulting to ~/.local/state
- XDG_CACHE_HOME, defaulting to ~/.cache

macOS and Windows use their conventional application support locations.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "quartz"


def _home() -> Path:
    return Path.home()


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    if not value:
        return None
    return Path(value).expanduser()


def config_dir() -> Path:
    if sys.platform == "darwin":
        return _ensure(_home() / "Library" / "Application Support" / APP_NAME)
    if sys.platform == "win32":
        base = _env_path("APPDATA") or (_home() / "AppData" / "Roaming")
        return _ensure(base / APP_NAME)
    base = _env_path("XDG_CONFIG_HOME") or (_home() / ".config")
    return _ensure(base / APP_NAME)


def data_dir() -> Path:
    if sys.platform == "darwin":
        return _ensure(_home() / "Library" / "Application Support" / APP_NAME)
    if sys.platform == "win32":
        base = _env_path("LOCALAPPDATA") or (_home() / "AppData" / "Local")
        return _ensure(base / APP_NAME)
    base = _env_path("XDG_DATA_HOME") or (_home() / ".local" / "share")
    return _ensure(base / APP_NAME)


def state_dir() -> Path:
    if sys.platform == "darwin":
        return _ensure(_home() / "Library" / "Application Support" / APP_NAME)
    if sys.platform == "win32":
        base = _env_path("LOCALAPPDATA") or (_home() / "AppData" / "Local")
        return _ensure(base / APP_NAME)
    base = _env_path("XDG_STATE_HOME") or (_home() / ".local" / "state")
    return _ensure(base / APP_NAME)


def cache_dir() -> Path:
    if sys.platform == "darwin":
        return _ensure(_home() / "Library" / "Caches" / APP_NAME)
    if sys.platform == "win32":
        base = _env_path("LOCALAPPDATA") or (_home() / "AppData" / "Local")
        return _ensure(base / APP_NAME / "Cache")
    base = _env_path("XDG_CACHE_HOME") or (_home() / ".cache")
    return _ensure(base / APP_NAME)


def tournaments_dir() -> Path:
    return _ensure(config_dir() / "tournaments")


def state_file() -> Path:
    return state_dir() / "state.yaml"


def tournament_data_dir(name: str) -> Path:
    return _ensure(data_dir() / name)
