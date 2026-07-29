import json
import os

import pytest
import requests

import fetch_copa
from competition_config import CompetitionConfig
from fetch_copa import build_knockout_fixtures, classify_round, fetch_and_save

CONFIG_DATA = {
    "slug": "copa_del_rey",
    "name": "Copa del Rey",
    "format": "knockout_only",
    "openfootball_repo": "openfootball/espana",
    "openfootball_files": [{"season": "2024-25", "path": "2024-25/cup.txt"}],
    "extra_training_sources": [
        {"repo": "openfootball/espana", "path": "2024-25/1-liga.txt"},
    ],
    "team_aliases": {},
}

PRELIM_MATCH = {"round": "Preliminary round", "date": "2024-10-09",
                "home": "San Tirso SD", "away": "Selaya FC", "score": (5, 3), "pen_score": (5, 3)}
ROUND1_MATCH = {"round": "Round 1", "date": "2024-10-29",
                "home": "Rayo Vallecano", "away": "CD Villamuriel", "score": (5, 0)}
UNPLAYED_ROUND1_MATCH = {"round": "Round 1", "date": "2024-10-30",
                         "home": "Sevilla FC", "away": "Las Rozas CF", "score": None}
SEMIFINAL_LEG1 = {"round": "Semifinals", "date": "2025-02-25",
                  "home": "FC Barcelona", "away": "Atlético Madrid", "score": (4, 4)}
FINAL_MATCH = {"round": "Final", "date": "2025-04-26",
               "home": "FC Barcelona", "away": "Real Madrid", "score": (3, 2), "pen_score": None}
UNRECOGNISED_ROUND_MATCH = {"round": "Group Stage", "date": "2024-09-01",
                            "home": "FC Barcelona", "away": "Real Madrid", "score": (1, 0)}


def test_classify_round_matches_all_eight_real_stages():
    assert classify_round("Preliminary round") == "preliminary"
    assert classify_round("Round 1") == "round_1"
    assert classify_round("Round 2") == "round_2"
    assert classify_round("Round 3") == "round_3"
    assert classify_round("Round of 16") == "round_of_16"
    assert classify_round("Quarterfinals") == "quarterfinal"
    assert classify_round("Semifinals") == "semifinal"
    assert classify_round("Final") == "final"


def test_classify_round_rejects_unrecognised_label():
    assert classify_round("Group Stage") is None
    assert classify_round(None) is None


def test_build_knockout_fixtures_includes_every_recognised_round():
    config = CompetitionConfig(CONFIG_DATA)
    fixtures, n_skipped = build_knockout_fixtures(
        config, [PRELIM_MATCH, ROUND1_MATCH, UNPLAYED_ROUND1_MATCH, SEMIFINAL_LEG1,
                  FINAL_MATCH, UNRECOGNISED_ROUND_MATCH])
    assert n_skipped == 0
    assert len(fixtures) == 5  # every match except the unrecognised "Group Stage" one
    assert fixtures[0]["round"] == "Preliminary round"
    assert fixtures[0]["score"] == [5, 3]
    assert fixtures[0]["pen_score"] == [5, 3]
    assert fixtures[2]["score"] is None  # UNPLAYED_ROUND1_MATCH
    assert fixtures[2]["pen_score"] is None
    assert fixtures[4]["round"] == "Final"


def test_build_knockout_fixtures_skips_unmapped_team_names():
    config = CompetitionConfig(dict(CONFIG_DATA, teams=["FC Barcelona", "Real Madrid"]))
    fixtures, n_skipped = build_knockout_fixtures(config, [FINAL_MATCH, ROUND1_MATCH])
    assert n_skipped == 1  # ROUND1_MATCH's teams aren't on the explicit roster
    assert len(fixtures) == 1


def test_fetch_and_save_merges_training_rows_from_copa_and_extra_sources(tmp_path, monkeypatch):
    config = CompetitionConfig(CONFIG_DATA)
    text_by_path = {"2024-25/cup.txt": "cup-text", "2024-25/1-liga.txt": "liga-text"}

    def fake_fetch(repo, path, timeout=10):
        return text_by_path[path]

    def fake_parse(text):
        if text == "cup-text":
            return [ROUND1_MATCH, UNPLAYED_ROUND1_MATCH, FINAL_MATCH]
        return [{"round": "Matchday 1", "date": "2024-08-16",
                 "home": "Real Madrid", "away": "Osasuna", "score": (2, 0)}]

    monkeypatch.setattr(fetch_copa, "fetch_openfootball_file", fake_fetch)
    monkeypatch.setattr(fetch_copa, "parse_openfootball_txt", fake_parse)

    summary = fetch_and_save(config, str(tmp_path))

    assert summary == {
        "matches": 3, "knockout_fixtures": 3, "skipped": 0,
        "failed_seasons": [], "current_season_failed": False,
    }
    out_dir = tmp_path / "competitions" / "copa_del_rey"
    with open(out_dir / "fetched_matches.json") as f:
        rows = json.load(f)
    assert len(rows) == 3  # 2 played Copa matches + 1 La Liga match
    assert ["Real Madrid", "Osasuna"] in [[r[1], r[2]] for r in rows]
    with open(out_dir / "knockout_fixtures.json") as f:
        ko = json.load(f)
    assert [fx["round"] for fx in ko] == ["Round 1", "Round 1", "Final"]


def test_fetch_and_save_extra_source_failure_is_not_fatal(tmp_path, monkeypatch):
    config = CompetitionConfig(CONFIG_DATA)

    def fake_fetch(repo, path, timeout=10):
        if path == "2024-25/1-liga.txt":
            raise requests.RequestException("boom")
        return "cup-text"

    def fake_parse(text):
        return [FINAL_MATCH]

    monkeypatch.setattr(fetch_copa, "fetch_openfootball_file", fake_fetch)
    monkeypatch.setattr(fetch_copa, "parse_openfootball_txt", fake_parse)

    summary = fetch_and_save(config, str(tmp_path))

    assert summary["current_season_failed"] is False  # only the EXTRA source failed, not Copa's own
    assert "2024-25/1-liga.txt" in summary["failed_seasons"]
    assert summary["matches"] == 1  # just the Copa final, extra source contributed nothing


def test_fetch_and_save_preserves_knockout_fixtures_when_current_season_fetch_fails(tmp_path, monkeypatch):
    config = CompetitionConfig(CONFIG_DATA)
    out_dir = os.path.join(str(tmp_path), "competitions", config.slug)
    os.makedirs(out_dir, exist_ok=True)
    preexisting = [{"round": "Final", "date": "2023-05-30", "home": "A", "away": "B",
                     "score": [1, 0], "pen_score": None}]
    with open(os.path.join(out_dir, "knockout_fixtures.json"), "w") as f:
        json.dump(preexisting, f)

    def fake_fetch(repo, path, timeout=10):
        raise requests.RequestException("boom")

    monkeypatch.setattr(fetch_copa, "fetch_openfootball_file", fake_fetch)

    summary = fetch_and_save(config, str(tmp_path))

    assert summary["current_season_failed"] is True
    with open(os.path.join(out_dir, "knockout_fixtures.json")) as f:
        assert json.load(f) == preexisting  # untouched, not wiped


def test_main_exits_nonzero_when_current_season_fetch_fails(tmp_path, monkeypatch):
    config_path = tmp_path / "copa_del_rey.json"
    config_path.write_text(json.dumps(CONFIG_DATA))

    monkeypatch.setattr(fetch_copa, "load_competition",
                         lambda path: CompetitionConfig(CONFIG_DATA))
    monkeypatch.setattr(fetch_copa, "fetch_and_save",
                         lambda config, base_dir: {
                             "matches": 0, "knockout_fixtures": 0, "skipped": 0,
                             "failed_seasons": ["2024-25/cup.txt"], "current_season_failed": True,
                         })
    monkeypatch.setattr(fetch_copa.sys, "argv", ["fetch_copa.py", str(config_path)])

    with pytest.raises(SystemExit) as exc_info:
        fetch_copa.main()
    assert exc_info.value.code == 1
