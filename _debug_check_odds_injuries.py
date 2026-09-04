"""
TEMPORARY diagnostic, not part of the pipeline -- deleted after use.
Verifies ODDS_API_KEY (the-odds-api.com) and BIGBALLS_API_KEY (Big Balls
Sports Data), just added as repo secrets, actually work, and confirms the
real request/response shapes before any production code is written against
them -- same discipline as every other external-API check this session.

The Odds API: confirms the exact sport_key strings for La Liga/Bundesliga
(only soccer_epl was verified from real docs so far) via GET /v4/sports/,
then fetches real upcoming-fixture odds for one confirmed soccer sport_key
to see the live response shape (bookmakers/markets/outcomes nesting).

Big Balls Sports Data: confirms the real league-wide injuries list-endpoint
request format and response shape for soccer (only the single-player
endpoint + base URL + auth header were confirmed from docs, not this).
"""
import json
import os

import requests

ODDS_KEY = os.environ.get("ODDS_API_KEY", "")
BIGBALLS_KEY = os.environ.get("BIGBALLS_API_KEY", "")

print("=== The Odds API: GET /v4/sports/ (looking for soccer_* keys) ===")
if not ODDS_KEY:
    print("no ODDS_API_KEY")
else:
    resp = requests.get(
        "https://api.the-odds-api.com/v4/sports/",
        params={"apiKey": ODDS_KEY}, timeout=15)
    print("status", resp.status_code, "remaining-quota-header:",
          resp.headers.get("x-requests-remaining"))
    if resp.status_code == 200:
        soccer = [s for s in resp.json() if "soccer" in s.get("key", "")]
        for s in soccer:
            print(s.get("key"), "|", s.get("title"), "|", s.get("group"),
                  "| active:", s.get("active"))
    else:
        print(resp.text[:500])

print()
print("=== The Odds API: GET /v4/sports/soccer_epl/odds/ (real upcoming odds shape) ===")
if not ODDS_KEY:
    print("no ODDS_API_KEY")
else:
    resp = requests.get(
        "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/",
        params={"apiKey": ODDS_KEY, "regions": "uk,eu", "markets": "h2h", "oddsFormat": "decimal"},
        timeout=15)
    print("status", resp.status_code, "remaining-quota-header:",
          resp.headers.get("x-requests-remaining"))
    if resp.status_code == 200:
        data = resp.json()
        print(f"{len(data)} upcoming fixtures returned")
        if data:
            print(json.dumps(data[0], indent=2)[:3000])
    else:
        print(resp.text[:500])

print()
print("=== Big Balls Sports Data: /v1/leagues?sport=football (real league keys) ===")
if not BIGBALLS_KEY:
    print("no BIGBALLS_API_KEY")
else:
    base = "https://api.bigballsdata.com/v1"
    headers = {"Authorization": f"Bearer {BIGBALLS_KEY}"}
    resp = requests.get(f"{base}/leagues", params={"sport": "football"}, headers=headers, timeout=15)
    print("status", resp.status_code)
    print(resp.text[:1500])

    print()
    print("=== Big Balls Sports Data: league-wide injuries list endpoint (path TBD from docs) ===")
    # Docs (bigballsdata.com/injuries-api) describe a league-wide feed as
    # `GET /v1/injuries?sport=<sport>`, and the football matches/standings
    # endpoints all take `league=<key>` alongside `sport=football` -- try
    # both the sport-only form and the sport+league form for each candidate
    # league key, and report exactly what each returns rather than assuming
    # which one is real.
    for params in [
        {"sport": "football", "league": "laliga"},
        {"sport": "football", "league": "bundesliga"},
    ]:
        resp = requests.get(f"{base}/injuries", params=params, headers=headers, timeout=15)
        print(params, "-> status", resp.status_code)
        print(resp.text[:2500])
        print("---")

    print()
    print("=== Big Balls Sports Data: /v1/teams?sport=football&league=laliga (id->name mapping?) ===")
    resp = requests.get(f"{base}/teams", params={"sport": "football", "league": "laliga"}, headers=headers, timeout=15)
    print("status", resp.status_code)
    print(resp.text[:2500])

    print()
    print("=== Big Balls Sports Data: single-player injury detail (first la_liga injured player) ===")
    resp = requests.get(f"{base}/injuries", params={"sport": "football", "league": "laliga"}, headers=headers, timeout=15)
    if resp.status_code == 200:
        try:
            first_id = resp.json()["data"]["injuries"]["value"][0]["id"]
            detail = requests.get(f"{base}/players/{first_id}/injury", params={"sport": "football"}, headers=headers, timeout=15)
            print("player_id:", first_id, "-> status", detail.status_code)
            print(detail.text[:1500])
        except (KeyError, IndexError) as e:
            print("could not extract a player id to test:", e)
