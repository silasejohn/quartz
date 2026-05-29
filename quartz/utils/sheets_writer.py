"""
SheetsWriter — push Quartz export data to a pre-formatted Google Sheets spreadsheet.

Clear-and-rewrite strategy:
  1. Clear the full data range (values + formatting reset to white).
  2. Write all row values via values().update().
  3. Apply formatting in one batchUpdate:
       - Columns A–D: row background pink (captain) or purple (sub); white for main.
       - Column E (pv): green→yellow→red gradient by PV value.
       - Columns F–J: values only — data validation handles rank column colors.

Authentication: OAuth2 with credentials.json + token.json in config/.
First run opens a browser to authorize; token is cached and auto-refreshed after that.
Copy config/credentials.json from Zephyr's backend/config/ to get started.
"""

import os
from pathlib import Path
from typing import Optional

from quartz.utils.logging import error_print, info_print, success_print, warning_print

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Row background colors (RGB 0.0–1.0) for A–D columns
_CAPTAIN_COLOR = {"red": 0.988, "green": 0.820, "blue": 0.820}  # soft pink
_SUB_COLOR     = {"red": 0.851, "green": 0.816, "blue": 0.925}  # soft lavender
_WHITE         = {"red": 1.0,   "green": 1.0,   "blue": 1.0}

# Stats sheet section styling
_SECTION_HEADER_COLOR = {"red": 0.180, "green": 0.369, "blue": 0.557}  # dark blue
_SUBHEADER_COLOR      = {"red": 0.851, "green": 0.851, "blue": 0.851}  # light gray
_N_STATS_COLS = 12

# PV gradient: low PV (strong player) = green, mid = yellow, high (weak) = red
_PV_MIN    = 5.0
_PV_MAX    = 75.0
_GREEN     = (0.714, 0.886, 0.714)
_YELLOW    = (1.000, 0.949, 0.600)
_RED       = (0.918, 0.600, 0.600)

# Clear slightly beyond any realistic roster size to wipe stale formatting from previous pushes
_MAX_ROWS = 300


def _pv_color(pv: float) -> dict:
    t = max(0.0, min(1.0, (pv - _PV_MIN) / (_PV_MAX - _PV_MIN)))
    if t <= 0.5:
        s = t * 2
        c = tuple(_GREEN[i] + s * (_YELLOW[i] - _GREEN[i]) for i in range(3))
    else:
        s = (t - 0.5) * 2
        c = tuple(_YELLOW[i] + s * (_RED[i] - _YELLOW[i]) for i in range(3))
    return {"red": c[0], "green": c[1], "blue": c[2]}


class SheetsWriter:
    """
    Writes Quartz export rows to a single sheet in a Google Spreadsheet.

    Usage:
        writer = SheetsWriter.from_config(config.sheets)
        writer.push(rows, fieldnames)
    """

    def __init__(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        credentials_path: str,
        token_path: str,
    ):
        self.spreadsheet_id = spreadsheet_id
        self.sheet_name = sheet_name
        self._creds_path = str(_PROJECT_ROOT / credentials_path)
        self._token_path = str(_PROJECT_ROOT / token_path)
        self._service = self._authenticate()
        self._sheet_id = self._resolve_sheet_id()

    @classmethod
    def from_config(cls, sheets_config) -> "SheetsWriter":
        return cls(
            spreadsheet_id=sheets_config.spreadsheet_id,
            sheet_name=sheets_config.sheet_name,
            credentials_path=sheets_config.credentials_path,
            token_path=sheets_config.token_path,
        )

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _authenticate(self):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError:
            raise ImportError(
                "Google API packages not installed. Run: uv pip install -e '.[sheets]'"
            )

        creds = None
        if os.path.exists(self._token_path):
            try:
                creds = Credentials.from_authorized_user_file(self._token_path, _SCOPES)
            except Exception as e:
                warning_print(f"SheetsWriter: failed to load cached token: {e}")

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    info_print("SheetsWriter: refreshed OAuth2 token")
                except Exception as e:
                    warning_print(f"SheetsWriter: token refresh failed, re-authorizing: {e}")
                    creds = None

            if not creds:
                if not os.path.exists(self._creds_path):
                    raise FileNotFoundError(
                        f"SheetsWriter: credentials not found at {self._creds_path}\n"
                        "Copy config/credentials.json from Zephyr's backend/config/."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(self._creds_path, _SCOPES)
                creds = flow.run_local_server(port=0)
                info_print("SheetsWriter: obtained new OAuth2 token via browser")

            try:
                with open(self._token_path, "w") as f:
                    f.write(creds.to_json())
            except Exception as e:
                warning_print(f"SheetsWriter: could not save token: {e}")

        return build("sheets", "v4", credentials=creds)

    def _resolve_sheet_id(self) -> int:
        meta = self._service.spreadsheets().get(
            spreadsheetId=self.spreadsheet_id
        ).execute()
        for sheet in meta["sheets"]:
            if sheet["properties"]["title"] == self.sheet_name:
                return sheet["properties"]["sheetId"]
        raise ValueError(
            f"SheetsWriter: sheet '{self.sheet_name}' not found in spreadsheet {self.spreadsheet_id}"
        )

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def push(self, rows: list[dict], fieldnames: list[str]) -> None:
        """Clear data rows and write all rows with formatting in three API calls."""
        n_cols = len(fieldnames)
        last_col_letter = chr(ord("A") + n_cols - 1)
        full_range   = self._a1(f"A2:{last_col_letter}{_MAX_ROWS}")
        write_range  = self._a1("A2")

        # 1 — clear values
        self._service.spreadsheets().values().clear(
            spreadsheetId=self.spreadsheet_id,
            range=full_range,
        ).execute()
        info_print("SheetsWriter: cleared data range")

        # 2 — write values
        values = [[row.get(col, "") for col in fieldnames] for row in rows]
        self._service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=write_range,
            valueInputOption="USER_ENTERED",
            body={"values": values},
        ).execute()
        info_print(f"SheetsWriter: wrote {len(rows)} rows")

        # 3 — apply formatting
        requests = self._build_format_requests(rows, fieldnames, n_cols)
        if requests:
            self._service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"requests": requests},
            ).execute()
            info_print(f"SheetsWriter: applied formatting ({len(requests)} requests)")

        success_print(f"SheetsWriter: pushed {len(rows)} rows to '{self.sheet_name}'")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _a1(self, cell_range: str) -> str:
        """Wrap sheet name in single quotes for A1 notation (handles special chars/spaces)."""
        name = self.sheet_name.replace("'", "\\'")
        return f"'{name}'!{cell_range}"

    def _repeat_cell_bg(self, row_idx: int, start_col: int, end_col: int, color: dict) -> dict:
        return {
            "repeatCell": {
                "range": {
                    "sheetId": self._sheet_id,
                    "startRowIndex": row_idx,
                    "endRowIndex": row_idx + 1,
                    "startColumnIndex": start_col,
                    "endColumnIndex": end_col,
                },
                "cell": {"userEnteredFormat": {"backgroundColor": color}},
                "fields": "userEnteredFormat.backgroundColor",
            }
        }

    def _build_format_requests(
        self, rows: list[dict], fieldnames: list[str], n_cols: int
    ) -> list[dict]:
        requests = []
        pv_col = fieldnames.index("pv") if "pv" in fieldnames else None

        # Reset entire data area to white first (clears stale colors from previous pushes)
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": self._sheet_id,
                    "startRowIndex": 1,       # row 2 (0-based)
                    "endRowIndex": _MAX_ROWS,
                    "startColumnIndex": 0,
                    "endColumnIndex": n_cols,
                },
                "cell": {"userEnteredFormat": {"backgroundColor": _WHITE}},
                "fields": "userEnteredFormat.backgroundColor",
            }
        })

        for i, row in enumerate(rows):
            row_idx = i + 1  # 0-based; row 1 = header, data starts at row index 1

            player_type = row.get("player_type", "")
            if player_type == "captain":
                requests.append(self._repeat_cell_bg(row_idx, 0, 4, _SUB_COLOR))
            elif player_type == "sub":
                requests.append(self._repeat_cell_bg(row_idx, 0, 4, _CAPTAIN_COLOR))

            if pv_col is not None:
                try:
                    color = _pv_color(float(row.get("pv", 50)))
                    requests.append(self._repeat_cell_bg(row_idx, pv_col, pv_col + 1, color))
                except (ValueError, TypeError):
                    pass

        return requests

    # ------------------------------------------------------------------
    # Stats sheet push
    # ------------------------------------------------------------------

    def push_stats(self, section1_rows: list[list], section2_rows: list[list]) -> None:
        """Clear and write pool stats with two sections (captains+mains, then subs)."""
        last_col = chr(ord("A") + _N_STATS_COLS - 1)
        gap      = [[""] * _N_STATS_COLS] * 2
        all_rows = section1_rows + gap + section2_rows

        # 1 — clear
        self._service.spreadsheets().values().clear(
            spreadsheetId=self.spreadsheet_id,
            range=self._a1(f"A1:{last_col}{_MAX_ROWS}"),
        ).execute()

        # 2 — write values
        self._service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=self._a1("A1"),
            valueInputOption="USER_ENTERED",
            body={"values": all_rows},
        ).execute()
        info_print(f"SheetsWriter: wrote {len(all_rows)} stats rows")

        # 3 — format
        requests = self._build_stats_format_requests(section1_rows, section2_rows)
        if requests:
            self._service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"requests": requests},
            ).execute()

        success_print(f"SheetsWriter: pushed pool stats to '{self.sheet_name}'")

    def _build_stats_format_requests(
        self, section1_rows: list[list], section2_rows: list[list]
    ) -> list[dict]:
        requests = []

        # Reset entire area to white
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": self._sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": _MAX_ROWS,
                    "startColumnIndex": 0,
                    "endColumnIndex": _N_STATS_COLS,
                },
                "cell": {"userEnteredFormat": {"backgroundColor": _WHITE}},
                "fields": "userEnteredFormat.backgroundColor",
            }
        })

        section2_offset = len(section1_rows) + 2
        requests.extend(self._stats_section_requests(section1_rows, row_offset=0))
        requests.extend(self._stats_section_requests(section2_rows, row_offset=section2_offset))
        return requests

    def _stats_section_requests(self, section_rows: list[list], row_offset: int) -> list[dict]:
        if not section_rows:
            return []
        requests = []
        n = _N_STATS_COLS

        # Row 0: section header — dark blue bg, merged, white bold text
        h = row_offset
        requests.append(self._repeat_cell_bg(h, 0, n, _SECTION_HEADER_COLOR))
        requests.append({
            "mergeCells": {
                "range": {
                    "sheetId": self._sheet_id,
                    "startRowIndex": h, "endRowIndex": h + 1,
                    "startColumnIndex": 0, "endColumnIndex": n,
                },
                "mergeType": "MERGE_ALL",
            }
        })
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": self._sheet_id,
                    "startRowIndex": h, "endRowIndex": h + 1,
                    "startColumnIndex": 0, "endColumnIndex": n,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {
                            "bold": True,
                            "fontSize": 11,
                            "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                        }
                    }
                },
                "fields": "userEnteredFormat.textFormat",
            }
        })

        # Row 1: sub-header — light gray bg, bold
        if len(section_rows) > 1:
            sh = row_offset + 1
            requests.append(self._repeat_cell_bg(sh, 0, n, _SUBHEADER_COLOR))
            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": self._sheet_id,
                        "startRowIndex": sh, "endRowIndex": sh + 1,
                        "startColumnIndex": 0, "endColumnIndex": n,
                    },
                    "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                    "fields": "userEnteredFormat.textFormat",
                }
            })

        # Data rows: color type label cells (A–B only)
        for i, row in enumerate(section_rows[2:]):
            row_idx    = row_offset + 2 + i
            type_label = str(row[0]) if row[0] else ""
            if type_label == "captain":
                requests.append(self._repeat_cell_bg(row_idx, 0, 2, _CAPTAIN_COLOR))
            elif type_label == "sub":
                requests.append(self._repeat_cell_bg(row_idx, 0, 2, _SUB_COLOR))

        return requests
