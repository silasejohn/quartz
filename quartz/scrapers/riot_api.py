"""
RiotAPIClient
Minimal Riot API client for PUUID resolution.

Endpoint: GET /riot/account/v1/accounts/by-riot-id/{gameName}/{tagLine}
Route:    americas (NA, BR, LAN, LAS) | europe (EUW, EUNE, TR, RU) | asia (KR, JP)

Reads RIOT_API_KEY from config/api.env (via config.config.get_riot_api_config).
Rate-limited to stay within Riot dev key limits (20 req/s, 100 req/2min).

Usage:
    client = RiotAPIClient()
    puuid = client.lookup_puuid("GameName#TAG", region="NA")
    client.close()
"""

import os
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import requests

from quartz.utils.logging import error_print, warning_print

# Load RIOT_API_KEY from config/api.env if not already in environment
try:
    _config_dir = Path(__file__).parents[2] / "config"
    sys.path.insert(0, str(_config_dir.parent))
    from config.config import get_riot_api_config as _get_riot_api_config
    _key_from_config = _get_riot_api_config("RIOT_API_KEY")
    if _key_from_config and not os.environ.get("RIOT_API_KEY"):
        os.environ["RIOT_API_KEY"] = _key_from_config
except Exception:
    pass

_REGION_ROUTE = {
    "NA": "americas", "BR": "americas", "LAN": "americas", "LAS": "americas",
    "EUW": "europe",  "EUNE": "europe",  "TR": "europe",   "RU": "europe",
    "KR": "asia",     "JP": "asia",
}
_DEFAULT_ROUTE = "americas"

_BASE_URL = "https://{route}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"


class RiotAPIClient:
    """
    Thin synchronous Riot Account API v1 client.
    Handles 429 backoff and 5xx retries. Returns None on 404 or persistent failure.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("RIOT_API_KEY", "")
        if not self.api_key:
            raise RuntimeError(
                "RIOT_API_KEY not set — export it before running: export RIOT_API_KEY=RGAPI-..."
            )
        self.session = requests.Session()
        self.session.headers["X-Riot-Token"] = self.api_key

    def lookup_puuid(self, riot_id: str, region: str = "NA") -> Optional[str]:
        """
        Resolve riot_id ("GameName#TAG") → PUUID.
        Returns None on 404 (account not found) or unrecoverable error.
        """
        if "#" not in riot_id:
            error_print(f"  RiotAPI: invalid riot_id (missing #): {riot_id!r}")
            return None

        game_name, tag_line = riot_id.split("#", 1)
        route = _REGION_ROUTE.get(region.upper(), _DEFAULT_ROUTE)
        url = _BASE_URL.format(
            route=route,
            game_name=quote(game_name, safe=""),
            tag_line=quote(tag_line, safe=""),
        )

        for attempt in range(3):
            try:
                resp = self.session.get(url, timeout=10)
            except requests.RequestException as e:
                error_print(f"  RiotAPI: request error for {riot_id}: {e}")
                return None

            if resp.status_code == 200:
                return resp.json().get("puuid")

            if resp.status_code == 404:
                warning_print(f"  RiotAPI: account not found — {riot_id}")
                return None

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 6))
                warning_print(f"  RiotAPI: rate limited — waiting {retry_after}s")
                time.sleep(retry_after)
                continue

            if 500 <= resp.status_code < 600:
                wait = 2 ** attempt
                warning_print(f"  RiotAPI: server error {resp.status_code} for {riot_id} — retry in {wait}s")
                time.sleep(wait)
                continue

            error_print(f"  RiotAPI: unexpected status {resp.status_code} for {riot_id}")
            return None

        error_print(f"  RiotAPI: failed after 3 attempts for {riot_id}")
        return None

    def close(self) -> None:
        self.session.close()
