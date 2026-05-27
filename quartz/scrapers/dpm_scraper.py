"""
DPMScraper
Intercepts DPM.lol's internal champion API via Chrome DevTools Protocol (CDP).

Navigates to a player's DPM champion page with queue+lane filters, captures the
/v1/players/{puuid}/champions XHR response from the CDP performance log, and
maps the JSON to AccountChampionData.

Scraped combinations:
  queue: solo, flex
  lane:  top, jungle, middle, bottom, utility

Each combo is a separate page load + API intercept. Results are stored as
ChampionEntry objects with role set (e.g. "JGL") so role-specific data is
preserved. "No champions found" pages (empty API response) are skipped silently.

Requires visible browser — Cloudflare JS challenge blocks headless Chrome on DPM.lol.
No DOM parsing. No CSS selectors.

Usage:
    scraper = DPMScraper()
    scraper.setup()
    ok, champ_data, puuid = scraper.extract_champion_data("GameName#TAG", "S2026")
    scraper.close()
"""

import json
import random
import re
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

import undetected_chromedriver as uc
from selenium import webdriver

from quartz.constants import ROLE_ALIASES
from quartz.models.champion_data import (
    AccountChampionData,
    AccountQueueChampionPool,
    ChampionEntry,
    ChampionSplitStats,
)
from quartz.scrapers.core.base_scraper import BaseScraper
from quartz.utils.champion_names import normalize_champion_name
from quartz.utils.logging import error_print, info_print, warning_print

_PUUID_RE = re.compile(r"/v1/players/([^/?]+)/champions")
_LANES = ("top", "jungle", "middle", "bottom", "utility")


class DPMScraper(BaseScraper):
    """
    Scrapes DPM.lol champion data via CDP network interception.

    extract_champion_data() — navigate to player's champion page, return AccountChampionData + puuid
    """

    requires_visible_browser = True   # Cloudflare JS challenge now blocks headless Chrome

    def __init__(self):
        super().__init__(config_file="dpm_config.yaml", website_timeout=3)

    # ------------------------------------------------------------------
    # Override: add CDP performance logging capability before driver creation
    # ------------------------------------------------------------------

    def _setup_chrome(self, config: dict, browser_headless: Optional[bool] = None) -> webdriver.Chrome:
        # undetected_chromedriver patches Chrome's automation fingerprint to bypass Cloudflare
        options = uc.ChromeOptions()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        # Required for network event capture via driver.get_log("performance")
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

        chrome_version = self._chrome_major_version()
        return uc.Chrome(options=options, headless=False, version_main=chrome_version)

    def _chrome_major_version(self) -> Optional[int]:
        """
        Return Chrome major version for uc.Chrome(version_main=...).
        Reads browser.chrome_version from dpm_config.yaml — update it when Chrome updates.
        Falls back to subprocess detection if not pinned, with a nudge to pin it.
        """
        pinned = self.config.get("browser.chrome_version")
        if pinned is not None:
            return int(pinned)

        import subprocess
        warning_print("DPMScraper: chrome_version not set in dpm_config.yaml — detecting via subprocess")
        try:
            out = subprocess.check_output(
                ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--version"],
                stderr=subprocess.DEVNULL,
            ).decode()
            version = int(out.strip().split()[-1].split(".")[0])
            warning_print(f"DPMScraper: detected Chrome {version} — set browser.chrome_version: {version} in dpm_config.yaml to skip this")
            return version
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Override: enable CDP network tracking immediately after driver creation
    # ------------------------------------------------------------------

    def setup(self, browser_headless: Optional[bool] = None) -> int:
        result = super().setup(browser_headless)
        if result == 1 and self.driver:
            self.driver.execute_cdp_cmd("Network.enable", {})
        return result

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def extract_champion_data(
        self,
        riot_id: str,
        lol_season: str,
        api_timeout: int = 10,
    ) -> tuple[bool, Optional[AccountChampionData], Optional[str]]:
        """
        Navigate to each queue×lane combination on DPM and capture API responses.

        [param] riot_id:     "GameName#TAG"
        [param] lol_season:  e.g. "S2026" — stored on ChampionSplitStats.lol_season
        [param] api_timeout: seconds to wait per combo (empty lanes return [] quickly)

        Returns (ok, AccountChampionData, puuid):
          ok=True if any champion data was captured across all combos.
          puuid is extracted from the first successful API URL.
          ChampionEntry.role is set to the canonical role (TOP/JGL/MID/BOT/SUP).
        """
        if not self.driver:
            error_print("DPMScraper: driver not initialized — call setup() first")
            return False, None, None

        self._trigger_profile_update(riot_id)

        now = datetime.now(timezone.utc)
        champion_data = AccountChampionData(
            solo=AccountQueueChampionPool(dpm_scraped_at=now),
            flex=AccountQueueChampionPool(dpm_scraped_at=now),
        )
        puuid: Optional[str] = None

        t_start = time.time()
        nav_count = 0

        for queue_key in ("solo", "flex"):
            pool = champion_data.solo if queue_key == "solo" else champion_data.flex

            for lane in _LANES:
                role = ROLE_ALIASES[lane]
                url = self._build_url(riot_id, queue=queue_key, lane=lane)
                info_print(f"  DPMScraper: {riot_id} {queue_key}/{lane}")

                if nav_count > 0:
                    self._nav_delay()
                self._drain_log()
                nav_count += 1
                try:
                    self.driver.get(url)
                except Exception as e:
                    error_print(f"  DPMScraper: navigation error ({queue_key}/{lane}): {e}")
                    continue

                body, found_puuid = self._poll_for_champ_api(api_timeout)
                if found_puuid and puuid is None:
                    puuid = found_puuid

                if body is None:
                    warning_print(f"  DPMScraper: no API response for {queue_key}/{lane} — skipping")
                    continue
                if not body:
                    continue  # "No champions found" — empty list, nothing to store

                self._add_to_pool(pool, body, lol_season, role=role)
                info_print(f"    {len(body)} champions ({queue_key}/{lane})")

            # All-lanes aggregate — role="ALL"
            url = self._build_url(riot_id, queue=queue_key)
            info_print(f"  DPMScraper: {riot_id} {queue_key}/all")
            self._nav_delay()
            self._drain_log()
            nav_count += 1
            try:
                self.driver.get(url)
            except Exception as e:
                error_print(f"  DPMScraper: navigation error ({queue_key}/all): {e}")
            else:
                body, found_puuid = self._poll_for_champ_api(api_timeout)
                if found_puuid and puuid is None:
                    puuid = found_puuid
                if body:
                    self._add_to_pool(pool, body, lol_season, role="ALL")
                    info_print(f"    {len(body)} champions ({queue_key}/all)")

        elapsed = time.time() - t_start
        info_print(f"  DPMScraper: {riot_id} done — {nav_count} pages in {elapsed:.1f}s")

        has_data = bool(champion_data.solo.champions or champion_data.flex.champions)
        if not has_data:
            warning_print(f"  DPMScraper: no champion data captured for {riot_id}")
        return has_data, champion_data, puuid

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _nav_delay(self, min_s: float = 1.0, jitter: float = 0.5) -> None:
        """Sleep between page navigations to avoid hammering DPM."""
        time.sleep(min_s + random.uniform(0.0, jitter))

    def _build_main_url(self, riot_id: str) -> str:
        name, tag = riot_id.split("#", 1) if "#" in riot_id else (riot_id, "NA1")
        slug = f"{quote(name, safe='')}-{tag}"
        template = self.config.get("urls.player_profile", "https://dpm.lol/{slug}")
        return template.replace("{slug}", slug)

    def _build_url(self, riot_id: str, queue: str = "solo", lane: Optional[str] = None) -> str:
        name, tag = riot_id.split("#", 1) if "#" in riot_id else (riot_id, "NA1")
        slug = f"{quote(name, safe='')}-{tag}"
        template = self.config.get("urls.player_champions", "https://dpm.lol/{slug}/champions")
        base = template.replace("{slug}", slug)
        return f"{base}?queue={queue}&lane={lane}" if lane else f"{base}?queue={queue}"

    def _trigger_profile_update(self, riot_id: str) -> None:
        """Navigate to the DPM main profile page and click the update button if present."""
        main_url = self._build_main_url(riot_id)
        info_print(f"  DPMScraper: navigating to main page for update — {main_url}")
        try:
            self.driver.get(main_url)
        except Exception as e:
            warning_print(f"  DPMScraper: failed to navigate to main page: {e}")
            return
        time.sleep(3)

        update_timeout = self.config.get("timeouts.profile_update", 30)
        btn_xpath = self.config.get_selectors("update_button").get("xpath")
        if not btn_xpath:
            warning_print("  DPMScraper: update_button selector not configured")
            return

        try:
            btns = self.driver.find_elements("xpath", btn_xpath)
        except Exception as e:
            warning_print(f"  DPMScraper: update button lookup failed: {e}")
            return

        if not btns:
            info_print("  DPMScraper: update button not found — profile may already be current")
            return

        info_print("  DPMScraper: clicking update button...")
        try:
            btns[0].click()
        except Exception as e:
            warning_print(f"  DPMScraper: could not click update button: {e}")
            return

        # Brief pause so the update request fires before we navigate away.
        # DPM refreshes asynchronously — the champion pages will reflect updated data.
        post_click_wait = min(update_timeout, 5)
        time.sleep(post_click_wait)
        info_print("  DPMScraper: update triggered — proceeding to champion pages")

    def _drain_log(self) -> None:
        """Consume any buffered CDP log entries before a new navigation."""
        try:
            self.driver.get_log("performance")
        except Exception:
            pass

    def _poll_for_champ_api(self, timeout: int) -> tuple[Optional[list], Optional[str]]:
        """
        Drain CDP performance log until /v1/players/{puuid}/champions response appears,
        then immediately fetch the body before Chrome can GC it.

        Returns (body_list, puuid) or (None, None) on timeout/error.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                logs = self.driver.get_log("performance")
            except Exception as e:
                error_print(f"  DPMScraper: performance log unavailable: {e}")
                return None, None

            for entry in logs:
                try:
                    msg = json.loads(entry["message"])["message"]
                    if msg.get("method") != "Network.responseReceived":
                        continue
                    params = msg.get("params", {})
                    resp = params.get("response", {})
                    url = resp.get("url", "")
                    status = resp.get("status", 0)
                    mime = resp.get("mimeType", "")

                    if (
                        "/v1/players/" in url
                        and "/champions" in url
                        and status == 200
                        and "application/json" in mime
                    ):
                        request_id = params.get("requestId")
                        m = _PUUID_RE.search(url)
                        puuid = m.group(1) if m else None
                        body = self._fetch_response_body(request_id)
                        return body, puuid
                except Exception:
                    continue

            time.sleep(0.5)

        return None, None

    def _fetch_response_body(self, request_id: str) -> Optional[list]:
        try:
            result = self.driver.execute_cdp_cmd(
                "Network.getResponseBody", {"requestId": request_id}
            )
            body_str = result.get("body", "")
            return json.loads(body_str) if body_str else None
        except Exception as e:
            error_print(f"  DPMScraper: could not fetch response body: {e}")
            return None

    def _add_to_pool(
        self,
        pool: AccountQueueChampionPool,
        data: list[dict],
        lol_season: str,
        role: Optional[str] = None,
    ) -> None:
        """Append DPM API champion entries into pool, tagged with the given role."""
        for item in data:
            games = item.get("gamesPlayed", 0) or 0
            if games == 0:
                continue

            wins = item.get("win", 0) or 0
            fb_rate = ((item.get("fbkill") or 0) + (item.get("fbassist") or 0)) / games

            split_stats = ChampionSplitStats(
                lol_season=lol_season,
                source="dpm",
                games=games,
                wins=wins,
                losses=games - wins,
                win_rate=(item.get("winrate") or 0) / 100,
                kills_per_game=item.get("kills"),
                deaths_per_game=item.get("deaths"),
                assists_per_game=item.get("assists"),
                kda=item.get("kda"),
                dpm_score=item.get("averageScore"),
                cs_per_min=item.get("csm"),
                first_blood_rate=fb_rate if fb_rate > 0 else None,
                dpm=item.get("dpm"),
                kill_participation_pct=(item.get("kp") or 0) / 100,
                gpm=item.get("gpm"),
                vision_score_per_min=item.get("visionScore"),
            )

            champ_name = normalize_champion_name(item.get("championName", ""))
            entry = pool.get_champion(champ_name, role=role)
            if entry is None:
                entry = ChampionEntry(champion=champ_name, role=role)
                pool.champions.append(entry)
            entry.upsert_split(split_stats)
