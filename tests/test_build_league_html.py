from build_league_html import (compute_full_standings, build_standings_rows,
                                 render_rows_html, top_zone_for, season_span,
                                 build_accuracy_html, build_results_rows_html,
                                 build_bracket_html, build_champion_html)

SCHEDULE_SAMPLE = {
    "Strong FC|Weak FC": {"date": "2026-08-01", "status": "FINISHED",
                           "goals": {"Strong FC": 3, "Weak FC": 1}, "round": "Matchday 1"},
    "Weak FC|Strong FC": {"date": "2026-12-01", "status": "SCHEDULED",
                           "goals": {"Weak FC": None, "Strong FC": None}, "round": "Matchday 20"},
}

RANK_DIST_SAMPLE = {
    "Strong FC": [0.9, 0.1],
    "Weak FC": [0.1, 0.9],
}


def test_compute_full_standings_from_finished_matches():
    table = compute_full_standings(SCHEDULE_SAMPLE)
    assert table["Strong FC"] == {"played": 1, "w": 1, "d": 0, "l": 0, "gf": 3, "ga": 1, "gd": 2, "pts": 3}
    assert table["Weak FC"] == {"played": 1, "w": 0, "d": 0, "l": 1, "gf": 1, "ga": 3, "gd": -2, "pts": 0}


def test_build_standings_rows_ranks_by_points_then_assigns_position():
    rows = build_standings_rows(SCHEDULE_SAMPLE, RANK_DIST_SAMPLE, relegation_zone=1)
    assert rows[0]["team"] == "Strong FC"
    assert rows[0]["pos"] == 1
    assert rows[0]["title_pct"] == 0.9
    assert rows[0]["releg_pct"] == 0.1  # last-place probability, dist[-1:]
    assert rows[1]["team"] == "Weak FC"
    assert rows[1]["pos"] == 2
    assert rows[1]["releg_pct"] == 0.9


def test_build_standings_rows_uses_expected_rank_as_tiebreak_when_tied():
    tied_schedule = {
        "Contender FC|Filler FC": {"date": "2026-08-01", "status": "SCHEDULED",
                                     "goals": {"Contender FC": None, "Filler FC": None}, "round": "Matchday 1"},
    }
    tied_dist = {
        "Contender FC": [0.7, 0.3],  # strongly expected to finish 1st
        "Filler FC": [0.3, 0.7],
    }
    rows = build_standings_rows(tied_schedule, tied_dist, relegation_zone=1)
    # both teams are tied at 0 pts/gd/gf (no matches played) -> tiebreak on
    # expected_rank should still put the model's stronger pick first
    assert rows[0]["team"] == "Contender FC"
    assert rows[0]["pos"] == 1


def test_top_zone_for_championship_is_two_not_four():
    # Regression test for a real bug found in the 22 Jul audit: the live
    # Championship page highlighted 4 rows as "promoted" using the same
    # Champions-League-qualification zone size as Premier League, but
    # Championship promotion is top-2-automatic + a playoff for the 3rd
    # spot (3rd-6th) -- highlighting rows 3-4 as promoted was factually
    # wrong, not just a display simplification.
    assert top_zone_for("Championship") == 2


def test_top_zone_for_defaults_to_four_for_other_leagues():
    assert top_zone_for("Premier League") == 4
    assert top_zone_for("La Liga") == 4
    assert top_zone_for("Bundesliga") == 4
    assert top_zone_for("Some Future League") == 4


def test_render_rows_html_escapes_team_names():
    rows = [{"pos": 1, "team": "A & B FC", "played": 0, "w": 0, "d": 0, "l": 0,
             "gf": 0, "ga": 0, "gd": 0, "pts": 0, "title_pct": 0.5, "releg_pct": 0.1}]
    out = render_rows_html(rows)
    assert "A &amp; B FC" in out


def test_season_span_covers_earliest_to_latest_fixture():
    start, end = season_span(SCHEDULE_SAMPLE)
    assert start == "1 Aug 2026"
    assert end == "1 Dec 2026"


def test_season_span_empty_schedule():
    assert season_span({}) == (None, None)


def test_build_accuracy_html_empty_state_before_any_match_scored():
    out = build_accuracy_html({})
    assert "No matches scored yet" in out


def test_build_accuracy_html_renders_cards_from_summary():
    accuracy = {
        "matches": [{"correct_winner": True}, {"correct_winner": False}, {"correct_winner": True}],
        "summary": {"n_scored": 3, "accuracy": 2 / 3, "avg_brier": 0.55, "avg_log_loss": 0.9},
    }
    out = build_accuracy_html(accuracy)
    assert "2/3" in out
    assert "66.7%" in out
    assert "0.550" in out


def test_build_results_rows_html_empty_state():
    out = build_results_rows_html({}, SCHEDULE_SAMPLE, {})
    assert "No matches scored yet" in out


def test_build_results_rows_html_shows_actual_and_predicted_score_newest_first():
    accuracy = {"matches": [
        {"home": "Strong FC", "away": "Weak FC", "date": "2026-08-01",
         "correct_winner": True, "brier": 0.2, "log_loss": 0.3},
        {"home": "Weak FC", "away": "Strong FC", "date": "2026-09-01",
         "correct_winner": False, "brier": 0.8, "log_loss": 1.2},
    ]}
    schedule = {
        "Strong FC|Weak FC": {"date": "2026-08-01", "status": "FINISHED",
                               "goals": {"Strong FC": 3, "Weak FC": 1}, "round": "Matchday 1"},
        "Weak FC|Strong FC": {"date": "2026-09-01", "status": "FINISHED",
                               "goals": {"Weak FC": 0, "Strong FC": 2}, "round": "Matchday 2"},
    }
    snapshot = {"Strong FC|Weak FC": {"predicted_score": "2-0"}}
    out = build_results_rows_html(accuracy, schedule, snapshot)
    # newest first: the Sep match's row appears before the Aug match's row
    assert out.index("2026-09-01") < out.index("2026-08-01")
    assert "2-0" in out  # locked prediction for the Aug match
    assert "0-2" in out  # actual score for the Sep match
    assert "res-ok" in out and "res-err" in out


def test_build_bracket_html_sorts_matchdays_numerically_not_lexically():
    schedule = {
        "A|B": {"date": "2026-08-01", "status": "SCHEDULED", "goals": {"A": None, "B": None}, "round": "Matchday 2"},
        "C|D": {"date": "2026-08-08", "status": "SCHEDULED", "goals": {"C": None, "D": None}, "round": "Matchday 10"},
    }
    out = build_bracket_html(schedule, {})
    # "Matchday 2" must render before "Matchday 10" (lexical sort would reverse this)
    assert out.index("Matchday 2") < out.index("Matchday 10")


def test_build_bracket_html_shows_score_for_finished_and_prediction_for_locked():
    schedule = {
        "Strong FC|Weak FC": {"date": "2026-08-01", "status": "FINISHED",
                               "goals": {"Strong FC": 3, "Weak FC": 1}, "round": "Matchday 1"},
        "Weak FC|Strong FC": {"date": "2026-12-01", "status": "SCHEDULED",
                               "goals": {"Weak FC": None, "Strong FC": None}, "round": "Matchday 20"},
    }
    snapshot = {"Weak FC|Strong FC": {"predicted_score": "1-2", "predicted_winner": "A"}}
    out = build_bracket_html(schedule, snapshot)
    assert "2026-08-01" in out and "2026-12-01" in out
    assert '<span class="bm-sc">3</span>' in out  # finished match shows the actual score
    assert "1-2" in out  # locked prediction for the unplayed match


def test_build_bracket_html_unpredicted_match_shows_placeholder():
    schedule = {
        "A|B": {"date": "2026-08-01", "status": "SCHEDULED", "goals": {"A": None, "B": None}, "round": "Matchday 1"},
    }
    out = build_bracket_html(schedule, {})
    assert "not yet predicted" in out


def test_build_champion_html_picks_highest_title_pct_not_first_row():
    rows = [
        {"team": "Standings Leader FC", "title_pct": 0.10},
        {"team": "Model Favourite FC", "title_pct": 0.80},
    ]
    out = build_champion_html(rows)
    assert "Model Favourite FC" in out
    assert "80.0%" in out
    assert "Standings Leader FC" not in out


def test_build_champion_html_empty_rows():
    assert build_champion_html([]) == ""


import json

import pytest


def test_build_league_html_writes_index_and_consumes_all_placeholders(tmp_path):
    from build_league_html import build_league_html
    from competition_config import CompetitionConfig
    config = CompetitionConfig({
        "slug": "test_league", "name": "Test League", "format": "round_robin",
        "openfootball_repo": "openfootball/example",
        "openfootball_files": [{"season": "2026-27", "path": "x.txt"}],
        "team_aliases": {},
    })
    out_dir = tmp_path / "competitions" / "test_league"
    out_dir.mkdir(parents=True)
    (out_dir / "schedule.json").write_text(json.dumps(SCHEDULE_SAMPLE))
    (out_dir / "league_sim.json").write_text(json.dumps(RANK_DIST_SAMPLE))

    template_path = tmp_path / "league_template.html"
    template_path.write_text(
        "<html><title>__COMPETITION_NAME__</title>"
        "<p>__GENERATED_DATE__ __N_SIMS__ __RELEGATION_ZONE__</p>"
        "<table>__STANDINGS_ROWS__</table></html>"
    )

    out_path = build_league_html(config, str(tmp_path), str(template_path))
    content = open(out_path, encoding="utf-8").read()
    assert "Test League" in content
    assert "__" not in content  # no leftover placeholder tokens
    assert "Strong FC" in content


def test_build_league_html_raises_on_unconsumed_placeholder(tmp_path):
    from build_league_html import build_league_html
    from competition_config import CompetitionConfig
    config = CompetitionConfig({
        "slug": "test_league", "name": "Test League", "format": "round_robin",
        "openfootball_repo": "openfootball/example",
        "openfootball_files": [{"season": "2026-27", "path": "x.txt"}],
        "team_aliases": {},
    })
    out_dir = tmp_path / "competitions" / "test_league"
    out_dir.mkdir(parents=True)
    (out_dir / "schedule.json").write_text(json.dumps(SCHEDULE_SAMPLE))
    (out_dir / "league_sim.json").write_text(json.dumps(RANK_DIST_SAMPLE))

    template_path = tmp_path / "bad_template.html"
    template_path.write_text("<html>__COMPETITION_NAME__ __TYPO_TOKEN__</html>")  # unconsumed token

    with pytest.raises(AssertionError, match="unconsumed placeholder"):
        build_league_html(config, str(tmp_path), str(template_path))


def test_build_league_html_substitutes_top_zone_per_competition(tmp_path):
    from build_league_html import build_league_html
    from competition_config import CompetitionConfig

    template_path = tmp_path / "league_template.html"
    template_path.write_text(
        "<html><title>__COMPETITION_NAME__</title>"
        "<style>tr:nth-child(-n+__TOP_ZONE__){}</style>"
        "<p>__GENERATED_DATE__ __N_SIMS__ __RELEGATION_ZONE__</p>"
        "<table>__STANDINGS_ROWS__</table></html>"
    )

    def _build(name, slug):
        config = CompetitionConfig({
            "slug": slug, "name": name, "format": "round_robin",
            "openfootball_repo": "openfootball/example",
            "openfootball_files": [{"season": "2026-27", "path": "x.txt"}],
            "team_aliases": {},
        })
        out_dir = tmp_path / "competitions" / slug
        out_dir.mkdir(parents=True)
        (out_dir / "schedule.json").write_text(json.dumps(SCHEDULE_SAMPLE))
        (out_dir / "league_sim.json").write_text(json.dumps(RANK_DIST_SAMPLE))
        out_path = build_league_html(config, str(tmp_path), str(template_path))
        return open(out_path, encoding="utf-8").read()

    championship_html = _build("Championship", "championship_test")
    premier_league_html = _build("Premier League", "premier_league_test")

    assert "nth-child(-n+2)" in championship_html
    assert "nth-child(-n+4)" in premier_league_html


def test_build_league_html_raises_without_league_sim(tmp_path):
    from build_league_html import build_league_html
    from competition_config import CompetitionConfig
    config = CompetitionConfig({
        "slug": "test_league", "name": "Test League", "format": "round_robin",
        "openfootball_repo": "openfootball/example",
        "openfootball_files": [{"season": "2026-27", "path": "x.txt"}],
        "team_aliases": {},
    })
    out_dir = tmp_path / "competitions" / "test_league"
    out_dir.mkdir(parents=True)
    (out_dir / "schedule.json").write_text(json.dumps(SCHEDULE_SAMPLE))
    # no league_sim.json written

    template_path = tmp_path / "league_template.html"
    template_path.write_text("<html></html>")

    with pytest.raises(FileNotFoundError, match="league_sim.json"):
        build_league_html(config, str(tmp_path), str(template_path))
