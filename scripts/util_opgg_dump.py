"""
util_opgg_dump.py
Navigates to an OP.GG profile and dumps the full page HTML to a file.

Use this to inspect the live DOM and update selectors in:
    quartz/scrapers/configs/opgg_config.yaml

Usage:
    python3 util_opgg_dump.py RiotName#TAG [region]
    python3 util_opgg_dump.py PingSpam#NA1 na
Output:
    opgg_dump.html  (open in a browser or search with grep/Find)
"""

import sys
import time

from quartz.scrapers.opgg_scraper import OPGGScraper
from quartz.utils.color_utils import info_print, success_print, error_print

if len(sys.argv) < 2:
    print("Usage: python3 util_opgg_dump.py RiotName#TAG [region]")
    print("Example: python3 util_opgg_dump.py PingSpam#NA1 na")
    sys.exit(1)

RIOT_ID = sys.argv[1]
REGION  = sys.argv[2] if len(sys.argv) > 2 else "na"
OUT     = "opgg_dump.html"

scraper = OPGGScraper()
if scraper.setup() == -1:
    error_print("Failed to set up browser — aborting")
    sys.exit(1)

try:
    ok, url = scraper.navigate_to_profile(RIOT_ID, REGION)
    if not ok:
        error_print(f"Profile not found for {RIOT_ID}")
        sys.exit(1)

    info_print("Waiting 3s for page to settle...")
    time.sleep(3)

    html = scraper.driver.page_source
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)

    success_print(f"HTML dumped to: {OUT}  ({len(html):,} chars)")
    info_print("Search for rank-related class names with:")
    info_print("  grep -i 'tier\\|rank\\|lp\\|solo' opgg_dump.html | head -60")

finally:
    scraper.close()
