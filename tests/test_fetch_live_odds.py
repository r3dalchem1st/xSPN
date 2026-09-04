import math

import requests

import fetch_live_odds
from competition_config import CompetitionConfig
from fetch_live_odds import average_h2h_odds, build_odds_lookup, fetch_upcoming_odds

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
        self._payload = payload if payload is not None else []

    def json(self):
        return self._payload


def test_fetch_upcoming_odds_noop_without_api_key(monkeypatch):
    monkeypatch.delenv(fetch_live_odds.API_KEY_ENV, raising=False)
    assert fetch_upcoming_odds("soccer_epl") == []


def test_fetch_upcoming_odds_returns_fixtures_with_api_key(monkeypatch):
    monkeypatch.setenv(fetch_live_odds.API_KEY_ENV, "test-key")
    fake_fixtures = [{"home_team": "Fulham FC", "away_team": "Brentford FC"}]

    def fake_get(url, params=None, timeout=15):
        assert url == "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/"
        assert params["apiKey"] == "test-key"
        return FakeResponse(200, fake_fixtures)

    monkeypatch.setattr(fetch_live_odds.requests, "get", fake_get)
    assert fetch_upcoming_odds("soccer_epl") == fake_fixtures


def test_fetch_upcoming_odds_noop_on_non_200(monkeypatch):
    monkeypatch.setenv(fetch_live_odds.API_KEY_ENV, "test-key")
    monkeypatch.setattr(fetch_live_odds.requests, "get", lambda *a, **k: FakeResponse(401, []))
    assert fetch_upcoming_odds("soccer_epl") == []


def test_fetch_upcoming_odds_noop_on_request_exception(monkeypatch):
    monkeypatch.setenv(fetch_live_odds.API_KEY_ENV, "test-key")

    def raise_exc(*a, **k):
        raise requests.RequestException("boom")

    monkeypatch.setattr(fetch_live_odds.requests, "get", raise_exc)
    assert fetch_upcoming_odds("soccer_epl") == []


def _fixture(home, away, books):
    """books: list of {name: price} outcome dicts, one per bookmaker's h2h market."""
    return {
        "home_team": home, "away_team": away,
        "bookmakers": [
            {"key": f"book{i}", "markets": [{"key": "h2h", "outcomes": [
                {"name": k, "price": v} for k, v in b.items()]}]}
            for i, b in enumerate(books)
        ],
    }


def test_average_h2h_odds_averages_across_bookmakers():
    fx = _fixture("Fulham FC", "Brentford FC", [
        {"Fulham FC": 2.0, "Brentford FC": 4.0, "Draw": 3.0},
        {"Fulham FC": 2.2, "Brentford FC": 3.8, "Draw": 3.2},
    ])
    ph, pd, pa = average_h2h_odds(fx)
    assert math.isclose(ph, 2.1)
    assert math.isclose(pd, 3.1)
    assert math.isclose(pa, 3.9)


def test_average_h2h_odds_ignores_non_h2h_markets():
    fx = _fixture("Fulham FC", "Brentford FC", [{"Fulham FC": 2.0, "Brentford FC": 4.0, "Draw": 3.0}])
    fx["bookmakers"].append({"key": "book_totals", "markets": [
        {"key": "totals", "outcomes": [{"name": "Over", "price": 1.9}]}]})
    ph, pd, pa = average_h2h_odds(fx)
    assert math.isclose(ph, 2.0)


def test_average_h2h_odds_returns_none_when_no_complete_market():
    fx = {"home_team": "Fulham FC", "away_team": "Brentford FC", "bookmakers": []}
    assert average_h2h_odds(fx) is None


def test_average_h2h_odds_skips_bookmaker_missing_an_outcome():
    fx = _fixture("Fulham FC", "Brentford FC", [{"Fulham FC": 2.0, "Draw": 3.0}])  # no away price
    assert average_h2h_odds(fx) is None


def test_build_odds_lookup_resolves_aliases_and_devigs():
    config = CompetitionConfig(CONFIG_DATA)
    raw = [_fixture("Man Utd", "Fulham FC", [{"Man Utd": 1.5, "Fulham FC": 6.0, "Draw": 4.0}])]
    lookup = build_odds_lookup(config, raw)
    assert ("Manchester United FC", "Fulham FC") in lookup
    ph, pd, pa = lookup[("Manchester United FC", "Fulham FC")]
    assert math.isclose(ph + pd + pa, 1.0)
    assert ph > pa  # Man Utd heavily favored at 1.5 vs 6.0


def test_build_odds_lookup_skips_unresolved_team_name():
    config = CompetitionConfig(dict(CONFIG_DATA, teams=["Manchester United FC", "Fulham FC"]))
    raw = [_fixture("Some Random FC", "Fulham FC", [{"Some Random FC": 2.0, "Fulham FC": 3.0, "Draw": 3.5}])]
    assert build_odds_lookup(config, raw) == {}


def test_build_odds_lookup_skips_fixture_with_no_usable_odds():
    config = CompetitionConfig(CONFIG_DATA)
    raw = [{"home_team": "Man Utd", "away_team": "Fulham FC", "bookmakers": []}]
    assert build_odds_lookup(config, raw) == {}
