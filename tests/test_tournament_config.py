import pytest

from quartz import paths
from quartz.tournament_config import load_active_tournament, set_active_tournament_override
from quartz.tournament_registry import TournamentRegistry, TournamentRegistryError


def isolate_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(paths.Path, "home", lambda: tmp_path)


def write_tournament(registry: TournamentRegistry, name: str, **overrides):
    payload = {
        "name": name,
        "tournament": name.split("-")[0].upper(),
        "current_lol_split": "S2026",
        "tournament_rounds": ["S4"],
        "current_round": "S4",
        "raw_csv": "raw/players.csv",
    }
    payload.update(overrides)
    return registry.write_yaml(name, payload)


def test_load_active_tournament_uses_registry_selection(tmp_path, monkeypatch):
    isolate_paths(tmp_path, monkeypatch)
    registry = TournamentRegistry()
    write_tournament(registry, "gcs-s4")
    registry.use("gcs-s4")

    config = load_active_tournament()

    assert config.name == "gcs-s4"
    assert config.round_id == "GCS-S4"
    assert config.abs_data_dir == str(paths.tournament_data_dir("gcs-s4"))
    assert config.abs_raw_csv == str(paths.tournament_data_dir("gcs-s4") / "raw" / "players.csv")


def test_load_active_tournament_supports_one_shot_override(tmp_path, monkeypatch):
    isolate_paths(tmp_path, monkeypatch)
    registry = TournamentRegistry()
    write_tournament(registry, "gcs-s4")
    write_tournament(registry, "abc-s1")
    registry.use("gcs-s4")

    config = load_active_tournament("abc-s1")

    assert config.name == "abc-s1"


def test_load_active_tournament_errors_without_active(tmp_path, monkeypatch):
    isolate_paths(tmp_path, monkeypatch)

    with pytest.raises(TournamentRegistryError, match="No active tournament"):
        load_active_tournament()


def test_load_active_tournament_resolves_absolute_data_dir(tmp_path, monkeypatch):
    isolate_paths(tmp_path, monkeypatch)
    registry = TournamentRegistry()
    absolute_data = tmp_path / "elsewhere"
    write_tournament(registry, "gcs-s4", data_dir=str(absolute_data))
    registry.use("gcs-s4")

    config = load_active_tournament()

    assert config.abs_data_dir == str(absolute_data)


def test_context_override_is_used(tmp_path, monkeypatch):
    isolate_paths(tmp_path, monkeypatch)
    registry = TournamentRegistry()
    write_tournament(registry, "gcs-s4")
    write_tournament(registry, "abc-s1")
    registry.use("gcs-s4")

    set_active_tournament_override("abc-s1")
    try:
        assert load_active_tournament().name == "abc-s1"
    finally:
        set_active_tournament_override(None)
