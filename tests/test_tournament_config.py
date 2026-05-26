import pytest

from quartz import paths
from quartz.tournament_config import load_active_tournament, set_active_tournament_override
from quartz.tournament_registry import TournamentRegistry, TournamentRegistryError

GCS_TOURNAMENT = "gcs-s4"
ABC_TOURNAMENT = "abc-s1"
ROUND = "S4"
RAW_CSV = "raw/players.csv"


def write_tournament(registry: TournamentRegistry, name: str, **overrides):
    payload = {
        "name": name,
        "tournament": name.split("-")[0].upper(),
        "current_lol_split": "S2026",
        "tournament_rounds": [ROUND],
        "current_round": ROUND,
        "raw_csv": RAW_CSV,
    }
    payload.update(overrides)
    return registry.write_yaml(name, payload)


def test_load_active_tournament_uses_registry_selection(isolate_paths):
    registry = TournamentRegistry()
    write_tournament(registry, GCS_TOURNAMENT)
    registry.use(GCS_TOURNAMENT)

    config = load_active_tournament()

    assert config.name == GCS_TOURNAMENT
    assert config.round_id == "GCS-S4"
    assert config.abs_data_dir == str(paths.tournament_data_dir(GCS_TOURNAMENT))
    assert config.abs_raw_csv == str(paths.tournament_data_dir(GCS_TOURNAMENT) / RAW_CSV)


def test_load_active_tournament_supports_one_shot_override(isolate_paths):
    registry = TournamentRegistry()
    write_tournament(registry, GCS_TOURNAMENT)
    write_tournament(registry, ABC_TOURNAMENT)
    registry.use(GCS_TOURNAMENT)

    config = load_active_tournament(ABC_TOURNAMENT)

    assert config.name == ABC_TOURNAMENT


def test_load_active_tournament_errors_without_active(isolate_paths):
    with pytest.raises(TournamentRegistryError, match="No active tournament"):
        load_active_tournament()


def test_load_active_tournament_resolves_absolute_data_dir(tmp_path, isolate_paths):
    registry = TournamentRegistry()
    absolute_data = tmp_path / "elsewhere"
    write_tournament(registry, GCS_TOURNAMENT, data_dir=str(absolute_data))
    registry.use(GCS_TOURNAMENT)

    config = load_active_tournament()

    assert config.abs_data_dir == str(absolute_data)


def test_context_override_is_used(isolate_paths):
    registry = TournamentRegistry()
    write_tournament(registry, GCS_TOURNAMENT)
    write_tournament(registry, ABC_TOURNAMENT)
    registry.use(GCS_TOURNAMENT)

    set_active_tournament_override(ABC_TOURNAMENT)
    try:
        assert load_active_tournament().name == ABC_TOURNAMENT
    finally:
        set_active_tournament_override(None)
