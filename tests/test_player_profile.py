from quartz.models.player_profile import PlayerProfile


def test_player_profile_from_csv_row_does_not_require_prior_enrichment_imports():
    profile = PlayerProfile.from_csv_row(
        {
            "discord_username": "emgym",
            "player_type_override": "main",
            "primary_role": "BOT",
            "secondary_role": "MID",
            "stated_current_rank": "Emerald 4",
            "stated_peak_rank": "Emerald 4",
            "accounts": [
                {
                    "riot_id": "emgym#iwnl",
                    "player_region": "NA",
                }
            ],
        },
        "GCS-S4",
    )

    assert profile.discord_id == "emgym"
    assert profile.effective_id == "emgym"
    assert profile.season_data[0].season == "GCS-S4"
    assert profile.accounts[0].riot_id == "emgym#iwnl"
