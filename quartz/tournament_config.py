"""
TournamentConfig — loads active_tournament.yaml from the project root.

All scripts import this to get tournament context (name, season, data paths,
csv column mappings). To switch tournaments, edit active_tournament.yaml only.

Usage:
    from quartz.tournament_config import load_tournament_config

    config = load_tournament_config()
    print(config.tournament)    # "GCS"
    print(config.current_round) # "S4"
    print(config.players_dir)   # "data/gcs/s4/players"
"""

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel

# Project root is two levels up from this file (quartz/tournament_config.py → quartz/ → Quartz/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class CSVColumns(BaseModel):
    """Column name mapping for the Google Form response CSV."""
    discord: str      = "Discord Username"
    riot_id: str      = "Riot ID"
    current_rank: str = "Stated Current Rank"
    peak_rank: str    = "Stated Peak Rank"
    primary_role: str = "Primary Role"
    secondary_role: str = "Secondary Role"


class TournamentConfig(BaseModel):
    """Full config for the active tournament, loaded from active_tournament.yaml."""
    tournament: str             # league name e.g. "GCS"
    current_lol_split: str      # active LoL ranked split e.g. "S2026" — key from SEASON_ORDER
    tournament_rounds: list[str]
    current_round: str          # round label e.g. "S4"
    data_dir: str               # relative to project root, e.g. "data/gcs/s4"
    raw_csv: str                # relative to project root
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
        return os.path.join(self.data_dir, "players")

    @property
    def processed_dir(self) -> str:
        return os.path.join(self.data_dir, "processed")

    @property
    def abs_data_dir(self) -> str:
        return str(_PROJECT_ROOT / self.data_dir)

    @property
    def abs_players_dir(self) -> str:
        return str(_PROJECT_ROOT / self.data_dir / "players")

    @property
    def abs_processed_dir(self) -> str:
        return str(_PROJECT_ROOT / self.data_dir / "processed")

    @property
    def abs_raw_csv(self) -> str:
        return str(_PROJECT_ROOT / self.raw_csv)


def load_tournament_config(config_path: Optional[str] = None) -> TournamentConfig:
    """
    Load active_tournament.yaml from the project root (or a given path).

    [param] config_path: optional explicit path to a tournament YAML file.
                         Defaults to {project_root}/active_tournament.yaml.
    """
    if config_path:
        path = Path(config_path)
    else:
        path = _PROJECT_ROOT / "active_tournament.yaml"

    if not path.exists():
        raise FileNotFoundError(
            f"Tournament config not found at {path}. "
            "Make sure active_tournament.yaml exists at the project root."
        )

    with open(path, "r") as f:
        data = yaml.safe_load(f)

    return TournamentConfig(**data)
