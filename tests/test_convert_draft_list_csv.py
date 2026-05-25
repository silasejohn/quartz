import csv
import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "convert_draft_list_csv.py"
SPEC = importlib.util.spec_from_file_location("convert_draft_list_csv", SCRIPT_PATH)
convert_draft_list_csv = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(convert_draft_list_csv)


def test_convert_row_normalizes_draft_list_fields():
    row = {
        "Player": "Mordschlag",
        "Rank": "PLATINUM I",
        "Roles": "BOTTOM/MIDDLE",
        "U.gg": "",
        "Op.gg": (
            "https://op.gg/lol/multisearch/na?"
            "summoners=SOLO%20DRAVEN%20ONLY%23DRVEN,NA%20Mordschlag%23T1WIN&amp;region=na1"
        ),
    }

    converted = convert_draft_list_csv.convert_row(row, peak_strategy="current")

    assert converted == {
        "Discord Username": "Mordschlag",
        "Riot ID": "SOLO DRAVEN ONLY#DRVEN | NA Mordschlag#T1WIN",
        "Stated Current Rank": "Platinum 1",
        "Stated Peak Rank": "Platinum 1",
        "Primary Role": "BOT",
        "Secondary Role": "MID",
    }


def test_parse_account_url_does_not_include_region_query_param():
    accounts = convert_draft_list_csv.parse_account_url(
        "https://op.gg/lol/multisearch/na?"
        "summoners=Glazza%23Atrox,Glazza%23pppoo&region=na1"
    )

    assert accounts == ["Glazza#Atrox", "Glazza#pppoo"]


def test_unique_accounts_preserves_order_case_insensitively():
    accounts = convert_draft_list_csv.unique_accounts(["Player#NA1", "Other#NA1", "player#na1"])

    assert accounts == ["Player#NA1", "Other#NA1"]


def test_convert_file_writes_existing_ingest_columns(tmp_path):
    input_path = tmp_path / "draft_list.csv"
    output_path = tmp_path / "raw_form.csv"
    input_path.write_text(
        "\n".join(
            [
                "Player,Rank,Roles,U.gg,Op.gg,Notes,PV",
                "Sushiman.,DIAMOND IV,TOP/JUNGLE,https://u.gg/lol/profile/NA1/sush1man-bozo,,,"
            ]
        ),
        encoding="utf-8",
    )

    count, warnings = convert_draft_list_csv.convert_file(input_path, output_path)

    assert count == 1
    assert warnings == []
    with output_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert rows == [
        {
            "Discord Username": "Sushiman.",
            "Riot ID": "sush1man#bozo",
            "Stated Current Rank": "Diamond 4",
            "Stated Peak Rank": "Diamond 4",
            "Primary Role": "TOP",
            "Secondary Role": "JGL",
        }
    ]


def test_convert_file_rejects_unexpected_csv_shape(tmp_path):
    input_path = tmp_path / "wrong.csv"
    output_path = tmp_path / "raw_form.csv"
    input_path.write_text("Name,Rank\nSushiman.,DIAMOND IV\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing required columns"):
        convert_draft_list_csv.convert_file(input_path, output_path)
