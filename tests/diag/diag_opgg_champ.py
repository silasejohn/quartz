"""
Diagnostic: test OPGGScraper.extract_all_champion_seasons() against a live account.

Run: python tests/diag/diag_opgg_champ.py
"""

from quartz.scrapers.opgg_scraper import OPGGScraper

RIOT_ID = "dont ever stop#NA1"
REGION  = "NA"

scraper = OPGGScraper()
scraper.setup()

try:
    results = scraper.extract_all_champion_seasons(RIOT_ID, REGION)

    if not results:
        print("\n[!] No results — check selector warnings above.")
    else:
        print(f"\n=== Champion season data for {RIOT_ID} ===")
        for season, queues in results.items():
            print(f"\n  {season}")
            for queue_key in ("solo", "flex"):
                data = queues.get(queue_key, {})
                wins, losses = data.get("wins"), data.get("losses")
                champions = data.get("champions", {})
                wl = f"{wins}W {losses}L" if wins is not None else "no data"
                print(f"    {queue_key:<6}  {wl}  ({len(champions)} champions)")
                for champ, cd in list(champions.items())[:3]:
                    cw, cl, ops = cd["wins"], cd["losses"], cd["op_score"]
                    ops_str = f"{ops}" if ops is not None else "—"
                    print(f"      {champ:<20}  {cw}W {cl}L  OP Score: {ops_str}")
                if len(champions) > 3:
                    print(f"      … and {len(champions) - 3} more")
finally:
    input("\nPress Enter to close browser...")
    scraper.close()
