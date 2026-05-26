"""Tests for ScrapeResult and AccountScrapeOutcome."""

import pytest
from quartz.scrapers.core.scrape_result import AccountScrapeOutcome, ScrapeResult


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def mixed_result():
    r = ScrapeResult(task="OPGG_SCRAPE_RANK")
    r.outcomes = [
        AccountScrapeOutcome(riot_id="OK#NA1",      player_id="okplayer",      status="ok"),
        AccountScrapeOutcome(riot_id="Gone#NA1",    player_id="goneplayer",    status="not_found",  detail="name changed"),
        AccountScrapeOutcome(riot_id="Bad#NA1",     player_id="badplayer",     status="soft_error", detail="split_rank is None for S2026"),
        AccountScrapeOutcome(riot_id="Slow#NA1",    player_id="slowplayer",    status="timeout",    detail="update button timed out"),
        AccountScrapeOutcome(riot_id="Flagged#NA1", player_id="flaggedplayer", status="flagged",    detail="account level 42 < 100"),
        AccountScrapeOutcome(riot_id="Arc#NA1",     player_id="arcplayer",     status="skipped",    detail="archived"),
    ]
    return r


# ------------------------------------------------------------------
# Derived views
# ------------------------------------------------------------------

def test_ok_view(mixed_result):
    assert len(mixed_result.ok) == 1
    assert mixed_result.ok[0].riot_id == "OK#NA1"


def test_retryable_includes_not_found_soft_error_timeout(mixed_result):
    riot_ids = {o.riot_id for o in mixed_result.retryable}
    assert riot_ids == {"Gone#NA1", "Bad#NA1", "Slow#NA1"}


def test_retryable_excludes_ok_flagged_skipped(mixed_result):
    riot_ids = {o.riot_id for o in mixed_result.retryable}
    assert "OK#NA1" not in riot_ids
    assert "Flagged#NA1" not in riot_ids
    assert "Arc#NA1" not in riot_ids


def test_flagged_view(mixed_result):
    assert len(mixed_result.flagged) == 1
    assert mixed_result.flagged[0].riot_id == "Flagged#NA1"


def test_errors_excludes_ok_and_skipped(mixed_result):
    statuses = {o.status for o in mixed_result.errors}
    assert "ok" not in statuses
    assert "skipped" not in statuses


# ------------------------------------------------------------------
# soft_error subtype matching
# ------------------------------------------------------------------

def test_retryable_matches_soft_error_subtypes():
    r = ScrapeResult(task="OPGG_SCRAPE_RANK")
    r.outcomes = [
        AccountScrapeOutcome(riot_id="A#NA1", player_id="a", status="soft_error_no_rank"),
        AccountScrapeOutcome(riot_id="B#NA1", player_id="b", status="soft_error_no_peak"),
    ]
    assert len(r.retryable) == 2


# ------------------------------------------------------------------
# retry_hint
# ------------------------------------------------------------------

def test_retry_hint_returns_none_when_nothing_retryable():
    r = ScrapeResult(task="OPGG_SCRAPE_RANK")
    r.outcomes = [AccountScrapeOutcome(riot_id="OK#NA1", player_id="okplayer", status="ok")]
    assert r.retry_hint("opgg") is None


def test_retry_hint_lists_unique_player_ids_sorted(mixed_result):
    hint = mixed_result.retry_hint("opgg")
    assert hint is not None
    assert hint.startswith("quartz scrape opgg --players ")
    players_part = hint.split("--players ")[1]
    players = players_part.split(",")
    assert players == sorted(players)
    assert set(players) == {"badplayer", "goneplayer", "slowplayer"}


def test_retry_hint_deduplicates_player_with_multiple_retryable_accounts():
    r = ScrapeResult(task="OPGG_SCRAPE_RANK")
    r.outcomes = [
        AccountScrapeOutcome(riot_id="AccA#NA1", player_id="dupeplayer", status="not_found"),
        AccountScrapeOutcome(riot_id="AccB#NA1", player_id="dupeplayer", status="soft_error"),
    ]
    hint = r.retry_hint("opgg")
    assert hint == "quartz scrape opgg --players dupeplayer"


# ------------------------------------------------------------------
# summary
# ------------------------------------------------------------------

def test_summary_format(mixed_result):
    s = mixed_result.summary()
    assert "OPGG_SCRAPE_RANK" in s
    assert "1/5 ok" in s   # 5 non-skipped outcomes


def test_summary_no_errors():
    r = ScrapeResult(task="TEST_TASK")
    r.outcomes = [AccountScrapeOutcome(riot_id="X#NA1", player_id="x", status="ok")]
    assert "TEST_TASK: 1/1 ok" == r.summary()


# ------------------------------------------------------------------
# Empty result
# ------------------------------------------------------------------

def test_empty_result_views():
    r = ScrapeResult(task="OPGG_SCRAPE_RANK")
    assert r.ok == []
    assert r.retryable == []
    assert r.flagged == []
    assert r.errors == []
    assert r.retry_hint("opgg") is None
