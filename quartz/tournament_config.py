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
import re
from pathlib import Path
from typing import Optional, Union

import yaml
from pydantic import BaseModel, Field

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


class SignupSheetConfig(BaseModel):
    """Column mapping for a raw tournament signup sheet (Google Form export).

    Columns can be named (str) for sheets with a header row, or positional (int)
    for headerless exports. Set has_header: false and use integer indices when the
    CSV has no column headers.

    Used by SignupSheetAdapter to convert free-form signup data into the
    normalized ingest format. Set signup_sheet: in active_tournament.yaml
    to enable; omit it to fall back to the legacy LocalCSVInput path.
    """
    has_header:     bool = True
    player_id:      Union[str, int] = "Player"    # → discord_username / player_id
    rank:           Union[str, int] = "Rank"      # → stated_current_rank (normalized); peak = None
    roles:          Union[str, int] = "Roles"     # → primary_role + secondary_role (split on "/")
    opgg_url:       Optional[Union[str, int]] = "Op.gg"  # → riot_ids; None if sheet has no OP.GG column
    ugg_url:        Optional[Union[str, int]] = "U.gg"   # → riot_ids fallback when opgg_url is blank
    default_region: str = "NA"        # player_region for all extracted accounts


class SheetsConfig(BaseModel):
    """Target spreadsheet for `quartz export --push` and `quartz export --team --push`."""
    spreadsheet_id: str
    sheet_name: str
    stats_sheet_name: Optional[str] = None   # tab for pool overview; set to enable --team --push
    credentials_path: str = "config/credentials.json"
    token_path: str = "config/token.json"


class EligibilityConfig(BaseModel):
    """Tournament eligibility rule — minimum ranked games to be draft-eligible.

    Example (GCS rulebook): 30 games in S2026, or 50+ games in S2025 as backup.
    If not set on TournamentConfig, all players are considered eligible.
    """
    primary_split: str
    primary_min_games: int
    backup_split: Optional[str] = None
    backup_min_games: Optional[int] = None


class FrozenPoolStats(BaseModel):
    """Pool-level hyperparameters locked by `quartz pv --freeze`.

    When present on TournamentConfig, PV_COMPUTE uses these values directly
    instead of recomputing from live roster data. Clear with `quartz pv --clear`.
    """
    N: int
    champ_dpm_baseline: float
    champ_dpm_pool_stddev: float
    realistic_max: float
    atp_miss_scale: float
    atp_season_min_games: dict[str, int]    # SEASON_ORDER key → min games
    n_hist_thresholds: dict[str, int]       # past split key → N threshold


class DraftFormat(BaseModel):
    """Structural rules for the snake draft — varies per tournament."""
    picks_per_captain: int = 4
    reorder_after_round: Optional[int] = None   # None = no reorder; integer = reorder after that round
    randomize_captain_order: bool = False
    soft_cap_trigger: Optional[float] = None    # None = no soft cap
    soft_cap_scale: float = 0.5                 # linear multiplier on soft cap excess


class TournamentConfig(BaseModel):
    """Full config for the active tournament, loaded from active_tournament.yaml."""
    tournament: str             # league name e.g. "GCS"
    current_lol_split: str      # active LoL ranked split e.g. "S2026" — key from SEASON_ORDER
    tournament_rounds: list[str]
    current_round: str          # round label e.g. "S4"
    data_dir: str               # relative to project root, e.g. "data/gcs/s4"
    raw_csv: str                # relative to project root
    draft_format: DraftFormat = DraftFormat()
    captain_slots: list[tuple[int, str]] = []  # draft order: [(slot, effective_id), ...]
    csv_columns: CSVColumns = CSVColumns()
    signup_sheet: Optional[SignupSheetConfig] = None  # set to enable raw signup sheet adapter
    scraper_delays: dict[str, int] = {}        # seconds between accounts per source; override in YAML if needed
    eligibility: Optional[EligibilityConfig] = None  # tournament games requirement; None = no rule
    sheets: Optional[SheetsConfig] = None     # set to enable `quartz export --push`
    frozen_pool_stats: Optional[FrozenPoolStats] = None  # locked by `quartz pv --freeze`; None = dynamic
    config_path: Optional[str] = Field(default=None, exclude=True)  # resolved path to tournament YAML (not serialized)

    def get_scraper_delay(self, source: str, default: int = 3) -> int:
        """Return the inter-account delay (seconds) for a given scraper source."""
        return self.scraper_delays.get(source, default)

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
                         Also reads QUARTZ_CONFIG env var as a fallback before the default.
    """
    if config_path:
        path = Path(config_path)
    elif env_path := os.environ.get("QUARTZ_CONFIG"):
        path = _PROJECT_ROOT / env_path
    else:
        path = _PROJECT_ROOT / "active_tournament.yaml"

    if not path.exists():
        raise FileNotFoundError(
            f"Tournament config not found at {path}. "
            "Make sure active_tournament.yaml exists at the project root."
        )

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # If the file is just a pointer, follow it
    if set(data.keys()) == {"source"}:
        path = _PROJECT_ROOT / data["source"]
        if not path.exists():
            raise FileNotFoundError(
                f"Tournament config source not found: {path}. "
                f"Check the 'source:' key in active_tournament.yaml."
            )
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

    config = TournamentConfig(**data)
    config.config_path = str(path)
    return config


def write_frozen_pool_stats(config: TournamentConfig, stats: Optional[FrozenPoolStats]) -> None:
    """Write (or clear) the frozen_pool_stats block in the tournament YAML.

    Preserves all other content including comments. Always writes to the resolved
    tournament file (e.g. tournaments/gcs_s4.yaml), never to active_tournament.yaml.
    """
    if not config.config_path:
        raise RuntimeError("config_path not set — cannot write back to YAML")

    yaml_path = Path(config.config_path)
    content = yaml_path.read_text(encoding="utf-8")

    if stats is None:
        replacement = "frozen_pool_stats: ~"
    else:
        def _dict_lines(d: dict, indent: int) -> str:
            pad = " " * indent
            return "".join(f"{pad}{k}: {v}\n" for k, v in d.items())

        replacement = (
            f"frozen_pool_stats:\n"
            f"  N: {stats.N}\n"
            f"  champ_dpm_baseline: {round(stats.champ_dpm_baseline, 4)}\n"
            f"  champ_dpm_pool_stddev: {round(stats.champ_dpm_pool_stddev, 4)}\n"
            f"  realistic_max: {round(stats.realistic_max, 6)}\n"
            f"  atp_miss_scale: {round(stats.atp_miss_scale, 4)}\n"
            f"  atp_season_min_games:\n"
            f"{_dict_lines(stats.atp_season_min_games, 4)}"
            f"  n_hist_thresholds:\n"
            f"{_dict_lines(stats.n_hist_thresholds, 4)}"
        ).rstrip("\n")

    # Replace existing block (null or multi-line) — anchored at line start,
    # consumes until the next top-level key or EOF.
    pattern = re.compile(
        r"^frozen_pool_stats:.*?(?=\n[^\s#\n]|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    if pattern.search(content):
        content = pattern.sub(replacement, content)
    else:
        content = content.rstrip("\n") + "\n\n" + replacement + "\n"

    yaml_path.write_text(content, encoding="utf-8")
