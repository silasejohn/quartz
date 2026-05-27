"""
General-purpose network inspector — capture every JSON API call a page makes.

Navigates to a URL using CDP network interception and dumps all JSON responses.
Useful for discovering hidden API endpoints, finding embedded metadata (e.g. lane/role
fields in champion data), or understanding what a site fetches on page load.

Usage:
    python tests/diag/diag_network_inspector.py <URL> [--wait N] [--filter DOMAIN] [--save]

Examples:
    # OP.GG champion page — find every API call made
    python tests/diag/diag_network_inspector.py "https://www.op.gg/en/lol/summoners/na/dont%20ever%20stop-NA1/champions?queue_type=SOLORANKED&season_id=31"

    # DPM no-filter vs lane-filtered — compare responses
    python tests/diag/diag_network_inspector.py "https://dpm.lol/Brezyy-001/champions"
    python tests/diag/diag_network_inspector.py "https://dpm.lol/Brezyy-001/champions?queue=solo&lane=jungle"

    # With longer wait (slow sites) and save fixtures
    python tests/diag/diag_network_inspector.py "https://www.op.gg/..." --wait 10 --save

Arguments:
    URL             Page to load
    --wait N        Seconds to wait for API calls (default: 8)
    --filter TERM   Only show responses whose URL contains TERM (default: show all JSON)
    --save          Save response bodies to tests/diag/fixtures/network/
    --visible       Open a visible browser window (default: headless)
    --items N       Max champion/list items to print per response (default: 2)
"""

import argparse
import json
import re
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions

from quartz.scrapers.core.chrome_driver import chrome_service

FIXTURE_DIR  = Path("tests/diag/fixtures/network")


def make_driver(headless: bool = True) -> webdriver.Chrome:
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
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    return webdriver.Chrome(service=chrome_service(), options=options)


def harvest(driver, url_filter: str | None) -> list[dict]:
    """Drain CDP performance log and return all JSON API responses."""
    results = []
    try:
        logs = driver.get_log("performance")
    except Exception as e:
        print(f"  [log error] {e}")
        return results

    for entry in logs:
        try:
            msg    = json.loads(entry["message"])["message"]
            if msg.get("method") != "Network.responseReceived":
                continue
            params = msg.get("params", {})
            resp   = params.get("response", {})
            url    = resp.get("url", "")
            status = resp.get("status", 0)
            mime   = resp.get("mimeType", "")

            if "application/json" not in mime:
                continue
            if url_filter and url_filter not in url:
                continue

            results.append({
                "url":       url,
                "status":    status,
                "requestId": params.get("requestId"),
            })
        except Exception:
            continue
    return results


def fetch_body(driver, request_id: str):
    try:
        result   = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": request_id})
        body_str = result.get("body", "")
        return json.loads(body_str) if body_str else None
    except Exception as e:
        print(f"    [body error] {e}")
        return None


def print_body(body, max_items: int) -> None:
    if isinstance(body, list):
        print(f"    shape  : list({len(body)} items)")
        for i, item in enumerate(body[:max_items]):
            print(f"    [{i}]    : {json.dumps(item, indent=10)}")
        if len(body) > max_items:
            print(f"           ... {len(body) - max_items} more items")
    elif isinstance(body, dict):
        print(f"    shape  : dict  keys={list(body.keys())}")
        # If it has a data/items/results list inside, print that instead
        for key in ("data", "items", "results", "champions", "content"):
            if isinstance(body.get(key), list):
                inner = body[key]
                print(f"    [{key}]  : list({len(inner)} items)")
                for i, item in enumerate(inner[:max_items]):
                    print(f"    [{i}]    : {json.dumps(item, indent=10)}")
                if len(inner) > max_items:
                    print(f"           ... {len(inner) - max_items} more items")
                return
        # Fallback: print full dict
        print(f"    body   : {json.dumps(body, indent=6)}")
    else:
        print(f"    shape  : {type(body).__name__}  =  {body!r}")


def run(url: str, wait: int, url_filter: str | None, save: bool, headless: bool, max_items: int) -> None:
    print("\nNetwork Inspector")
    print(f"  URL     : {url}")
    print(f"  wait    : {wait}s   filter : {url_filter or '(all JSON)'}   headless : {headless}")
    print(f"{'='*72}")

    driver = make_driver(headless=headless)
    driver.execute_cdp_cmd("Network.enable", {})

    try:
        driver.get(url)
        print(f"  waiting {wait}s for API calls...")
        time.sleep(wait)

        responses = harvest(driver, url_filter)
        print(f"\n  {len(responses)} JSON response(s) captured\n")

        if save:
            FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

        for i, resp in enumerate(responses):
            short = resp["url"].replace("https://", "")
            print(f"  [{i+1}] [{resp['status']}] {short}")

            body = fetch_body(driver, resp["requestId"])
            if body is None:
                print("    (no body)")
                continue

            print_body(body, max_items)

            if save:
                safe = re.sub(r"[^a-zA-Z0-9_-]", "_", short)[:100]
                path = FIXTURE_DIR / f"{safe}.json"
                path.write_text(json.dumps(body, indent=2), encoding="utf-8")
                print(f"    saved  → {path}")
            print()

    finally:
        driver.quit()


def main() -> None:
    parser = argparse.ArgumentParser(description="CDP network inspector for any URL")
    parser.add_argument("url",             help="URL to load")
    parser.add_argument("--wait",    "-w", type=int, default=8,    help="seconds to wait (default 8)")
    parser.add_argument("--filter",  "-f", default=None,           help="only show URLs containing this string")
    parser.add_argument("--save",    "-s", action="store_true",    help="save response bodies to fixtures/network/")
    parser.add_argument("--visible", "-v", action="store_true",    help="open visible browser window")
    parser.add_argument("--items",   "-n", type=int, default=2,    help="max list items to print per response (default 2)")
    args = parser.parse_args()

    run(
        url        = args.url,
        wait       = args.wait,
        url_filter = args.filter,
        save       = args.save,
        headless   = not args.visible,
        max_items  = args.items,
    )


if __name__ == "__main__":
    main()
