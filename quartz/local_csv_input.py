"""
LocalCSVInput
Reads and validates a local CSV form response file.
Returns one cleaned dict per player row — no pandas dependency downstream.
"""

import csv
import os
from typing import Optional

from quartz.constants import RANK_ALIASES, RANK_ORDER, ROLE_ALIASES
from quartz.utils.logging import error_print, info_print, success_print, warning_print

REQUIRED_COLUMNS = [
    "Discord Username",
    "Riot ID",
    "Stated Current Rank",
    "Stated Peak Rank",
    "Primary Role",
    "Secondary Role",
]


class LocalCSVInput:
    """
    Reads a local CSV form response and returns cleaned player rows.

    Usage:
        reader = LocalCSVInput("data/gcs/s4/raw/gcs_draft_info_s4.csv")
        players = reader.load()   # list of dicts, one per player
    """

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.rows: list[dict] = []
        self.errors: list[str] = []

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def load(self) -> list[dict]:
        """
        Read, validate, and clean the CSV.
        Returns a list of player dicts with standardized field values.
        Logs warnings for soft issues, raises on hard failures.
        """
        raw = self._read_csv()
        self._validate_columns(raw)
        self.rows = [self._clean_row(i, row) for i, row in enumerate(raw)]

        success_print(f"LocalCSVInput: loaded {len(self.rows)} players from {self.file_path}")
        if self.errors:
            warning_print(f"LocalCSVInput: {len(self.errors)} warnings during load")
            for e in self.errors:
                warning_print(f"  {e}")

        return self.rows

    # ------------------------------------------------------------------
    # Internal — I/O
    # ------------------------------------------------------------------

    def _read_csv(self) -> list[dict]:
        if not os.path.exists(self.file_path):
            error_print(f"LocalCSVInput: file not found: {self.file_path}")
            raise FileNotFoundError(self.file_path)

        with open(self.file_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            # Strip headers and cell values: remove all newlines and Unicode
            # bidirectional/formatting control characters anywhere in the string,
            # then strip leading/trailing whitespace
            _BIDI_CHARS = (
                "\u2066", "\u2067", "\u2068", "\u2069",  # isolate controls
                "\u200e", "\u200f",                       # LRM / RLM marks
                "\u202a", "\u202b", "\u202c",             # embedding/pop controls
                "\u202d", "\u202e",                       # override controls
                "\u2061", "\u2062", "\u2063", "\u2064",  # invisible math operators
            )
            def _clean_cell(s):
                for ch in _BIDI_CHARS:
                    s = s.replace(ch, "")
                return s.replace("\r\n", "").replace("\r", "").replace("\n", "").strip()

            rows = [
                {_clean_cell(k): _clean_cell(v) if isinstance(v, str) else v for k, v in row.items()}
                for row in reader
            ]

        info_print(f"LocalCSVInput: read {len(rows)} rows from {self.file_path}")
        return rows

    def _validate_columns(self, rows: list[dict]) -> None:
        if not rows:
            raise ValueError("CSV is empty — no rows found.")
        present = set(rows[0].keys())
        missing = [c for c in REQUIRED_COLUMNS if c not in present]
        if missing:
            raise ValueError(f"CSV is missing required columns: {missing}")

    # ------------------------------------------------------------------
    # Internal — row cleaning
    # ------------------------------------------------------------------

    def _clean_row(self, index: int, row: dict) -> dict:
        discord = self._require_field(row, "Discord Username", index)
        player_type_override, accounts = self._parse_riot_id_cell(
            row.get("Riot ID", ""), index
        )
        current_rank = self._clean_rank(row.get("Stated Current Rank", ""), index, "Stated Current Rank")
        peak_rank    = self._clean_rank(row.get("Stated Peak Rank", ""),    index, "Stated Peak Rank")
        primary_role   = self._clean_role(row.get("Primary Role", ""),   index, "Primary Role")
        secondary_role = self._clean_role(row.get("Secondary Role", ""), index, "Secondary Role")

        return {
            "discord_username":     discord,
            "player_type_override": player_type_override,  # "captain" | "sub" | None
            "accounts":             accounts,               # list of {"riot_id", "player_region"}
            "stated_current_rank":  current_rank,
            "stated_peak_rank":     peak_rank,
            "primary_role":         primary_role,
            "secondary_role":       secondary_role,
        }

    # ------------------------------------------------------------------
    # Internal — Riot ID cell parsing
    # ------------------------------------------------------------------

    def _parse_riot_id_cell(
        self, raw: str, index: int
    ) -> tuple[Optional[str], list[dict]]:
        """
        Parse the Riot ID cell, which encodes player type and region inline.

        Prefix rules (applied to the whole cell, checked in order):
          *(CAP)  -> player_type = "captain", strip prefix
          *(SUB)  -> player_type = "sub",     strip prefix
          *       -> player_type = "other" (tracked but not in tournament), strip prefix
          (REGION) per-entry -> player_region = that region (default "NA")

        Multiple accounts separated by " | ".

        Returns:
            player_type_override: "captain" | "sub" | None
            accounts: [{"riot_id": str, "player_region": str}, ...]
        """
        cell = self._clean_string(raw)
        if not cell:
            return None, []

        player_type_override: Optional[str] = None

        # Check whole-cell player type prefixes first
        if cell.startswith("*(CAP)"):
            player_type_override = "captain"
            cell = cell[len("*(CAP)"):].strip()
        elif cell.startswith("*(SUB)"):
            player_type_override = "sub"
            cell = cell[len("*(SUB)"):].strip()
        elif cell.startswith("*") and not cell.startswith("*("):
            # * without a ( after it = tracked player not in the tournament
            player_type_override = "other"
            cell = cell[1:].strip()

        # Split into individual account entries
        entries = [e.strip() for e in cell.split("|")]
        accounts = []

        for entry in entries:
            entry = entry.strip()
            if not entry:
                continue

            region = "NA"

            # Per-entry region prefix: (EUW)RiotID#Tag
            if entry.startswith("("):
                close = entry.find(")")
                if close != -1:
                    candidate = entry[1:close].upper()
                    # Only treat as region if it looks geographic (not CAP/SUB — already stripped)
                    if candidate not in ("CAP", "SUB"):
                        region = candidate
                        entry = entry[close + 1:].strip()

            if not entry:
                self.errors.append(f"Row {index + 1}: empty Riot ID after stripping region prefix")
                continue

            accounts.append({"riot_id": entry, "player_region": region})

        return player_type_override, accounts

    # ------------------------------------------------------------------
    # Internal — field cleaners
    # ------------------------------------------------------------------

    def _require_field(self, row: dict, col: str, index: int) -> str:
        val = self._clean_string(row.get(col, ""))
        if not val:
            raise ValueError(f"Row {index + 1}: required field '{col}' is empty.")
        return val

    def _clean_role(self, raw: str, index: int, field: str) -> Optional[str]:
        normalized = self._clean_string(raw).upper()
        if not normalized:
            return None
        role = ROLE_ALIASES.get(normalized)
        if role is None:
            self.errors.append(
                f"Row {index + 1}: unrecognized {field} '{raw}', leaving as None"
            )
        return role

    def _clean_rank(self, raw: str, index: int, field: str) -> Optional[str]:
        normalized = self._clean_string(raw)
        if not normalized or normalized.lower() in ("unranked", "n/a"):
            return "Unranked"

        # Try alias lookup (handles "Plat 4", "Masters", short codes, etc.)
        aliased = RANK_ALIASES.get(normalized) or RANK_ALIASES.get(normalized.title())
        candidate = aliased if aliased else normalized.title()

        if candidate in RANK_ORDER or candidate == "Unranked":
            return candidate

        self.errors.append(
            f"Row {index + 1}: unrecognized {field} '{raw}', leaving as None"
        )
        return None

    @staticmethod
    def _clean_string(val) -> str:
        return str(val).strip() if val is not None else ""
