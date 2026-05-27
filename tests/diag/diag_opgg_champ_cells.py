"""
Diagnostic: dump raw cell text for every champion row on an OP.GG champion page.

Used to map cell indices → field names before extending _extract_champ_season_data().

Run: python tests/diag/diag_opgg_champ_cells.py

Edit RIOT_ID / REGION / SEASON_ID below to target different splits:
  33 = S2026  |  31 = S2025  |  29 = S2024 S3  |  27 = S2024 S2
"""

from quartz.scrapers.opgg_scraper import OPGGScraper

RIOT_ID   = "dont ever stop#NA1"
REGION    = "NA"
QUEUE     = "SOLORANKED"
SEASON_ID = 29  # change to 33/31/29/27 to compare formats

scraper = OPGGScraper()
scraper.setup()

try:
    url = scraper._build_champions_url(RIOT_ID, REGION, SEASON_ID, QUEUE)
    print(f"\nNavigating to: {url}")
    scraper.driver.get(url)

    import time
    time.sleep(4)

    rows = scraper.find_elements("champ_table_rows", timeout=8)
    if not rows:
        print("[!] No rows found — check champ_table_rows selector in opgg_config.yaml")
    else:
        print(f"\n{len(rows)} rows found\n")
        for i, row in enumerate(rows[:8]):  # first 8 rows
            cells = row.find_elements("xpath", ".//td")
            print(f"--- Row {i} ({len(cells)} cells) ---")
            for j, cell in enumerate(cells):
                raw = cell.text.strip()
                lines = raw.splitlines()
                if lines:
                    print(f"  cell[{j}]: {repr(lines[0])}")
                    for extra in lines[1:]:
                        print(f"           {repr(extra)}")
                else:
                    print(f"  cell[{j}]: (empty)")
            print()
finally:
    input("Press Enter to close browser...")
    scraper.close()
