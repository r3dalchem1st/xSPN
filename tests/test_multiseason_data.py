import multiseason_data
from multiseason_data import (load_season_csv, parse_fd_date, parse_season_rows, team_name_splits,
                              to_fit_rows)

HEADER = "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,{odds}\n"


def _csv(rows, odds_cols="AvgH,AvgD,AvgA"):
    return HEADER.format(odds=odds_cols) + "\n".join(rows) + "\n"


def test_parse_fd_date_handles_two_and_four_digit_years():
    assert parse_fd_date("16/08/14") == "2014-08-16"
    assert parse_fd_date("15/08/2025") == "2025-08-15"


def test_parse_season_rows_reads_result_and_devigged_market_from_the_preferred_columns():
    rows = parse_season_rows(_csv(["E0,15/08/2025, Arsenal ,Chelsea,2,1,2.0,3.5,4.0"]))
    assert len(rows) == 1
    r = rows[0]
    assert (r["date"], r["home"], r["away"], r["hg"], r["ag"]) == ("2025-08-15", "Arsenal", "Chelsea", 2, 1)
    assert abs(sum(r["market"]) - 1.0) < 1e-9 and r["market"][0] > r["market"][2]


def test_parse_season_rows_falls_back_to_older_average_then_a_single_book():
    old = parse_season_rows(_csv(["E0,16/08/14,A,B,1,0,2.0,3.0,4.0"], "BbAvH,BbAvD,BbAvA"))
    assert old[0]["market"] is not None
    single = parse_season_rows(_csv(["E0,16/08/14,A,B,1,0,2.0,3.0,4.0"], "B365H,B365D,B365A"))
    assert single[0]["market"] is not None


def test_parse_season_rows_market_is_none_when_odds_are_missing_or_blank():
    assert parse_season_rows(_csv(["E0,16/08/14,A,B,1,0,,,"]))[0]["market"] is None
    assert parse_season_rows(_csv(["E0,16/08/14,A,B,1,0,2.0,3.0,4.0"], "Nothing,Here,AtAll"))[0]["market"] is None


def test_parse_season_rows_skips_unplayed_rows_and_sorts_by_date():
    rows = parse_season_rows(_csv(["E0,20/08/14,A,B,1,0,2,3,4", "E0,16/08/14,C,D,0,0,2,3,4", "E0,30/08/14,E,F,,,2,3,4"]))
    assert [r["date"] for r in rows] == ["2014-08-16", "2014-08-20"]


def test_load_season_csv_caches_to_disk_and_does_not_refetch(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(multiseason_data, "fetch_season_csv", lambda code, season: calls.append((code, season)) or "csv text")
    assert load_season_csv("E0", "2526", str(tmp_path)) == "csv text"
    assert load_season_csv("E0", "2526", str(tmp_path)) == "csv text"
    assert calls == [("E0", "2526")]


def test_team_name_splits_lists_clubs_that_appear_in_only_one_of_two_seasons():
    by_season = {"1415": [{"home": "A", "away": "B"}, {"home": "B", "away": "C"}],
                 "1516": [{"home": "A", "away": "B"}, {"home": "B", "away": "D"}]}
    assert team_name_splits(by_season) == {("1415", "1516"): (["C"], ["D"])}


def test_to_fit_rows_matches_fit_leagues_row_shape():
    rows = [{"date": "2025-08-15", "home": "A", "away": "B", "hg": 2, "ag": 1, "market": None}]
    assert to_fit_rows(rows, "La Liga") == [["2025-08-15", "A", "B", 2, 1, "La Liga", False]]
