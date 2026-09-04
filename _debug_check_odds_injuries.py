"""
TEMPORARY diagnostic, not part of the pipeline -- deleted after use.
Cross-checks The Odds API's own team-naming convention against each
league's real, committed schedule.json (checked out fresh on the runner)
to find any name that wouldn't resolve through the existing team_aliases
tables before shipping fetch_live_odds.py against them for real.
"""
import json
import os
import sys

import requests

sys.path.insert(0, ".")
from competition_config import load_competition  # noqa: E402

ODDS_KEY = os.environ.get("ODDS_API_KEY", "")

LEAGUE_SPORT_KEYS = {
    "premier_league": "soccer_epl",
    "la_liga": "soccer_spain_la_liga",
    "bundesliga": "soccer_germany_bundesliga",
}

print("=== The Odds API: cross-check team names against our own schedule.json (all 3 leagues) ===")
if not ODDS_KEY:
    print("no ODDS_API_KEY")
else:
    for slug, sport_key in LEAGUE_SPORT_KEYS.items():
        resp = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/",
            params={"apiKey": ODDS_KEY, "regions": "eu", "markets": "h2h", "oddsFormat": "decimal"},
            timeout=15)
        print(f"--- {slug} ({sport_key}): status {resp.status_code}, "
              f"quota remaining {resp.headers.get('x-requests-remaining')} ---")
        if resp.status_code != 200:
            print(resp.text[:500])
            continue
        data = resp.json()
        odds_names = sorted({fx["home_team"] for fx in data} | {fx["away_team"] for fx in data})
        print(f"{len(data)} upcoming fixtures, {len(odds_names)} unique team names: {odds_names}")

        sched_path = f"competitions/{slug}/schedule.json"
        canonical_names = []
        try:
            with open(sched_path) as f:
                schedule = json.load(f)
            canonical_names = sorted({t for key in schedule for t in key.split("|")})
        except FileNotFoundError:
            print(f"(no {sched_path} in this checkout to cross-check against)")

        config = load_competition(f"competitions/{slug}.json")
        unresolved = sorted(n for n in odds_names if config.resolve_team(n) not in canonical_names)
        print(f"NOT resolving to a real canonical team name: {unresolved}")
