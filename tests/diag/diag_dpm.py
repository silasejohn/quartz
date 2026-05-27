"""
Diagnostic: DPM.lol API interception via CDP network log.

Loads a player's champion page, captures all XHR/fetch API responses via
Chrome DevTools Protocol performance log, and dumps structured JSON.
No DOM parsing — we intercept the raw API responses.

Goals:
  1. Find the player lookup call (to understand how player_id is obtained)
  2. Find the /champions endpoint JSON structure
  3. Confirm whether access_token is required (test without login)
  4. Understand all API calls fired on page load

NOT a pytest test — run manually with a real network connection.

Usage (from repo root, venv active):
    python tests/diag/diag_dpm.py
    python tests/diag/diag_dpm.py "GameName#TAG"
"""

import json
import sys
import time
from pathlib import Path
from urllib.parse import quote

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.support.ui import WebDriverWait

from quartz.scrapers.core.chrome_driver import chrome_service


def build_url(riot_id: str) -> str:
    name, tag = riot_id.split("#") if "#" in riot_id else (riot_id, "NA1")
    # DPM page format: dpm.lol/{gameName}-{tagLine}/champions
    return f"https://dpm.lol/{quote(name, safe='')}-{tag}/champions"


def make_driver(headless: bool = False) -> webdriver.Chrome:
    options = ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1920,1080")
    else:
        options.add_argument("--start-maximized")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    # Enable performance logging for network event capture
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    options.page_load_strategy = "eager"
    return webdriver.Chrome(service=chrome_service(), options=options)


def extract_network_responses(driver: webdriver.Chrome) -> list[dict]:
    """Pull all network responses from CDP performance log."""
    responses = []
    try:
        logs = driver.get_log("performance")
    except Exception as e:
        print(f"  Could not get performance log: {e}")
        return []

    for entry in logs:
        try:
            msg = json.loads(entry["message"])["message"]
            method = msg.get("method", "")
            params = msg.get("params", {})

            if method == "Network.responseReceived":
                url = params.get("response", {}).get("url", "")
                status = params.get("response", {}).get("status", 0)
                mime = params.get("response", {}).get("mimeType", "")
                request_id = params.get("requestId")
                if "dpm.lol" in url and "application/json" in mime:
                    responses.append({
                        "url": url,
                        "status": status,
                        "requestId": request_id,
                    })
        except Exception:
            continue
    return responses


def fetch_response_body(driver: webdriver.Chrome, request_id: str) -> dict | None:
    """Fetch the response body for a captured requestId via CDP."""
    try:
        result = driver.execute_cdp_cmd(
            "Network.getResponseBody", {"requestId": request_id}
        )
        body = result.get("body", "")
        return json.loads(body) if body else None
    except Exception as e:
        print(f"    Could not fetch body for {request_id}: {e}")
        return None


def probe(riot_id: str, headless: bool) -> None:
    mode = "HEADLESS" if headless else "VISIBLE"
    url = build_url(riot_id)
    print(f"\n{'='*60}")
    print(f"  MODE: {mode}")
    print(f"  URL : {url}")
    print(f"{'='*60}")

    driver = make_driver(headless)
    try:
        # Enable CDP network tracking before navigation
        driver.execute_cdp_cmd("Network.enable", {})

        driver.get(url)
        print(f"  Waiting 8s for page + API calls to complete...")
        time.sleep(8)

        print(f"  Page title : {driver.title!r}")
        print(f"  Final URL  : {driver.current_url!r}")

        # Harvest all JSON API responses
        responses = extract_network_responses(driver)
        print(f"\n  DPM JSON API calls captured: {len(responses)}")

        out_dir = Path("tests/diag/fixtures")
        out_dir.mkdir(parents=True, exist_ok=True)

        for resp in responses:
            short_url = resp["url"].replace("https://dpm.lol", "")
            print(f"\n  [{resp['status']}] {short_url}")

            body = fetch_response_body(driver, resp["requestId"])
            if body is None:
                print(f"    (no body / could not decode)")
                continue

            # Save full response to fixture
            slug = short_url.strip("/").replace("/", "_").replace("?", "_")[:80]
            out_path = out_dir / f"dpm_{mode.lower()}_{slug}.json"
            out_path.write_text(json.dumps(body, indent=2), encoding="utf-8")
            print(f"    Saved → {out_path}")

            # Print top-level structure
            if isinstance(body, dict):
                print(f"    Keys: {list(body.keys())}")
            elif isinstance(body, list):
                print(f"    List of {len(body)} items")
                if body:
                    first = body[0]
                    if isinstance(first, dict):
                        print(f"    Item[0] keys: {list(first.keys())}")
            else:
                print(f"    Type: {type(body).__name__}")

    finally:
        driver.quit()


def main() -> None:
    riot_id = sys.argv[1] if len(sys.argv) > 1 else "dont ever stop#NA1"
    print(f"DPM.lol API interception diagnostic")
    print(f"Account : {riot_id}")
    print(f"Strategy: CDP performance log → JSON response capture")

    # Test visible first (most likely to work), then headless
    probe(riot_id, headless=False)
    probe(riot_id, headless=True)

    print(f"\n\nDone. Check tests/diag/fixtures/ for captured JSON responses.")
    print(f"Key things to verify:")
    print(f"  - Is there a player lookup call? (to get player_id from riot_id)")
    print(f"  - What does /champions response look like?")
    print(f"  - Did headless capture the same responses as visible?")
    print(f"    (if headless missed them, Cloudflare blocked the API calls)")


if __name__ == "__main__":
    main()
