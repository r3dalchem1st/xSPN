"""
Live upcoming-fixture odds from The Odds API (the-odds-api.com) -- unlike
fetch_odds_history.py's football-data.co.uk CLOSING odds (historical only,
used for backtest_odds.py's comparison), this fetches odds for fixtures
that HAVEN'T been played yet, which is what snapshot_league.py needs to
price a match before it locks.

Confirmed live against the real API (2026-09-04, see CONTEXT.md): GET
/v4/sports/<sport_key>/odds/ returns a list of upcoming fixtures, each with
`home_team`/`away_team` (The Odds API's own team-naming convention -- a
fourth alias table on top of openfootball/openfootball-shortform/
football-data.co.uk, resolved through the same config.team_aliases every
other source uses) and `bookmakers[].markets[].outcomes` -- one h2h market
per bookmaker, each outcome a {name, price} pair keyed by team name or
"Draw", decimal odds. Real sport_key values confirmed via GET /v4/sports/:
soccer_epl, soccer_spain_la_liga, soccer_germany_bundesliga -- not a fixed
naming pattern, so CompetitionConfig.odds_api_sport_key is always set from
a real lookup, never guessed.

No ODDS_API_KEY, no odds_api_sport_key configured, a network failure, or a
non-2xx response -> no-op (empty list/dict), same fail-open discipline as
fetch_live_scores.py: a live-odds hiccup must never break the pipeline it's
an optional enhancement to. The free tier caps at 500 requests/month;
`regions="eu"` with a single market (h2h) costs 1 credit/request (confirmed
live), so a once-daily fetch across all 3 leagues costs ~90/month.
"""
import os

import requests

from odds_utils import implied_probs_from_odds

API_KEY_ENV = "ODDS_API_KEY"
BASE = "https://api.the-odds-api.com/v4"


def fetch_upcoming_odds(sport_key, timeout=15):
    """Raw list of upcoming-fixture odds objects for one Odds API sport_key.
    Empty list on no key, network failure, or non-2xx response -- mirrors
    fetch_live_scores.fetch_matches()'s fail-open convention exactly."""
    api_key = os.environ.get(API_KEY_ENV, "")
    if not api_key:
        return []
    url = f"{BASE}/sports/{sport_key}/odds/"
    params = {"apiKey": api_key, "regions": "eu", "markets": "h2h", "oddsFormat": "decimal"}
    try:
        resp = requests.get(url, params=params, timeout=timeout)
    except requests.RequestException as e:
        print(f"    ! live-odds fetch failed for {sport_key}: {e}")
        return []
    if resp.status_code != 200:
        print(f"    ! live-odds API {resp.status_code} for {sport_key}")
        return []
    return resp.json()


def average_h2h_odds(fixture):
    """Average decimal (home, draw, away) odds across every bookmaker's h2h
    market on one fixture object -- the live-feed equivalent of
    football-data.co.uk's AvgH/AvgD/AvgA columns (fetch_odds_history.py),
    same "market average over one bookmaker's line" rationale already
    established for the historical odds source. Only a bookmaker quoting
    all three outcomes counts; returns None if none do (e.g. a fixture too
    far out for any book to have posted a line yet)."""
    home, away = fixture.get("home_team"), fixture.get("away_team")
    home_odds, draw_odds, away_odds = [], [], []
    for bm in fixture.get("bookmakers", []):
        for market in bm.get("markets", []):
            if market.get("key") != "h2h":
                continue
            outcomes = {o["name"]: o["price"] for o in market.get("outcomes", [])}
            if home in outcomes and away in outcomes and "Draw" in outcomes:
                home_odds.append(outcomes[home])
                draw_odds.append(outcomes["Draw"])
                away_odds.append(outcomes[away])
    if not home_odds:
        return None
    avg = lambda xs: sum(xs) / len(xs)
    return avg(home_odds), avg(draw_odds), avg(away_odds)


def build_odds_lookup(config, raw_fixtures):
    """{("home", "away"): (ph, pd, pa)} de-vigged probability triples for
    every fixture with a resolvable team pair AND a usable h2h market,
    keyed by this competition's own canonical team names (resolved through
    config.team_aliases, same as every other external source). A fixture
    failing either check is simply excluded, not fabricated -- same
    discipline as backtest_odds.py's join_matches_with_odds."""
    lookup = {}
    for fx in raw_fixtures:
        home = config.resolve_team(fx.get("home_team", ""))
        away = config.resolve_team(fx.get("away_team", ""))
        if not home or not away:
            continue
        avg = average_h2h_odds(fx)
        if avg is None:
            continue
        lookup[(home, away)] = implied_probs_from_odds(*avg)
    return lookup
