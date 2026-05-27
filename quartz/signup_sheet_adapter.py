"""
SignupSheetAdapter
Converts a raw tournament signup sheet CSV (Google Form export) into the
normalized row format expected by local_csv_ingest.

Handles:
  - OP.GG single-profile URLs  → one Riot ID
  - OP.GG multisearch URLs     → multiple Riot IDs
  - U.GG single/multisearch    → same, as fallback when OP.GG absent
  - Direct "Name#Tag" input    → passed through as-is
  - Rank normalization         → "DIAMOND IV" → "Diamond 4"
  - Role splitting             → "TOP/JUNGLE" → ("TOP", "JGL")

Output row shape (same as LocalCSVInput.load()):
  {
    "discord_username":     str,
    "player_type_override": None,
    "accounts":             [{"riot_id": str, "player_region": str}, ...],
    "stated_current_rank":  Optional[str],
    "stated_peak_rank":     None,          # not collected on signup sheets
    "primary_role":         Optional[str],
    "secondary_role":       Optional[str],
  }
"""

import csv
import html
import os
import urllib.parse
from typing import Optional

from quartz.constants import APEX_RANKS, RANK_ALIASES, RANK_ORDER, ROLE_ALIASES
from quartz.utils.logging import info_print, success_print, warning_print

_ROMAN = {"IV": "4", "III": "3", "II": "2", "I": "1"}

# Region normalization: strip trailing digit (NA1 → NA, EUW1 → EUW, KR → KR)
def _normalize_region(raw: str, default: str) -> str:
    upper = raw.upper().strip()
    if upper and upper[-1].isdigit():
        upper = upper[:-1]
    return upper or default


def sanitize_riot_id(riot_id: str) -> str:
    """Strip URL/HTML-entity artifacts from a Riot ID tag.

    Google Sheets copy-paste can mangle '&region=na1' into '®ion=na1'
    (HTML entity &reg; = ®) which then gets appended to the tag portion.
    Strip anything from '&' or '®' onward in the tag.
    """
    if "#" not in riot_id:
        return riot_id
    name, tag = riot_id.split("#", 1)
    # Split on & or ® and discard the rest
    for sep in ("&", "®"):
        tag = tag.split(sep)[0]
    return f"{name}#{tag}"


def _riot_id_from_slug(slug: str) -> Optional[str]:
    """Convert a URL slug to a Riot ID. 'sush1man-bozo' → 'sush1man#bozo'."""
    slug = urllib.parse.unquote(slug.strip())
    parts = slug.rsplit("-", 1)
    if len(parts) == 2 and parts[0] and parts[1]:
        return sanitize_riot_id(f"{parts[0]}#{parts[1]}")
    return None


def _parse_opgg_single(url: str, default_region: str) -> list[dict]:
    parsed = urllib.parse.urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    try:
        idx = parts.index("summoners")
        region_raw = parts[idx + 1] if idx + 1 < len(parts) else None
        slug = parts[idx + 2] if idx + 2 < len(parts) else None
    except (ValueError, IndexError):
        return []
    if not slug:
        return []
    riot_id = _riot_id_from_slug(slug)
    if not riot_id:
        return []
    region = _normalize_region(region_raw, default_region) if region_raw else default_region
    return [{"riot_id": riot_id, "player_region": region}]


def _parse_opgg_multi(url: str, default_region: str) -> list[dict]:
    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query)
    summoners_str = params.get("summoners", [""])[0]
    accounts = []
    seen = set()
    for entry in summoners_str.split(","):
        entry = urllib.parse.unquote(entry.strip())
        if not entry:
            continue
        riot_id = sanitize_riot_id(entry) if "#" in entry else _riot_id_from_slug(entry)
        if riot_id and riot_id.lower() not in seen:
            seen.add(riot_id.lower())
            accounts.append({"riot_id": riot_id, "player_region": default_region})
    return accounts


def _parse_ugg_single(url: str, default_region: str) -> list[dict]:
    parsed = urllib.parse.urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    try:
        idx = parts.index("profile")
        region_raw = parts[idx + 1] if idx + 1 < len(parts) else None
        slug = parts[idx + 2] if idx + 2 < len(parts) else None
    except (ValueError, IndexError):
        return []
    if not slug:
        return []
    riot_id = _riot_id_from_slug(slug)
    if not riot_id:
        return []
    region = _normalize_region(region_raw, default_region) if region_raw else default_region
    return [{"riot_id": riot_id, "player_region": region}]


def _parse_ugg_multi(url: str, default_region: str) -> list[dict]:
    # u.gg multisearch uses Name-TAG slugs (no #)
    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query)
    summoners_str = params.get("summoners", [""])[0]
    accounts = []
    seen = set()
    for entry in summoners_str.split(","):
        entry = urllib.parse.unquote(entry.strip())
        if not entry:
            continue
        riot_id = sanitize_riot_id(entry) if "#" in entry else _riot_id_from_slug(entry)
        if riot_id and riot_id.lower() not in seen:
            seen.add(riot_id.lower())
            accounts.append({"riot_id": riot_id, "player_region": default_region})
    return accounts


def _parse_url(url: str, default_region: str) -> list[dict]:
    url = html.unescape(url.strip())
    if not url:
        return []
    if "#" in url and "://" not in url:
        return [{"riot_id": url, "player_region": default_region}]
    if "op.gg" in url:
        if "multisearch" in url:
            return _parse_opgg_multi(url, default_region)
        return _parse_opgg_single(url, default_region)
    if "u.gg" in url:
        if "multisearch" in url:
            return _parse_ugg_multi(url, default_region)
        return _parse_ugg_single(url, default_region)
    return []


def _normalize_rank(raw: str) -> Optional[str]:
    """Normalize a signup-sheet rank string to canonical form.

    Handles: 'DIAMOND IV' → 'Diamond 4', 'MASTER' → 'Master',
             short codes via RANK_ALIASES, blank/unranked → 'Unranked'.
    """
    normalized = raw.strip()
    if not normalized or normalized.lower() in ("unranked", "n/a"):
        return "Unranked"

    aliased = RANK_ALIASES.get(normalized) or RANK_ALIASES.get(normalized.title())
    if aliased and aliased in RANK_ORDER:
        return aliased

    parts = normalized.upper().split()
    if len(parts) == 2:
        tier, division = parts
        tier_title = tier.title()
        if tier_title in APEX_RANKS:
            return tier_title
        arabic = _ROMAN.get(division, division)
        candidate = f"{tier_title} {arabic}"
        if candidate in RANK_ORDER:
            return candidate
    elif len(parts) == 1:
        candidate = parts[0].title()
        if candidate in RANK_ORDER:
            return candidate

    return None


def _split_roles(raw: str) -> tuple[Optional[str], Optional[str]]:
    """Split 'TOP/JUNGLE' → ('TOP', 'JGL') via ROLE_ALIASES."""
    parts = [p.strip().upper() for p in raw.split("/") if p.strip()]
    primary   = ROLE_ALIASES.get(parts[0]) if len(parts) > 0 else None
    secondary = ROLE_ALIASES.get(parts[1]) if len(parts) > 1 else None
    return primary, secondary


class SignupSheetAdapter:
    """
    Reads a raw signup sheet CSV and returns normalized player rows.

    [param] config:    SignupSheetConfig from TournamentConfig
    [param] file_path: absolute path to the signup sheet CSV
    """

    def __init__(self, config, file_path: str):
        self.config = config
        self.file_path = file_path
        self.warnings: list[str] = []

    def load(self) -> list[dict]:
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"SignupSheetAdapter: file not found: {self.file_path}")

        with open(self.file_path, newline="", encoding="utf-8-sig") as f:
            raw_rows = list(csv.DictReader(f))

        info_print(f"SignupSheetAdapter: read {len(raw_rows)} rows from {self.file_path}")

        rows = [self._clean_row(i, row) for i, row in enumerate(raw_rows)]
        rows = [r for r in rows if r is not None]

        success_print(f"SignupSheetAdapter: processed {len(rows)} players")
        for w in self.warnings:
            warning_print(f"  {w}")

        return rows

    def _clean_row(self, index: int, row: dict) -> Optional[dict]:
        cfg = self.config
        player_id = row.get(cfg.player_id, "").strip()
        if not player_id:
            self.warnings.append(f"Row {index + 1}: empty player ID — skipping")
            return None

        opgg_raw = row.get(cfg.opgg_url, "").strip()
        ugg_raw  = row.get(cfg.ugg_url,  "").strip()
        rank_raw = row.get(cfg.rank,     "").strip()
        roles_raw = row.get(cfg.roles,   "").strip()

        accounts = _parse_url(opgg_raw, cfg.default_region)
        if not accounts:
            accounts = _parse_url(ugg_raw, cfg.default_region)
        if not accounts:
            self.warnings.append(f"Row {index + 1} ({player_id}): no accounts parsed from OP.GG or U.GG")

        stated_rank = _normalize_rank(rank_raw)
        if rank_raw and stated_rank is None:
            self.warnings.append(f"Row {index + 1} ({player_id}): unrecognized rank '{rank_raw}'")

        primary, secondary = _split_roles(roles_raw)
        if roles_raw and primary is None:
            self.warnings.append(f"Row {index + 1} ({player_id}): unrecognized roles '{roles_raw}'")

        return {
            "discord_username":     player_id,
            "player_type_override": None,
            "accounts":             accounts,
            "stated_current_rank":  stated_rank,
            "stated_peak_rank":     None,
            "primary_role":         primary,
            "secondary_role":       secondary,
        }
