"""
TEMPORARY diagnostic, not part of the pipeline -- deleted after use.
Finds API-Football's real league id for Copa del Rey and checks whether it
already has any 2026-27 season fixtures (draws for early rounds happen much
later than league season starts, so openfootball has nothing yet -- this
checks whether API-Football is ahead of it).
"""
import json
import os

import requests

AF_KEY = os.environ.get("API_FOOTBALL_KEY", "")

print("=== API-Football: search leagues matching 'Copa del Rey' ===")
if not AF_KEY:
    print("no API_FOOTBALL_KEY")
else:
    resp = requests.get("https://v3.football.api-sports.io/leagues",
                         headers={"x-apisports-key": AF_KEY},
                         params={"search": "Copa del Rey"}, timeout=15)
    print("status", resp.status_code)
    data = resp.json()
    print("results:", data.get("results"))
    league_ids = []
    for entry in data.get("response", []):
        league = entry["league"]
        country = entry.get("country", {})
        print(league["id"], league["name"], league["type"], "-", country.get("name"),
              "seasons:", [s["year"] for s in entry.get("seasons", [])])
        if country.get("name") == "Spain":
            league_ids.append(league["id"])

    print()
    print("=== Fixtures for each Spain-country match, season 2026 ===")
    for lid in league_ids:
        resp = requests.get("https://v3.football.api-sports.io/fixtures",
                             headers={"x-apisports-key": AF_KEY},
                             params={"league": lid, "season": 2026}, timeout=15)
        data = resp.json()
        print(f"league {lid}: status {resp.status_code}, results {data.get('results')}")
        for fx in data.get("response", [])[:5]:
            f = fx["fixture"]
            teams = fx["teams"]
            print("  ", f["date"], f["status"]["short"], teams["home"]["name"], "vs", teams["away"]["name"])
