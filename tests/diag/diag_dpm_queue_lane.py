"""
Diagnostic: verify DPM queue+lane URL filtering via CDP interception.

Tests:
  1. CDP still captures /v1/players/{puuid}/champions with query params attached
  2. Drain between navigations works (no stale events leak to next request)
  3. "No champions found" lane returns empty list [] (not a timeout)
  4. Solo and flex return different champion sets

Run: python tests/diag/diag_dpm_queue_lane.py
"""

import json
import re
import time
from urllib.parse import quote

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions

from quartz.scrapers.core.chrome_driver import chrome_service

RIOT_ID     = "Brezyy#001"

_PUUID_RE = re.compile(r"/v1/players/([^/?]+)/champions")

# Combinations to test — pick a sample, not all 10
COMBOS = [
    ("solo",  "top"),
    ("solo",  "jungle"),
    ("solo",  "bottom"),   # expect "No champions found" for Brezyy (top laner)
    ("flex",  "top"),
]


def build_url(riot_id: str, queue: str, lane: str) -> str:
    name, tag = riot_id.split("#") if "#" in riot_id else (riot_id, "NA1")
    slug = f"{quote(name, safe='')}-{tag}"
    return f"https://dpm.lol/{slug}/champions?queue={queue}&lane={lane}"


def make_driver() -> webdriver.Chrome:
    options = ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    return webdriver.Chrome(service=chrome_service(), options=options)


def poll_for_champ_api(driver, timeout=10):
    """Return (request_id, puuid, api_url) or (None, None, None) on timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        logs = driver.get_log("performance")
        for entry in logs:
            try:
                msg = json.loads(entry["message"])["message"]
                if msg.get("method") != "Network.responseReceived":
                    continue
                params = msg.get("params", {})
                resp   = params.get("response", {})
                url    = resp.get("url", "")
                status = resp.get("status", 0)
                mime   = resp.get("mimeType", "")
                if "/v1/players/" in url and "/champions" in url and status == 200 and "application/json" in mime:
                    request_id = params.get("requestId")
                    m = _PUUID_RE.search(url)
                    puuid = m.group(1) if m else None
                    return request_id, puuid, url
            except Exception:
                continue
        time.sleep(0.4)
    return None, None, None


def fetch_body(driver, request_id):
    try:
        result = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": request_id})
        body_str = result.get("body", "")
        return json.loads(body_str) if body_str else None
    except Exception as e:
        print(f"    [body fetch error] {e}")
        return None


def main():
    print(f"DPM queue+lane URL diagnostic — {RIOT_ID}")
    print(f"{'='*60}")

    driver = make_driver()
    driver.execute_cdp_cmd("Network.enable", {})

    try:
        for queue, lane in COMBOS:
            url = build_url(RIOT_ID, queue, lane)
            print(f"\n  [{queue}/{lane}]  {url}")

            # Drain stale log before navigating
            stale = driver.get_log("performance")
            if stale:
                print(f"    drained {len(stale)} stale log entries")

            driver.get(url)

            request_id, puuid, api_url = poll_for_champ_api(driver, timeout=10)

            if request_id is None:
                print("    TIMEOUT — no champion API response captured in 10s")
                print("    → DPM may not call API for empty result sets")
                continue

            print(f"    API URL  : {api_url}")
            print(f"    puuid    : {puuid[:12]}..." if puuid else "    puuid    : (none)")

            body = fetch_body(driver, request_id)
            if body is None:
                print("    body     : (none / parse error)")
            elif isinstance(body, list):
                print(f"    body     : list of {len(body)} champions")
                if body:
                    champs = [(c.get("championName", "?"), c.get("gamesPlayed", 0)) for c in body[:5]]
                    for name, g in champs:
                        print(f"      {name:<20} {g} games")
                    if len(body) > 5:
                        print(f"      … and {len(body)-5} more")
                else:
                    print("    → empty list — 'No champions found' confirmed")
            else:
                print(f"    body type: {type(body).__name__}  keys={list(body.keys()) if isinstance(body, dict) else '?'}")

    finally:
        driver.quit()

    print(f"\n{'='*60}")
    print("Check above for:")
    print("  - API URL contains queue/lane params (or not — DPM may strip them)")
    print("  - Empty list [] for lanes with no data (vs timeout)")
    print("  - No stale events leaking between navigations")


if __name__ == "__main__":
    main()
