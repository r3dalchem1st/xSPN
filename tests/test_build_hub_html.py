import json
import os

import pytest

from build_hub_html import (build_hub_cards, build_hub_html, copa_snapshot,
                             cup_snapshot, league_snapshot, world_cup_snapshot)


def _write_league(tmp_path, slug, name, rank_dist=None):
    comp_dir = tmp_path / "competitions" / slug
    comp_dir.mkdir(parents=True)
    (tmp_path / "competitions" / f"{slug}.json").write_text(json.dumps({
        "slug": slug, "name": name, "format": "round_robin",
        "openfootball_repo": "openfootball/example",
        "openfootball_files": [{"season": "2026-27", "path": "x.txt"}],
        "team_aliases": {},
    }))
    if rank_dist is not None:
        (comp_dir / "league_sim.json").write_text(json.dumps(rank_dist))


def test_league_snapshot_reports_the_title_odds_leader(tmp_path):
    _write_league(tmp_path, "premier_league", "Premier League",
                  rank_dist={"Arsenal FC": [0.48, 0.52], "Man City FC": [0.35, 0.65]})
    snapshot = league_snapshot(str(tmp_path), "premier_league")
    assert "Arsenal FC" in snapshot
    assert "48%" in snapshot


def test_league_snapshot_none_when_no_simulation_yet(tmp_path):
    _write_league(tmp_path, "premier_league", "Premier League", rank_dist=None)
    assert league_snapshot(str(tmp_path), "premier_league") is None


def _write_cup(tmp_path, slug, name, stage_odds=None):
    comp_dir = tmp_path / "competitions" / slug
    comp_dir.mkdir(parents=True)
    (tmp_path / "competitions" / f"{slug}.json").write_text(json.dumps({
        "slug": slug, "name": name, "format": "league_phase_knockout",
        "openfootball_repo": "openfootball/example",
        "openfootball_files": [{"season": "2026-27", "path": "x.txt"}],
        "team_aliases": {},
    }))
    if stage_odds is not None:
        (comp_dir / "cup_sim.json").write_text(json.dumps({"zone_odds": {}, "stage_odds": stage_odds}))


def test_cup_snapshot_reports_the_champion_odds_leader(tmp_path):
    _write_cup(tmp_path, "champions_league", "UEFA Champions League",
               stage_odds={"PSG": {"champion": 0.63}, "Arsenal FC": {"champion": 0.11}})
    snapshot = cup_snapshot(str(tmp_path), "champions_league")
    assert "PSG" in snapshot
    assert "63%" in snapshot


def test_cup_snapshot_none_when_no_simulation_yet(tmp_path):
    _write_cup(tmp_path, "champions_league", "UEFA Champions League", stage_odds=None)
    assert cup_snapshot(str(tmp_path), "champions_league") is None


def test_build_hub_cards_uses_cup_snapshot_for_league_phase_knockout_competitions(tmp_path):
    (tmp_path / "bracket_data.json").write_text(json.dumps({"champion": "Spain"}))
    _write_cup(tmp_path, "champions_league", "UEFA Champions League",
               stage_odds={"PSG": {"champion": 0.63}})
    cards = build_hub_cards(str(tmp_path))
    cup_card = next(c for c in cards if c["name"] == "UEFA Champions League")
    assert "PSG" in cup_card["snapshot"]


def test_copa_snapshot_returns_none_when_no_sim_yet(tmp_path):
    os.makedirs(tmp_path / "competitions" / "copa_del_rey")
    assert copa_snapshot(str(tmp_path), "copa_del_rey") is None


def test_copa_snapshot_returns_none_when_every_team_eliminated_or_empty(tmp_path):
    comp_dir = tmp_path / "competitions" / "copa_del_rey"
    comp_dir.mkdir(parents=True)
    (comp_dir / "copa_sim.json").write_text(json.dumps({
        "A": {"champion": 0.0}, "B": {"champion": 0.0},
    }))
    assert copa_snapshot(str(tmp_path), "copa_del_rey") is None


def test_copa_snapshot_shows_the_title_odds_leader(tmp_path):
    comp_dir = tmp_path / "competitions" / "copa_del_rey"
    comp_dir.mkdir(parents=True)
    (comp_dir / "copa_sim.json").write_text(json.dumps({
        "Real Madrid": {"champion": 0.18}, "Minnow FC": {"champion": 0.0},
    }))
    snapshot = copa_snapshot(str(tmp_path), "copa_del_rey")
    assert snapshot == "Real Madrid leads at 18% to win the title"


def test_build_hub_cards_uses_copa_snapshot_fallback_for_knockout_only(tmp_path):
    comp_dir = tmp_path / "competitions"
    comp_dir.mkdir()
    (comp_dir / "copa_del_rey.json").write_text(json.dumps({
        "slug": "copa_del_rey", "name": "Copa del Rey", "format": "knockout_only",
        "openfootball_repo": "openfootball/espana",
        "openfootball_files": [{"season": "2024-25", "path": "2024-25/cup.txt"}],
        "team_aliases": {},
    }))
    cards = build_hub_cards(str(tmp_path))
    copa_card = next(c for c in cards if c["name"] == "Copa del Rey")
    assert copa_card["snapshot"] == "Draw not yet released"


def test_world_cup_snapshot_shows_champion_when_decided(tmp_path):
    (tmp_path / "bracket_data.json").write_text(json.dumps({"champion": "Spain"}))
    assert world_cup_snapshot(str(tmp_path)) == "Champion: Spain"


def test_world_cup_snapshot_falls_back_when_bracket_missing(tmp_path):
    assert world_cup_snapshot(str(tmp_path)) == "2026 tournament predictions"


def test_title_odds_at_100_percent_name_the_champion_and_the_edition_not_leads_at_100(tmp_path):
    # A finished edition simulates to a certain champion; "leads at 100%" read like a live forecast.
    _write_cup(tmp_path, "champions_league", "UEFA Champions League", stage_odds={"PSG": {"champion": 1.0}})
    assert cup_snapshot(str(tmp_path), "champions_league", "2025-26") == "Champion: PSG (2025-26)"
    assert cup_snapshot(str(tmp_path), "champions_league") == "Champion: PSG"
    comp_dir = tmp_path / "competitions" / "copa_del_rey"
    comp_dir.mkdir(parents=True)
    (comp_dir / "copa_sim.json").write_text(json.dumps({"FC Barcelona": {"champion": 1.0}, "Minnow FC": {"champion": 0.0}}))
    assert copa_snapshot(str(tmp_path), "copa_del_rey", "2024-25") == "Champion: FC Barcelona (2024-25)"
    _write_league(tmp_path, "la_liga", "La Liga", rank_dist={"Real Madrid CF": [1.0, 0.0]})
    assert league_snapshot(str(tmp_path), "la_liga", "2026-27") == "Champion: Real Madrid CF (2026-27)"


def test_build_hub_cards_puts_open_competitions_first_and_closed_ones_by_next_edition(tmp_path):
    (tmp_path / "bracket_data.json").write_text(json.dumps({"champion": "Spain"}))
    _write_league(tmp_path, "premier_league", "Premier League", rank_dist={"Arsenal FC": [0.48, 0.52]})
    _write_league(tmp_path, "bundesliga", "Bundesliga", rank_dist={"FC Bayern": [0.88, 0.12]})
    _write_cup(tmp_path, "champions_league", "UEFA Champions League", stage_odds={"PSG": {"champion": 1.0}})
    comp_dir = tmp_path / "competitions" / "copa_del_rey"
    comp_dir.mkdir(parents=True)
    (tmp_path / "competitions" / "copa_del_rey.json").write_text(json.dumps({
        "slug": "copa_del_rey", "name": "Copa del Rey", "format": "knockout_only",
        "openfootball_repo": "openfootball/espana",
        "openfootball_files": [{"season": "2024-25", "path": "2024-25/cup.txt"}], "team_aliases": {}}))
    (comp_dir / "copa_sim.json").write_text(json.dumps({"FC Barcelona": {"champion": 1.0}}))
    cards = build_hub_cards(str(tmp_path))
    assert [c["name"] for c in cards] == ["Bundesliga", "Premier League", "UEFA Champions League",
                                          "Copa del Rey", "World Cup 2026"]
    assert [c["closed"] for c in cards] == [False, False, True, True, True]
    assert cards[2]["snapshot"] == "Champion: PSG (2026-27)"    # the stub config's season
    assert cards[-1]["href"] == "/xSPN/competitions/world_cup_2026/"
    assert cards[0]["href"] == "/xSPN/competitions/bundesliga/"


def test_build_hub_html_writes_output_and_consumes_all_placeholders(tmp_path):
    (tmp_path / "bracket_data.json").write_text(json.dumps({"champion": "Spain"}))
    _write_league(tmp_path, "premier_league", "Premier League", rank_dist={"Arsenal FC": [0.48, 0.52]})
    template_path = tmp_path / "hub_template.html"
    template_path.write_text("<html>__NAV__<div>__HUB_CARDS__</div><i>__HUB_CARDS_CLOSED__</i>__FOOTER__</html>")
    out_path = tmp_path / "index.html"

    build_hub_html(str(tmp_path), str(template_path), str(out_path))

    content = out_path.read_text(encoding="utf-8")
    assert "__" not in content
    assert "World Cup 2026" in content
    assert "Spain" in content
    open_part, closed_part = content.split("<div>", 1)[1].split("<i>")   # past the nav bar, which names both
    assert "Premier League" in open_part and "World Cup 2026" not in open_part   # open grid first
    assert "World Cup 2026" in closed_part and "Premier League" not in closed_part
    assert "Football data provided by the" in content and "Football-Data.org API" in content


def test_build_hub_html_raises_on_unconsumed_placeholder(tmp_path):
    (tmp_path / "bracket_data.json").write_text(json.dumps({"champion": "Spain"}))
    template_path = tmp_path / "bad_template.html"
    template_path.write_text("<html>__NAV__ __TYPO_TOKEN__</html>")
    out_path = tmp_path / "index.html"

    with pytest.raises(AssertionError, match="unconsumed placeholder"):
        build_hub_html(str(tmp_path), str(template_path), str(out_path))
