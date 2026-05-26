import yaml

from quartz import paths
from quartz.tournament_registry import TournamentRegistry

GCS_TOURNAMENT = "gcs-s4"
GCS_TOURNAMENT_FILE = f"{GCS_TOURNAMENT}.yaml"
IMPORTED_TOURNAMENT = "gcs"
DEFAULT_DATA_TOURNAMENT = "default-data"
ABSOLUTE_DATA_TOURNAMENT = "absolute-data"


def test_registry_create_list_and_use(isolate_paths):
    registry = TournamentRegistry()
    path = registry.create("GCS S4")

    assert path.name == GCS_TOURNAMENT_FILE
    assert registry.list() == [GCS_TOURNAMENT]

    registry.use(GCS_TOURNAMENT)
    assert registry.active_name() == GCS_TOURNAMENT


def test_registry_import_export_and_rename(tmp_path, isolate_paths):
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
    assert registry.active_name() == IMPORTED_TOURNAMENT

    renamed = registry.rename(IMPORTED_TOURNAMENT, GCS_TOURNAMENT)
    assert renamed.name == GCS_TOURNAMENT_FILE
    assert registry.active_name() == GCS_TOURNAMENT

    exported = registry.export_yaml(GCS_TOURNAMENT, tmp_path / "exported.yaml")
    assert exported.exists()
    assert yaml.safe_load(exported.read_text())["name"] == GCS_TOURNAMENT


def test_registry_data_dir_defaults_and_absolute_override(tmp_path, isolate_paths):
    absolute_data = tmp_path / "external-data"

    registry = TournamentRegistry()
    registry.create(DEFAULT_DATA_TOURNAMENT)
    registry.create(ABSOLUTE_DATA_TOURNAMENT, data_dir=absolute_data)

    assert registry.data_dir_for(DEFAULT_DATA_TOURNAMENT) == paths.tournament_data_dir(DEFAULT_DATA_TOURNAMENT)
    assert registry.data_dir_for(ABSOLUTE_DATA_TOURNAMENT) == absolute_data


def test_registry_remove_can_purge_data(isolate_paths):
    registry = TournamentRegistry()
    registry.create(GCS_TOURNAMENT)
    data_dir = registry.data_dir_for(GCS_TOURNAMENT)
    (data_dir / "players").mkdir(parents=True)

    registry.remove(GCS_TOURNAMENT, purge_data=True)

    assert registry.list() == []
    assert not data_dir.exists()
