"""
TournamentConfig — loads the active tournament from the CLI-managed registry.

All scripts import this to get tournament context (name, season, data paths,
csv column mappings). To switch tournaments, use `quartz tournament use`.

Usage:
    from quartz.tournament_config import load_active_tournament

    config = load_active_tournament()
    print(config.tournament)    # "GCS"
    print(config.current_round) # "S4"
    print(config.players_dir)   # "data/gcs/s4/players"
"""

from contextvars import ContextVar
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, PrivateAttr

from quartz.tournament_registry import TournamentRegistry, TournamentRegistryError

_ACTIVE_TOURNAMENT_OVERRIDE: ContextVar[str | None] = ContextVar("active_tournament_override", default=None)


class CSVColumns(BaseModel):
    """Column name mapping for the Google Form response CSV."""
    discord: str      = "Discord Username"
    riot_id: str      = "Riot ID"
    current_rank: str = "Stated Current Rank"
    peak_rank: str    = "Stated Peak Rank"
    primary_role: str = "Primary Role"
    secondary_role: str = "Secondary Role"


class TournamentConfig(BaseModel):
    """Full config for the active tournament, loaded from the registry."""
    model_config = ConfigDict(extra="ignore")

    _data_root: Path = PrivateAttr(default_factory=Path.cwd)

    name: str
    display_name: Optional[str] = None
    tournament: str             # league name e.g. "GCS"
    current_lol_split: str      # active LoL ranked split e.g. "S2026" — key from SEASON_ORDER
    tournament_rounds: list[str]
    current_round: str          # round label e.g. "S4"
    data_dir: Optional[str] = None
    raw_csv: str                # relative to tournament data dir, unless absolute
    captain_slots: list[tuple[int, str]] = []  # draft order: [(slot, effective_id), ...]
    csv_columns: CSVColumns = CSVColumns()

    @property
    def round_id(self) -> str:
        """Composite key for the current round e.g. 'GCS-S4'. Used as SeasonData.season key."""
        return f"{self.tournament}-{self.current_round}"

    @property
    def round_ids(self) -> list[str]:
        """Composite keys for all tournament rounds e.g. ['GCS-S4']. Use for season filters."""
        return [f"{self.tournament}-{r}" for r in self.tournament_rounds]

    @property
    def players_dir(self) -> str:
        return str(Path(self.data_dir or ".") / "players")

    @property
    def processed_dir(self) -> str:
        return str(Path(self.data_dir or ".") / "processed")

    @property
    def abs_data_dir(self) -> str:
        return str(self._data_root)

    @property
    def abs_players_dir(self) -> str:
        return str(self._data_root / "players")

    @property
    def abs_processed_dir(self) -> str:
        return str(self._data_root / "processed")

    @property
    def abs_raw_csv(self) -> str:
        raw_csv = Path(self.raw_csv).expanduser()
        if raw_csv.is_absolute():
            return str(raw_csv)
        return str(self._data_root / raw_csv)


def set_active_tournament_override(name: str | None) -> None:
    _ACTIVE_TOURNAMENT_OVERRIDE.set(name)


def load_active_tournament(name: Optional[str] = None) -> TournamentConfig:
    """Load a tournament from the registry, defaulting to the active selection."""
    registry = TournamentRegistry()
    selected = name or _ACTIVE_TOURNAMENT_OVERRIDE.get() or registry.active_name()
    if not selected:
        raise TournamentRegistryError(
            "No active tournament is selected. Run 'quartz tournament list' or 'quartz tournament use NAME'."
        )

    data = registry.read_yaml(selected)
    config = TournamentConfig(**data)
    config._data_root = registry.data_dir_for(config.name)
    return config
