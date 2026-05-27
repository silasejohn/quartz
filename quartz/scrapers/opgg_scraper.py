"""
OPGGScraper
Scrapes op.gg for per-account rank data across all tracked splits.

Inherits BaseScraper — all element access goes through named selectors
defined in scrapers/configs/opgg_config.yaml. No selectors in this file.

Usage:
    scraper = OPGGScraper()
    scraper.setup()

    ok, url = scraper.navigate_to_profile("PlayerName#NA1", region="NA")
    if ok:
        rank_data = scraper.extract_rank_data(existing=account.rank_data)

    scraper.close()
"""

import re
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.action_chains import ActionChains

from quartz.constants import (
    APEX_RANKS,
    OPGG_CHAMP_SEASON_IDS,
    PEAK_RANK_SEASONS,
    RANK_ALIASES,
    RANK_ORDER,
    SEASON_LABEL_MAP,
    SEASON_ORDER,
)
from quartz.models.rank_data import AccountRankData, SplitRankEntry, merge_split_entries
from quartz.scrapers.core.base_scraper import BaseScraper
from quartz.utils.logging import info_print, warning_print


class OPGGScraper(BaseScraper):
    """
    Scrapes op.gg for rank data and champion page data.

    navigate_to_profile()        — navigate to a player's profile and trigger refresh
    extract_solo_rank_data()     — pull current + peak rank for all tracked splits
    extract_champion_page_data() — navigate to /champions tab, select queue+season,
                                   return (wins, losses, {champion: op_score})
    """

    def __init__(self):
        super().__init__(config_file="opgg_config.yaml", website_timeout=3)

    # ------------------------------------------------------------------
    # Public — navigation
    # ------------------------------------------------------------------

    def navigate_to_profile(self, riot_id: str, region: str = "NA") -> tuple[bool, Optional[str]]:
        """
        Navigate to a player's OP.GG profile and trigger a data refresh.

        [param] riot_id: "PlayerName#TAG"
        [param] region:  "NA", "EUW", etc.
        Returns (True, url) if profile loaded, (False, None) if not found or error.
        """
        url = self._build_profile_url(riot_id, region)
        info_print(f"  OPGGScraper: navigating to {url}")
        self.driver.get(url)
        time.sleep(3)

        if self.wait_for_element("profile_not_found", timeout=3):
            warning_print(f"  OPGGScraper: profile not found for {riot_id}")
            return False, None

        self._trigger_profile_update()
        return True, url

    # ------------------------------------------------------------------
    # Public — extraction
    # ------------------------------------------------------------------

    def extract_solo_rank_data(self, existing: Optional[AccountRankData] = None, current_lol_split: str = None) -> AccountRankData:
        """
        Extract solo queue rank data from the currently open profile page.
        Flex splits on the existing record are carried forward untouched — scraped separately.

        Rules:
          - Current split: always replaced entirely (fresh scrape wins).
          - Historical splits: per-field rank-score merge — keep the better rank value.
            If new data is None for a field, the existing value is preserved.
            If existing has no entry for a split, scraped data is added as-is.
          - Splits in existing not seen in this scrape are carried forward unchanged.

        [param] existing:          the account's current AccountRankData (or None if first scrape)
        [param] current_lol_split: active LoL split key e.g. "S2026" — defaults to SEASON_ORDER[0]
        """
        if current_lol_split is None:
            current_lol_split = SEASON_ORDER[0]

        final_solo_splits: list[SplitRankEntry] = []

        # --- Current split — always replace entirely ---
        current_rank = self._extract_current_rank()

        if current_rank == "Unranked":
            peak_rank = "Unranked"
            wins, losses = 0, 0
            win_rate = None
            info_print(f"  OPGGScraper: current split ({current_lol_split}) -> Unranked / 0W 0L")
        else:
            peak_rank = self._extract_peak_rank()
            wins, losses = self._extract_wins_losses()
            win_rate = (
                round(wins / (wins + losses) * 100, 1)
                if wins is not None and losses is not None and (wins + losses) > 0
                else None
            )
            wl = f"{wins}W {losses}L ({win_rate}%)" if win_rate is not None else "W/L unavailable"
            info_print(f"  OPGGScraper: current split ({current_lol_split}) -> {current_rank} / peak {peak_rank} / {wl}")
        final_solo_splits.append(SplitRankEntry(
            season=current_lol_split,
            split_rank=current_rank,
            peak_rank=peak_rank,
            wins=wins,
            losses=losses,
            win_rate=win_rate,
        ))

        # --- Historical splits — rank-score merge ---
        scraped_history = self._extract_season_history()
        scraped_seasons_seen = {current_lol_split}

        for scraped in scraped_history:
            if scraped.season == current_lol_split:
                continue
            scraped_seasons_seen.add(scraped.season)

            existing_split = existing.get_split(scraped.season, queue="solo") if existing else None
            if existing_split is None:
                info_print(f"  OPGGScraper: {scraped.season} -> {scraped.split_rank} / peak {scraped.peak_rank}")
                final_solo_splits.append(scraped)
            else:
                merged = merge_split_entries(existing_split, scraped)
                info_print(f"  OPGGScraper: {scraped.season} -> {merged.split_rank} / peak {merged.peak_rank}")
                if merged.split_rank != existing_split.split_rank:
                    info_print(f"      ^ split updated: {existing_split.split_rank} -> {merged.split_rank}")
                if merged.peak_rank != existing_split.peak_rank:
                    info_print(f"      ^ peak updated:  {existing_split.peak_rank} -> {merged.peak_rank}")
                final_solo_splits.append(merged)

        # --- Carry over existing solo splits not seen in this scrape ---
        if existing:
            for ex_split in existing.solo_splits:
                if ex_split.season not in scraped_seasons_seen:
                    final_solo_splits.append(ex_split)

        return AccountRankData(
            solo_splits=final_solo_splits,
            flex_splits=existing.flex_splits if existing else [],
            scraped_at=datetime.now(timezone.utc),
            source="opgg",
        )

    def extract_account_level(self) -> Optional[int]:
        """Extract the summoner level badge from the currently open profile page."""
        text = self.get_element_text("account_level", timeout=5)
        if not text:
            warning_print("  OPGGScraper: could not find account level — check account_level selector in opgg_config.yaml")
            return None
        try:
            return int(text.strip())
        except ValueError:
            warning_print(f"  OPGGScraper: could not parse account level from '{text.strip()}'")
            return None

    def extract_all_champion_seasons(
        self,
        riot_id: str,
        region: str,
    ) -> dict[str, dict]:
        """
        Scrape OP.GG champion stats for each tracked season via direct URL navigation —
        no dropdown interaction required. Covers both Solo/Duo and Flex queues.

        URL format: /champions?queue_type=SOLORANKED&season_id=31
        Season IDs are defined in OPGG_CHAMP_SEASON_IDS (constants.py).

        Returns {lol_season: {
            "solo": {"wins": int|None, "losses": int|None, "champions": {name: {"wins", "losses", "op_score"}}},
            "flex": {"wins": int|None, "losses": int|None, "champions": {name: {"wins", "losses", "op_score"}}},
        }}.
        op_score is None for seasons before S2024 S3 (not available on OP.GG).
        """
        results = {}
        for lol_season, season_id in OPGG_CHAMP_SEASON_IDS.items():
            include_op = lol_season in PEAK_RANK_SEASONS
            season_data = {}

            for queue_key, queue_type in [("solo", "SOLORANKED"), ("flex", "FLEXRANKED")]:
                url = self._build_champions_url(riot_id, region, season_id, queue_type)
                info_print(f"  OPGGScraper: {lol_season} {queue_key} → {url}")
                self.driver.get(url)
                time.sleep(3)

                wins, losses, champions = self._extract_champ_season_data(include_op_score=include_op)
                season_data[queue_key] = {"wins": wins, "losses": losses, "champions": champions}
                wl_str = f"{wins}W {losses}L" if wins is not None else "no data"
                info_print(f"    {queue_key}: {wl_str}, {len(champions)} champions")

            results[lol_season] = season_data

        return results

    # ------------------------------------------------------------------
    # Internal — profile update
    # ------------------------------------------------------------------

    def _trigger_profile_update(self) -> None:
        """Click the update button if in IDLE state and wait for completion."""
        update_timeout = self.config.get("timeouts.profile_update", 45)

        if not self.wait_for_element("update_button_idle", timeout=5):
            info_print("  OPGGScraper: profile already up to date")
            return

        info_print("  OPGGScraper: triggering profile update...")
        self.click_element("update_button_idle")

        if self.wait_for_element("update_button_complete", timeout=update_timeout):
            info_print("  OPGGScraper: profile update complete")
        else:
            warning_print("  OPGGScraper: profile update timed out — proceeding with available data")

        time.sleep(2)

    # ------------------------------------------------------------------
    # Internal — champions tab helpers
    # ------------------------------------------------------------------

    def _build_champions_url(
        self, riot_id: str, region: str, season_id: int, queue_type: str
    ) -> str:
        base = self._build_profile_url(riot_id, region) + "/champions"
        return f"{base}?queue_type={queue_type}&season_id={season_id}"

    def _extract_champ_season_data(
        self, include_op_score: bool = False
    ) -> tuple[Optional[int], Optional[int], dict[str, dict]]:
        """
        Read all champion rows from the table and return (total_wins, total_losses, champions).

        Handles two table formats:
          - S2024 S3+ (include_op_score=True, 15 cells):
              cell[3] KDA, cell[4] OP score, cell[5] laning, cell[6] DPM/dmg share,
              cell[7] vision, cell[8] CS/min, cell[9] GPM.
          - S2024 S2 and older (include_op_score=False, 12 cells):
              cell[3] KDA, cell[4] CS/min, cell[5] GPM. All other stats absent.

        champions dict shape:
          {name: {"wins", "losses", "kda", "kills_per_game", "deaths_per_game",
                  "assists_per_game", "op_score", "expected_op_score",
                  "op_laning_score", "expected_laning_pct", "dpm", "damage_share_pct",
                  "avg_vision_score", "cs_per_min", "gpm"}}
        Absent fields are omitted (not set to None) so merge logic never overwrites existing data.
        Returns (None, None, {}) when no data found.
        """
        rows = self.find_elements("champ_table_rows", timeout=5)
        champions: dict[str, dict] = {}
        for row in rows:
            try:
                cells = row.find_elements("xpath", ".//td")
                if len(cells) < 3:
                    continue

                champ_name = cells[1].text.strip().split("\n")[0]
                if not champ_name or champ_name in ("All Champions", "vs"):
                    continue

                played_text = cells[2].text.strip().splitlines()
                mw = re.match(r'(\d+)W', played_text[0]) if len(played_text) > 0 else None
                ml = re.match(r'(\d+)L', played_text[1]) if len(played_text) > 1 else None
                wins   = int(mw.group(1)) if mw else None
                losses = int(ml.group(1)) if ml else None

                cd: dict = {"wins": wins, "losses": losses}

                # cell[3] — KDA (both formats)
                if len(cells) >= 4:
                    cd.update(_parse_kda_cell(cells[3].text.strip().splitlines()))

                if include_op_score and len(cells) >= 10:
                    # New format (S2024 S3+)
                    cd.update(_parse_op_score_cell(cells[4].text.strip().splitlines()))
                    cd.update(_parse_laning_cell(cells[5].text.strip().splitlines()))
                    cd.update(_parse_dpm_cell(cells[6].text.strip().splitlines()))
                    cd.update(_parse_vision_cell(cells[7].text.strip().splitlines()))
                    cd.update(_parse_cs_cell(cells[8].text.strip().splitlines()))
                    cd.update(_parse_gpm_cell(cells[9].text.strip().splitlines()))
                elif not include_op_score and len(cells) >= 6:
                    # Old format (S2024 S2−): CS/min at [4], GPM at [5]
                    cd.update(_parse_cs_cell(cells[4].text.strip().splitlines()))
                    cd.update(_parse_gpm_cell(cells[5].text.strip().splitlines()))

                champions[champ_name] = cd
            except Exception as e:
                warning_print(f"  OPGGScraper: champion row parse error: {e}")

        if not champions:
            return None, None, {}

        total_wins   = sum(cd["wins"]   or 0 for cd in champions.values())
        total_losses = sum(cd["losses"] or 0 for cd in champions.values())
        return total_wins, total_losses, champions

    # ------------------------------------------------------------------
    # Internal — rank extraction
    # ------------------------------------------------------------------

    def _extract_current_rank(self) -> Optional[str]:
        """Extract solo queue rank + LP for the current split."""
        tier_text = self.get_element_text("solo_rank_tier", timeout=10)
        lp_text = self.get_element_text("solo_rank_lp", timeout=5)

        if not tier_text:
            if self.wait_for_element("solo_rank_unranked", timeout=3):
                return "Unranked"
            # Fallback: player has no prior ranked history so no history table exists
            tier_text = self.get_element_text("solo_rank_tier_fallback", timeout=5)
            lp_text   = self.get_element_text("solo_rank_lp_fallback", timeout=3)

        if not tier_text:
            warning_print("  OPGGScraper: could not find current rank — check solo_rank_tier selector in opgg_config.yaml")
            return None

        return self._build_rank_string(tier_text, lp_text)

    def _extract_peak_rank(self) -> Optional[str]:
        """Extract the peak rank + LP for the current split."""
        tier_text = self.get_element_text("peak_rank_tier", timeout=5)
        lp_text   = self.get_element_text("peak_rank_lp",   timeout=5)
        if not tier_text:
            tier_text = self.get_element_text("peak_rank_tier_fallback", timeout=3)
            lp_text   = self.get_element_text("peak_rank_lp_fallback",   timeout=3)
        return self._build_rank_string(tier_text, lp_text) if tier_text else None

    def _extract_wins_losses(self) -> tuple[Optional[int], Optional[int]]:
        """Extract wins and losses for the current split from the 'XW YL' label."""
        text = self.get_element_text("solo_wins_losses", timeout=5)
        if not text:
            text = self.get_element_text("solo_wins_losses_fallback", timeout=3)
        if not text:
            return None, None
        match = re.match(r'(\d+)W\s+(\d+)L', text.strip(), re.IGNORECASE)
        if not match:
            warning_print(f"  OPGGScraper: could not parse wins/losses from '{text.strip()}'")
            return None, None
        return int(match.group(1)), int(match.group(2))

    def _extract_season_history(self) -> list[SplitRankEntry]:
        """
        Extract rank data from the season history table (previous splits).
        For each row, hovers over the rank cell to retrieve the peak rank tooltip.
        Returns entries only for seasons present in SEASON_ORDER.
        """
        initial_rows = self.find_elements("season_history_row", timeout=5)
        if not initial_rows:
            info_print("  OPGGScraper: no season history rows — player has no prior ranked seasons")
            return []

        row_count = len(initial_rows)
        splits = []
        for i in range(row_count):
            try:
                # Re-fetch rows each iteration — hover can trigger DOM re-renders
                # that invalidate previously held element references
                rows = self.find_elements("season_history_row", timeout=5)
                if not rows or i >= len(rows):
                    break
                row = rows[i]

                season_els = row.find_elements("xpath", ".//td[1]/strong")
                rank_els   = row.find_elements("xpath", ".//td[2]//span[contains(@class,'lowercase')]")
                lp_els     = row.find_elements("xpath", ".//td[3]")

                season_text = season_els[0].text.strip() if season_els else None
                rank_text   = rank_els[0].text.strip()   if rank_els   else None
                lp_text     = lp_els[0].text.strip()     if lp_els     else None

                if not season_text or not rank_text:
                    continue

                season = self._map_opgg_season_label(season_text)
                if season is None:
                    continue

                split_rank = self._build_rank_string(rank_text, lp_text)

                # --- Peak rank via hover tooltip ---
                peak_rank = None
                hover_els = row.find_elements("xpath", ".//td[2]//div[@data-tooltip-id='opgg-tooltip']")
                if hover_els:
                    raw_tooltip = self._hover_and_read_tooltip(hover_els[0])
                    if raw_tooltip:
                        peak_rank = self._parse_tooltip_peak_rank(raw_tooltip)

                # Fallback: peak_rank defaults to split_rank
                if peak_rank is None:
                    peak_rank = split_rank
                    if season in PEAK_RANK_SEASONS:
                        warning_print(f"  OPGGScraper: expected peak rank for {season} but tooltip unavailable — falling back to split rank")

                splits.append(SplitRankEntry(
                    season=season,
                    split_rank=split_rank,
                    peak_rank=peak_rank,
                ))
            except Exception as e:
                warning_print(f"  OPGGScraper: error parsing history row: {e}")
                continue

        return splits

    def _hover_and_read_tooltip(self, hover_element) -> Optional[str]:
        """Hover over an element and return the react-tooltip portal text (or None on timeout)."""
        try:
            ActionChains(self.driver).move_to_element(hover_element).perform()
        except WebDriverException:
            return None

        tooltip_xpath = self.config.get_selectors("tooltip_container").get("xpath", "//div[@id='opgg-tooltip']")
        deadline = time.time() + 1.0
        while time.time() < deadline:
            els = self.driver.find_elements("xpath", tooltip_xpath)
            if els:
                text = els[0].text.strip()
                if text:
                    return text
            time.sleep(0.1)
        return None

    def _parse_tooltip_peak_rank(self, tooltip_text: str) -> Optional[str]:
        """
        Parse the peak rank out of a hover tooltip string.

        Observed format:
            Ranked Solo/Duo
            platinum 4       <- split rank (skip this)
            99 LP
            Top Tier
            platinum 1       <- peak rank (this is what we want)
            95 LP

        Strategy: take the rank that appears AFTER the "Top Tier" marker.
        Falls back to scanning for the last rank+LP pair if "Top Tier" is absent.
        """
        lines = [line.strip() for line in tooltip_text.splitlines() if line.strip()]

        # Find everything after "Top Tier"
        try:
            top_tier_idx = next(i for i, line in enumerate(lines) if line.lower() == "top tier")
            peak_lines = lines[top_tier_idx + 1:]
        except StopIteration:
            # No "Top Tier" marker — fall back to last rank+LP pair in tooltip
            peak_lines = lines

        # Extract rank text and LP from the remaining lines
        rank_text = None
        lp_text   = None
        for line in peak_lines:
            lp_match = re.match(r'^(\d+)\s*LP$', line, re.IGNORECASE)
            if lp_match:
                lp_text = lp_match.group(1) + " LP"
                continue
            # Treat as potential rank if it looks like "word digit" or apex name
            if re.match(r'^[A-Za-z]', line):
                rank_text = line

        if rank_text:
            return self._build_rank_string(rank_text, lp_text)
        return None

    # ------------------------------------------------------------------
    # Internal — rank string helpers
    # ------------------------------------------------------------------

    def _build_rank_string(self, tier_text: str, lp_text: Optional[str]) -> Optional[str]:
        """Combine tier and LP into canonical rank string."""
        rank = self._parse_rank_string(tier_text)
        if not rank:
            return None
        lp = self._parse_lp(lp_text) if lp_text else None
        return f"{rank} {lp} LP" if lp is not None else rank

    def _parse_rank_string(self, text: str) -> Optional[str]:
        """
        Normalize a raw rank string from OP.GG to our canonical format.
        e.g. "Diamond II" -> "Diamond 2", "MASTER" -> "Master"
        """
        if not text:
            return None
        text = text.strip()

        # Alias table first (handles "Plat 4", "D1", "Masters", short codes, etc.)
        aliased = RANK_ALIASES.get(text) or RANK_ALIASES.get(text.title())
        if aliased and aliased in RANK_ORDER:
            return aliased

        # Roman numeral division: "Gold IV" -> "Gold 4"
        roman_map = {"IV": "4", "III": "3", "II": "2", "I": "1"}
        for roman, arabic in roman_map.items():
            if text.endswith(f" {roman}"):
                candidate = text[: -len(roman)].strip() + f" {arabic}"
                if candidate in RANK_ORDER:
                    return candidate
                if candidate.title() in RANK_ORDER:
                    return candidate.title()

        candidate = text.title()
        if candidate in RANK_ORDER:
            return candidate

        for apex in APEX_RANKS:
            if text.lower() == apex.lower():
                return apex

        warning_print(f"  OPGGScraper: unrecognized rank string '{text}' — update RANK_ALIASES in constants.py if needed")
        return None

    def _parse_lp(self, text: str) -> Optional[int]:
        """Extract LP integer from strings like '75 LP', '75', 'LP: 75'."""
        if not text:
            return None
        match = re.search(r"(\d+)", text)
        return int(match.group(1)) if match else None

    # ------------------------------------------------------------------
    # Internal — URL / season mapping
    # ------------------------------------------------------------------

    def _build_profile_url(self, riot_id: str, region: str) -> str:
        """Build the OP.GG profile URL for a Riot ID and region."""
        encoded = quote(riot_id.replace("#", "-"), safe="-")
        template = self.config.get("urls.player_profile", "")
        return template.format(region=region.lower(), encoded_riot_id=encoded)

    def _map_opgg_season_label(self, label: str) -> Optional[str]:
        """
        Map a season label string to our SEASON_ORDER key using SEASON_LABEL_MAP
        from constants.py. Returns None if the label is unrecognized.
        """
        season = SEASON_LABEL_MAP.get(label.strip())
        if season is None:
            warning_print(f"  OPGGScraper: unknown season label '{label}' — add to SEASON_LABEL_MAP in constants.py")
        return season


# ------------------------------------------------------------------
# Module-level cell parsers for _extract_champ_season_data
# Each returns a dict of field_name → value for present fields only.
# Absent/unparseable fields are omitted so merge logic preserves existing data.
# ------------------------------------------------------------------

def _safe_float(s: str) -> Optional[float]:
    try:
        return float(s.strip().rstrip("%").replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _parse_kda_cell(lines: list[str]) -> dict:
    """cell[3]: KDA ratio (line 0) + 'K / D / A' (line 1)."""
    result: dict = {}
    is_perfect = lines[0].strip() == "Perfect" if lines else False

    if not is_perfect and lines:
        m = re.match(r'([\d.]+)', lines[0].strip())
        if m:
            result["kda"] = float(m.group(1))

    if len(lines) > 1:
        m = re.match(r'([\d.]+)\s*/\s*([\d.]+)\s*/\s*([\d.]+)', lines[1].strip())
        if m:
            k, d, a = float(m.group(1)), float(m.group(2)), float(m.group(3))
            result["kills_per_game"] = k
            result["deaths_per_game"] = d
            result["assists_per_game"] = a
            if is_perfect:
                result["kda"] = (k + a) / 1.0

    return result


def _parse_op_score_cell(lines: list[str]) -> dict:
    """cell[4]: avg op_score (line 0) + expected_op_score (line 1)."""
    result: dict = {}
    if lines:
        v = _safe_float(lines[0])
        if v is not None and 0.0 <= v <= 10.0:
            result["op_score"] = v
    if len(lines) > 1:
        v = _safe_float(lines[1])
        if v is not None and 0.0 <= v <= 10.0:
            result["expected_op_score"] = v
    return result


def _parse_laning_cell(lines: list[str]) -> dict:
    """cell[5]: 'X:Y' laning score (line 0) + expected laning % (line 1)."""
    result: dict = {}
    if lines:
        m = re.match(r'(\d+)\s*:', lines[0].strip())
        if m:
            result["op_laning_score"] = float(m.group(1))
    if len(lines) > 1:
        v = _safe_float(lines[1])
        if v is not None:
            result["expected_laning_pct"] = v
    return result


def _parse_dpm_cell(lines: list[str]) -> dict:
    """cell[6]: DPM (line 0) + damage share % (line 1)."""
    result: dict = {}
    if lines:
        v = _safe_float(lines[0])
        if v is not None and v > 0:
            result["dpm"] = v
    if len(lines) > 1:
        v = _safe_float(lines[1])
        if v is not None:
            result["damage_share_pct"] = v
    return result


def _parse_vision_cell(lines: list[str]) -> dict:
    """cell[7]: avg vision score per game (line 0)."""
    if lines:
        v = _safe_float(lines[0])
        if v is not None and v >= 0:
            return {"avg_vision_score": v}
    return {}


def _parse_cs_cell(lines: list[str]) -> dict:
    """cell[8] (new) / cell[4] (old): avg total CS per game (line 0), CS per minute (line 1)."""
    result: dict = {}
    if lines:
        v = _safe_float(lines[0])
        if v is not None and v >= 0:
            result["avg_cs_per_game"] = v
    if len(lines) > 1:
        v = _safe_float(lines[1])
        if v is not None and v >= 0:
            result["cs_per_min"] = v
    return result


def _parse_gpm_cell(lines: list[str]) -> dict:
    """cell[9] (new) / cell[5] (old): avg total gold per game (line 0), gold per minute (line 1)."""
    result: dict = {}
    if lines:
        v = _safe_float(lines[0])
        if v is not None and v > 0:
            result["avg_gold_per_game"] = v
    if len(lines) > 1:
        v = _safe_float(lines[1])
        if v is not None and v > 0:
            result["gpm"] = v
    return result
