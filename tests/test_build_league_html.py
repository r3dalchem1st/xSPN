from build_league_html import (compute_full_standings, build_standings_rows,
                                 render_rows_html, top_zone_for)

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
