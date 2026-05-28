"""
Tests for ChampionEntry.merge_split() and _merge_dpm_into_existing().

merge_split rules:
  - More games  → new source overwrites all non-None fields it provides.
  - Same/fewer  → gap-fill only: writes fields that are currently None, never overwrites.
  - No match    → appends new split.

_merge_dpm_into_existing rules:
  - New (champion, role) not yet in pool → appended.
  - Existing (champion, role) found      → merge_split() applied per season.
  - dpm_scraped_at always updated.
  - Entries from other roles (e.g. role="ALL" from OPGG) are untouched.
"""

from datetime import datetime, timezone

from quartz.models.champion_data import (
    AccountChampionData,
    AccountQueueChampionPool,
    ChampionEntry,
    ChampionSplitStats,
)
from quartz.tasks.dpm_scrape_champ import _merge_dpm_into_existing, _strip_dpm_data
from quartz.tasks.opgg_scrape_champ import _strip_opgg_champ_data

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_split(season="S2026", games=10, wins=6, source="dpm", **kwargs) -> ChampionSplitStats:
    return ChampionSplitStats(
        lol_season=season,
        games=games,
        wins=wins,
        losses=games - wins,
        win_rate=wins / games if games else None,
        source=source,
        **kwargs,
    )


def make_entry(champion="Amumu", role="ALL", splits=None) -> ChampionEntry:
    entry = ChampionEntry(champion=champion, role=role)
    for s in (splits or []):
        entry.splits.append(s)
    return entry


def make_pool(*entries) -> AccountQueueChampionPool:
    pool = AccountQueueChampionPool()
    pool.champions = list(entries)
    return pool


def make_champ_data(solo_pool=None, flex_pool=None) -> AccountChampionData:
    data = AccountChampionData()
    if solo_pool:
        data.solo = solo_pool
    if flex_pool:
        data.flex = flex_pool
    return data


# ---------------------------------------------------------------------------
# merge_split — append
# ---------------------------------------------------------------------------

def test_merge_split_appends_new_season():
    entry = make_entry(splits=[make_split("S2025", games=10)])
    entry.merge_split(make_split("S2026", games=5))
    assert len(entry.splits) == 2
    seasons = {s.lol_season for s in entry.splits}
    assert seasons == {"S2025", "S2026"}


def test_merge_split_appends_when_no_splits():
    entry = make_entry()
    entry.merge_split(make_split("S2026", games=10))
    assert len(entry.splits) == 1
    assert entry.splits[0].games == 10


# ---------------------------------------------------------------------------
# merge_split — more games wins (overwrite mode)
# ---------------------------------------------------------------------------

def test_merge_split_more_games_overwrites_shared_fields():
    entry = make_entry(splits=[make_split("S2026", games=30, wins=15, source="opgg")])
    entry.merge_split(make_split("S2026", games=40, wins=28, source="dpm"))
    s = entry.get_split("S2026")
    assert s.games == 40
    assert s.wins == 28
    assert s.source == "dpm"


def test_merge_split_more_games_fills_none_fields():
    entry = make_entry(splits=[make_split("S2026", games=30, source="opgg")])
    entry.merge_split(make_split("S2026", games=40, cs_per_min=6.5, source="dpm"))
    s = entry.get_split("S2026")
    assert s.cs_per_min == 6.5


def test_merge_split_more_games_overwrites_non_exclusive_fields():
    """New source with more games takes over shared fields (not source-exclusive ones)."""
    entry = make_entry(splits=[make_split("S2026", games=30, wins=10, source="opgg")])
    entry.merge_split(make_split("S2026", games=40, wins=28, kda=3.5, source="dpm"))
    s = entry.get_split("S2026")
    assert s.games == 40    # overwritten — dpm has more games
    assert s.wins  == 28    # overwritten
    assert s.kda   == 3.5   # filled in (shared field)


# ---------------------------------------------------------------------------
# merge_split — same/fewer games (gap-fill mode)
# ---------------------------------------------------------------------------

def test_merge_split_fewer_games_does_not_overwrite():
    entry = make_entry(splits=[make_split("S2026", games=50, wins=30, source="opgg")])
    entry.merge_split(make_split("S2026", games=40, wins=10, source="dpm"))
    s = entry.get_split("S2026")
    assert s.games == 50
    assert s.wins == 30
    assert s.source == "opgg"


def test_merge_split_fewer_games_fills_none_fields():
    """DPM has fewer games but provides cs_per_min which OPGG didn't set."""
    entry = make_entry(splits=[make_split("S2026", games=50, source="opgg")])
    entry.merge_split(make_split("S2026", games=40, cs_per_min=7.1, kda=3.2, source="dpm"))
    s = entry.get_split("S2026")
    assert s.cs_per_min == 7.1
    assert s.kda == 3.2
    assert s.games == 50  # unchanged


def test_merge_split_same_games_is_gap_fill_only():
    entry = make_entry(splits=[make_split("S2026", games=30, wins=20, op_score=7.0, source="opgg")])
    entry.merge_split(make_split("S2026", games=30, wins=15, op_score=5.0, cs_per_min=6.0, source="dpm"))
    s = entry.get_split("S2026")
    assert s.wins == 20        # not overwritten
    assert s.op_score == 7.0   # not overwritten
    assert s.cs_per_min == 6.0 # filled in (was None)


def test_merge_split_fewer_games_does_not_overwrite_non_none_field():
    """Existing field already set — fewer-games source must not touch it."""
    entry = make_entry(splits=[make_split("S2026", games=50, kda=4.0, source="opgg")])
    entry.merge_split(make_split("S2026", games=30, kda=2.0, source="dpm"))
    assert entry.get_split("S2026").kda == 4.0


# ---------------------------------------------------------------------------
# merge_split — season isolation
# ---------------------------------------------------------------------------

def test_merge_split_only_affects_matching_season():
    entry = make_entry(splits=[
        make_split("S2025", games=20, wins=10),
        make_split("S2026", games=30, wins=15),
    ])
    entry.merge_split(make_split("S2026", games=40, wins=25))
    assert entry.get_split("S2025").games == 20  # untouched
    assert entry.get_split("S2026").games == 40  # updated


# ---------------------------------------------------------------------------
# _merge_dpm_into_existing — pool-level behaviour
# ---------------------------------------------------------------------------

def test_merge_dpm_appends_new_champion():
    existing = make_champ_data(solo_pool=make_pool())
    new_entry = make_entry("Jinx", role="BOT", splits=[make_split("S2026", games=10)])
    new = make_champ_data(solo_pool=make_pool(new_entry))

    _merge_dpm_into_existing(existing, new)

    assert len(existing.solo.champions) == 1
    assert existing.solo.champions[0].champion == "Jinx"


def test_merge_dpm_updates_existing_champion():
    old_split = make_split("S2026", games=20, wins=10)
    existing = make_champ_data(solo_pool=make_pool(make_entry("Amumu", "JGL", splits=[old_split])))

    new_split = make_split("S2026", games=30, wins=20, cs_per_min=5.5)
    new = make_champ_data(solo_pool=make_pool(make_entry("Amumu", "JGL", splits=[new_split])))

    _merge_dpm_into_existing(existing, new)

    s = existing.solo.champions[0].get_split("S2026")
    assert s.games == 30
    assert s.cs_per_min == 5.5


def test_merge_dpm_does_not_touch_different_role():
    """role='ALL' entry (from OPGG) should be left alone when DPM writes role='JGL'."""
    opgg_entry = make_entry("Amumu", role="ALL", splits=[
        make_split("S2026", games=50, op_score=7.5, source="opgg")
    ])
    dpm_entry = make_entry("Amumu", role="JGL", splits=[
        make_split("S2026", games=40, cs_per_min=6.0, source="dpm")
    ])

    existing = make_champ_data(solo_pool=make_pool(opgg_entry))
    new = make_champ_data(solo_pool=make_pool(dpm_entry))

    _merge_dpm_into_existing(existing, new)

    pool = existing.solo
    assert len(pool.champions) == 2  # ALL and JGL both present
    all_entry = pool.get_champion("Amumu", role="ALL")
    jgl_entry = pool.get_champion("Amumu", role="JGL")
    assert all_entry.get_split("S2026").op_score == 7.5   # OPGG data untouched
    assert jgl_entry.get_split("S2026").cs_per_min == 6.0  # DPM entry appended


def test_merge_dpm_updates_dpm_scraped_at():
    ts = datetime(2026, 5, 25, tzinfo=timezone.utc)
    new_pool = AccountQueueChampionPool(dpm_scraped_at=ts)
    existing = make_champ_data(solo_pool=AccountQueueChampionPool())
    new = AccountChampionData(solo=new_pool)

    _merge_dpm_into_existing(existing, new)

    assert existing.solo.dpm_scraped_at == ts


def test_merge_dpm_flex_and_solo_independent():
    solo_entry = make_entry("Jinx", role="BOT", splits=[make_split("S2026", games=15)])
    flex_entry = make_entry("Amumu", role="JGL", splits=[make_split("S2026", games=8)])

    existing = make_champ_data(
        solo_pool=make_pool(),
        flex_pool=make_pool(),
    )
    new = make_champ_data(
        solo_pool=make_pool(solo_entry),
        flex_pool=make_pool(flex_entry),
    )

    _merge_dpm_into_existing(existing, new)

    assert existing.solo.get_champion("Jinx", role="BOT") is not None
    assert existing.flex.get_champion("Amumu", role="JGL") is not None
    assert existing.solo.get_champion("Amumu", role="JGL") is None  # not in solo


# ---------------------------------------------------------------------------
# Source-exclusive field protection (dpm_score / op_score)
# ---------------------------------------------------------------------------

def test_dpm_score_never_overwritten_by_opgg():
    """op_score winning on games must not wipe dpm_score."""
    entry = make_entry(splits=[make_split("S2026", games=40, dpm_score=7.2, source="dpm")])
    entry.merge_split(make_split("S2026", games=50, op_score=8.0, source="opgg"))
    s = entry.get_split("S2026")
    assert s.dpm_score == 7.2   # dpm owns this — untouched
    assert s.op_score  == 8.0   # opgg fills its own field


def test_op_score_never_overwritten_by_dpm():
    """dpm winning on games must not wipe op_score."""
    entry = make_entry(splits=[make_split("S2026", games=30, op_score=6.5, source="opgg")])
    entry.merge_split(make_split("S2026", games=40, dpm_score=7.8, source="dpm"))
    s = entry.get_split("S2026")
    assert s.op_score  == 6.5   # opgg owns this — untouched
    assert s.dpm_score == 7.8   # dpm fills its own field


# ---------------------------------------------------------------------------
# role="ALL" merge scenario (DPM-ALL vs OPGG-ALL)
# ---------------------------------------------------------------------------

def test_all_role_opgg_wins_on_games():
    """OPGG-ALL has more games — it should win shared fields but DPM fills unique ones."""
    entry = make_entry("Amumu", role="ALL")
    entry.merge_split(make_split("S2026", games=40, cs_per_min=6.2, kda=3.5, source="dpm"))
    entry.merge_split(make_split("S2026", games=50, wins=30, op_score=7.5, source="opgg"))

    s = entry.get_split("S2026")
    assert s.games == 50          # OPGG wins
    assert s.op_score == 7.5      # OPGG unique field
    assert s.cs_per_min == 6.2    # DPM unique field — preserved (gap-fill from first merge)
    assert s.source == "opgg"


def test_all_role_dpm_wins_on_games():
    """DPM-ALL has more games — it overwrites shared fields, OPGG unique fields are gap-filled."""
    entry = make_entry("Amumu", role="ALL")
    entry.merge_split(make_split("S2026", games=50, wins=30, op_score=7.5, source="opgg"))
    entry.merge_split(make_split("S2026", games=60, wins=40, cs_per_min=6.2, kda=3.5, source="dpm"))

    s = entry.get_split("S2026")
    assert s.games == 60          # DPM wins
    assert s.wins == 40           # DPM overwrites
    assert s.cs_per_min == 6.2   # DPM unique field
    assert s.op_score == 7.5     # OPGG unique field — preserved (gap-fill, DPM didn't set it)
    assert s.source == "dpm"


# ---------------------------------------------------------------------------
# New OPGG-exclusive fields — never overwritten by DPM even with more games
# ---------------------------------------------------------------------------

def test_opgg_exclusive_fields_preserved_when_dpm_wins_games():
    """DPM has more games — OPGG-exclusive fields (expected_op_score, op_laning_score,
    expected_laning_pct, avg_vision_score) must survive unchanged."""
    entry = make_entry(splits=[make_split(
        "S2026", games=40, source="opgg",
        expected_op_score=6.8,
        op_laning_score=51.0,
        expected_laning_pct=49.5,
        avg_vision_score=31.0,
    )])
    entry.merge_split(make_split(
        "S2026", games=60, source="dpm",
        kda=3.5, cs_per_min=7.0,
    ))
    s = entry.get_split("S2026")
    assert s.expected_op_score  == 6.8    # opgg-exclusive — untouched
    assert s.op_laning_score    == 51.0   # opgg-exclusive — untouched
    assert s.expected_laning_pct == 49.5  # opgg-exclusive — untouched
    assert s.avg_vision_score   == 31.0   # opgg-exclusive — untouched
    assert s.kda                == 3.5    # contested — DPM wins (more games)
    assert s.cs_per_min         == 7.0    # contested — DPM wins


def test_dpm_exclusive_fields_preserved_when_opgg_wins_games():
    """OPGG has more games — DPM-exclusive fields (cs_at_15, vision_score_per_min,
    solo_kills_per_game, kill_participation_pct, gold_share_pct, first_blood_rate)
    must survive unchanged."""
    entry = make_entry(splits=[make_split(
        "S2026", games=40, source="dpm",
        cs_at_15=80.0,
        vision_score_per_min=1.2,
        solo_kills_per_game=0.4,
        kill_participation_pct=65.0,
        gold_share_pct=22.5,
        first_blood_rate=0.15,
    )])
    entry.merge_split(make_split(
        "S2026", games=60, source="opgg",
        op_score=7.2, kda=4.0,
    ))
    s = entry.get_split("S2026")
    assert s.cs_at_15               == 80.0   # dpm-exclusive — untouched
    assert s.vision_score_per_min   == 1.2    # dpm-exclusive — untouched
    assert s.solo_kills_per_game    == 0.4    # dpm-exclusive — untouched
    assert s.kill_participation_pct == 65.0   # dpm-exclusive — untouched
    assert s.gold_share_pct         == 22.5   # dpm-exclusive — untouched
    assert s.first_blood_rate       == 0.15   # dpm-exclusive — untouched
    assert s.op_score               == 7.2    # opgg-exclusive — filled
    assert s.kda                    == 4.0    # contested — OPGG wins (more games)


def test_contested_fields_use_more_games_winner():
    """kda, dpm, damage_share_pct, cs_per_min, gpm are contested — more-games source wins."""
    entry = make_entry(splits=[make_split(
        "S2026", games=30, source="dpm",
        kda=3.0, dpm=200.0, damage_share_pct=15.0, cs_per_min=6.5, gpm=280.0,
    )])
    entry.merge_split(make_split(
        "S2026", games=50, source="opgg",
        kda=4.5, dpm=240.0, damage_share_pct=18.0, cs_per_min=7.2, gpm=310.0,
    ))
    s = entry.get_split("S2026")
    assert s.kda              == 4.5    # OPGG wins (50 > 30)
    assert s.dpm              == 240.0
    assert s.damage_share_pct == 18.0
    assert s.cs_per_min       == 7.2
    assert s.gpm              == 310.0


# ---------------------------------------------------------------------------
# "multi" source — set when both DPM-exclusive and OPGG-exclusive fields present
# ---------------------------------------------------------------------------

def test_source_becomes_multi_when_both_contribute():
    entry = make_entry(splits=[make_split("S2026", games=40, source="dpm", dpm_score=7.2)])
    entry.merge_split(make_split("S2026", games=30, source="opgg", op_score=6.5))
    assert entry.get_split("S2026").source == "multi"


def test_source_stays_single_when_only_one_source():
    entry = make_entry(splits=[make_split("S2026", games=40, source="dpm", kda=3.0)])
    entry.merge_split(make_split("S2026", games=30, source="opgg", kda=2.5))
    # No exclusive fields from either → source unchanged (DPM had more games, stays "dpm")
    assert entry.get_split("S2026").source == "dpm"


# ---------------------------------------------------------------------------
# _strip_dpm_data — multi split handling
# ---------------------------------------------------------------------------

def test_strip_dpm_removes_pure_dpm_split():
    entry = make_entry(splits=[make_split("S2026", games=40, source="dpm", dpm_score=7.0)])
    data = make_champ_data(solo_pool=make_pool(entry))
    _strip_dpm_data(data)
    assert data.solo.get_champion("Amumu", role="ALL") is None


def test_strip_dpm_preserves_opgg_exclusive_on_multi_split():
    """Multi split: stripping DPM keeps op_score/expected_op_score, clears dpm_score."""
    entry = make_entry()
    entry.merge_split(make_split("S2026", games=50, source="dpm", dpm_score=7.2, kda=3.0))
    entry.merge_split(make_split("S2026", games=40, source="opgg", op_score=6.5, expected_op_score=5.9))
    assert entry.get_split("S2026").source == "multi"

    data = make_champ_data(solo_pool=make_pool(entry))
    _strip_dpm_data(data)

    surviving = data.solo.get_champion("Amumu", role="ALL")
    assert surviving is not None
    s = surviving.get_split("S2026")
    assert s.source           == "opgg"
    assert s.op_score         == 6.5    # preserved
    assert s.expected_op_score == 5.9   # preserved
    assert s.dpm_score        is None   # stripped
    assert s.kda              is None   # stripped (contested — DPM owned it)
    assert s.games            == 0      # reset — DPM owned the game count


def test_strip_dpm_removes_multi_split_when_no_opgg_exclusive_data():
    """Multi split with no actual OPGG exclusive data → dropped entirely."""
    entry = make_entry()
    # Force a "multi" label without OPGG exclusive fields by manually setting source
    entry.splits.append(make_split("S2026", games=50, source="multi", dpm_score=7.2))
    data = make_champ_data(solo_pool=make_pool(entry))
    _strip_dpm_data(data)
    assert data.solo.get_champion("Amumu", role="ALL") is None


# ---------------------------------------------------------------------------
# _strip_opgg_champ_data — multi split handling
# ---------------------------------------------------------------------------

def test_strip_opgg_removes_pure_opgg_split():
    entry = make_entry(splits=[make_split("S2026", games=30, source="opgg", op_score=6.5)])
    data = make_champ_data(solo_pool=make_pool(entry))
    _strip_opgg_champ_data(data)
    assert data.solo.get_champion("Amumu", role="ALL") is None


def test_strip_opgg_preserves_dpm_exclusive_on_multi_split():
    """Multi split: stripping OPGG keeps dpm_score/cs_at_15, clears op_score."""
    entry = make_entry()
    entry.merge_split(make_split("S2026", games=50, source="dpm", dpm_score=7.2, cs_at_15=85.0, kda=3.5))
    entry.merge_split(make_split("S2026", games=40, source="opgg", op_score=6.5))
    assert entry.get_split("S2026").source == "multi"

    data = make_champ_data(solo_pool=make_pool(entry))
    _strip_opgg_champ_data(data)

    surviving = data.solo.get_champion("Amumu", role="ALL")
    assert surviving is not None
    s = surviving.get_split("S2026")
    assert s.source    == "dpm"
    assert s.dpm_score == 7.2    # preserved
    assert s.cs_at_15  == 85.0   # preserved
    assert s.kda       == 3.5    # preserved (DPM owned contested fields)
    assert s.games     == 50     # preserved (DPM owned the game count)
    assert s.op_score  is None   # stripped
