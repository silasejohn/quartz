"""
Diagnostic: Cloudflare bypass test for League of Graphs using undetected-chromedriver.

Cloudflare blocks standard Selenium (even visible mode) by detecting:
  - navigator.webdriver = True
  - CDP fingerprints, timing patterns, canvas fingerprinting, missing plugins

undetected-chromedriver patches ChromeDriver at the binary level to strip
all detectable signals. This script tests whether it gets past the challenge.

NOT a pytest test — run manually, requires real network + Chrome installed.

Usage (from repo root, venv active):
    python tests/diag/diag_log_undetected.py
    python tests/diag/diag_log_undetected.py "GameName#TAG"
"""

import sys
import time
from urllib.parse import quote

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

LOG_BASE_URL = "https://www.leagueofgraphs.com/summoner/na"

RANK_SELECTORS = [
    ("css",   ".soloqueue-rank"),
    ("css",   ".ranking"),
    ("css",   "[class*='rank']"),
    ("css",   "[class*='tier']"),
    ("xpath", "//*[contains(@class,'rank')]"),
    ("xpath", "//*[contains(text(),'Solo')]"),
    ("xpath", "//*[contains(text(),'Ranked')]"),
    ("xpath", "//*[contains(text(),'Diamond')]"),
    ("xpath", "//*[contains(text(),'Platinum')]"),
    ("xpath", "//*[contains(text(),'Emerald')]"),
    ("xpath", "//*[contains(text(),'Gold')]"),
]


def build_url(riot_id: str) -> str:
    name, tag = riot_id.split("#") if "#" in riot_id else (riot_id, "NA1")
    encoded = quote(f"{name}-{tag}", safe="-")
    return f"{LOG_BASE_URL}/{encoded}"


def probe(headless: bool, url: str) -> None:
    mode = "HEADLESS" if headless else "VISIBLE"
    sep = "=" * 60
    print(f"\n{sep}\n  MODE: {mode} (undetected-chromedriver)\n  URL:  {url}\n{sep}")

    options = uc.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1920,1080")
    else:
        options.add_argument("--start-maximized")

    driver = uc.Chrome(options=options, use_subprocess=True, version_main=148)
    try:
        driver.get(url)
        time.sleep(6)  # give Cloudflare challenge + page JS time to resolve

        flag = driver.execute_script("return navigator.webdriver")
        print(f"\n  navigator.webdriver = {flag!r}")
        print(f"  Page title          = {driver.title!r}")

        if "just a moment" in driver.title.lower():
            print("  *** STILL BLOCKED by Cloudflare — challenge not bypassed ***")
            return

        print("\n  DOM probe (after 6s):")
        found_any = False
        for strategy, selector in RANK_SELECTORS:
            by = By.CSS_SELECTOR if strategy == "css" else By.XPATH
            try:
                els = driver.find_elements(by, selector)
                if els:
                    texts = [e.text.strip() for e in els[:3] if e.text.strip()]
                    print(f"    FOUND  [{strategy}] {selector!r:45s} → {texts or '(no text)'}")
                    found_any = True
                else:
                    print(f"    absent [{strategy}] {selector!r}")
            except Exception as e:
                print(f"    error  [{strategy}] {selector!r} — {e}")

        if not found_any:
            print("  Past Cloudflare but no rank selectors matched — update selectors via DevTools")

    finally:
        driver.quit()


def main() -> None:
    riot_id = sys.argv[1] if len(sys.argv) > 1 else "Doublelift#NA1"
    url = build_url(riot_id)

    print("Cloudflare bypass diagnostic — League of Graphs")
    print(f"Account : {riot_id}")
    print(f"URL     : {url}")
    print("Driver  : undetected-chromedriver")

    for headless in (True, False):
        probe(headless, url)

    print("\n\nDone. Key outcomes:")
    print("  'Just a moment' gone → undetected-chromedriver bypasses Cloudflare")
    print("  Rank selectors found → proceed with LOG scraper on this driver")
    print("  Still blocked        → Cloudflare has hardened; consider deprioritising LOG")


if __name__ == "__main__":
    main()
