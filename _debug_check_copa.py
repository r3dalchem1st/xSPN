"""TEMPORARY diagnostic, deleted after use. Checks whether API-Football's
season=2025 for Copa del Rey (league 143) has the actual 2025-26 tournament
-- the most recent one openfootball is missing entirely."""
import os

import requests

AF_KEY = os.environ.get("API_FOOTBALL_KEY", "")
resp = requests.get("https://v3.football.api-sports.io/fixtures",
                     headers={"x-apisports-key": AF_KEY},
                     params={"league": 143, "season": 2025}, timeout=15)
data = resp.json()
print("status", resp.status_code, "results", data.get("results"))
matches = data.get("response", [])
print("total matches:", len(matches))
if matches:
    dates = sorted(fx["fixture"]["date"] for fx in matches)
    print("date range:", dates[0], "-", dates[-1])
    statuses = {}
    for fx in matches:
        s = fx["fixture"]["status"]["short"]
        statuses[s] = statuses.get(s, 0) + 1
    print("statuses:", statuses)
    print("first 3:")
    for fx in matches[:3]:
        f, t = fx["fixture"], fx["teams"]
        print(" ", f["date"], f["round"] if "round" in f else fx.get("league", {}).get("round"),
              t["home"]["name"], "vs", t["away"]["name"], fx["goals"])
    print("last 3:")
    for fx in matches[-3:]:
        f, t = fx["fixture"], fx["teams"]
        print(" ", f["date"], fx.get("league", {}).get("round"),
              t["home"]["name"], "vs", t["away"]["name"], fx["goals"])
