import fetch_odds_history
from competition_config import CompetitionConfig
from fetch_odds_history import fetch_season_csv, parse_odds_rows

CONFIG_DATA = {
    "slug": "test_league", "name": "Test League", "format": "round_robin",
    "openfootball_repo": "openfootball/example",
    "openfootball_files": [{"season": "2026-27", "path": "2026-27/1-test.txt"}],
    "team_aliases": {"Man City": "Manchester City FC", "Brighton": "Brighton & Hove Albion FC"},
}

# Real header + 2 real rows from football-data.co.uk's actual 2025-26
# Premier League CSV (trimmed to the columns this module reads).
REAL_CSV = (
    "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,AvgH,AvgD,AvgA\n"
    "E0,15/08/2025,20:00,Liverpool,Bournemouth,4,2,H,1.35,5.96,8.31\n"
    "E0,16/08/2025,12:30,Man City,Brighton,2,0,H,1.30,5.50,9.00\n"
)


def test_parse_odds_rows_extracts_date_score_and_odds():
    config = CompetitionConfig(CONFIG_DATA)
    rows, n_skipped = parse_odds_rows(REAL_CSV, config)
    # No roster restriction configured -> resolve_team aliases "Man City"/
    # "Brighton" and passes "Liverpool"/"Bournemouth" through unchanged --
    # both rows parse, nothing genuinely unresolved with this config.
    assert n_skipped == 0
    assert len(rows) == 2
    aliased_row = rows[1]
    assert aliased_row["date"] == "2025-08-16"
    assert aliased_row["home"] == "Manchester City FC"
    assert aliased_row["away"] == "Brighton & Hove Albion FC"
    assert aliased_row["hg"] == 2
    assert aliased_row["ag"] == 0
    assert aliased_row["odds"] == (1.30, 5.50, 9.00)


def test_parse_odds_rows_rejects_a_name_not_on_an_explicit_roster():
    # A roster-restricted config genuinely rejects an unlisted name (same
    # mechanism resolve_team already uses elsewhere) -- exercises the real
    # "unresolved" path distinct from "passed through unaliased".
    config = CompetitionConfig(dict(CONFIG_DATA, teams=["Manchester City FC",
                                                         "Brighton & Hove Albion FC"]))
    rows, n_skipped = parse_odds_rows(REAL_CSV, config)
    assert n_skipped == 1  # Liverpool/Bournemouth rejected -- not on the roster
    assert len(rows) == 1
    assert rows[0]["home"] == "Manchester City FC"


def test_parse_odds_rows_skips_a_row_missing_odds():
    csv_missing_odds = (
        "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,AvgH,AvgD,AvgA\n"
        "E0,16/08/2025,12:30,Man City,Brighton,2,0,H,,,\n"
    )
    config = CompetitionConfig(CONFIG_DATA)
    rows, n_skipped = parse_odds_rows(csv_missing_odds, config)
    assert n_skipped == 1
    assert rows == []


def test_fetch_season_csv_uses_the_documented_url_pattern(monkeypatch):
    captured = {}

    class FakeResponse:
        text = "fake,csv,text"
        def raise_for_status(self):
            pass

    def fake_get(url, timeout=15):
        captured["url"] = url
        return FakeResponse()

    monkeypatch.setattr(fetch_odds_history.requests, "get", fake_get)
    text = fetch_season_csv("E0", "2526")
    assert text == "fake,csv,text"
    assert captured["url"] == "https://www.football-data.co.uk/mmz4281/2526/E0.csv"
