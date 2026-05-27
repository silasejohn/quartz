"""
Account flag evaluation — auto-computes structured flags on Account objects.

See docs/flags.md for the full type catalogue, evaluation timing, and CLI reference.

Public API:
  evaluate_account_flags(account, weights) -> None   re-evaluates all auto flags in-place
"""

from quartz.constants import PAST_YEAR_SEASONS, SEASON_ORDER, rank_score
from quartz.models.player_profile import Account, AccountFlag
from quartz.models.pv_model import PVWeights

# Known flag type constants — import these instead of using raw strings
FLAG_LOW_LEVEL    = "low_level"
FLAG_LOW_VOLUME   = "low_volume"
FLAG_SMURF_PEAK   = "smurf_peak"
FLAG_SMURF_JUMP   = "smurf_jump"
FLAG_NAME_CHANGED = "name_changed"

# Flag types managed by auto-evaluation (FLAG_NAME_CHANGED is set by the rank scraper, not here)
_AUTO_EVAL_TYPES = {FLAG_LOW_LEVEL, FLAG_LOW_VOLUME, FLAG_SMURF_PEAK, FLAG_SMURF_JUMP}

_PAST_YEAR_SET = set(PAST_YEAR_SEASONS)
_EMERALD_THRESHOLD = 46.8    # rank_score("Emerald 4 0 LP") — Emerald+ boundary
_LOW_LEVEL_THRESHOLD = 100
_LOW_LEVEL_SMURF_THRESHOLD = 200
_LOW_VOLUME_GAMES = 50

# Human-readable descriptions shown in quartz view and quartz flags list
FLAG_DESCRIPTIONS: dict[str, str] = {
    FLAG_LOW_LEVEL:    f"account level below {_LOW_LEVEL_THRESHOLD} — possible new or smurf account",
    FLAG_LOW_VOLUME:   f"fewer than {_LOW_VOLUME_GAMES} ranked games across all past-year splits",
    FLAG_SMURF_PEAK:   "high peak rank on a low-level account — likely a smurf",
    FLAG_SMURF_JUMP:   "rank jumped suspiciously relative to account level",
    FLAG_NAME_CHANGED: "Riot ID changed since last scrape — verify it's the same account",
}

_SEASON_IDX: dict[str, int] = {s: i for i, s in enumerate(SEASON_ORDER)}


def evaluate_account_flags(account: Account, weights: PVWeights) -> None:
    """
    Re-evaluate all auto-computed flags on the account in-place.

    Clears stale auto flags for managed types, then re-adds any that still apply.
    Preserves: manual flags (auto=False) and name_changed (set by rank scraper).
    """
    account.flags = [
        f for f in account.flags
        if not (f.auto and f.flag_type in _AUTO_EVAL_TYPES)
    ]

    _check_low_level(account)

    if not account.rank_data:
        return

    _check_low_volume(account)
    _check_smurf_peak(account)
    _check_smurf_jump(account, weights.smurf_jump_threshold)


# ------------------------------------------------------------------
# Individual flag checks
# ------------------------------------------------------------------

def _check_low_level(account: Account) -> None:
    if account.account_level is not None and account.account_level < _LOW_LEVEL_THRESHOLD:
        account.flags.append(AccountFlag(
            flag_type=FLAG_LOW_LEVEL,
            detail=f"account level {account.account_level} < {_LOW_LEVEL_THRESHOLD}",
        ))


def _check_low_volume(account: Account) -> None:
    splits = account.rank_data.solo_splits  # type: ignore[union-attr]
    past_year_splits = [s for s in splits if s.season in _PAST_YEAR_SET]
    if not past_year_splits:
        return
    if all(((s.wins or 0) + (s.losses or 0)) < _LOW_VOLUME_GAMES for s in past_year_splits):
        totals = {s.season: (s.wins or 0) + (s.losses or 0) for s in past_year_splits}
        detail = "  ".join(f"{k}: {v}g" for k, v in totals.items())
        account.flags.append(AccountFlag(flag_type=FLAG_LOW_VOLUME, detail=detail))


def _check_smurf_peak(account: Account) -> None:
    if account.account_level is None or account.account_level >= _LOW_LEVEL_SMURF_THRESHOLD:
        return
    for split in account.rank_data.solo_splits:  # type: ignore[union-attr]
        if not split.peak_rank:
            continue
        score = rank_score(split.peak_rank)
        if score is not None and score <= _EMERALD_THRESHOLD:
            account.flags.append(AccountFlag(
                flag_type=FLAG_SMURF_PEAK,
                detail=f"peaked {split.peak_rank} in {split.season} (level {account.account_level})",
            ))
            return


def _check_smurf_jump(account: Account, threshold: float) -> None:
    if account.account_level is None or account.account_level >= _LOW_LEVEL_SMURF_THRESHOLD:
        return

    splits = account.rank_data.solo_splits  # type: ignore[union-attr]
    sorted_splits = sorted(splits, key=lambda s: _SEASON_IDX.get(s.season, 999))

    for i in range(len(sorted_splits) - 1):
        newer = sorted_splits[i]
        older = sorted_splits[i + 1]
        if not older.split_rank or not newer.peak_rank:
            continue
        older_score = rank_score(older.split_rank)
        newer_score = rank_score(newer.peak_rank)
        if older_score is None or newer_score is None:
            continue
        jump = older_score - newer_score  # positive = player climbed (lower score = stronger)
        if jump > threshold:
            account.flags.append(AccountFlag(
                flag_type=FLAG_SMURF_JUMP,
                detail=(
                    f"{older.split_rank} ({older.season}) → "
                    f"{newer.peak_rank} peak ({newer.season}), Δ{jump:.1f} pts"
                ),
            ))
            return
