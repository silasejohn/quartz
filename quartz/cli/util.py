"""quartz debug/util — resync, opgg-dump, and fixture commands."""

import json
import os
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import typer

from quartz.models.player_profile import PlayerProfile
from quartz.models.rank_data import compute_enrichment
from quartz.pipeline_runner import PipelineRunner, Task
from quartz.player_registry import PlayerRegistry
from quartz.scrapers.core.chrome_driver import chrome_service
from quartz.tournament_config import load_tournament_config
from quartz.utils.logging import error_print, info_print, success_print, warning_print

app = typer.Typer(no_args_is_help=True)


def _find_profile(registry: PlayerRegistry, query: str) -> PlayerProfile | None:
    profile = registry.load(query)
    if profile:
        return profile
    for p in registry.load_all():
        if any(a.riot_id.lower() == query.lower() for a in p.accounts):
            return p
    return None


def resync():
    """Re-save all profiles through the registry after manual JSON edits."""
    config = load_tournament_config()

    info_print("Running RIOT_ENRICH_PUUID...")
    PipelineRunner(config).run_task(Task.RIOT_ENRICH_PUUID)

    registry = PlayerRegistry(config.abs_players_dir)
    registry.rebuild_index()
    profiles = registry.load_all()

    renamed = 0
    ok      = 0

    for profile in profiles:
        old_slug       = profile.make_player_id(profile.discord_id)
        new_slug       = profile.effective_id
        old_file_exists = (old_slug != new_slug) and os.path.exists(
            os.path.join(config.abs_players_dir, old_slug + _JSON_EXT)
        )

        profile.stats = compute_enrichment(profile.accounts, config.current_lol_split)

        from quartz.account_flags import evaluate_account_flags
        from quartz.pv_compute import evaluate_eligibility
        from quartz.pv_weights_io import load_weights
        weights, _ = load_weights(config.abs_data_dir)
        for account in profile.accounts:
            if not account.archived:
                evaluate_account_flags(account, weights)

        season_entry = next((sd for sd in profile.season_data if sd.season == config.round_id), None)
        if season_entry:
            season_entry.eligible = evaluate_eligibility(profile, config.eligibility)

        registry.save(profile)

        if old_file_exists:
            info_print(f"  Renamed: {old_slug} -> {new_slug}")
            renamed += 1
        else:
            ok += 1

    success_print(f"Done: {renamed} renamed, {ok} unchanged ({len(profiles)} total)")


@app.command("opgg-dump")
def opgg_dump(
    player: str = typer.Argument(..., help="Player ID or Riot ID (e.g. PlayerName#NA1)"),
    out: Optional[str] = typer.Option(None, "--out", help="Output HTML file path (default: opgg_dump.html)"),
    region: str = typer.Option("na", "--region", help="Region code (default: na)"),
):
    """Dump OP.GG page HTML for inspecting/updating CSS selectors."""
    from quartz.scrapers.opgg_scraper import OPGGScraper

    out_path = out or "opgg_dump.html"

    scraper = OPGGScraper()
    if scraper.setup() == -1:
        error_print("Failed to set up browser — aborting")
        raise typer.Exit(1)

    try:
        ok, url, _ = scraper.navigate_to_profile(player, region)
        if not ok:
            error_print(f"Profile not found for {player}")
            raise typer.Exit(1)

        info_print("Waiting 3s for page to settle...")
        time.sleep(3)

        html = scraper.driver.page_source
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)

        success_print(f"HTML dumped to: {out_path}  ({len(html):,} chars)")
        info_print("Search for rank-related class names with:")
        info_print("  grep -i 'tier\\|rank\\|lp\\|solo' opgg_dump.html | head -60")
    finally:
        scraper.close()


# ---------------------------------------------------------------------------
# Site presets for the fixture command
# ---------------------------------------------------------------------------

_FIXTURE_DIR   = Path("data/raw/network")
_DENYLIST_PATH = Path("tests/diag/fixture_denylist.json")  # NOSONAR
_JSON_EXT      = ".json"
_SLUG_RE       = re.compile(r"[^a-zA-Z0-9]")

_SITES = {
    "1": {
        "label":        "DPM.lol",
        "base":         "https://dpm.lol",
        "needs_player": True,
        "extensions": [
            ("/champions",                           "all queues, no lane filter"),
            ("/champions?queue=solo",               "solo queue, all lanes"),
            ("/champions?queue=flex",               "flex queue, all lanes"),
            ("/champions?queue=solo&lane=top",      "solo / top"),
            ("/champions?queue=solo&lane=jungle",   "solo / jungle"),
            ("/champions?queue=solo&lane=middle",   "solo / mid"),
            ("/champions?queue=solo&lane=bottom",   "solo / bot"),
            ("/champions?queue=solo&lane=utility",  "solo / support"),
        ],
    },
    "2": {
        "label":        "OP.GG",
        "base":         "https://www.op.gg/en/lol/summoners/na",
        "needs_player": True,
        "extensions": [
            ("/champions?queue_type=SOLORANKED&season_id=33", "solo / S2026"),
            ("/champions?queue_type=SOLORANKED&season_id=31", "solo / S2025"),
            ("/champions?queue_type=SOLORANKED&season_id=29", "solo / S2024 S3"),
            ("/champions?queue_type=FLEXRANKED&season_id=33", "flex / S2026"),
            ("/champions?queue_type=FLEXRANKED&season_id=31", "flex / S2025"),
        ],
    },
    "3": {
        "label":        "Custom URL",
        "base":         None,
        "needs_player": False,
        "extensions":   [],
    },
}


def _build_player_slug(riot_id: str) -> str:
    name, tag = riot_id.split("#", 1) if "#" in riot_id else (riot_id, "NA1")
    return f"{quote(name, safe='')}-{tag}"


def _auto_filename(site_label: str, player_slug: str, extension: str) -> str:
    parts = [_SLUG_RE.sub("_", site_label).strip("_")]
    if player_slug:
        parts.append(_SLUG_RE.sub("_", player_slug).strip("_"))
    if extension:
        parts.append(_SLUG_RE.sub("_", extension).strip("_")[:60])
    return "_".join(p for p in parts if p)


def _load_denylist() -> set[str]:
    if not _DENYLIST_PATH.exists():
        return set()
    data = json.loads(_DENYLIST_PATH.read_text(encoding="utf-8"))
    return set(data.get("domains", []))


def _load_allowlist() -> set[str]:
    if not _DENYLIST_PATH.exists():
        return set()
    data = json.loads(_DENYLIST_PATH.read_text(encoding="utf-8"))
    return set(data.get("allowlist", []))


def _save_denylist(domains: set[str]) -> None:
    existing = {}
    if _DENYLIST_PATH.exists():
        existing = json.loads(_DENYLIST_PATH.read_text(encoding="utf-8"))
    existing["domains"] = sorted(domains)
    _DENYLIST_PATH.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def _url_domain(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).netloc


def _is_denied(url: str, denylist: set[str]) -> bool:
    domain = _url_domain(url)
    return any(domain == d or domain.endswith("." + d) for d in denylist)


def _run_inspector(url: str, wait: int, url_filter: Optional[str], save_path: Path) -> None:
    from datetime import datetime, timezone

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions

    denylist = _load_denylist()

    options = ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    driver = webdriver.Chrome(service=chrome_service(), options=options)
    driver.execute_cdp_cmd("Network.enable", {})

    try:
        driver.get(url)
        info_print(f"  Waiting {wait}s for API calls...")
        time.sleep(wait)

        raw_logs = driver.get_log("performance")

        # Classify every JSON response before touching the filesystem
        all_entries = []   # {"url", "status", "requestId", "outcome", "reason"}
        for entry in raw_logs:
            try:
                msg    = json.loads(entry["message"])["message"]
                if msg.get("method") != "Network.responseReceived":
                    continue
                params   = msg.get("params", {})
                resp     = params.get("response", {})
                resp_url = resp.get("url", "")
                mime     = resp.get("mimeType", "")
                status   = resp.get("status", 0)
                if "application/json" not in mime:
                    continue
                if url_filter and url_filter not in resp_url:
                    continue
                if _is_denied(resp_url, denylist):
                    all_entries.append({"url": resp_url, "status": status, "requestId": None,
                                        "outcome": "denied", "reason": f"denylist: {_url_domain(resp_url)}"})
                    continue
                if status < 200 or status >= 300:
                    all_entries.append({"url": resp_url, "status": status,
                                        "requestId": params.get("requestId"),
                                        "outcome": "skipped", "reason": f"non-2xx ({status})"})
                    continue
                all_entries.append({"url": resp_url, "status": status,
                                    "requestId": params.get("requestId"),
                                    "outcome": "pending", "reason": None})
            except Exception:
                continue

        to_save   = [e for e in all_entries if e["outcome"] == "pending"]
        info_print(f"  {len(all_entries)} JSON response(s) seen  "
                   f"({len(to_save)} to save, "
                   f"{sum(1 for e in all_entries if e['outcome'] == 'denied')} denied, "
                   f"{sum(1 for e in all_entries if e['outcome'] == 'skipped')} skipped)\n")

        if not all_entries:
            warning_print("No JSON responses found. Try increasing wait or adjusting the URL filter.")
            return

        _FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

        # Fetch and save bodies for 2xx responses
        save_idx = 0
        for entry in to_save:
            try:
                result   = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": entry["requestId"]})
                body_str = result.get("body", "")
                body     = json.loads(body_str) if body_str else None
            except Exception as e:
                entry["outcome"] = "skipped"
                entry["reason"]  = f"body error: {e}"
                continue

            if body is None:
                entry["outcome"] = "skipped"
                entry["reason"]  = "empty body"
                continue

            save_idx += 1
            out_path = save_path if len(to_save) == 1 else save_path.parent / f"{save_path.stem}_{save_idx:02d}{_JSON_EXT}"
            out_path.write_text(json.dumps(body, indent=2), encoding="utf-8")
            entry["outcome"] = "saved"
            entry["file"]    = out_path.name
            shape = f"list({len(body)} items)" if isinstance(body, list) else f"dict  keys={list(body.keys())[:6]}"
            entry["shape"]   = shape

            success_print(f"  [saved] [{entry['status']}] {entry['url'].replace('https://', '')}")
            info_print(f"          shape : {shape}")
            info_print(f"          file  : {out_path.name}")

        # Write manifest
        manifest = {
            "page_url":    url,
            "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "summary": {
                "total":   len(all_entries),
                "saved":   sum(1 for e in all_entries if e["outcome"] == "saved"),
                "denied":  sum(1 for e in all_entries if e["outcome"] == "denied"),
                "skipped": sum(1 for e in all_entries if e["outcome"] == "skipped"),
            },
            "endpoints": [
                {k: v for k, v in e.items() if k != "requestId" and v is not None}
                for e in all_entries
            ],
        }
        manifest_path = save_path.parent / f"{save_path.stem}_manifest{_JSON_EXT}"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        info_print(f"\n  manifest: {manifest_path.name}")

        saved_count = manifest["summary"]["saved"]
        typer.echo(f"\nDone — {saved_count} fixture(s) saved.")
        typer.echo("Analyze with:  python tests/diag/diag_network_analyze.py\n")

        # Offer to extend deny list from non-denied domains seen this run
        allowlist     = _load_allowlist()
        seen_domains  = {_url_domain(e["url"]) for e in all_entries if e["outcome"] != "denied"}
        new_domains   = sorted(seen_domains - denylist - allowlist)
        protected     = sorted(seen_domains & allowlist)
        if protected:
            info_print(f"  Protected (allowlisted, cannot be denied): {', '.join(protected)}")
        if new_domains:
            typer.echo("Domains seen this run (not in denylist):")
            for i, d in enumerate(new_domains, 1):
                typer.echo(f"  [{i}] {d}")
            raw = typer.prompt(
                "\nAdd to denylist? Enter numbers (e.g. 1,3) or press Enter to skip",
                default=""
            ).strip()
            if raw:
                chosen = set()
                for part in raw.split(","):
                    part = part.strip()
                    if part.isdigit():
                        idx = int(part) - 1
                        if 0 <= idx < len(new_domains):
                            chosen.add(new_domains[idx])
                if chosen:
                    denylist |= chosen
                    _save_denylist(denylist)
                    success_print(f"Added {len(chosen)} domain(s) to denylist: {', '.join(sorted(chosen))}")

    finally:
        driver.quit()


@app.command("fixture")
def fixture():
    """
    Interactive CDP network inspector — capture JSON API calls made by any page
    and save them as fixtures for analysis.

    Flow: choose site → enter player (if needed) → pick URL extension → run.
    """
    typer.echo("\nCapture network fixtures\n")

    # Step 1: site selection
    typer.echo("Choose a site:")
    for key, site in _SITES.items():
        typer.echo(f"  [{key}] {site['label']}")
    typer.echo("")

    site_key = typer.prompt("Site").strip()
    site = _SITES.get(site_key)
    if site is None:
        error_print(f"Unknown choice '{site_key}'")
        raise typer.Exit(1)

    # Step 2: build URL
    extension   = ""
    player_slug = ""
    if site["base"] is None:
        # Custom URL — no further prompting needed
        url = typer.prompt("Full URL").strip()
    else:
        if site["needs_player"]:
            riot_id    = typer.prompt(f"\n  {site['label']} player Riot ID (GameName#TAG)").strip()
            player_slug = _build_player_slug(riot_id)

        typer.echo(f"\n  URL extensions for {site['label']}:")
        for i, (ext, desc) in enumerate(site["extensions"], 1):
            typer.echo(f"    [{i}] {ext}  ({desc})")
        typer.echo("    [0] Enter custom extension")
        typer.echo("    [–] No extension\n")

        ext_choice = typer.prompt("  Extension").strip()
        if ext_choice in ("", "–", "-"):
            extension = ""
        elif ext_choice == "0":
            extension = typer.prompt("  Custom (e.g. /champions?queue=solo)").strip()
        else:
            try:
                idx = int(ext_choice) - 1
                extension = site["extensions"][idx][0]
            except (ValueError, IndexError):
                error_print(f"Invalid choice '{ext_choice}'")
                raise typer.Exit(1)

        base = site["base"]
        url  = f"{base}/{player_slug}{extension}" if player_slug else f"{base}{extension}"

    typer.echo(f"\n  URL  : {url}")

    # Step 3: wait / filter
    wait_raw   = typer.prompt("  Wait seconds", default="8").strip()
    wait       = int(wait_raw) if wait_raw.isdigit() else 8
    filter_raw = typer.prompt("  URL filter   (blank = all JSON)", default="").strip()
    url_filter = filter_raw or None

    # Step 4: filename
    auto_name = _auto_filename(site["label"], player_slug, extension)
    filename  = typer.prompt("\n  Save as", default=auto_name).strip()
    if not filename.endswith(_JSON_EXT):
        filename += _JSON_EXT

    save_path = _FIXTURE_DIR / filename
    typer.echo(f"  Path : {save_path}\n")

    # Step 5: run
    _run_inspector(url, wait, url_filter, save_path)
