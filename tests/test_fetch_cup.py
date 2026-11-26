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


def test_fetch_and_save_overlays_live_results_into_league_schedule(tmp_path, monkeypatch):
    data = dict(CONFIG_DATA, football_data_code="CL")
    config = CompetitionConfig(data)

    def fake_fetch(repo, path, timeout=10):
        return "current-season"

    def fake_parse(text):
        return [UNPLAYED_LEAGUE_MATCH]  # Real Madrid CF vs Fulham FC, SCHEDULED

    monkeypatch.setattr(fetch_cup, "fetch_openfootball_file", fake_fetch)
    monkeypatch.setattr(fetch_cup, "parse_openfootball_txt", fake_parse)
    monkeypatch.setattr(fetch_cup, "fetch_live_matches",
                         lambda code: [{"homeTeam": {"name": "Real Madrid CF"},
                                        "awayTeam": {"name": "Fulham FC"},
                                        "status": "FINISHED",
                                        "score": {"fullTime": {"home": 3, "away": 1}}}])

    summary = fetch_and_save(config, str(tmp_path))
    out_dir = tmp_path / "competitions" / "test_cup"
    with open(out_dir / "league_schedule.json") as f:
        sched = json.load(f)
    key = "Real Madrid CF|Fulham FC"
    assert sched[key]["status"] == "FINISHED"
    assert sched[key]["goals"] == {"Real Madrid CF": 3, "Fulham FC": 1}


def test_fetch_and_save_skips_live_overlay_when_not_configured(tmp_path, monkeypatch):
    config = CompetitionConfig(CONFIG_DATA)  # no football_data_code

    def fake_fetch(repo, path, timeout=10):
        return "current-season"

    def fake_parse(text):
        return [UNPLAYED_LEAGUE_MATCH]

    def fail_if_called(code):
        raise AssertionError("fetch_live_matches should not be called without football_data_code")

    monkeypatch.setattr(fetch_cup, "fetch_openfootball_file", fake_fetch)
    monkeypatch.setattr(fetch_cup, "parse_openfootball_txt", fake_parse)
    monkeypatch.setattr(fetch_cup, "fetch_live_matches", fail_if_called)

    summary = fetch_and_save(config, str(tmp_path))
    assert summary["league_scheduled"] == 1  # ran fine, never touched the live fetch


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


# ---- football-data.org as the current season's source (the 2026-27 Champions League) ----

def _fd(stage, status="FINISHED", home="Real Madrid CF", away="Arsenal FC", date="2026-11-25T20:00:00Z",
        matchday=None, **score):
    return {"stage": stage, "matchday": matchday, "status": status, "utcDate": date,
            "homeTeam": {"name": home}, "awayTeam": {"name": away}, "score": score}


def test_football_data_match_maps_the_league_phase_to_the_openfootball_shape():
    m = fetch_cup.football_data_match(_fd("LEAGUE_STAGE", matchday=5, duration="REGULAR",
                                          fullTime={"home": 2, "away": 1}))
    assert m == {"round": "League, Matchday 5", "date": "2026-11-25", "home": "Real Madrid CF",
                 "away": "Arsenal FC", "score": (2, 1)}
    assert classify_stage(m["round"]) == "league"


def test_football_data_match_gives_an_unplayed_match_no_score():
    m = fetch_cup.football_data_match(_fd("LEAGUE_STAGE", status="TIMED", matchday=6,
                                          fullTime={"home": None, "away": None}))
    assert m["score"] is None
    in_play = fetch_cup.football_data_match(_fd("LEAGUE_STAGE", status="IN_PLAY", matchday=6,
                                                fullTime={"home": 1, "away": 0}))
    assert in_play["score"] is None                     # only a FINISHED match carries a score


def test_football_data_match_labels_every_knockout_stage_the_way_sim_cup_reads_them():
    from sim_cup import _bracket_round
    want = {"PLAYOFFS": "playoff", "LAST_16": "round_of_16", "QUARTER_FINALS": "quarterfinal",
            "SEMI_FINALS": "semifinal", "FINAL": "final"}
    for stage, bracket_round in want.items():
        m = fetch_cup.football_data_match(_fd(stage, fullTime={"home": 1, "away": 0}))
        assert _bracket_round(m["round"]) == bracket_round
        assert classify_stage(m["round"]) == ("playoff" if stage == "PLAYOFFS" else "final")


def test_football_data_match_keeps_extra_time_goals_and_a_shootout_apart():
    et = fetch_cup.football_data_match(_fd("LAST_16", duration="EXTRA_TIME", fullTime={"home": 3, "away": 2},
                                           regularTime={"home": 2, "away": 2}, extraTime={"home": 1, "away": 0}))
    assert et["score"] == (3, 2) and "pen_score" not in et
    # fullTime of a shoot-out match may include the shoot-out goals (5-4 here): use 90 + extra time instead
    pens = fetch_cup.football_data_match(_fd("FINAL", duration="PENALTY_SHOOTOUT", fullTime={"home": 5, "away": 4},
                                            regularTime={"home": 1, "away": 1}, extraTime={"home": 0, "away": 0},
                                            penalties={"home": 4, "away": 3}))
    assert pens["score"] == (1, 1) and pens["pen_score"] == (4, 3)


def test_football_data_match_skips_slots_without_teams_or_stages_we_dont_model():
    assert fetch_cup.football_data_match(_fd("LAST_16", home=None, status="TIMED", fullTime={})) is None
    assert fetch_cup.football_data_match(_fd("PRELIMINARY_ROUND", fullTime={"home": 1, "away": 0})) is None


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code != 200:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def test_fetch_football_data_season_returns_known_matches_in_date_order(monkeypatch):
    monkeypatch.setenv("FD_API_KEY", "k")
    seen = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.update(url=url, params=params, token=headers["X-Auth-Token"])
        return _Resp(200, {"matches": [
            _fd("LEAGUE_STAGE", matchday=2, date="2026-09-16T19:00:00Z", fullTime={"home": 0, "away": 0}),
            _fd("LAST_16", home=None, status="TIMED", fullTime={}),              # draw not made yet
            _fd("LEAGUE_STAGE", matchday=1, date="2026-09-08T19:00:00Z", fullTime={"home": 2, "away": 3})]})

    monkeypatch.setattr(fetch_cup.requests, "get", fake_get)
    out = fetch_cup.fetch_football_data_season("CL", 2026)
    assert [m["date"] for m in out] == ["2026-09-08", "2026-09-16"]
    assert seen["url"].endswith("/competitions/CL/matches") and seen["params"] == {"season": 2026}
    assert seen["token"] == "k"


def test_fetch_football_data_season_raises_without_a_key_or_on_an_http_error(monkeypatch):
    monkeypatch.delenv("FD_API_KEY", raising=False)
    with pytest.raises(requests.RequestException):
        fetch_cup.fetch_football_data_season("CL", 2026)
    monkeypatch.setenv("FD_API_KEY", "k")
    monkeypatch.setattr(fetch_cup.requests, "get", lambda *a, **k: _Resp(429, {}))
    with pytest.raises(requests.RequestException):
        fetch_cup.fetch_football_data_season("CL", 2026)


FD_CONFIG_DATA = dict(CONFIG_DATA, football_data_code="CL", football_data_seasons=[2027],
                      openfootball_files=[{"season": "2026-27", "path": "2026-27/cup.txt"}])


def test_fetch_and_save_takes_the_current_season_from_football_data_and_history_from_openfootball(tmp_path, monkeypatch):
    config = CompetitionConfig(FD_CONFIG_DATA)
    monkeypatch.setattr(fetch_cup, "fetch_football_data_season",
                        lambda code, season: [LEAGUE_MATCH, UNPLAYED_LEAGUE_MATCH, PLAYOFF_MATCH])
    monkeypatch.setattr(fetch_cup, "fetch_openfootball_file", lambda repo, path, timeout=10: "history")
    monkeypatch.setattr(fetch_cup, "parse_openfootball_txt", lambda text: [LEAGUE_PHASE_LABEL_MATCH])
    monkeypatch.setattr(fetch_cup, "fetch_live_matches",
                        lambda code: pytest.fail("the overlay is redundant when football-data.org is the source"))

    summary = fetch_and_save(config, str(tmp_path))

    assert summary["current_season_failed"] is False
    assert summary["matches"] == 3 and summary["league_scheduled"] == 2 and summary["knockout_fixtures"] == 1
    sched = json.loads((tmp_path / "competitions" / "test_cup" / "league_schedule.json").read_text())
    assert sched["Real Madrid CF|Arsenal FC"]["status"] == "FINISHED"      # came from football-data.org
    assert "Manchester United FC|Fulham FC" not in sched                    # the history season only trains


def test_fetch_and_save_aborts_on_a_football_data_failure_and_leaves_the_artifacts_alone(tmp_path, monkeypatch):
    config = CompetitionConfig(FD_CONFIG_DATA)
    out_dir = tmp_path / "competitions" / "test_cup"
    out_dir.mkdir(parents=True)
    (out_dir / "league_schedule.json").write_text('{"keep": "me"}')

    def boom(code, season):
        raise requests.RequestException("429")

    monkeypatch.setattr(fetch_cup, "fetch_football_data_season", boom)
    monkeypatch.setattr(fetch_cup, "fetch_openfootball_file", lambda repo, path, timeout=10: "history")
    monkeypatch.setattr(fetch_cup, "parse_openfootball_txt", lambda text: [LEAGUE_MATCH])

    summary = fetch_and_save(config, str(tmp_path))

    assert summary["current_season_failed"] is True
    assert summary["failed_seasons"] == ["football-data.org CL 2027"]
    assert json.loads((out_dir / "league_schedule.json").read_text()) == {"keep": "me"}
