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

from quartz.models.champion_data import (
    AccountChampionData,
    AccountQueueChampionPool,
    ChampionEntry,
    ChampionSplitStats,
)
from quartz.constants import ROLE_ALIASES
from quartz.scrapers.core.chrome_driver import chrome_service
from quartz.utils.champion_names import normalize_champion_name
from quartz.scrapers.core.base_scraper import BaseScraper
from quartz.utils.logging import error_print, info_print, warning_print

_PUUID_RE = re.compile(r"/v1/players/([^/?]+)/champions")
_LANES = ("top", "jungle", "middle", "bottom", "utility")


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

        return webdriver.Chrome(service=chrome_service(config.get("driver_path")), options=options)

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

        now = datetime.now(timezone.utc)
        champion_data = AccountChampionData(
            solo=AccountQueueChampionPool(dpm_scraped_at=now),
            flex=AccountQueueChampionPool(dpm_scraped_at=now),
        )
        puuid: Optional[str] = None

        for queue_key in ("solo", "flex"):
            pool = champion_data.solo if queue_key == "solo" else champion_data.flex

            for lane in _LANES:
                role = ROLE_ALIASES[lane]
                url = self._build_url(riot_id, queue=queue_key, lane=lane)
                info_print(f"  DPMScraper: {riot_id} {queue_key}/{lane}")

                self._drain_log()
                try:
                    self.driver.get(url)
                except Exception as e:
                    error_print(f"  DPMScraper: navigation error ({queue_key}/{lane}): {e}")
                    continue

                request_id, found_puuid = self._poll_for_champ_api(api_timeout)
                if found_puuid and puuid is None:
                    puuid = found_puuid

                if request_id is None:
                    warning_print(f"  DPMScraper: no API response for {queue_key}/{lane} — skipping")
                    continue

                body = self._fetch_response_body(request_id)
                if not isinstance(body, list):
                    continue
                if not body:
                    continue  # "No champions found" — empty list, nothing to store

                self._add_to_pool(pool, body, lol_season, role=role)
                info_print(f"    {len(body)} champions ({queue_key}/{lane})")

            # All-lanes aggregate — role="ALL"
            url = self._build_url(riot_id, queue=queue_key)
            info_print(f"  DPMScraper: {riot_id} {queue_key}/all")
            self._drain_log()
            try:
                self.driver.get(url)
            except Exception as e:
                error_print(f"  DPMScraper: navigation error ({queue_key}/all): {e}")
            else:
                request_id, found_puuid = self._poll_for_champ_api(api_timeout)
                if found_puuid and puuid is None:
                    puuid = found_puuid
                if request_id is not None:
                    body = self._fetch_response_body(request_id)
                    if isinstance(body, list) and body:
                        self._add_to_pool(pool, body, lol_season, role="ALL")
                        info_print(f"    {len(body)} champions ({queue_key}/all)")

        has_data = bool(champion_data.solo.champions or champion_data.flex.champions)
        if not has_data:
            warning_print(f"  DPMScraper: no champion data captured for {riot_id}")
        return has_data, champion_data, puuid

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_url(self, riot_id: str, queue: str = "solo", lane: Optional[str] = None) -> str:
        name, tag = riot_id.split("#", 1) if "#" in riot_id else (riot_id, "NA1")
        slug = f"{quote(name, safe='')}-{tag}"
        template = self.config.get("urls.player_champions", "https://dpm.lol/{slug}/champions")
        base = template.replace("{slug}", slug)
        return f"{base}?queue={queue}&lane={lane}" if lane else f"{base}?queue={queue}"

    def _drain_log(self) -> None:
        """Consume any buffered CDP log entries before a new navigation."""
        try:
            self.driver.get_log("performance")
        except Exception:
            pass

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
