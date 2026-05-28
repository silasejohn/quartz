"""
Diagnostic: dump OP.GG champion page HTML for new-format and old-format seasons.

Saves to tests/fixtures/opgg/ so cell parsing can be tested offline without hitting
the live site. Two files:
  champ_new_format.html  — S2026 (season_id=33, include_op_score=True, ~15 cells)
  champ_old_format.html  — S2024 S1 (season_id=25, include_op_score=False, ~12 cells)

Run: python tests/diag/diag_opgg_champ_fixtures.py
Edit RIOT_ID / REGION below if needed.
"""

import time
from pathlib import Path

from quartz.scrapers.opgg_scraper import OPGGScraper

RIOT_ID = "dont ever stop#NA1"
REGION  = "NA"
QUEUE   = "SOLORANKED"

TARGETS = [
    ("champ_new_format.html", 33, "S2026"),   # new format — has op_score, laning, DPM, vision
    ("champ_old_format.html", 25, "S2024 S1"), # old format — KDA, CS, GPM only
]

out_dir = Path("tests/fixtures/opgg")
out_dir.mkdir(parents=True, exist_ok=True)

scraper = OPGGScraper()
scraper.setup()

try:
    for filename, season_id, label in TARGETS:
        url = scraper._build_champions_url(RIOT_ID, REGION, season_id, QUEUE)
        print(f"\n[{label}] Navigating to: {url}")
        scraper.driver.get(url)
        time.sleep(4)

        html = scraper.driver.page_source
        out = out_dir / filename
        out.write_text(html, encoding="utf-8")
        print(f"  Saved {len(html):,} bytes → {out}")

        # Quick sanity: count champion rows and print first row cell text
        rows = scraper.find_elements("champ_table_rows", timeout=5)
        print(f"  {len(rows)} champion rows found")
        if rows:
            cells = rows[0].find_elements("xpath", ".//td")
            print(f"  First row: {len(cells)} cells")
            for j, cell in enumerate(cells[:12]):
                lines = cell.text.strip().splitlines()
                if lines:
                    print(f"    cell[{j}]: {repr(lines[0])}" + (f" / {repr(lines[1])}" if len(lines) > 1 else ""))

        time.sleep(2)
finally:
    input("\nPress Enter to close browser...")
    scraper.close()
