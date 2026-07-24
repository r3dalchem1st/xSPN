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


def test_nav_entries_hub_first_then_explicit_nav_order():
    # Real, live repo: hub, then the explicit NAV_ORDER sequence (24 Jul
    # reorder request) -- World Cup moved from 2nd to LAST here, a direct
    # instruction, not something derivable from season-start date.
    entries = nav_entries(os.path.dirname(os.path.abspath(__file__)) + "/..", active=None)
    labels = [e["label"] for e in entries]
    assert labels == ["xSPN", "La Liga", "Premier League", "Bundesliga",
                       "UEFA Champions League", "World Cup 2026"]


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


def test_nav_entries_uses_explicit_nav_order_not_season_start(tmp_path):
    # NAV_ORDER is now an explicit, hand-picked sequence (24 Jul reorder
    # request), not derived from season-start date -- proven by setting up
    # schedule dates in the OPPOSITE order from NAV_ORDER and confirming
    # the explicit order still wins.
    _make_competitions_dir(tmp_path, {
        "bundesliga": "Bundesliga", "la_liga": "La Liga", "premier_league": "Premier League",
    })
    _write_schedule(tmp_path, "bundesliga", "2026-08-01")   # earliest date...
    _write_schedule(tmp_path, "premier_league", "2026-08-10")
    _write_schedule(tmp_path, "la_liga", "2026-08-20")      # ...latest date

    entries = nav_entries(str(tmp_path), active=None)
    labels = [e["label"] for e in entries[1:] if e["label"] != "World Cup 2026"]  # skip hub + the always-present WC entry
    assert labels == ["La Liga", "Premier League", "Bundesliga"]  # NAV_ORDER wins, not dates


def test_nav_entries_appends_unnamed_competitions_after_named_ones(tmp_path):
    # A competition not yet added to NAV_ORDER (e.g. a freshly onboarded
    # Copa del Rey) sorts after every explicitly-ordered entry, regardless
    # of its own season start date.
    _make_competitions_dir(tmp_path, {"la_liga": "La Liga", "copa_del_rey": "Copa del Rey"})
    _write_schedule(tmp_path, "la_liga", "2026-08-16")
    _write_schedule(tmp_path, "copa_del_rey", "2026-01-01")  # earlier date, still sorts after

    entries = nav_entries(str(tmp_path), active=None)
    labels = [e["label"] for e in entries[1:] if e["label"] != "World Cup 2026"]
    assert labels == ["La Liga", "Copa del Rey"]


def test_nav_entries_sorts_unnamed_competitions_by_season_start_among_themselves(tmp_path):
    _make_competitions_dir(tmp_path, {"copa_del_rey": "Copa del Rey", "afcon": "AFCON"})
    _write_schedule(tmp_path, "afcon", "2027-01-10")
    _write_schedule(tmp_path, "copa_del_rey", "2026-11-01")

    entries = nav_entries(str(tmp_path), active=None)
    labels = [e["label"] for e in entries[1:] if e["label"] != "World Cup 2026"]
    assert labels == ["Copa del Rey", "AFCON"]


def test_nav_entries_sorts_unnamed_competition_without_schedule_yet_last(tmp_path):
    _make_competitions_dir(tmp_path, {"copa_del_rey": "Copa del Rey", "afcon": "AFCON"})
    _write_schedule(tmp_path, "copa_del_rey", "2026-11-01")
    # "afcon" has no schedule.json yet (not fetched for the first time)

    entries = nav_entries(str(tmp_path), active=None)
    labels = [e["label"] for e in entries[1:] if e["label"] != "World Cup 2026"]
    assert labels == ["Copa del Rey", "AFCON"]


def test_nav_entries_orders_a_league_phase_knockout_competition_by_its_own_schedule_filename(tmp_path):
    # Regression test for a real gap: league_phase_knockout competitions
    # write "league_schedule.json", not "schedule.json" -- without a
    # fallback, _season_start() would never find their fixtures. Uses an
    # id NOT in NAV_ORDER (champions_league now is, and would always sort
    # by NAV_ORDER regardless of date) so this still isolates the
    # fallback-filename mechanism itself.
    _make_competitions_dir(tmp_path, {"copa_del_rey": "Copa del Rey", "afcon": "AFCON"})
    comp_dir = tmp_path / "competitions" / "afcon"
    comp_dir.mkdir(parents=True)
    (comp_dir / "league_schedule.json").write_text(json.dumps({
        "A|B": {"date": "2026-07-01", "status": "SCHEDULED", "goals": {"A": None, "B": None}, "round": "League, Matchday 1"},
    }))
    _write_schedule(tmp_path, "copa_del_rey", "2026-08-16")

    entries = nav_entries(str(tmp_path), active=None)
    labels = [e["label"] for e in entries[1:] if e["label"] != "World Cup 2026"]
    assert labels == ["AFCON", "Copa del Rey"]  # July < August


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
