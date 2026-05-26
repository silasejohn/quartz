import yaml

from quartz import paths
from quartz.tournament_registry import TournamentRegistry


def isolate_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(paths.Path, "home", lambda: tmp_path)


def test_registry_create_list_and_use(tmp_path, monkeypatch):
    isolate_paths(tmp_path, monkeypatch)

    registry = TournamentRegistry()
    path = registry.create("GCS S4")

    assert path.name == "gcs-s4.yaml"
    assert registry.list() == ["gcs-s4"]

    registry.use("gcs-s4")
    assert registry.active_name() == "gcs-s4"


def test_registry_import_export_and_rename(tmp_path, monkeypatch):
    isolate_paths(tmp_path, monkeypatch)
    source = tmp_path / "source.yaml"
    source.write_text(
        """
tournament: GCS
current_lol_split: S2026
tournament_rounds: [S4]
current_round: S4
raw_csv: raw/players.csv
"""
    )

    registry = TournamentRegistry()
    registry.import_yaml(source, use=True)
    assert registry.active_name() == "gcs"

    renamed = registry.rename("gcs", "gcs-s4")
    assert renamed.name == "gcs-s4.yaml"
    assert registry.active_name() == "gcs-s4"

    exported = registry.export_yaml("gcs-s4", tmp_path / "exported.yaml")
    assert exported.exists()
    assert yaml.safe_load(exported.read_text())["name"] == "gcs-s4"


def test_registry_data_dir_defaults_and_absolute_override(tmp_path, monkeypatch):
    isolate_paths(tmp_path, monkeypatch)
    absolute_data = tmp_path / "external-data"

    registry = TournamentRegistry()
    registry.create("default-data")
    registry.create("absolute-data", data_dir=absolute_data)

    assert registry.data_dir_for("default-data") == paths.tournament_data_dir("default-data")
    assert registry.data_dir_for("absolute-data") == absolute_data


def test_registry_remove_can_purge_data(tmp_path, monkeypatch):
    isolate_paths(tmp_path, monkeypatch)

    registry = TournamentRegistry()
    registry.create("gcs-s4")
    data_dir = registry.data_dir_for("gcs-s4")
    (data_dir / "players").mkdir(parents=True)

    registry.remove("gcs-s4", purge_data=True)

    assert registry.list() == []
    assert not data_dir.exists()
