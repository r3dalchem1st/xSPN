import requests

import fetch_live_scores
from competition_config import CompetitionConfig
from fetch_live_scores import fetch_matches, overlay_live_results

CONFIG_DATA = {
    "slug": "test_league",
    "name": "Test League",
    "format": "round_robin",
    "openfootball_repo": "openfootball/example",
    "openfootball_files": [{"season": "2026-27", "path": "2026-27/1-test.txt"}],
    "team_aliases": {"Man Utd": "Manchester United FC"},
}


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_fetch_matches_noop_without_api_key(monkeypatch):
    monkeypatch.delenv(fetch_live_scores.API_KEY_ENV, raising=False)
    assert fetch_matches("PD") == []


def test_fetch_matches_returns_matches_with_api_key(monkeypatch):
    monkeypatch.setenv(fetch_live_scores.API_KEY_ENV, "test-key")
    fake_matches = [{"homeTeam": {"name": "FC Barcelona"}}]

    def fake_get(url, headers=None, timeout=10):
        assert headers == {"X-Auth-Token": "test-key"}
        return FakeResponse(200, {"matches": fake_matches})

    monkeypatch.setattr(fetch_live_scores.requests, "get", fake_get)
    assert fetch_matches("PD") == fake_matches


def test_fetch_matches_noop_on_non_200(monkeypatch):
    monkeypatch.setenv(fetch_live_scores.API_KEY_ENV, "test-key")
    monkeypatch.setattr(fetch_live_scores.requests, "get",
                         lambda *a, **k: FakeResponse(403, {}))
    assert fetch_matches("PD") == []


def test_fetch_matches_noop_on_request_exception(monkeypatch):
    monkeypatch.setenv(fetch_live_scores.API_KEY_ENV, "test-key")

    def raise_exc(*a, **k):
        raise requests.RequestException("boom")

    monkeypatch.setattr(fetch_live_scores.requests, "get", raise_exc)
    assert fetch_matches("PD") == []


def _finished(home, away, hg, ag):
    return {"homeTeam": {"name": home}, "awayTeam": {"name": away}, "status": "FINISHED",
            "score": {"fullTime": {"home": hg, "away": ag}}}


def _unplayed(home, away, utc_date, status="TIMED"):
    return {"homeTeam": {"name": home}, "awayTeam": {"name": away}, "status": status,
            "utcDate": utc_date, "score": {"fullTime": {"home": None, "away": None}}}


def test_overlay_patches_a_scheduled_fixture():
    config = CompetitionConfig(CONFIG_DATA)
    schedule = {"Fulham FC|Brentford FC": {
        "date": "2026-08-16", "status": "SCHEDULED",
        "goals": {"Fulham FC": None, "Brentford FC": None}, "round": "Matchday 1",
    }}
    _, n_overlaid, n_date_corrected, n_unmatched = overlay_live_results(
        config, schedule, [_finished("Fulham FC", "Brentford FC", 2, 1)])
    assert n_overlaid == 1
    assert n_date_corrected == 0
    assert n_unmatched == 0
    assert schedule["Fulham FC|Brentford FC"]["status"] == "FINISHED"
    assert schedule["Fulham FC|Brentford FC"]["goals"] == {"Fulham FC": 2, "Brentford FC": 1}
    assert schedule["Fulham FC|Brentford FC"]["round"] == "Matchday 1"  # untouched


def test_overlay_resolves_team_aliases():
    config = CompetitionConfig(CONFIG_DATA)
    schedule = {"Manchester United FC|Fulham FC": {
        "date": "2026-08-16", "status": "SCHEDULED",
        "goals": {"Manchester United FC": None, "Fulham FC": None}, "round": "Matchday 1",
    }}
    _, n_overlaid, _, _ = overlay_live_results(
        config, schedule, [_finished("Man Utd", "Fulham FC", 3, 0)])
    assert n_overlaid == 1
    assert schedule["Manchester United FC|Fulham FC"]["goals"] == {
        "Manchester United FC": 3, "Fulham FC": 0,
    }


def test_overlay_skips_unresolved_team_names():
    # A roster-restricted config rejects any name not on the roster (same
    # mechanism build_training_rows relies on) -- exercises the "resolve_team
    # itself rejects it" path distinctly from "resolved fine, just not in
    # schedule" (covered separately below).
    config = CompetitionConfig(dict(CONFIG_DATA, teams=["Manchester United FC", "Fulham FC"]))
    schedule = {}
    _, n_overlaid, _, n_unmatched = overlay_live_results(
        config, schedule, [_finished("Some Random FC", "Fulham FC", 1, 0)])
    assert n_overlaid == 0
    assert n_unmatched == 1


def test_overlay_skips_fixture_already_finished_by_openfootball():
    config = CompetitionConfig(CONFIG_DATA)
    schedule = {"Fulham FC|Brentford FC": {
        "date": "2026-08-16", "status": "FINISHED",
        "goals": {"Fulham FC": 1, "Brentford FC": 1}, "round": "Matchday 1",
    }}
    _, n_overlaid, n_date_corrected, _ = overlay_live_results(
        config, schedule, [_finished("Fulham FC", "Brentford FC", 2, 1)])
    assert n_overlaid == 0
    assert n_date_corrected == 0
    assert schedule["Fulham FC|Brentford FC"]["goals"] == {"Fulham FC": 1, "Brentford FC": 1}


def test_overlay_counts_a_resolved_name_with_no_matching_fixture_as_unmatched():
    # Regression test for a real bug caught live: a resolved-but-unrecognised
    # pair used to be dropped with n_unmatched staying 0 and no log line at
    # all. This must be visible and counted, not just as quiet as "already
    # FINISHED".
    config = CompetitionConfig(CONFIG_DATA)
    schedule = {}
    _, n_overlaid, _, n_unmatched = overlay_live_results(
        config, schedule, [_finished("Fulham FC", "Brentford FC", 2, 1)])
    assert n_overlaid == 0
    assert n_unmatched == 1


def test_overlay_skips_finished_match_with_no_fulltime_score():
    config = CompetitionConfig(CONFIG_DATA)
    schedule = {"Fulham FC|Brentford FC": {
        "date": "2026-08-16", "status": "SCHEDULED",
        "goals": {"Fulham FC": None, "Brentford FC": None}, "round": "Matchday 1",
    }}
    match = {"homeTeam": {"name": "Fulham FC"}, "awayTeam": {"name": "Brentford FC"},
             "status": "FINISHED", "score": {"fullTime": {"home": None, "away": None}}}
    _, n_overlaid, _, _ = overlay_live_results(config, schedule, [match])
    assert n_overlaid == 0
    assert schedule["Fulham FC|Brentford FC"]["status"] == "SCHEDULED"


def test_overlay_corrects_date_of_a_still_unplayed_fixture():
    # Regression test for a real bug caught live: La Liga's openfootball
    # file stamps an entire matchday with one placeholder date (all of
    # Matchday 1 as "2026-08-16"), but football-data.org's real per-match
    # dates showed the round staggered across nearly two weeks -- a
    # not-yet-played fixture's WRONG date should be corrected even though
    # there's no score to overlay yet.
    config = CompetitionConfig(CONFIG_DATA)
    schedule = {"Fulham FC|Brentford FC": {
        "date": "2026-08-16", "status": "SCHEDULED",
        "goals": {"Fulham FC": None, "Brentford FC": None}, "round": "Matchday 1",
    }}
    _, n_overlaid, n_date_corrected, n_unmatched = overlay_live_results(
        config, schedule, [_unplayed("Fulham FC", "Brentford FC", "2026-08-27T19:00:00Z")])
    assert n_overlaid == 0
    assert n_date_corrected == 1
    assert n_unmatched == 0
    assert schedule["Fulham FC|Brentford FC"]["date"] == "2026-08-27"
    assert schedule["Fulham FC|Brentford FC"]["status"] == "SCHEDULED"  # untouched -- no result yet


def test_overlay_leaves_date_alone_when_it_already_matches():
    config = CompetitionConfig(CONFIG_DATA)
    schedule = {"Fulham FC|Brentford FC": {
        "date": "2026-08-27", "status": "SCHEDULED",
        "goals": {"Fulham FC": None, "Brentford FC": None}, "round": "Matchday 1",
    }}
    _, _, n_date_corrected, _ = overlay_live_results(
        config, schedule, [_unplayed("Fulham FC", "Brentford FC", "2026-08-27T19:00:00Z")])
    assert n_date_corrected == 0


def test_overlay_never_touches_date_of_an_already_finished_fixture():
    config = CompetitionConfig(CONFIG_DATA)
    schedule = {"Fulham FC|Brentford FC": {
        "date": "2026-08-16", "status": "FINISHED",
        "goals": {"Fulham FC": 1, "Brentford FC": 1}, "round": "Matchday 1",
    }}
    _, _, n_date_corrected, _ = overlay_live_results(
        config, schedule, [_unplayed("Fulham FC", "Brentford FC", "2026-08-27T19:00:00Z")])
    assert n_date_corrected == 0
    assert schedule["Fulham FC|Brentford FC"]["date"] == "2026-08-16"
