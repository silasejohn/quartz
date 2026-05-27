"""Tests for AccountRankData.is_complete, AccountQueueChampionPool.dpm_complete / opgg_complete,
and backwards-compat loading of existing JSONs that lack the new scrape state fields."""

import json
import os
import tempfile
from datetime import datetime, timezone

from quartz.models.champion_data import AccountChampionData, AccountQueueChampionPool
from quartz.models.player_profile import Account, PlayerProfile
from quartz.models.rank_data import AccountRankData, SplitRankEntry


def _now():
    return datetime.now(timezone.utc)


# ── AccountRankData.is_complete ──────────────────────────────────────────────

def test_is_complete_true_when_scraped_with_current_split():
    rd = AccountRankData(
        solo_splits=[SplitRankEntry(season="S2026", split_rank="Gold 2")],
        scraped_at=_now(),
        last_scrape_error=None,
    )
    assert rd.is_complete("S2026") is True


def test_is_complete_false_when_scraped_at_missing():
    rd = AccountRankData(
        solo_splits=[SplitRankEntry(season="S2026", split_rank="Gold 2")],
        scraped_at=None,
    )
    assert rd.is_complete("S2026") is False


def test_is_complete_false_when_last_scrape_error_set():
    rd = AccountRankData(
        solo_splits=[SplitRankEntry(season="S2026", split_rank="Gold 2")],
        scraped_at=_now(),
        last_scrape_error="timeout",
    )
    assert rd.is_complete("S2026") is False


def test_is_complete_false_when_current_split_missing():
    rd = AccountRankData(
        solo_splits=[SplitRankEntry(season="S2025", split_rank="Gold 2")],
        scraped_at=_now(),
        last_scrape_error=None,
    )
    assert rd.is_complete("S2026") is False


def test_is_complete_false_when_no_splits():
    rd = AccountRankData(scraped_at=_now(), last_scrape_error=None)
    assert rd.is_complete("S2026") is False


# ── AccountQueueChampionPool.dpm_complete ────────────────────────────────────

def test_dpm_complete_true_when_scraped_for_current_split():
    pool = AccountQueueChampionPool(
        dpm_scraped_at=_now(),
        dpm_scraped_for_split="S2026",
        dpm_last_scrape_error=None,
    )
    assert pool.dpm_complete("S2026") is True


def test_dpm_complete_false_when_scraped_for_old_split():
    pool = AccountQueueChampionPool(
        dpm_scraped_at=_now(),
        dpm_scraped_for_split="S2025",
        dpm_last_scrape_error=None,
    )
    assert pool.dpm_complete("S2026") is False


def test_dpm_complete_false_when_dpm_scraped_at_missing():
    pool = AccountQueueChampionPool(
        dpm_scraped_at=None,
        dpm_scraped_for_split="S2026",
    )
    assert pool.dpm_complete("S2026") is False


def test_dpm_complete_false_when_error_set():
    pool = AccountQueueChampionPool(
        dpm_scraped_at=_now(),
        dpm_scraped_for_split="S2026",
        dpm_last_scrape_error="parse failed",
    )
    assert pool.dpm_complete("S2026") is False


# ── AccountQueueChampionPool.opgg_complete ───────────────────────────────────

def test_opgg_complete_true_when_scraped_no_error():
    pool = AccountQueueChampionPool(
        opgg_scraped_at=_now(),
        opgg_last_scrape_error=None,
    )
    assert pool.opgg_complete() is True


def test_opgg_complete_false_when_opgg_scraped_at_missing():
    pool = AccountQueueChampionPool(opgg_scraped_at=None)
    assert pool.opgg_complete() is False


def test_opgg_complete_false_when_error_set():
    pool = AccountQueueChampionPool(
        opgg_scraped_at=_now(),
        opgg_last_scrape_error="browser crash",
    )
    assert pool.opgg_complete() is False


# ── Backwards compat — existing JSONs without scrape state fields ────────────

def _bare_profile_json(**extra) -> dict:
    return {
        "discord_id": "legacy_user",
        "season_data": [],
        "accounts": [{
            "riot_id": "LegacyAcc#NA1",
            "player_region": "NA",
            **extra,
        }],
        "created_at": "2025-01-01T00:00:00+00:00",
        "last_updated_at": "2025-01-01T00:00:00+00:00",
    }


def test_account_loads_without_rank_data_scrape_fields():
    """rank_data without scrape state fields must still load."""
    raw = _bare_profile_json(rank_data={
        "solo_splits": [{"season": "S2025", "split_rank": "Gold 1"}],
        "flex_splits": [],
        "scraped_at": "2025-01-01T00:00:00+00:00",
        "source": "opgg",
        # scrape_started_at and last_scrape_error intentionally absent
    })
    profile = PlayerProfile.model_validate(raw)
    rd = profile.accounts[0].rank_data
    assert rd is not None
    assert rd.scrape_started_at is None
    assert rd.last_scrape_error is None
    assert rd.scraped_at is not None


def test_account_loads_without_champion_data_scrape_fields():
    """champion_data without scrape state fields must still load."""
    raw = _bare_profile_json(champion_data={
        "solo": {
            "champions": [],
            # All new scrape state fields absent
        },
        "flex": {
            "champions": [],
        },
    })
    profile = PlayerProfile.model_validate(raw)
    cd = profile.accounts[0].champion_data
    assert cd is not None
    assert cd.solo.dpm_scraped_at is None
    assert cd.solo.opgg_scraped_at is None
    assert cd.solo.dpm_last_scrape_error is None
    assert cd.solo.opgg_last_scrape_error is None


def test_account_loads_with_old_dpm_scraped_at_field():
    """champion_data with old-style dpm_scraped_at (no split key) must still load."""
    raw = _bare_profile_json(champion_data={
        "solo": {
            "champions": [],
            "dpm_scraped_at": "2025-06-01T00:00:00+00:00",
            # dpm_scraped_for_split absent
        },
        "flex": {"champions": []},
    })
    profile = PlayerProfile.model_validate(raw)
    cd = profile.accounts[0].champion_data
    assert cd.solo.dpm_scraped_at is not None
    assert cd.solo.dpm_scraped_for_split is None
