import os
import sys
from pathlib import Path

from quartz import paths

APP_NAME = paths.APP_NAME
PLATFORM_ATTR = "platform"
CONFIG_DIR_NAME = "config"
DATA_DIR_NAME = "data"
STATE_DIR_NAME = "state"
CACHE_DIR_NAME = "cache"
MACOS_LIBRARY_DIR = "Library"
WINDOWS_APP_DATA_DIR = "AppData"
WINDOWS_LOCAL_DIR = "Local"
WINDOWS_ROAMING_DIR = "Roaming"


def test_xdg_paths_use_environment_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, PLATFORM_ATTR, "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / CONFIG_DIR_NAME))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / DATA_DIR_NAME))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / STATE_DIR_NAME))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / CACHE_DIR_NAME))

    assert paths.config_dir() == tmp_path / CONFIG_DIR_NAME / APP_NAME
    assert paths.data_dir() == tmp_path / DATA_DIR_NAME / APP_NAME
    assert paths.state_dir() == tmp_path / STATE_DIR_NAME / APP_NAME
    assert paths.cache_dir() == tmp_path / CACHE_DIR_NAME / APP_NAME
    assert paths.tournaments_dir() == tmp_path / CONFIG_DIR_NAME / APP_NAME / "tournaments"
    assert paths.state_file() == tmp_path / STATE_DIR_NAME / APP_NAME / "state.yaml"
    assert paths.tournament_data_dir("gcs-s4") == tmp_path / DATA_DIR_NAME / APP_NAME / "gcs-s4"


def test_macos_paths_use_application_support(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, PLATFORM_ATTR, paths.PLATFORM_MACOS)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    expected = tmp_path / MACOS_LIBRARY_DIR / "Application Support" / APP_NAME
    assert paths.config_dir() == expected
    assert paths.data_dir() == expected
    assert paths.state_dir() == expected
    assert paths.cache_dir() == tmp_path / MACOS_LIBRARY_DIR / "Caches" / APP_NAME


def test_windows_paths_use_appdata(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, PLATFORM_ATTR, paths.PLATFORM_WINDOWS)
    monkeypatch.setenv("APPDATA", str(tmp_path / WINDOWS_ROAMING_DIR))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / WINDOWS_LOCAL_DIR))

    assert paths.config_dir() == tmp_path / WINDOWS_ROAMING_DIR / APP_NAME
    assert paths.data_dir() == tmp_path / WINDOWS_LOCAL_DIR / APP_NAME
    assert paths.state_dir() == tmp_path / WINDOWS_LOCAL_DIR / APP_NAME
    assert paths.cache_dir() == tmp_path / WINDOWS_LOCAL_DIR / APP_NAME / "Cache"


def test_windows_paths_have_home_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, PLATFORM_ATTR, paths.PLATFORM_WINDOWS)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    assert paths.config_dir() == tmp_path / WINDOWS_APP_DATA_DIR / WINDOWS_ROAMING_DIR / APP_NAME
    assert paths.data_dir() == tmp_path / WINDOWS_APP_DATA_DIR / WINDOWS_LOCAL_DIR / APP_NAME


def test_no_custom_quartz_home_is_used(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, PLATFORM_ATTR, "linux")
    monkeypatch.setenv("QUARTZ_HOME", str(tmp_path / "ignored"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / CONFIG_DIR_NAME))

    assert os.environ["QUARTZ_HOME"]
    assert paths.config_dir() == tmp_path / CONFIG_DIR_NAME / APP_NAME
