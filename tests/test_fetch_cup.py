import json
import os

import pytest
import requests

import fetch_cup
from competition_config import CompetitionConfig
from fetch_cup import (build_knockout_fixtures, build_league_schedule,
                        build_training_rows, classify_stage, fetch_and_save,
                        strip_country_suffix)

CONFIG_DATA = {
    "slug": "test_cup",
    "name": "Test Cup",
    "format": "league_phase_knockout",
    "openfootball_repo": "openfootball/example",
    "openfootball_files": [
        {"season": "2026-27", "path": "2026-27/cup.txt"},
        {"season": "2025-26", "path": "2025-26/cup.txt"},
    ],
    "team_aliases": {"Man Utd": "Manchester United FC"},  # alias keys are matched AFTER the country suffix is stripped
}

LEAGUE_MATCH = {"round": "League, Matchday 1", "date": "2026-09-16",
                "home": "Real Madrid CF (ESP)", "away": "Arsenal FC (ENG)", "score": (2, 1)}
LEAGUE_PHASE_LABEL_MATCH = {"round": "League phase", "date": "2026-09-25",
                            "home": "Man Utd (ENG)", "away": "Fulham FC (ENG)", "score": (0, 0)}
UNPLAYED_LEAGUE_MATCH = {"round": "League, Matchday 2", "date": "2026-09-30",
                         "home": "Real Madrid CF (ESP)", "away": "Fulham FC (ENG)", "score": None}
PLAYOFF_MATCH = {"round": "Playoffs, Matchday 1", "date": "2027-02-17",
                 "home": "Real Madrid CF (ESP)", "away": "Arsenal FC (ENG)", "score": (1, 0),
                 "pen_score": None}
FINAL_ET_MATCH = {"round": "Finals, Final", "date": "2027-05-30",
                   "home": "Real Madrid CF (ESP)", "away": "Arsenal FC (ENG)", "score": (1, 1),
                   "pen_score": (4, 3)}
UNRECOGNISED_ROUND_MATCH = {"round": "Qualifying, Round 1", "date": "2026-07-01",
                             "home": "Real Madrid CF (ESP)", "away": "Arsenal FC (ENG)", "score": (3, 0)}


def test_strip_country_suffix():
    assert strip_country_suffix("Real Madrid CF (ESP)") == "Real Madrid CF"
    assert strip_country_suffix("Manchester United FC") == "Manchester United FC"


def test_classify_stage():
    assert classify_stage("League, Matchday 1") == "league"
    assert classify_stage("League phase") == "league"
    assert classify_stage("Playoffs, Matchday 2") == "playoff"
    assert classify_stage("Finals, Round of 16") == "final"
    assert classify_stage("Finals, Final") == "final"
    assert classify_stage("Qualifying, Round 1") is None
    assert classify_stage(None) is None


def test_classify_stage_recognises_bare_knockout_round_names():
    # Regression test for a real bug caught via a live smoke test: 2024-25's
    # openfootball Europa League file labels the knockout bracket with no
    # "Finals," prefix at all ("▪ Quarterfinals", not "▪ Finals,
    # Quarterfinals") -- without this, every Round-of-16-onward match in
    # that file was silently dropped.
    assert classify_stage("Round of 16") == "final"
    assert classify_stage("Quarterfinals") == "final"
    assert classify_stage("Semifinals") == "final"
    assert classify_stage("Final") == "final"


def test_build_training_rows_covers_every_stage_and_strips_country_suffix():
    config = CompetitionConfig(CONFIG_DATA)
    rows, n_skipped = build_training_rows(
        config, [LEAGUE_MATCH, PLAYOFF_MATCH, FINAL_ET_MATCH, UNRECOGNISED_ROUND_MATCH])
    assert rows == [
        ["2026-09-16", "Real Madrid CF", "Arsenal FC", 2, 1, "Test Cup", False],
        ["2027-02-17", "Real Madrid CF", "Arsenal FC", 1, 0, "Test Cup", False],
        ["2027-05-30", "Real Madrid CF", "Arsenal FC", 1, 1, "Test Cup", False],
    ]
    assert n_skipped == 0  # the unrecognised-round match is silently excluded, not "skipped" (not an error)


def test_build_training_rows_resolves_alias_after_stripping_suffix():
    config = CompetitionConfig(CONFIG_DATA)
    rows, n_skipped = build_training_rows(config, [LEAGUE_PHASE_LABEL_MATCH])
    assert rows == [["2026-09-25", "Manchester United FC", "Fulham FC", 0, 0, "Test Cup", False]]
    assert n_skipped == 0


def test_build_league_schedule_only_includes_league_stage():
    config = CompetitionConfig(CONFIG_DATA)
    sched, n_skipped = build_league_schedule(
        config, [LEAGUE_MATCH, UNPLAYED_LEAGUE_MATCH, PLAYOFF_MATCH, FINAL_ET_MATCH])
    assert n_skipped == 0
    assert set(sched.keys()) == {"Real Madrid CF|Arsenal FC", "Real Madrid CF|Fulham FC"}
    assert sched["Real Madrid CF|Arsenal FC"]["status"] == "FINISHED"
    assert sched["Real Madrid CF|Fulham FC"]["status"] == "SCHEDULED"


def test_build_knockout_fixtures_only_includes_playoff_and_final_stages():
    config = CompetitionConfig(CONFIG_DATA)
    fixtures, n_skipped = build_knockout_fixtures(
        config, [LEAGUE_MATCH, PLAYOFF_MATCH, FINAL_ET_MATCH])
    assert n_skipped == 0
    assert len(fixtures) == 2
    assert fixtures[0]["round"] == "Playoffs, Matchday 1"
    assert fixtures[0]["score"] == [1, 0]
    assert fixtures[0]["pen_score"] is None
    assert fixtures[1]["round"] == "Finals, Final"
    assert fixtures[1]["score"] == [1, 1]
    assert fixtures[1]["pen_score"] == [4, 3]


def test_fetch_and_save_writes_all_three_artifacts(tmp_path, monkeypatch):
    config = CompetitionConfig(CONFIG_DATA)
    text_by_path = {"2026-27/cup.txt": "current-season", "2025-26/cup.txt": "prior-season"}

    def fake_fetch(repo, path, timeout=10):
        return text_by_path[path]

    def fake_parse(text):
        if text == "current-season":
            return [LEAGUE_MATCH, UNPLAYED_LEAGUE_MATCH, PLAYOFF_MATCH, FINAL_ET_MATCH]
        return [LEAGUE_MATCH]

    monkeypatch.setattr(fetch_cup, "fetch_openfootball_file", fake_fetch)
    monkeypatch.setattr(fetch_cup, "parse_openfootball_txt", fake_parse)

    summary = fetch_and_save(config, str(tmp_path))

    assert summary == {
        "matches": 4, "league_scheduled": 2, "knockout_fixtures": 2, "skipped": 0,
        "failed_seasons": [], "current_season_failed": False,
    }
    out_dir = tmp_path / "competitions" / "test_cup"
    with open(out_dir / "fetched_matches.json") as f:
        assert len(json.load(f)) == 4
    with open(out_dir / "league_schedule.json") as f:
        league_sched = json.load(f)
    assert league_sched["Real Madrid CF|Fulham FC"]["status"] == "SCHEDULED"
    with open(out_dir / "knockout_fixtures.json") as f:
        ko = json.load(f)
    assert [fx["round"] for fx in ko] == ["Playoffs, Matchday 1", "Finals, Final"]


def test_fetch_and_save_preserves_knockout_fixtures_when_current_season_fetch_fails(tmp_path, monkeypatch):
    config = CompetitionConfig(CONFIG_DATA)
    out_dir = os.path.join(str(tmp_path), "competitions", config.slug)
    os.makedirs(out_dir, exist_ok=True)
    preexisting = [{"round": "Finals, Final", "date": "2026-05-30",
                     "home": "Real Madrid CF", "away": "Arsenal FC", "score": None, "pen_score": None}]
    with open(os.path.join(out_dir, "knockout_fixtures.json"), "w") as f:
        json.dump(preexisting, f)

    def fake_fetch(repo, path, timeout=10):
        if path == "2026-27/cup.txt":
            raise requests.RequestException("boom")
        return "prior-season"

    def fake_parse(text):
        return [LEAGUE_MATCH]

    monkeypatch.setattr(fetch_cup, "fetch_openfootball_file", fake_fetch)
    monkeypatch.setattr(fetch_cup, "parse_openfootball_txt", fake_parse)

    summary = fetch_and_save(config, str(tmp_path))

    assert summary["current_season_failed"] is True
    with open(os.path.join(out_dir, "knockout_fixtures.json")) as f:
        assert json.load(f) == preexisting  # untouched, not wiped


def test_main_exits_nonzero_when_current_season_fetch_fails(tmp_path, monkeypatch):
    config_path = tmp_path / "test_cup.json"
    config_path.write_text(json.dumps(CONFIG_DATA))

    monkeypatch.setattr(fetch_cup, "load_competition",
                         lambda path: CompetitionConfig(CONFIG_DATA))
    monkeypatch.setattr(fetch_cup, "fetch_and_save",
                         lambda config, base_dir: {
                             "matches": 0, "league_scheduled": 0, "knockout_fixtures": 0,
                             "skipped": 0, "failed_seasons": ["2026-27/cup.txt"],
                             "current_season_failed": True,
                         })
    monkeypatch.setattr(fetch_cup.sys, "argv", ["fetch_cup.py", str(config_path)])

    with pytest.raises(SystemExit) as exc_info:
        fetch_cup.main()
    assert exc_info.value.code == 1
