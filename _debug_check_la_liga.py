"""
TEMPORARY diagnostic, not part of the pipeline -- deleted after use.
Cross-checks football-data.org's raw La Liga schedule (not just FINISHED)
against API-Football's for the same window, to find out whether the 5
still-SCHEDULED Matchday 1 fixtures genuinely haven't been played yet, or
whether one source is just lagging the other.
"""
import json
import os

import requests

FD_KEY = os.environ.get("FD_API_KEY", "")
AF_KEY = os.environ.get("API_FOOTBALL_KEY", "")

print("=== football-data.org: PD (La Liga), all statuses, matchday 1 ===")
if not FD_KEY:
    print("no FD_API_KEY")
else:
    resp = requests.get("https://api.football-data.org/v4/competitions/PD/matches",
                         headers={"X-Auth-Token": FD_KEY}, params={"matchday": "1"}, timeout=15)
    print("status", resp.status_code)
    if resp.status_code == 200:
        for m in resp.json().get("matches", []):
            print(m.get("utcDate"), m.get("status"),
                  m.get("homeTeam", {}).get("name"), "vs", m.get("awayTeam", {}).get("name"),
                  m.get("score", {}).get("fullTime"))
    else:
        print(resp.text[:500])

print()
print("=== API-Football: league 140 (La Liga), season 2026, 2026-08-14..2026-08-19 ===")
if not AF_KEY:
    print("no API_FOOTBALL_KEY")
else:
    resp = requests.get("https://v3.football.api-sports.io/fixtures",
                         headers={"x-apisports-key": AF_KEY},
                         params={"league": 140, "season": 2026, "from": "2026-08-14", "to": "2026-08-19"},
                         timeout=15)
    print("status", resp.status_code)
    if resp.status_code == 200:
        data = resp.json()
        print("results:", data.get("results"))
        for fx in data.get("response", []):
            f = fx["fixture"]
            teams = fx["teams"]
            goals = fx["goals"]
            print(f["date"], f["status"]["short"],
                  teams["home"]["name"], "vs", teams["away"]["name"],
                  goals.get("home"), "-", goals.get("away"))
    else:
        print(resp.text[:500])
