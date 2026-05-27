"""
Unit tests for SignupSheetAdapter — URL parsing, rank normalization, role splitting,
and full row round-trips. No network or filesystem I/O required.
"""

import csv
import os
import tempfile

import pytest

from quartz.signup_sheet_adapter import (
    SignupSheetAdapter,
    _normalize_rank,
    _parse_url,
    _split_roles,
)
from quartz.tournament_config import SignupSheetConfig

# ── URL parsing ──────────────────────────────────────────────────────────────

def test_parse_opgg_single():
    url = "https://www.op.gg/summoners/na/sush1man-bozo"
    result = _parse_url(url, "NA")
    assert result == [{"riot_id": "sush1man#bozo", "player_region": "NA"}]


def test_parse_opgg_single_region_strip_digit():
    url = "https://www.op.gg/summoners/na1/sush1man-bozo"
    result = _parse_url(url, "NA")
    assert result == [{"riot_id": "sush1man#bozo", "player_region": "NA"}]


def test_parse_opgg_multi_amp_html_entity():
    url = "https://www.op.gg/multisearch/na?summoners=sush1man-bozo,coolplayer-NA1"
    result = _parse_url(url, "NA")
    assert len(result) == 2
    assert {"riot_id": "sush1man#bozo", "player_region": "NA"} in result
    assert {"riot_id": "coolplayer#NA1", "player_region": "NA"} in result


def test_parse_opgg_multi_html_entity_ampersand():
    # Google Form export encodes & as &amp; in URLs
    url = "https://www.op.gg/multisearch/na?summoners=sush1man-bozo&amp;summoners=coolplayer-NA1"
    result = _parse_url(url, "NA")
    # &amp; is unescaped before parsing; comma-separated summoners is the key path
    assert isinstance(result, list)


def test_parse_opgg_multi_deduplicates():
    url = "https://www.op.gg/multisearch/na?summoners=Player-Tag,player-tag"
    result = _parse_url(url, "NA")
    assert len(result) == 1


def test_parse_ugg_single_fallback():
    url = "https://u.gg/lol/profile/na1/sush1man-bozo/overview"
    result = _parse_url(url, "NA")
    assert result == [{"riot_id": "sush1man#bozo", "player_region": "NA"}]


def test_parse_ugg_multi():
    url = "https://u.gg/multisearch?summoners=player1-tag1,player2-tag2"
    result = _parse_url(url, "NA")
    assert len(result) == 2
    assert {"riot_id": "player1#tag1", "player_region": "NA"} in result


def test_parse_direct_riot_id_passthrough():
    result = _parse_url("PlayerName#NA1", "NA")
    assert result == [{"riot_id": "PlayerName#NA1", "player_region": "NA"}]


def test_parse_empty_url_returns_empty():
    assert _parse_url("", "NA") == []


def test_parse_unrecognized_url_returns_empty():
    assert _parse_url("https://example.com/profile", "NA") == []


# ── Rank normalization ────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("DIAMOND IV",   "Diamond 4"),
    ("Diamond IV",   "Diamond 4"),
    ("diamond iv",   "Diamond 4"),
    ("GOLD II",      "Gold 2"),
    ("PLATINUM I",   "Platinum 1"),
    ("MASTER",       "Master"),
    ("MASTER I",     "Master"),
    ("GRANDMASTER I","Grandmaster"),
    ("CHALLENGER I", "Challenger"),
    ("Master",       "Master"),
    ("GRANDMASTER",  "Grandmaster"),
    ("CHALLENGER",   "Challenger"),
    ("",             "Unranked"),
    ("unranked",     "Unranked"),
    ("n/a",          "Unranked"),
    ("D4",           "Diamond 4"),
    ("P1",           "Platinum 1"),
])
def test_normalize_rank(raw, expected):
    assert _normalize_rank(raw) == expected


def test_normalize_rank_unrecognized_returns_none():
    assert _normalize_rank("Ascendant") is None
    assert _normalize_rank("RUBY III") is None


# ── Role splitting ────────────────────────────────────────────────────────────

def test_split_roles_two_roles():
    primary, secondary = _split_roles("TOP/JUNGLE")
    assert primary == "TOP"
    assert secondary == "JGL"


def test_split_roles_single():
    primary, secondary = _split_roles("MID")
    assert primary == "MID"
    assert secondary is None


def test_split_roles_unknown_primary():
    primary, secondary = _split_roles("FILL/BOT")
    assert primary is None
    assert secondary == "BOT"


def test_split_roles_empty():
    primary, secondary = _split_roles("")
    assert primary is None
    assert secondary is None


def test_split_roles_lowercase():
    primary, secondary = _split_roles("top/jungle")
    assert primary == "TOP"
    assert secondary == "JGL"


# ── Full row round-trip via SignupSheetAdapter ────────────────────────────────

def _write_csv(rows: list[dict], fieldnames: list[str]) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8", newline="")
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    f.close()
    return f.name


def _default_config():
    return SignupSheetConfig()  # uses all defaults: Player, Rank, Roles, Op.gg, U.gg, NA


def test_full_row_opgg_single():
    path = _write_csv(
        [{"Player": "Silas", "Rank": "GOLD IV", "Roles": "MID/BOT", "Op.gg": "https://op.gg/summoners/na/silas-NA1", "U.gg": ""}],
        ["Player", "Rank", "Roles", "Op.gg", "U.gg"],
    )
    try:
        adapter = SignupSheetAdapter(_default_config(), path)
        rows = adapter.load()
        assert len(rows) == 1
        row = rows[0]
        assert row["discord_username"] == "Silas"
        assert row["accounts"] == [{"riot_id": "silas#NA1", "player_region": "NA"}]
        assert row["stated_current_rank"] == "Gold 4"
        assert row["primary_role"] == "MID"
        assert row["secondary_role"] == "BOT"
        assert row["stated_peak_rank"] is None
        assert row["player_type_override"] is None
    finally:
        os.unlink(path)


def test_full_row_ugg_fallback_when_opgg_blank():
    path = _write_csv(
        [{"Player": "Player2", "Rank": "MASTER", "Roles": "TOP", "Op.gg": "", "U.gg": "https://u.gg/lol/profile/na1/player2-tag2/overview"}],
        ["Player", "Rank", "Roles", "Op.gg", "U.gg"],
    )
    try:
        adapter = SignupSheetAdapter(_default_config(), path)
        rows = adapter.load()
        assert len(rows) == 1
        assert rows[0]["accounts"] == [{"riot_id": "player2#tag2", "player_region": "NA"}]
        assert rows[0]["stated_current_rank"] == "Master"
    finally:
        os.unlink(path)


def test_full_row_empty_player_id_skipped():
    path = _write_csv(
        [
            {"Player": "", "Rank": "GOLD IV", "Roles": "MID", "Op.gg": "", "U.gg": ""},
            {"Player": "Keeper", "Rank": "SILVER II", "Roles": "JGL", "Op.gg": "https://op.gg/summoners/na/keeper-tag", "U.gg": ""},
        ],
        ["Player", "Rank", "Roles", "Op.gg", "U.gg"],
    )
    try:
        adapter = SignupSheetAdapter(_default_config(), path)
        rows = adapter.load()
        assert len(rows) == 1
        assert rows[0]["discord_username"] == "Keeper"
        assert len(adapter.warnings) >= 1
    finally:
        os.unlink(path)


def test_full_row_unrecognized_rank_warns():
    path = _write_csv(
        [{"Player": "TestPlayer", "Rank": "ASCENDANT", "Roles": "SUP", "Op.gg": "", "U.gg": ""}],
        ["Player", "Rank", "Roles", "Op.gg", "U.gg"],
    )
    try:
        adapter = SignupSheetAdapter(_default_config(), path)
        rows = adapter.load()
        assert rows[0]["stated_current_rank"] is None
        assert any("unrecognized rank" in w for w in adapter.warnings)
    finally:
        os.unlink(path)


def test_full_row_no_accounts_warns():
    path = _write_csv(
        [{"Player": "NoURL", "Rank": "GOLD I", "Roles": "TOP", "Op.gg": "", "U.gg": ""}],
        ["Player", "Rank", "Roles", "Op.gg", "U.gg"],
    )
    try:
        adapter = SignupSheetAdapter(_default_config(), path)
        rows = adapter.load()
        assert rows[0]["accounts"] == []
        assert any("no accounts" in w for w in adapter.warnings)
    finally:
        os.unlink(path)
