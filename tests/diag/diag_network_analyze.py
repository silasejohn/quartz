"""
Companion to diag_network_inspector.py — analyze saved fixtures against what
the scraper currently captures.

Reads every JSON fixture in tests/diag/fixtures/network/, flattens all fields
found in list items or nested data keys, then cross-references against
ChampionSplitStats to show:
  - Fields we currently capture (mapped)
  - Fields the API returns that we ignore (unmapped — potential value)
  - Endpoints called that our scraper never intercepts

Usage:
    # Step 1: capture
    python tests/diag/diag_network_inspector.py "https://dpm.lol/Brezyy-001/champions?queue=solo&lane=jungle" --save

    # Step 2: analyze
    python tests/diag/diag_network_analyze.py

    # Analyze a specific fixture dir
    python tests/diag/diag_network_analyze.py --dir data/raw/network
"""

import argparse
import json
from pathlib import Path

FIXTURE_DIR = Path("data/raw/network")

# Fields ChampionSplitStats currently maps from DPM API responses
# key = DPM API field name, value = ChampionSplitStats field name
DPM_MAPPED = {
    "gamesPlayed":   "games",
    "win":           "wins",
    "winrate":       "win_rate",
    "kills":         "kills_per_game",
    "deaths":        "deaths_per_game",
    "assists":       "assists_per_game",
    "kda":           "kda",
    "averageScore":  "dpm_score",
    "csm":           "cs_per_min",
    "dpm":           "dpm",
    "kp":            "kill_participation_pct",
    "gpm":           "gpm",
    "visionScore":   "vision_score_per_min",
    "fbkill":        "first_blood_rate (partial)",
    "fbassist":      "first_blood_rate (partial)",
    "championName":  "ChampionEntry.champion",
}

# Fields we know about but intentionally ignore (add to suppress false positives)
DPM_KNOWN_IGNORED = {
    "championId",   # Riot int ID — we use name instead
}


def collect_fields(body) -> set[str]:
    """Flatten all keys from a response body (list of dicts or nested dict)."""
    fields = set()
    if isinstance(body, list):
        for item in body:
            if isinstance(item, dict):
                fields.update(item.keys())
    elif isinstance(body, dict):
        fields.update(body.keys())
        for key in ("data", "items", "results", "champions", "content"):
            if isinstance(body.get(key), list):
                for item in body[key]:
                    if isinstance(item, dict):
                        fields.update(item.keys())
    return fields


def analyze(fixture_dir: Path) -> None:
    files = sorted(fixture_dir.glob("*.json"))
    if not files:
        print(f"No fixtures found in {fixture_dir}")
        print("Run diag_network_inspector.py --save first.")
        return

    print(f"\nAnalyzing {len(files)} fixture(s) in {fixture_dir}")
    print(f"{'='*72}")

    all_endpoints: list[dict] = []

    for path in files:
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [skip] {path.name} — {e}")
            continue

        fields = collect_fields(body)
        is_list = isinstance(body, list)
        count   = len(body) if is_list else "dict"

        all_endpoints.append({
            "file":   path.name,
            "fields": fields,
            "shape":  f"list({count})" if is_list else "dict",
            "body":   body,
        })

    if not all_endpoints:
        print("  No parseable fixtures.")
        return

    # Per-endpoint breakdown
    for ep in all_endpoints:
        print(f"\n  FILE: {ep['file']}")
        print(f"  shape: {ep['shape']}")

        if not ep["fields"]:
            print(f"  (no fields found — empty response)")
            continue

        mapped   = {f: DPM_MAPPED[f]  for f in ep["fields"] if f in DPM_MAPPED}
        ignored  = {f for f in ep["fields"] if f in DPM_KNOWN_IGNORED}
        unmapped = ep["fields"] - set(DPM_MAPPED) - DPM_KNOWN_IGNORED

        if mapped:
            print(f"\n  CAPTURED ({len(mapped)}):")
            for api_field, model_field in sorted(mapped.items()):
                print(f"    {api_field:<22} → {model_field}")

        if unmapped:
            print(f"\n  NOT CAPTURED ({len(unmapped)}) — review these:")
            for f in sorted(unmapped):
                # Sample the value from first item
                sample = _sample_value(ep["body"], f)
                print(f"    {f:<22}  sample: {sample!r}")

        if ignored:
            print(f"\n  KNOWN IGNORED: {sorted(ignored)}")

    # Cross-endpoint summary: fields that appear in SOME endpoints but not others
    print(f"\n{'='*72}")
    print(f"CROSS-ENDPOINT FIELD SUMMARY")
    all_fields: dict[str, list[str]] = {}
    for ep in all_endpoints:
        for f in ep["fields"]:
            all_fields.setdefault(f, []).append(ep["file"])

    # Fields that only appear in some endpoints (potential lane/role differentiators)
    partial = {f: files for f, files in all_fields.items() if 0 < len(files) < len(all_endpoints)}
    if partial:
        print(f"\n  Fields NOT present in all endpoints (may indicate per-lane metadata):")
        for f, present_in in sorted(partial.items()):
            status = "CAPTURED" if f in DPM_MAPPED else "NOT CAPTURED"
            print(f"    {f:<22} [{status}]  in {len(present_in)}/{len(all_endpoints)} fixtures")
    else:
        print(f"\n  All fields are consistent across all {len(all_endpoints)} endpoint(s).")
        print(f"  → No hidden per-lane/role fields detected in the API responses.")


def _sample_value(body, field: str):
    """Pull one example value for a field from a response body."""
    if isinstance(body, list):
        for item in body:
            if isinstance(item, dict) and field in item:
                return item[field]
    elif isinstance(body, dict):
        if field in body:
            return body[field]
        for key in ("data", "items", "results", "champions"):
            inner = body.get(key, [])
            if isinstance(inner, list):
                for item in inner:
                    if isinstance(item, dict) and field in item:
                        return item[field]
    return "(not found)"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", "-d", default=str(FIXTURE_DIR),
                        help=f"fixture directory (default: {FIXTURE_DIR})")
    parser.add_argument("--file", "-f",
                        help="analyze a single fixture file instead of the whole directory")
    args = parser.parse_args()

    if args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"File not found: {path}")
            return
        # Wrap single file in a temp-dir-like container for analyze()
        import tempfile, shutil
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(path, Path(tmp) / path.name)
            analyze(Path(tmp))
    else:
        analyze(Path(args.dir))


if __name__ == "__main__":
    main()
