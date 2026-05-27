"""Tests for PlayerProfile model helpers — flags, I/O, mutation."""

import os
import tempfile
from datetime import datetime, timezone

import pytest

from quartz.models.player_profile import Account, AccountFlag, PlayerProfile, SeasonData


def _now():
    return datetime.now(timezone.utc)


def _bare_profile(**kwargs) -> PlayerProfile:
    defaults = dict(
        discord_id="testplayer",
        season_data=[SeasonData(season="GCS-S4")],
        accounts=[],
        created_at=_now(),
        last_updated_at=_now(),
    )
    defaults.update(kwargs)
    return PlayerProfile(**defaults)


# ── Account._migrate_legacy_fields ─────────────────────────────────────────

def test_migrate_non_dict_passthrough():
    sentinel = object()
    result = Account._migrate_legacy_fields(sentinel)
    assert result is sentinel


def test_migrate_update_riot_id_adds_name_changed_flag():
    data = {"riot_id": "x#NA1", "update_riot_id": True, "flags": []}
    result = Account._migrate_legacy_fields(data)
    assert any(
        (f.get("flag_type") if isinstance(f, dict) else f.flag_type) == "name_changed"
        for f in result["flags"]
    )


def test_migrate_update_riot_id_no_duplicate_flag():
    existing = {"flag_type": "name_changed", "auto": True, "detail": "already set"}
    data = {"riot_id": "x#NA1", "update_riot_id": True, "flags": [existing]}
    result = Account._migrate_legacy_fields(data)
    name_changed = [
        f for f in result["flags"]
        if (f.get("flag_type") if isinstance(f, dict) else f.flag_type) == "name_changed"
    ]
    assert len(name_changed) == 1


# ── account_flagged ─────────────────────────────────────────────────────────

def test_account_flagged_true_when_active_flag():
    account = Account(
        riot_id="x#NA1",
        flags=[AccountFlag(flag_type="low_level", dismissed=False)],
    )
    assert account.account_flagged is True


def test_account_flagged_false_when_only_dismissed():
    account = Account(
        riot_id="x#NA1",
        flags=[AccountFlag(flag_type="low_level", dismissed=True)],
    )
    assert account.account_flagged is False


def test_account_flagged_false_when_no_flags():
    account = Account(riot_id="x#NA1")
    assert account.account_flagged is False


# ── add_auto_flag / clear_auto_flag / get_flag ─────────────────────────────

def test_add_auto_flag_creates_new():
    account = Account(riot_id="x#NA1")
    account.add_auto_flag("low_volume", detail="only 5 games")
    assert len(account.flags) == 1
    assert account.flags[0].flag_type == "low_volume"
    assert account.flags[0].detail == "only 5 games"


def test_add_auto_flag_updates_existing_active():
    account = Account(
        riot_id="x#NA1",
        flags=[AccountFlag(flag_type="low_volume", detail="old detail", auto=True)],
    )
    account.add_auto_flag("low_volume", detail="new detail")
    assert len(account.flags) == 1
    assert account.flags[0].detail == "new detail"


def test_add_auto_flag_does_not_override_dismissed():
    account = Account(
        riot_id="x#NA1",
        flags=[AccountFlag(flag_type="low_volume", auto=True, dismissed=True)],
    )
    account.add_auto_flag("low_volume", detail="should be ignored")
    assert account.flags[0].dismissed is True
    assert len(account.flags) == 1


def test_clear_auto_flag_removes_flag():
    account = Account(
        riot_id="x#NA1",
        flags=[
            AccountFlag(flag_type="low_volume", auto=True),
            AccountFlag(flag_type="smurf_peak", auto=True),
        ],
    )
    account.clear_auto_flag("low_volume")
    assert len(account.flags) == 1
    assert account.flags[0].flag_type == "smurf_peak"


def test_get_flag_returns_matching():
    account = Account(
        riot_id="x#NA1",
        flags=[AccountFlag(flag_type="smurf_peak")],
    )
    flag = account.get_flag("smurf_peak")
    assert flag is not None
    assert flag.flag_type == "smurf_peak"


def test_get_flag_returns_none_when_missing():
    account = Account(riot_id="x#NA1")
    assert account.get_flag("nonexistent") is None


# ── profile_flagged ─────────────────────────────────────────────────────────

def test_profile_flagged_true_when_all_accounts_flagged():
    profile = _bare_profile(accounts=[
        Account(riot_id="a#NA1", flags=[AccountFlag(flag_type="low_level")]),
        Account(riot_id="b#NA1", flags=[AccountFlag(flag_type="smurf_peak")]),
    ])
    assert profile.profile_flagged is True


def test_profile_flagged_false_when_one_account_clean():
    profile = _bare_profile(accounts=[
        Account(riot_id="a#NA1", flags=[AccountFlag(flag_type="low_level")]),
        Account(riot_id="b#NA1"),
    ])
    assert profile.profile_flagged is False


def test_profile_flagged_false_when_no_accounts():
    profile = _bare_profile(accounts=[])
    assert profile.profile_flagged is False


def test_profile_flagged_ignores_archived_accounts():
    profile = _bare_profile(accounts=[
        Account(riot_id="a#NA1", archived=True),
        Account(riot_id="b#NA1", flags=[AccountFlag(flag_type="low_level")]),
    ])
    assert profile.profile_flagged is True


# ── from_json_file / to_json_file ───────────────────────────────────────────

def test_from_json_file_raises_when_missing():
    with pytest.raises(FileNotFoundError):
        PlayerProfile.from_json_file("/nonexistent/path/player.json")


def test_roundtrip_json_file():
    profile = _bare_profile(discord_id="roundtrip")
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "roundtrip.json")
        profile.to_json_file(path)
        loaded = PlayerProfile.from_json_file(path)
    assert loaded.discord_id == "roundtrip"
    assert loaded.season_data[0].season == "GCS-S4"


# ── upsert_season ───────────────────────────────────────────────────────────

def test_upsert_season_replaces_existing():
    profile = _bare_profile(season_data=[
        SeasonData(season="GCS-S4", player_type="main"),
    ])
    profile.upsert_season(SeasonData(season="GCS-S4", player_type="captain"))
    assert len(profile.season_data) == 1
    assert profile.season_data[0].player_type == "captain"


def test_upsert_season_appends_new():
    profile = _bare_profile(season_data=[SeasonData(season="GCS-S4")])
    profile.upsert_season(SeasonData(season="GCS-S5"))
    assert len(profile.season_data) == 2


# ── from_csv_row defaults ───────────────────────────────────────────────────

def test_from_csv_row_invalid_player_type_defaults_to_main():
    profile = PlayerProfile.from_csv_row(
        {"discord_username": "user", "player_type_override": "zzz_invalid", "accounts": []},
        "GCS-S4",
    )
    assert profile.season_data[0].player_type == "main"


# ── touch ───────────────────────────────────────────────────────────────────

def test_touch_updates_last_updated_at():
    profile = _bare_profile()
    before = profile.last_updated_at
    profile.touch()
    assert profile.last_updated_at >= before
