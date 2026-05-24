"""Tests for rank_score() — the numeric backbone of the PV model."""

import pytest
from quartz.constants import rank_score, RANK_ORDER


def test_unranked_returns_none():
    assert rank_score("Unranked") is None


def test_empty_returns_none():
    assert rank_score("") is None
    assert rank_score(None) is None


def test_unrecognized_returns_none():
    assert rank_score("SuperDiamond") is None


def test_challenger_is_lowest():
    assert rank_score("Challenger") < rank_score("Grandmaster")
    assert rank_score("Grandmaster") < rank_score("Master")


def test_iron4_is_highest():
    assert rank_score("Iron 4") > rank_score("Bronze 4")
    assert rank_score("Iron 4") > rank_score("Challenger")


def test_lp_interpolation_non_apex():
    # Higher LP in a tier = lower (better) score
    score_0lp = rank_score("Diamond 1")
    score_50lp = rank_score("Diamond 1 50 LP")
    score_100lp = rank_score("Diamond 1 100 LP")
    assert score_0lp > score_50lp > score_100lp


def test_lp_interpolation_apex():
    # Apex ranks: LP is unbounded, higher LP = lower score
    score_0lp = rank_score("Master")
    score_100lp = rank_score("Master 100 LP")
    score_500lp = rank_score("Master 500 LP")
    assert score_0lp > score_100lp > score_500lp


def test_every_rank_in_order_has_score():
    # Every rank in RANK_ORDER must return a finite score
    for rank in RANK_ORDER:
        score = rank_score(rank)
        assert score is not None, f"rank_score({rank!r}) returned None"
        assert score < 9999, f"rank_score({rank!r}) = {score} — unexpected sentinel"


def test_monotonically_non_increasing():
    # Each successive rank in RANK_ORDER should have an equal or lower score.
    # Iron 4-1 are all scored 85.0 by design — sub-tier Iron differences don't matter
    # for amateur tournament scouting. Everything above Iron is strictly decreasing.
    scores = [rank_score(r) for r in RANK_ORDER]
    for i in range(len(scores) - 1):
        assert scores[i] >= scores[i + 1], (
            f"Score went UP: rank_score({RANK_ORDER[i]}) = {scores[i]} "
            f"< rank_score({RANK_ORDER[i+1]}) = {scores[i+1]}"
        )
