import json
import os

import pytest

from build_cup_html import (build_bracket_html, build_champion_html,
                             build_cup_html, build_odds_rows_html,
                             build_standings_rows, render_rows_html)

LEAGUE_SCHEDULE = {
    "Strong FC|Weak FC": {"date": "2026-09-16", "status": "FINISHED",
                           "goals": {"Strong FC": 3, "Weak FC": 1}, "round": "League, Matchday 1"},
    "Weak FC|Mid FC": {"date": "2026-09-30", "status": "SCHEDULED",
                        "goals": {"Weak FC": None, "Mid FC": None}, "round": "League, Matchday 2"},
}
ZONE_ODDS = {
    "Strong FC": {"top8": 0.9, "playoff_zone": 0.1, "eliminated": 0.0},
    "Weak FC": {"top8": 0.1, "playoff_zone": 0.3, "eliminated": 0.6},
    "Mid FC": {"top8": 0.2, "playoff_zone": 0.5, "eliminated": 0.3},
}
EXPECTED_POS = {"Strong FC": 2.0, "Weak FC": 20.0, "Mid FC": 15.0}


def test_build_standings_rows_ranks_by_points_then_zone_odds():
    rows = build_standings_rows(LEAGUE_SCHEDULE, ZONE_ODDS, EXPECTED_POS)
    assert rows[0]["team"] == "Strong FC"
    assert rows[0]["pos"] == 1
    assert rows[0]["top8_pct"] == 0.9


def test_build_standings_rows_uses_expected_pos_tiebreak_when_tied():
    tied_schedule = {
        "Contender FC|Filler FC": {"date": "2026-09-16", "status": "SCHEDULED",
                                    "goals": {"Contender FC": None, "Filler FC": None}, "round": "League, Matchday 1"},
    }
    tied_odds = {
        "Contender FC": {"top8": 0.7, "playoff_zone": 0.2, "eliminated": 0.1},
        "Filler FC": {"top8": 0.1, "playoff_zone": 0.2, "eliminated": 0.7},
    }
    tied_pos = {"Contender FC": 3.0, "Filler FC": 25.0}
    rows = build_standings_rows(tied_schedule, tied_odds, tied_pos)
    assert rows[0]["team"] == "Contender FC"  # tied 0-0-0, but a stronger expected position


def test_render_rows_html_escapes_team_names():
    rows = [{"pos": 1, "team": "A & B FC", "played": 0, "w": 0, "d": 0, "l": 0,
             "gf": 0, "ga": 0, "gd": 0, "pts": 0, "top8_pct": 0.5, "playoff_pct": 0.1}]
    out = render_rows_html(rows)
    assert "A &amp; B FC" in out


def test_build_bracket_html_empty_state_when_not_drawn():
    out = build_bracket_html([], {})
    assert "not drawn yet" in out


def test_build_bracket_html_orders_stages_correctly_not_by_digit_extraction():
    # Regression test for a real gap: build_league_html.py's bracket sort
    # extracts the first digit in the round label ("Round of 16" -> 16),
    # which would put Quarterfinal/Semifinal/Final (no digits, sort at 0)
    # BEFORE Playoffs, and Round of 16 (extracts 16) AFTER everything else.
    fixtures = [
        {"round": "Finals, Final", "date": "2027-05-30", "home": "A", "away": "B",
         "score": None, "pen_score": None},
        {"round": "Playoffs, Matchday 1", "date": "2027-02-17", "home": "C", "away": "D",
         "score": None, "pen_score": None},
        {"round": "Finals, Round of 16", "date": "2027-03-10", "home": "E", "away": "F",
         "score": None, "pen_score": None},
    ]
    out = build_bracket_html(fixtures, {})
    assert out.index("Play-offs") < out.index("Round of 16") < out.index("Final")


def test_build_bracket_html_shows_aggregate_winner_for_a_decided_tie():
    fixtures = [
        {"round": "Playoffs, Matchday 1", "date": "2027-02-17", "home": "A", "away": "B",
         "score": [2, 0], "pen_score": None},
        {"round": "Playoffs, Matchday 2", "date": "2027-02-24", "home": "B", "away": "A",
         "score": [0, 1], "pen_score": None},
    ]
    out = build_bracket_html(fixtures, {})
    assert "Advances: A" in out
    assert '<span class="bm-sc">2</span>' in out


def test_build_bracket_html_shows_prediction_for_an_unplayed_leg():
    fixtures = [
        {"round": "Finals, Final", "date": "2027-05-30", "home": "A", "away": "B",
         "score": None, "pen_score": None},
    ]
    snapshot = {"Finals, Final|A|B": {"predicted_score": "2-1", "predicted_winner": "H"}}
    out = build_bracket_html(fixtures, snapshot)
    assert "2-1" in out


def test_build_odds_rows_html_empty_state():
    out = build_odds_rows_html({})
    assert "No simulation yet" in out


def test_build_odds_rows_html_sorted_by_champion_odds_descending():
    stage_odds = {
        "Underdog FC": {"round_of_16": 1.0, "quarterfinal": 0.4, "semifinal": 0.1, "final": 0.05, "champion": 0.02},
        "Favourite FC": {"round_of_16": 1.0, "quarterfinal": 0.9, "semifinal": 0.7, "final": 0.5, "champion": 0.3},
    }
    out = build_odds_rows_html(stage_odds)
    assert out.index("Favourite FC") < out.index("Underdog FC")


def test_build_champion_html_picks_highest_champion_odds():
    stage_odds = {
        "Standings Leader FC": {"champion": 0.10},
        "Model Favourite FC": {"champion": 0.63},
    }
    out = build_champion_html(stage_odds)
    assert "Model Favourite FC" in out
    assert "63.0%" in out


def test_build_champion_html_empty_state():
    assert build_champion_html({}) == ""


CUP_CONFIG_DATA = {
    "slug": "test_cup", "name": "Test Cup", "format": "league_phase_knockout",
    "openfootball_repo": "openfootball/example",
    "openfootball_files": [{"season": "2026-27", "path": "2026-27/cup.txt"}],
    "team_aliases": {},
}

TEMPLATE_BODY = (
    "<html><title>__COMPETITION_NAME__</title>"
    "<style>tr:nth-child(-n+__TOP_SEEDS__){}tr:nth-child(n+__PLAYOFF_START__):nth-child(-n+__PLAYOFF_END__){}</style>"
    "<p>__GENERATED_DATE__ __N_SIMS__</p>"
    "<table>__STANDINGS_ROWS__</table>"
    "<div>__BRACKET_HTML__</div>"
    "<div>__CHAMPION_LINE__</div>"
    "<table>__ODDS_ROWS__</table></html>"
)


def test_build_cup_html_writes_index_and_consumes_all_placeholders(tmp_path):
    from competition_config import CompetitionConfig
    config = CompetitionConfig(CUP_CONFIG_DATA)
    out_dir = tmp_path / "competitions" / "test_cup"
    out_dir.mkdir(parents=True)
    (out_dir / "league_schedule.json").write_text(json.dumps(LEAGUE_SCHEDULE))
    (out_dir / "cup_sim.json").write_text(json.dumps({
        "zone_odds": ZONE_ODDS,
        "stage_odds": {"Strong FC": {"round_of_16": 0.9, "quarterfinal": 0.6, "semifinal": 0.4, "final": 0.2, "champion": 0.1}},
        "expected_pos": EXPECTED_POS,
    }))
    template_path = tmp_path / "cup_template.html"
    template_path.write_text(TEMPLATE_BODY)

    out_path = build_cup_html(config, str(tmp_path), str(template_path))
    content = open(out_path, encoding="utf-8").read()
    assert "Test Cup" in content
    assert "__" not in content
    assert "Strong FC" in content


def test_build_cup_html_tolerates_missing_cup_sim(tmp_path):
    # A missing cup_sim.json must NOT be fatal here (unlike build_league_html.py's
    # league_sim.json requirement) -- sim_cup.py itself refuses to run until
    # the league-phase draw is released, a real weeks-long state for these
    # competitions, not a broken pipeline.
    from competition_config import CompetitionConfig
    config = CompetitionConfig(CUP_CONFIG_DATA)
    out_dir = tmp_path / "competitions" / "test_cup"
    out_dir.mkdir(parents=True)
    (out_dir / "league_schedule.json").write_text(json.dumps(LEAGUE_SCHEDULE))
    # no cup_sim.json written
    template_path = tmp_path / "cup_template.html"
    template_path.write_text(TEMPLATE_BODY)

    out_path = build_cup_html(config, str(tmp_path), str(template_path))
    content = open(out_path, encoding="utf-8").read()
    assert "No simulation yet" in content


def test_build_cup_html_raises_on_unconsumed_placeholder(tmp_path):
    from competition_config import CompetitionConfig
    config = CompetitionConfig(CUP_CONFIG_DATA)
    out_dir = tmp_path / "competitions" / "test_cup"
    out_dir.mkdir(parents=True)
    (out_dir / "league_schedule.json").write_text(json.dumps(LEAGUE_SCHEDULE))
    template_path = tmp_path / "bad_template.html"
    template_path.write_text("<html>__COMPETITION_NAME__ __TYPO_TOKEN__</html>")

    with pytest.raises(AssertionError, match="unconsumed placeholder"):
        build_cup_html(config, str(tmp_path), str(template_path))
