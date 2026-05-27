"""
Diagnostic: navigator.webdriver + DOM availability on League of Graphs (LOG)

Runs the same probe in HEADLESS then VISIBLE mode and reports:
  - navigator.webdriver value (True = site can detect Selenium)
  - Whether rank DOM elements are present/absent after JS render
  - Raw text of any rank elements found

NOT a pytest test — run manually with a real network connection.

Usage (from repo root, venv active):
    python tests/diag/diag_log_headless.py
    python tests/diag/diag_log_headless.py "Faker#KR1"
"""

import sys
import time
from urllib.parse import quote

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By

from quartz.scrapers.core.chrome_driver import chrome_service

LOG_BASE_URL = "https://www.leagueofgraphs.com/summoner/na"

# Selectors to probe — update as you identify the real ones via DevTools
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


def make_driver(headless: bool) -> webdriver.Chrome:
    options = ChromeOptions()
    if headless:
        options.add_argument("--headless")
        options.add_argument("--window-size=1920,1080")
    else:
        options.add_argument("--start-maximized")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.page_load_strategy = "eager"
    return webdriver.Chrome(service=chrome_service(), options=options)


def probe(driver: webdriver.Chrome, url: str, mode: str) -> None:
    sep = "=" * 60
    print(f"\n{sep}\n  MODE: {mode}\n  URL:  {url}\n{sep}")

    driver.get(url)

    # 1. navigator.webdriver — detects if site can fingerprint Selenium
    flag = driver.execute_script("return navigator.webdriver")
    print(f"\n  navigator.webdriver = {flag!r}")
    if flag:
        print("  *** DETECTED — site likely serves degraded content to bots ***")
    else:
        print("  Not detectable via navigator.webdriver")

    # 2. Wait for JS render then probe DOM
    print(f"\n  Waiting 5s for JS render...")
    time.sleep(5)

    print(f"  DOM probe:")
    found_any = False
    for strategy, selector in RANK_SELECTORS:
        by = By.CSS_SELECTOR if strategy == "css" else By.XPATH
        try:
            els = driver.find_elements(by, selector)
            if els:
                texts = [e.text.strip() for e in els[:3] if e.text.strip()]
                label = "FOUND "
                print(f"    {label} [{strategy}] {selector!r:45s} → {texts or '(element present, no text)'}")
                found_any = True
            else:
                print(f"    absent [{strategy}] {selector!r}")
        except Exception as e:
            print(f"    error  [{strategy}] {selector!r} — {e}")

    if not found_any:
        print("  No rank selectors matched — wrong selectors or data not rendered")

    print(f"\n  Page title: {driver.title!r}")


def main() -> None:
    riot_id = sys.argv[1] if len(sys.argv) > 1 else "Doublelift#NA1"
    url = build_url(riot_id)

    print(f"Diagnosing League of Graphs")
    print(f"Account : {riot_id}")
    print(f"URL     : {url}")

    for headless in (True, False):
        mode = "HEADLESS" if headless else "VISIBLE"
        driver = make_driver(headless)
        try:
            probe(driver, url, mode)
        finally:
            driver.quit()

    print("\n\nDiagnostic complete.")
    print("Compare HEADLESS vs VISIBLE:")
    print("  navigator.webdriver True in headless → bot detection is the issue")
    print("  Rank selectors absent in headless only → timing or rendering issue")
    print("  Both absent → wrong selectors, check DevTools on the live page")


if __name__ == "__main__":
    main()
