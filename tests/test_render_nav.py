import json
import os

from render_nav import nav_entries, render_nav_html


def _make_competitions_dir(tmp_path, configs):
    comp_dir = tmp_path / "competitions"
    comp_dir.mkdir()
    for slug, name in configs.items():
        (comp_dir / f"{slug}.json").write_text(json.dumps({
            "slug": slug, "name": name, "format": "round_robin",
            "openfootball_repo": "openfootball/example",
            "openfootball_files": [{"season": "2026-27", "path": "x.txt"}],
            "team_aliases": {},
        }))


def test_nav_entries_includes_hub_and_world_cup_first():
    entries = nav_entries(os.path.dirname(os.path.abspath(__file__)) + "/..", active=None)
    assert entries[0]["label"] == "xSPN"
    assert entries[1]["label"] == "World Cup 2026"


def test_nav_entries_discovers_competitions_dynamically(tmp_path):
    _make_competitions_dir(tmp_path, {"premier_league": "Premier League", "bundesliga": "Bundesliga"})
    entries = nav_entries(str(tmp_path), active=None)
    labels = [e["label"] for e in entries]
    assert "Premier League" in labels
    assert "Bundesliga" in labels
    # discovered slugs come after the two fixed entries
    assert len(labels) == 4


def _write_schedule(tmp_path, slug, first_date):
    comp_dir = tmp_path / "competitions" / slug
    comp_dir.mkdir(parents=True)
    (comp_dir / "schedule.json").write_text(json.dumps({
        "A|B": {"date": first_date, "status": "SCHEDULED", "goals": {"A": None, "B": None}, "round": "Matchday 1"},
    }))


def test_nav_entries_orders_leagues_by_season_start_not_alphabetically(tmp_path):
    # Real-world case this is a regression test for: alphabetically,
    # "bundesliga" sorts before "la_liga" and "premier_league" -- but the
    # Bundesliga season actually starts LAST of the three, so alphabetical
    # order put the tabs in the wrong reading order on the live site.
    _make_competitions_dir(tmp_path, {
        "bundesliga": "Bundesliga", "la_liga": "La Liga", "premier_league": "Premier League",
    })
    _write_schedule(tmp_path, "la_liga", "2026-08-16")
    _write_schedule(tmp_path, "premier_league", "2026-08-21")
    _write_schedule(tmp_path, "bundesliga", "2026-08-28")

    entries = nav_entries(str(tmp_path), active=None)
    labels = [e["label"] for e in entries[2:]]
    assert labels == ["La Liga", "Premier League", "Bundesliga"]


def test_nav_entries_sorts_competition_without_schedule_yet_last(tmp_path):
    _make_competitions_dir(tmp_path, {"la_liga": "La Liga", "new_league": "New League"})
    _write_schedule(tmp_path, "la_liga", "2026-08-16")
    # "new_league" has no schedule.json yet (not fetched for the first time)

    entries = nav_entries(str(tmp_path), active=None)
    labels = [e["label"] for e in entries[2:]]
    assert labels == ["La Liga", "New League"]


def test_nav_entries_orders_a_league_phase_knockout_competition_by_its_own_schedule_filename(tmp_path):
    # Regression test for a real gap: league_phase_knockout competitions
    # write "league_schedule.json", not "schedule.json" -- without a
    # fallback, _season_start() would never find their fixtures and every
    # cup competition would sort last forever, never reflecting its real
    # season start once fetched.
    _make_competitions_dir(tmp_path, {"la_liga": "La Liga", "champions_league": "UEFA Champions League"})
    _write_schedule(tmp_path, "la_liga", "2026-08-16")
    comp_dir = tmp_path / "competitions" / "champions_league"
    comp_dir.mkdir(parents=True)
    (comp_dir / "league_schedule.json").write_text(json.dumps({
        "A|B": {"date": "2026-07-01", "status": "SCHEDULED", "goals": {"A": None, "B": None}, "round": "League, Matchday 1"},
    }))

    entries = nav_entries(str(tmp_path), active=None)
    labels = [e["label"] for e in entries[2:]]
    assert labels == ["UEFA Champions League", "La Liga"]  # July < August


def test_nav_entries_marks_the_active_page(tmp_path):
    _make_competitions_dir(tmp_path, {"premier_league": "Premier League"})
    entries = nav_entries(str(tmp_path), active="premier_league")
    active = [e for e in entries if e["active"]]
    assert len(active) == 1
    assert active[0]["label"] == "Premier League"


def test_nav_entries_falls_back_to_slug_on_malformed_config(tmp_path):
    comp_dir = tmp_path / "competitions"
    comp_dir.mkdir()
    (comp_dir / "broken_league.json").write_text("not valid json {{{")
    entries = nav_entries(str(tmp_path), active=None)
    labels = [e["label"] for e in entries]
    assert "broken_league" in labels  # falls back to the slug, doesn't crash


def test_render_nav_html_marks_active_entry_and_links_every_entry():
    entries = [
        {"label": "xSPN", "href": "/xSPN/", "active": True},
        {"label": "World Cup 2026", "href": "/xSPN/competitions/world_cup_2026/", "active": False},
    ]
    html = render_nav_html(entries)
    assert '<a href="/xSPN/" class="active">xSPN</a>' in html
    assert '<a href="/xSPN/competitions/world_cup_2026/">World Cup 2026</a>' in html
