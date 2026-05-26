import os
import sys
from pathlib import Path

from quartz import paths


def test_xdg_paths_use_environment_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    assert paths.config_dir() == tmp_path / "config" / "quartz"
    assert paths.data_dir() == tmp_path / "data" / "quartz"
    assert paths.state_dir() == tmp_path / "state" / "quartz"
    assert paths.cache_dir() == tmp_path / "cache" / "quartz"
    assert paths.tournaments_dir() == tmp_path / "config" / "quartz" / "tournaments"
    assert paths.state_file() == tmp_path / "state" / "quartz" / "state.yaml"
    assert paths.tournament_data_dir("gcs-s4") == tmp_path / "data" / "quartz" / "gcs-s4"


def test_macos_paths_use_application_support(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    expected = tmp_path / "Library" / "Application Support" / "quartz"
    assert paths.config_dir() == expected
    assert paths.data_dir() == expected
    assert paths.state_dir() == expected
    assert paths.cache_dir() == tmp_path / "Library" / "Caches" / "quartz"


def test_windows_paths_use_appdata(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))

    assert paths.config_dir() == tmp_path / "Roaming" / "quartz"
    assert paths.data_dir() == tmp_path / "Local" / "quartz"
    assert paths.state_dir() == tmp_path / "Local" / "quartz"
    assert paths.cache_dir() == tmp_path / "Local" / "quartz" / "Cache"


def test_windows_paths_have_home_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    assert paths.config_dir() == tmp_path / "AppData" / "Roaming" / "quartz"
    assert paths.data_dir() == tmp_path / "AppData" / "Local" / "quartz"


def test_no_custom_quartz_home_is_used(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("QUARTZ_HOME", str(tmp_path / "ignored"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    assert os.environ["QUARTZ_HOME"]
    assert paths.config_dir() == tmp_path / "config" / "quartz"
