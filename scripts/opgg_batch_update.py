"""
opgg_batch_update.py
Runs OPGG_SCRAPE_RANK across all player profiles, one account at a time.

Progress is tracked per riot_id with four states:
  completed      — scraped cleanly, skipped on re-run
  soft_failed    — scraped but data incomplete (e.g. current rank missing), retried on re-run
  failed         — hard error during scrape, retried on re-run
  needs_riot_id  — OP.GG profile not found (name changed), skipped on re-run, needs manual fix

Only `completed` and `needs_riot_id` accounts are skipped. Both failed states are retried.

Usage:
    python3 opgg_batch_update.py           # run all remaining
    python3 opgg_batch_update.py --reset   # clear progress and start fresh
    python3 opgg_batch_update.py --status  # show progress summary
"""

import sys
import os
import json

from quartz.tournament_config import load_tournament_config
from quartz.pipeline_runner import PipelineRunner, Task
from quartz.player_registry import PlayerRegistry
from quartz.utils.color_utils import info_print, success_print, warning_print, error_print


def load_progress(progress_file: str) -> dict:
    defaults = {"completed": [], "soft_failed": [], "failed": [], "needs_riot_id": []}
    if os.path.exists(progress_file):
        with open(progress_file, "r") as f:
            data = json.load(f)
        for key, val in defaults.items():
            data.setdefault(key, val)
        return data
    return defaults


def save_progress(progress: dict, progress_file: str) -> None:
    with open(progress_file, "w") as f:
        json.dump(progress, f, indent=2)


def _remove_from_all(progress: dict, riot_id: str) -> None:
    for key in ("completed", "soft_failed", "failed", "needs_riot_id"):
        if riot_id in progress[key]:
            progress[key].remove(riot_id)


def mark_complete(progress: dict, riot_id: str, progress_file: str) -> None:
    _remove_from_all(progress, riot_id)
    progress["completed"].append(riot_id)
    save_progress(progress, progress_file)


def mark_soft_failed(progress: dict, riot_id: str, progress_file: str) -> None:
    _remove_from_all(progress, riot_id)
    progress["soft_failed"].append(riot_id)
    save_progress(progress, progress_file)


def mark_failed(progress: dict, riot_id: str, progress_file: str) -> None:
    _remove_from_all(progress, riot_id)
    progress["failed"].append(riot_id)
    save_progress(progress, progress_file)


def mark_needs_riot_id(progress: dict, riot_id: str, progress_file: str) -> None:
    _remove_from_all(progress, riot_id)
    progress["needs_riot_id"].append(riot_id)
    save_progress(progress, progress_file)


def main():
    config = load_tournament_config()
    progress_file = os.path.join(config.abs_data_dir, "opgg_enrich_progress.json")
    registry = PlayerRegistry(config.abs_players_dir)

    if "--reset" in sys.argv:
        if os.path.exists(progress_file):
            os.remove(progress_file)
            success_print("Progress cleared — all accounts will be re-run.")
        else:
            info_print("No progress file found — nothing to reset.")
        return

    all_profiles = registry.load_all()

    all_accounts = [
        (profile.effective_id, account.riot_id)
        for profile in all_profiles
        for account in profile.accounts
        if not account.archived
    ]

    progress      = load_progress(progress_file)
    completed     = set(progress["completed"])
    soft_failed   = set(progress["soft_failed"])
    failed        = set(progress["failed"])
    needs_riot_id = set(progress["needs_riot_id"])

    skip_set = completed | needs_riot_id

    if "--status" in sys.argv:
        remaining = [(pid, rid) for pid, rid in all_accounts if rid not in skip_set]
        print(f"\n  Total accounts:    {len(all_accounts)}")
        print(f"  Completed:         {len(completed)}")
        print(f"  Soft failed:       {len(soft_failed)}  (incomplete data, will retry)")
        print(f"  Failed:            {len(failed)}  (hard error, will retry)")
        print(f"  Needs riot_id:     {len(needs_riot_id)}  (name changed — needs manual fix, skipped)")
        print(f"  Remaining:         {len(remaining)}")
        if soft_failed:
            print(f"\n  Soft failed accounts:")
            for rid in sorted(soft_failed):
                print(f"    - {rid}")
        if failed:
            print(f"\n  Hard failed accounts:")
            for rid in sorted(failed):
                print(f"    - {rid}")
        if needs_riot_id:
            print(f"\n  Needs riot_id (name changed — update Account.riot_id manually):")
            for rid in sorted(needs_riot_id):
                print(f"    - {rid}")
        return

    remaining = [(pid, rid) for pid, rid in all_accounts if rid not in skip_set]

    if not remaining:
        success_print("All accounts completed. Use --reset to start fresh.")
        return

    info_print(
        f"Mass OPGG enrich: {len(remaining)} remaining / "
        f"{len(completed)} done / {len(soft_failed)} soft retry / "
        f"{len(failed)} hard retry / {len(needs_riot_id)} needs_riot_id / "
        f"{len(all_accounts)} total"
    )

    runner = PipelineRunner(config)

    succeeded           = 0
    soft_fail_count     = 0
    failed_count        = 0
    needs_riot_id_count = 0

    for i, (player_id, riot_id) in enumerate(remaining, 1):
        info_print(f"\n[{i}/{len(remaining)}] {player_id} — {riot_id}")
        try:
            task_soft_errors, task_not_found = runner.run_task(Task.OPGG_SCRAPE_RANK, players=[riot_id])
            if riot_id in task_not_found:
                mark_needs_riot_id(progress, riot_id, progress_file)
                warning_print(f"  {riot_id} — profile not found (name changed), marked needs_riot_id")
                needs_riot_id_count += 1
            elif riot_id in task_soft_errors:
                mark_soft_failed(progress, riot_id, progress_file)
                soft_fail_count += 1
            else:
                mark_complete(progress, riot_id, progress_file)
                succeeded += 1
        except KeyboardInterrupt:
            warning_print(f"\nInterrupted after {succeeded} accounts. Progress saved — re-run to continue.")
            break
        except Exception as e:
            error_print(f"  Error scraping {riot_id}: {e}")
            mark_failed(progress, riot_id, progress_file)
            failed_count += 1

    print()
    success_print(
        f"Done: {succeeded} completed, {soft_fail_count} soft failed, "
        f"{failed_count} hard failed, {needs_riot_id_count} need riot_id update."
    )


if __name__ == "__main__":
    main()
