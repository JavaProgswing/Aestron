from aestron_bot.valorant import ValorantStatsView
from aestron_bot.valorant_analytics import (
    AssetCatalog,
    coaching_notes,
    summarize_matches,
)


def _match(*, won: bool = True):
    return {
        "matchInfo": {
            "matchId": "match-123",
            "mapId": "/Game/Maps/Ascent/Ascent",
            "gameStartMillis": 1_700_000_000_000,
            "queueId": "competitive",
        },
        "players": [
            {
                "puuid": "player-1",
                "teamId": "Blue",
                "characterId": "add6443a-41bd-e414-f6ad-e58d267f4e95",
                "playerCard": "11111111-2222-3333-4444-555555555555",
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
        "teams": [
            {"teamId": "Blue", "won": won, "roundsWon": 2},
            {"teamId": "Red", "won": not won, "roundsWon": 0},
        ],
        "roundResults": [
            {
                "roundNum": 1,
                "winningTeam": "Blue",
                "roundResult": "Eliminated",
                "playerStats": [
                    {
                        "puuid": "player-1",
                        "economy": {
                            "loadoutValue": 3900,
                            "spent": 2900,
                            "remaining": 1000,
                            "weapon": "Vandal",
                            "armor": "Heavy",
                        },
                        "damage": [
                            {
                                "damage": 180,
                                "receiver": "other",
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
                                "victimLocation": {"x": 3980.9, "y": -5938.8},
                                "finishingDamage": {
                                    "damageItem": "9c82e19d-4575-0200-1a81-3eacf00cf872"
                                },
                            }
                        ],
                    }
                ],
            },
            {
                "roundNum": 2,
                "winningTeam": "Red",
                "roundResult": "Eliminated",
                "playerStats": [
                    {
                        "puuid": "other",
                        "damage": [{"damage": 80, "receiver": "player-1"}],
                        "kills": [
                            {
                                "killer": "other",
                                "victim": "player-1",
                                "timeSinceRoundStartMillis": 4000,
                                "victimLocation": {"x": -2344.1, "y": -7548.5},
                                "finishingDamage": {
                                    "damageItem": "9c82e19d-4575-0200-1a81-3eacf00cf872"
                                },
                            }
                        ],
                    },
                    {
                        "puuid": "player-1",
                        "economy": {
                            "loadoutValue": 4700,
                            "spent": 800,
                            "remaining": 200,
                            "weapon": "Vandal",
                            "armor": "Heavy",
                        },
                        "damage": [
                            {
                                "damage": 120,
                                "receiver": "other",
                                "headshots": 1,
                                "bodyshots": 1,
                                "legshots": 0,
                            }
                        ],
                        "kills": [],
                    },
                ],
            },
        ],
    }


def test_match_summary_uses_round_and_damage_data():
    catalog = AssetCatalog(
        agents={"add6443a-41bd-e414-f6ad-e58d267f4e95": "Jett"},
        maps={"/game/maps/ascent/ascent": "Ascent"},
    )
    summary = summarize_matches([_match()], "player-1", catalog)

    assert summary.matches == 1
    assert summary.wins == 1
    assert summary.kd_ratio == 3
    assert summary.acs == 250
    assert summary.adr == 150
    assert summary.damage_delta == 110
    assert summary.headshot_rate == 40
    assert summary.first_kills == 1
    assert summary.first_deaths == 1
    assert summary.ability_casts == 4
    assert summary.survival_rate == 50
    assert summary.performances[0].scoreline == "2-0"
    assert summary.performances[0].map_name == "Ascent"
    assert [item.won for item in summary.performances[0].round_details] == [
        True,
        False,
    ]
    assert summary.performances[0].round_details[0].loadout_value == 3900
    assert summary.performances[0].duels[0].kills == 1
    assert summary.performances[0].duels[0].deaths == 1
    assert len(summary.performances[0].kill_locations) == 2
    assert summary.performances[0].kill_locations[0].outcome == "kill"
    assert summary.performances[0].kill_locations[1].outcome == "death"


def test_coaching_is_transparent_and_never_creates_a_rank():
    summary = summarize_matches([_match(), _match(won=False)], "player-1")
    notes = coaching_notes(summary)

    assert notes
    assert all("MMR" not in note and "ELO" not in note for note in notes)
    assert any("Utility" in note for note in notes)


def test_missing_player_or_empty_matches_are_safe():
    summary = summarize_matches([_match()], "not-present")

    assert summary.matches == 0
    assert summary.kd_ratio == 0
    assert coaching_notes(summary) == [
        "Play a supported match, then run this command again."
    ]


def test_stats_panel_restores_interactive_drill_downs():
    summary = summarize_matches([_match()], "player-1")
    account = {"accountname": "Player", "accounttag": "AP"}
    view = ValorantStatsView(
        author_id=123,
        account=account,
        summary=summary,
    )

    assert len(view.children) == 8
    assert view.overview_button.disabled is True
    assert view.section_select.disabled is True
    assert view.round_select.disabled is True
    assert view.render().title == "Performance overview"
    assert view.render().fields == []
    assert len(view.render_image()) > 15_000

    view.current_page = "coaching"
    view._refresh_buttons()
    assert view.render().title == "Post-match review plan"
    assert view.coaching_button.disabled is True

    view.current_page = "match:0"
    assert view.render().title == "Match review · Summary"

    view.selected_match_index = 0
    view.current_page = "match:0:rounds"
    assert view.render().title == "Match review · Rounds"
    assert len(view.render_image()) > 15_000

    view.current_page = "match:0:economy"
    assert view.render().title == "Match review · Economy"

    view.current_page = "match:0:duels"
    assert view.render().title == "Match review · Duels"

    view.current_page = "match:0:round:1"
    assert view.render().title == "Match review · Round 1"
