"""
ScrapeResult
Structured result contract for all Quartz scrape tasks.

Every scrape task returns a ScrapeResult instead of a raw tuple.
AccountScrapeOutcome tracks per-account status; ScrapeResult aggregates
them and generates retry hints for the CLI.

Status values:
  "ok"           — scraped and saved successfully
  "not_found"    — site returned no profile (name change / wrong region likely)
  "soft_error"   — profile found but data is incomplete (detail says what's missing)
  "timeout"      — page or update button exceeded timeout
  "parse_error"  — element found but value could not be parsed
  "flagged"      — saved but account flagged for review (low level, suspicious data)
  "skipped"      — intentionally skipped (archived account, filtered out)

soft_error subtypes (e.g. "soft_error_no_rank") are added post-integration-testing
as real failure modes are observed — they are plain strings, not an enum.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AccountScrapeOutcome:
    """Result for a single account scrape attempt."""
    riot_id: str
    player_id: str
    status: str                  # see module docstring for valid values
    detail: Optional[str] = None  # human-readable context; required for soft_error


@dataclass
class ScrapeResult:
    """Aggregate result from one scrape task run."""
    task: str                                              # e.g. "OPGG_SCRAPE_RANK"
    outcomes: list[AccountScrapeOutcome] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Derived views
    # ------------------------------------------------------------------

    @property
    def ok(self) -> list[AccountScrapeOutcome]:
        return [o for o in self.outcomes if o.status == "ok"]

    @property
    def retryable(self) -> list[AccountScrapeOutcome]:
        """not_found, soft_error*, and timeout — all worth re-running."""
        return [
            o for o in self.outcomes
            if o.status in ("not_found", "timeout") or o.status.startswith("soft_error")
        ]

    @property
    def flagged(self) -> list[AccountScrapeOutcome]:
        return [o for o in self.outcomes if o.status == "flagged"]

    @property
    def errors(self) -> list[AccountScrapeOutcome]:
        """All non-ok, non-skipped, non-flagged outcomes."""
        return [o for o in self.outcomes if o.status not in ("ok", "skipped", "flagged")]

    # ------------------------------------------------------------------
    # CLI helpers
    # ------------------------------------------------------------------

    def retry_hint(self, cli_verb: str) -> Optional[str]:
        """
        Ready-to-run CLI command to re-scrape all retryable accounts.
        Returns None if nothing needs retrying.
        e.g. "quartz scrape opgg --players PlayerA,PlayerB"
        """
        if not self.retryable:
            return None
        player_ids = sorted({o.player_id for o in self.retryable})
        return f"quartz scrape {cli_verb} --players {','.join(player_ids)}"

    def summary(self) -> str:
        """One-line summary for CLI output."""
        total = len([o for o in self.outcomes if o.status != "skipped"])
        ok_count = len(self.ok)
        err_count = len(self.errors)
        flag_count = len(self.flagged)

        parts = [f"{self.task}: {ok_count}/{total} ok"]
        if err_count:
            parts.append(f"{err_count} errors")
        if flag_count:
            parts.append(f"{flag_count} flagged")
        return ", ".join(parts)
