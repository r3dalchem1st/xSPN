import json
import os

import pytest

from build_hub_html import (build_hub_cards, build_hub_html, cup_snapshot,
                             league_snapshot, world_cup_snapshot)


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


def test_world_cup_snapshot_shows_champion_when_decided(tmp_path):
    (tmp_path / "bracket_data.json").write_text(json.dumps({"champion": "Spain"}))
    assert world_cup_snapshot(str(tmp_path)) == "Champion: Spain"


def test_world_cup_snapshot_falls_back_when_bracket_missing(tmp_path):
    assert world_cup_snapshot(str(tmp_path)) == "2026 tournament predictions"


def test_build_hub_cards_puts_world_cup_first_then_leagues(tmp_path):
    (tmp_path / "bracket_data.json").write_text(json.dumps({"champion": "Spain"}))
    _write_league(tmp_path, "premier_league", "Premier League",
                  rank_dist={"Arsenal FC": [0.48, 0.52]})
    cards = build_hub_cards(str(tmp_path))
    assert cards[0]["name"] == "World Cup 2026"
    assert cards[1]["name"] == "Premier League"
    assert cards[0]["href"] == "/xSPN/competitions/world_cup_2026/"
    assert cards[1]["href"] == "/xSPN/competitions/premier_league/"


def test_build_hub_html_writes_output_and_consumes_all_placeholders(tmp_path):
    (tmp_path / "bracket_data.json").write_text(json.dumps({"champion": "Spain"}))
    template_path = tmp_path / "hub_template.html"
    template_path.write_text("<html>__NAV__<div>__HUB_CARDS__</div></html>")
    out_path = tmp_path / "index.html"

    build_hub_html(str(tmp_path), str(template_path), str(out_path))

    content = out_path.read_text(encoding="utf-8")
    assert "__" not in content
    assert "World Cup 2026" in content
    assert "Spain" in content


def test_build_hub_html_raises_on_unconsumed_placeholder(tmp_path):
    (tmp_path / "bracket_data.json").write_text(json.dumps({"champion": "Spain"}))
    template_path = tmp_path / "bad_template.html"
    template_path.write_text("<html>__NAV__ __TYPO_TOKEN__</html>")
    out_path = tmp_path / "index.html"

    with pytest.raises(AssertionError, match="unconsumed placeholder"):
        build_hub_html(str(tmp_path), str(template_path), str(out_path))
