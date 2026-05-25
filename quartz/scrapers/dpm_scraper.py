"""
DPMScraper
Intercepts DPM.lol's internal champion API via Chrome DevTools Protocol (CDP).

Navigates to a player's DPM champion page, captures the /v1/players/{puuid}/champions
XHR response from the CDP performance log, and maps the JSON to AccountChampionData.

Works in headless mode — no Cloudflare JS challenge on the internal API endpoint.
No DOM parsing. No CSS selectors.

Usage:
    scraper = DPMScraper()
    scraper.setup()
    ok, champ_data, puuid = scraper.extract_champion_data("GameName#TAG", "S2026")
    scraper.close()
"""

import json
import re
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService

from quartz.models.champion_data import (
    AccountChampionData,
    AccountQueueChampionPool,
    ChampionEntry,
    ChampionSplitStats,
)
from quartz.scrapers.core.base_scraper import BaseScraper
from quartz.utils.logging import error_print, info_print, warning_print

_PUUID_RE = re.compile(r"/v1/players/([^/?]+)/champions")


class DPMScraper(BaseScraper):
    """
    Scrapes DPM.lol champion data via CDP network interception.

    extract_champion_data() — navigate to player's champion page, return AccountChampionData + puuid
    """

    requires_visible_browser = False  # headless confirmed working — no Cloudflare on the API

    def __init__(self):
        super().__init__(config_file="dpm_config.yaml", website_timeout=3)

    # ------------------------------------------------------------------
    # Override: add CDP performance logging capability before driver creation
    # ------------------------------------------------------------------

    def _setup_chrome(self, config: dict, browser_headless: Optional[bool] = None) -> webdriver.Chrome:
        options = ChromeOptions()
        use_headless = browser_headless if browser_headless is not None else config.get("headless", True)

        chrome_options_config = self.config.get("browser.chrome_options", {})
        if chrome_options_config:
            mode = "headless_mode" if use_headless else "visible_mode"
            for arg in chrome_options_config.get(mode, []):
                options.add_argument(arg)
        else:
            if use_headless:
                options.add_argument("--headless=new")
                options.add_argument("--window-size=1920,1080")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")

        # Required for network event capture via driver.get_log("performance")
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        options.add_experimental_option("useAutomationExtension", False)
        options.add_experimental_option("excludeSwitches", ["enable-automation"])

        driver_path = config.get("driver_path", "/opt/homebrew/bin/chromedriver")
        return webdriver.Chrome(service=ChromeService(driver_path), options=options)

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
        api_timeout: int = 15,
    ) -> tuple[bool, Optional[AccountChampionData], Optional[str]]:
        """
        Navigate to the player's DPM champion page and capture the API response.

        [param] riot_id:     "GameName#TAG"
        [param] lol_season:  e.g. "S2026" — stored on ChampionSplitStats.lol_season
        [param] api_timeout: seconds to wait for the champion API response

        Returns (ok, AccountChampionData, puuid):
          ok=False when navigation fails or API response not captured within timeout.
          puuid is extracted from the API URL — store on Account for future Riot API calls.
        """
        if not self.driver:
            error_print("DPMScraper: driver not initialized — call setup() first")
            return False, None, None

        url = self._build_url(riot_id)
        info_print(f"  DPMScraper: {riot_id} → {url}")

        try:
            self.driver.get(url)
        except Exception as e:
            error_print(f"  DPMScraper: navigation error for {riot_id}: {e}")
            return False, None, None

        request_id, puuid = self._poll_for_champ_api(api_timeout)
        if request_id is None:
            warning_print(f"  DPMScraper: champion API not captured for {riot_id} ({api_timeout}s timeout)")
            return False, None, None

        body = self._fetch_response_body(request_id)
        if not isinstance(body, list):
            error_print(f"  DPMScraper: unexpected response type ({type(body).__name__}) for {riot_id}")
            return False, None, None

        champion_data = self._map_api_response(body, lol_season)
        return True, champion_data, puuid

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_url(self, riot_id: str) -> str:
        name, tag = riot_id.split("#", 1) if "#" in riot_id else (riot_id, "NA1")
        slug = f"{quote(name, safe='')}-{tag}"
        template = self.config.get("urls.player_champions", "https://dpm.lol/{slug}/champions")
        return template.replace("{slug}", slug)

    def _poll_for_champ_api(self, timeout: int) -> tuple[Optional[str], Optional[str]]:
        """
        Drain CDP performance log in a loop until the /v1/players/{puuid}/champions
        response appears. Chrome log entries are consumed on each get_log() call.

        Returns (request_id, puuid) or (None, None) on timeout.
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
                        return request_id, puuid
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

    def _map_api_response(self, data: list[dict], lol_season: str) -> AccountChampionData:
        """Map DPM API champion list → AccountChampionData (solo queue only)."""
        pool = AccountQueueChampionPool(scraped_at=datetime.now(timezone.utc))

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
                # Composite score — MVP champion feature
                dpm_score=item.get("averageScore"),
                # Cluster 1 — Laning / Early Game
                cs_per_min=item.get("csm"),
                first_blood_rate=fb_rate if fb_rate > 0 else None,
                # Cluster 2 — Combat / Carry Impact
                dpm=item.get("dpm"),
                kill_participation_pct=(item.get("kp") or 0) / 100,
                # Cluster 3 — Macro / Team Contribution
                gpm=item.get("gpm"),
                vision_score_per_min=item.get("visionScore"),  # already per-minute in DPM API
            )

            pool.champions.append(ChampionEntry(
                champion=item.get("championName", ""),
                splits=[split_stats],
            ))

        return AccountChampionData(solo=pool)
