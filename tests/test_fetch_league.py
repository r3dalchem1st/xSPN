import json

import pytest
import requests

import fetch_league
from competition_config import CompetitionConfig
from fetch_league import build_schedule, build_training_rows, fetch_and_save

CONFIG_DATA = {
    "slug": "test_league",
    "name": "Test League",
    "format": "round_robin",
    "openfootball_repo": "openfootball/example",
    "openfootball_files": [
        {"season": "2026-27", "path": "2026-27/1-test.txt"},
        {"season": "2025-26", "path": "2025-26/1-test.txt"},
    ],
    "team_aliases": {"Man Utd": "Manchester United FC"},
}

ALIASED_MATCH = {"round": "Matchday 1", "date": "2026-08-14", "home": "Man Utd",
                  "away": "Fulham FC", "score": (1, 0)}
PLAIN_MATCH = {"round": "Matchday 1", "date": "2026-08-15", "home": "Brentford FC",
               "away": "Fulham FC", "score": (2, 2)}
UNPLAYED_MATCH = {"round": "Matchday 1", "date": "2026-08-16", "home": "Man Utd",
                  "away": "Brentford FC", "score": None}


def test_build_training_rows_resolves_alias():
    config = CompetitionConfig(CONFIG_DATA)
    rows, n_skipped = build_training_rows(config, [ALIASED_MATCH])
    assert rows == [["2026-08-14", "Manchester United FC", "Fulham FC", 1, 0, "Test League", False]]
    assert n_skipped == 0


def test_build_training_rows_passes_through_unaliased_name_with_no_roster():
    config = CompetitionConfig(CONFIG_DATA)
    rows, n_skipped = build_training_rows(config, [PLAIN_MATCH])
    assert rows == [["2026-08-15", "Brentford FC", "Fulham FC", 2, 2, "Test League", False]]
    assert n_skipped == 0


def test_build_training_rows_rejects_unlisted_name_once_roster_set():
    data = dict(CONFIG_DATA, teams=["Manchester United FC", "Fulham FC"])
    config = CompetitionConfig(data)
    rows, n_skipped = build_training_rows(config, [PLAIN_MATCH])  # Brentford not on roster
    assert rows == []
    assert n_skipped == 1


def test_build_training_rows_ignores_unplayed():
    config = CompetitionConfig(CONFIG_DATA)
    rows, n_skipped = build_training_rows(config, [UNPLAYED_MATCH])
    assert rows == []
    assert n_skipped == 0


def test_build_schedule_includes_played_and_unplayed():
    config = CompetitionConfig(CONFIG_DATA)
    sched, n_skipped = build_schedule(config, [ALIASED_MATCH, UNPLAYED_MATCH])
    finished_key = "Manchester United FC|Fulham FC"
    scheduled_key = "Manchester United FC|Brentford FC"
    assert sched[finished_key]["status"] == "FINISHED"
    assert sched[finished_key]["goals"] == {"Manchester United FC": 1, "Fulham FC": 0}
    assert sched[scheduled_key]["status"] == "SCHEDULED"
    assert n_skipped == 0


def test_build_schedule_keeps_both_legs_of_a_double_round_robin():
    # A league plays each pair twice (home + away leg). A key derived from
    # the SORTED pair would collide the two legs into one entry, silently
    # dropping the other — this guards against that regression.
    config = CompetitionConfig(CONFIG_DATA)
    home_leg = {"round": "Matchday 1", "date": "2026-08-14", "home": "Man Utd",
                "away": "Fulham FC", "score": (1, 0)}
    away_leg = {"round": "Matchday 20", "date": "2027-01-10", "home": "Fulham FC",
                "away": "Man Utd", "score": (2, 2)}
    sched, n_skipped = build_schedule(config, [home_leg, away_leg])
    assert n_skipped == 0
    assert len(sched) == 2
    assert sched["Manchester United FC|Fulham FC"]["goals"] == {
        "Manchester United FC": 1, "Fulham FC": 0,
    }
    assert sched["Fulham FC|Manchester United FC"]["goals"] == {
        "Fulham FC": 2, "Manchester United FC": 2,
    }


def test_fetch_and_save_writes_artifacts(tmp_path, monkeypatch):
    config = CompetitionConfig(CONFIG_DATA)
    text_by_path = {
        "2026-27/1-test.txt": "current-season",
        "2025-26/1-test.txt": "prior-season",
    }

    def fake_fetch(repo, path, timeout=10):
        return text_by_path[path]

    def fake_parse(text):
        return [UNPLAYED_MATCH] if text == "current-season" else [ALIASED_MATCH]

    monkeypatch.setattr(fetch_league, "fetch_openfootball_file", fake_fetch)
    monkeypatch.setattr(fetch_league, "parse_openfootball_txt", fake_parse)

    summary = fetch_and_save(config, str(tmp_path))

    assert summary == {"matches": 1, "scheduled": 1, "skipped": 0, "failed_seasons": []}
    out_dir = tmp_path / "competitions" / "test_league"
    with open(out_dir / "fetched_matches.json") as f:
        assert json.load(f) == [["2026-08-14", "Manchester United FC", "Fulham FC", 1, 0, "Test League", False]]
    with open(out_dir / "schedule.json") as f:
        sched = json.load(f)
    scheduled_key = "Manchester United FC|Brentford FC"
    assert sched[scheduled_key]["status"] == "SCHEDULED"


def test_fetch_and_save_records_failed_season(tmp_path, monkeypatch):
    config = CompetitionConfig(CONFIG_DATA)

    def fake_fetch(repo, path, timeout=10):
        if path == "2025-26/1-test.txt":
            raise requests.RequestException("boom")
        return "current-season"

    def fake_parse(text):
        return [UNPLAYED_MATCH]

    monkeypatch.setattr(fetch_league, "fetch_openfootball_file", fake_fetch)
    monkeypatch.setattr(fetch_league, "parse_openfootball_txt", fake_parse)

    summary = fetch_and_save(config, str(tmp_path))
    assert summary["failed_seasons"] == ["2025-26/1-test.txt"]
    assert summary["matches"] == 0  # the only season that fetched had no played matches
