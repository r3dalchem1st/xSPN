import json
import os

from build_copa_html import (build_bracket_html, build_champion_html,
                              build_copa_html, build_odds_rows_html)
from competition_config import CompetitionConfig

CONFIG_DATA = {
    "slug": "copa_del_rey", "name": "Copa del Rey", "format": "knockout_only",
    "openfootball_repo": "openfootball/espana",
    "openfootball_files": [{"season": "2024-25", "path": "2024-25/cup.txt"}],
    "team_aliases": {},
}


def test_build_bracket_html_orders_stages_correctly_not_lexically():
    # "Round of 16" must come after "Round 3" and before "Quarterfinals" --
    # a lexical/numeric sort would scramble this (same trap
    # build_league_html.py's Matchday sort and build_cup_html.py's
    # STAGE_ORDER already had to guard against).
    fixtures = [
        {"round": "Quarterfinals", "date": "2025-02-04", "home": "A", "away": "B",
         "score": None, "pen_score": None},
        {"round": "Round 3", "date": "2024-12-03", "home": "C", "away": "D",
         "score": None, "pen_score": None},
        {"round": "Round of 16", "date": "2025-01-10", "home": "E", "away": "F",
         "score": None, "pen_score": None},
    ]
    html = build_bracket_html(fixtures, {})
    assert html.index("Round 3") < html.index("Round of 16") < html.index("Quarterfinals")


def test_build_bracket_html_empty_state_when_no_fixtures():
    assert "Draw not released" in build_bracket_html([], {})


def test_build_odds_rows_html_hides_eliminated_teams_with_a_count():
    stage_odds = {
        "Real Madrid": {"quarterfinal": 0.9, "semifinal": 0.7, "final": 0.5, "champion": 0.3},
        "Minnow FC": {"quarterfinal": 0.0, "semifinal": 0.0, "final": 0.0, "champion": 0.0},
    }
    html = build_odds_rows_html(stage_odds)
    assert "Real Madrid" in html
    assert "Minnow FC" not in html
    assert "1 eliminated" in html
    # The table has 5 header columns (Team, Quarterfinal, Semifinal, Final,
    # Champion) -- the full-width "eliminated" footer row must span all 5,
    # not the 4-column count left over from the league_phase_knockout
    # template this was adapted from.
    assert 'colspan="5"' in html


def test_build_odds_rows_html_no_simulation_empty_state_spans_all_columns():
    html = build_odds_rows_html({})
    assert "No simulation yet" in html
    assert 'colspan="5"' in html


def test_build_champion_html_empty_when_no_leader():
    assert build_champion_html({}) == ""
    assert build_champion_html({"A": {"champion": 0.0}}) == ""


TEMPLATE_BODY = (
    "<html><title>__COMPETITION_NAME__</title>"
    "<p>__GENERATED_DATE__ __N_SIMS__</p>"
    "<div>__NAV__</div>"
    "<div>__BRACKET_HTML__</div>"
    "<div>__CHAMPION_LINE__</div>"
    "<table>__ODDS_ROWS__</table></html>"
)


def test_build_copa_html_writes_index_with_no_unconsumed_placeholders(tmp_path):
    # Matches test_build_cup_html.py's established convention: write a
    # synthetic minimal template to tmp_path rather than pointing at the
    # real repo-root copa_template.html (avoids relative-path fragility
    # across environments and keeps this test isolated to build_copa_html.py's
    # own placeholder-substitution logic).
    config = CompetitionConfig(CONFIG_DATA)
    out_dir = os.path.join(str(tmp_path), "competitions", config.slug)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "knockout_fixtures.json"), "w") as f:
        json.dump([{"round": "Final", "date": "2025-04-26", "home": "A", "away": "B",
                     "score": [3, 2], "pen_score": None}], f)
    template_path = tmp_path / "copa_template.html"
    template_path.write_text(TEMPLATE_BODY)

    out_path = build_copa_html(config, str(tmp_path), str(template_path))

    with open(out_path) as f:
        content = f.read()
    assert "__" not in content
    assert "Copa del Rey" in content


def test_build_copa_html_against_the_real_template_file(tmp_path):
    config = CompetitionConfig(CONFIG_DATA)
    out_dir = os.path.join(str(tmp_path), "competitions", config.slug)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "knockout_fixtures.json"), "w") as f:
        json.dump([{"round": "Final", "date": "2025-04-26", "home": "A", "away": "B",
                     "score": [3, 2], "pen_score": None}], f)
    real_template_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "copa_template.html")

    out_path = build_copa_html(config, str(tmp_path), real_template_path)

    with open(out_path) as f:
        content = f.read()
    assert "Copa del Rey" in content
