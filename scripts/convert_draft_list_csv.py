"""Convert a GCS draft-list CSV into Quartz's existing form-response CSV format."""

from __future__ import annotations

import argparse
import csv
import html
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

COL_DISCORD_USERNAME = "Discord Username"
COL_RIOT_ID = "Riot ID"
COL_STATED_CURRENT_RANK = "Stated Current Rank"
COL_STATED_PEAK_RANK = "Stated Peak Rank"
COL_PRIMARY_ROLE = "Primary Role"
COL_SECONDARY_ROLE = "Secondary Role"

COL_PLAYER = "Player"
COL_RANK = "Rank"
COL_ROLES = "Roles"
COL_UGG = "U.gg"
COL_OPGG = "Op.gg"

OUTPUT_COLUMNS = [
    COL_DISCORD_USERNAME,
    COL_RIOT_ID,
    COL_STATED_CURRENT_RANK,
    COL_STATED_PEAK_RANK,
    COL_PRIMARY_ROLE,
    COL_SECONDARY_ROLE,
]

INPUT_COLUMNS = [COL_PLAYER, COL_RANK, COL_ROLES, COL_UGG, COL_OPGG]

ROLE_ALIASES = {
    "TOP": "TOP",
    "TOPLANE": "TOP",
    "TOP LANE": "TOP",
    "JGL": "JGL",
    "JG": "JGL",
    "JNG": "JGL",
    "JUNGLE": "JGL",
    "MID": "MID",
    "MIDDLE": "MID",
    "BOT": "BOT",
    "BOTTOM": "BOT",
    "ADC": "BOT",
    "SUP": "SUP",
    "SUPPORT": "SUP",
    "UTILITY": "SUP",
}

RANK_TIERS = {
    "IRON": "Iron",
    "BRONZE": "Bronze",
    "SILVER": "Silver",
    "GOLD": "Gold",
    "PLATINUM": "Platinum",
    "PLAT": "Platinum",
    "EMERALD": "Emerald",
    "DIAMOND": "Diamond",
    "MASTER": "Master",
    "MASTERS": "Master",
    "GRANDMASTER": "Grandmaster",
    "CHALLENGER": "Challenger",
}

ROMAN_DIVISIONS = {
    "I": "1",
    "II": "2",
    "III": "3",
    "IV": "4",
}


def clean(value: object) -> str:
    return html.unescape(str(value or "")).strip()


def canonical_rank(raw: str) -> str:
    rank = clean(raw).upper()
    if not rank or rank in {"N/A", "UNRANKED"}:
        return "Unranked"

    parts = rank.replace("-", " ").split()
    if not parts:
        return "Unranked"

    tier = RANK_TIERS.get(parts[0])
    if not tier:
        return clean(raw)

    if tier in {"Master", "Grandmaster", "Challenger"}:
        return tier

    division = parts[1] if len(parts) > 1 else ""
    division = ROMAN_DIVISIONS.get(division, division)
    return f"{tier} {division}" if division else tier


def split_roles(raw: str) -> tuple[str, str]:
    roles = clean(raw).upper().replace("\\", "/").replace("|", "/").replace(",", "/")
    parts = [p.strip() for p in roles.split("/") if p.strip()]
    canonical = [ROLE_ALIASES.get(part, part) for part in parts]
    primary = canonical[0] if canonical else ""
    secondary = canonical[1] if len(canonical) > 1 else ""
    return primary, secondary


def riot_id_from_slug(slug: str) -> str | None:
    decoded = unquote(clean(slug))
    if "-" not in decoded:
        return None
    name, tag = decoded.rsplit("-", 1)
    name = name.strip()
    tag = tag.strip()
    if not name or not tag:
        return None
    return f"{name}#{tag}"


def riot_id_from_multisearch_entry(entry: str) -> str | None:
    decoded = unquote(entry).strip()
    if not decoded:
        return None
    if "#" in decoded:
        return decoded
    return riot_id_from_slug(decoded)


def parse_multisearch_accounts(query: str) -> list[str]:
    accounts = []
    for value in parse_qs(query).get("summoners", []):
        accounts.extend(
            account
            for entry in value.split(",")
            if (account := riot_id_from_multisearch_entry(entry))
        )
    return accounts


def parse_account_url(raw: str) -> list[str]:
    url = str(raw or "").strip().replace("&amp;", "&")
    if not url:
        return []

    parsed = urlparse(url)
    accounts = parse_multisearch_accounts(parsed.query)
    if accounts:
        return accounts

    slug = parsed.path.rstrip("/").split("/")[-1]
    riot_id = riot_id_from_slug(slug)
    return [riot_id] if riot_id else []


def unique_accounts(accounts: list[str]) -> list[str]:
    seen = set()
    unique = []
    for account in accounts:
        key = account.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(account)
    return unique


def convert_row(row: dict[str, str], peak_strategy: str) -> dict[str, str]:
    current_rank = canonical_rank(row.get(COL_RANK, ""))
    primary_role, secondary_role = split_roles(row.get(COL_ROLES, ""))
    accounts = unique_accounts(parse_account_url(row.get(COL_OPGG, "")) or parse_account_url(row.get(COL_UGG, "")))

    return {
        COL_DISCORD_USERNAME: clean(row.get(COL_PLAYER, "")),
        COL_RIOT_ID: " | ".join(accounts),
        COL_STATED_CURRENT_RANK: current_rank,
        COL_STATED_PEAK_RANK: current_rank if peak_strategy == "current" else "",
        COL_PRIMARY_ROLE: primary_role,
        COL_SECONDARY_ROLE: secondary_role,
    }


def convert_file(input_path: Path, output_path: Path, peak_strategy: str = "current") -> tuple[int, list[str]]:
    warnings: list[str] = []

    with input_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = [col for col in INPUT_COLUMNS if col not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{input_path} is missing required columns: {', '.join(missing)}")
        rows = [row for row in reader if clean(row.get(COL_PLAYER, ""))]

    converted = []
    for index, row in enumerate(rows, start=2):
        converted_row = convert_row(row, peak_strategy=peak_strategy)
        if not converted_row[COL_RIOT_ID]:
            warnings.append(f"row {index}: no Riot ID parsed for {converted_row[COL_DISCORD_USERNAME]!r}")
        if not converted_row[COL_PRIMARY_ROLE]:
            warnings.append(f"row {index}: no primary role parsed for {converted_row[COL_DISCORD_USERNAME]!r}")
        converted.append(converted_row)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(converted)

    return len(converted), warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="input_path", required=True, type=Path, help="Draft-list CSV to convert")
    parser.add_argument("--out", dest="output_path", required=True, type=Path, help="Quartz raw CSV output path")
    parser.add_argument(
        "--peak-strategy",
        choices=("current", "blank"),
        default="current",
        help="How to populate Stated Peak Rank when the draft list has no peak-rank column",
    )
    args = parser.parse_args()

    count, warnings = convert_file(args.input_path, args.output_path, peak_strategy=args.peak_strategy)
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"Converted {count} rows -> {args.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
