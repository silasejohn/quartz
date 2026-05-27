"""
Diagnostic: dump main DPM.lol player page HTML to find the 'update' button.

Run: python tests/diag/diag_dpm_main_page.py

Output: tests/fixtures/dpm/main_page.html
Edit RIOT_ID below to target any player with recent DPM data.
"""

import time
from pathlib import Path
from urllib.parse import quote

from quartz.scrapers.dpm_scraper import DPMScraper

RIOT_ID = "dont ever stop#NA1"

name, tag = RIOT_ID.split("#", 1)
slug = f"{quote(name, safe='')}-{tag}"
main_url = f"https://dpm.lol/{slug}"

scraper = DPMScraper()
scraper.setup()

try:
    print(f"\nNavigating to: {main_url}")
    scraper.driver.get(main_url)
    time.sleep(5)

    html = scraper.driver.page_source
    out = Path("tests/fixtures/dpm/main_page.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Saved {len(html):,} bytes → {out}")

    # Verify the known update button XPath
    btn_xpath = "/html/body/main/div/div[1]/div/div/div[1]/div/div[2]/div[2]/div[1]/button"
    btns = scraper.driver.find_elements("xpath", btn_xpath)
    print(f"\nUpdate button found: {len(btns) > 0}")
    if btns:
        print(f"  text={repr(btns[0].text.strip())}")
        print(f"  class={repr(btns[0].get_attribute('class'))}")
finally:
    input("\nPress Enter to close browser...")
    scraper.close()
