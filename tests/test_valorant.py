from aestron_bot.valorant import coaching_notes, summarize_matches


def _match(*, won: bool = True):
    return {
        "matchInfo": {"mapId": "Ascent"},
        "players": [
            {
                "puuid": "player-1",
                "teamId": "Blue",
                "characterId": "Jett",
                "stats": {
                    "roundsPlayed": 2,
                    "kills": 3,
                    "deaths": 1,
                    "assists": 2,
                    "score": 500,
                    "abilityCasts": {
                        "grenadeCasts": 1,
                        "ability1Casts": 2,
                        "ability2Casts": 1,
                        "ultimateCasts": 0,
                    },
                },
            }
        ],
        "teams": [{"teamId": "Blue", "won": won}],
        "roundResults": [
            {
                "playerStats": [
                    {
                        "puuid": "player-1",
                        "damage": [
                            {
                                "damage": 180,
                                "headshots": 1,
                                "bodyshots": 2,
                                "legshots": 0,
                            }
                        ],
                        "kills": [
                            {
                                "killer": "player-1",
                                "victim": "other",
                                "timeSinceRoundStartMillis": 8000,
                            }
                        ],
                    }
                ]
            },
            {
                "playerStats": [
                    {
                        "puuid": "other",
                        "damage": [],
                        "kills": [
                            {
                                "killer": "other",
                                "victim": "player-1",
                                "timeSinceRoundStartMillis": 4000,
                            }
                        ],
                    },
                    {
                        "puuid": "player-1",
                        "damage": [
                            {
                                "damage": 120,
                                "headshots": 1,
                                "bodyshots": 1,
                                "legshots": 0,
                            }
                        ],
                        "kills": [],
                    },
                ]
            },
        ],
    }


def test_match_summary_uses_round_and_damage_data():
    summary = summarize_matches([_match()], "player-1")

    assert summary.matches == 1
    assert summary.wins == 1
    assert summary.kd_ratio == 3
    assert summary.acs == 250
    assert summary.adr == 150
    assert summary.headshot_rate == 40
    assert summary.first_kills == 1
    assert summary.first_deaths == 1
    assert summary.ability_casts == 4


def test_coaching_is_transparent_and_never_creates_a_rank():
    summary = summarize_matches([_match(), _match(won=False)], "player-1")
    notes = coaching_notes(summary)

    assert notes
    assert all("MMR" not in note and "ELO" not in note for note in notes)
    assert any("Utility usage" in note for note in notes)


def test_missing_player_or_empty_matches_are_safe():
    summary = summarize_matches([_match()], "not-present")

    assert summary.matches == 0
    assert summary.kd_ratio == 0
    assert coaching_notes(summary) == [
        "Play a supported match, then run this command again."
    ]
