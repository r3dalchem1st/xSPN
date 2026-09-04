"""TEMPORARY diagnostic, deleted after use. Checks real API-Football
coverage for injuries and odds at the DOMESTIC LEAGUE level (La Liga),
since the WC's own fetch_injuries.py/fetch_cards.py only prove this works
for international squads -- club-league coverage on the free tier is
unconfirmed."""
import json
import os

import requests

AF_KEY = os.environ.get("API_FOOTBALL_KEY", "")
H = {"x-apisports-key": AF_KEY}
BASE = "https://v3.football.api-sports.io"

print("=== Injuries: La Liga (league 140), season 2025 ===")
resp = requests.get(f"{BASE}/injuries", headers=H, params={"league": 140, "season": 2025}, timeout=15)
data = resp.json()
print("status", resp.status_code, "results", data.get("results"), "errors", data.get("errors"))
for inj in data.get("response", [])[:3]:
    print(" ", inj.get("player", {}).get("name"), inj.get("player", {}).get("reason"),
          inj.get("team", {}).get("name"), inj.get("fixture", {}).get("date"))

print()
print("=== Odds: La Liga (league 140), season 2025, one known fixture ===")
resp = requests.get(f"{BASE}/fixtures", headers=H, params={"league": 140, "season": 2025, "last": 1}, timeout=15)
data = resp.json()
fixtures = data.get("response", [])
if fixtures:
    fid = fixtures[0]["fixture"]["id"]
    print("sample fixture id:", fid, fixtures[0]["teams"]["home"]["name"], "vs", fixtures[0]["teams"]["away"]["name"])
    resp2 = requests.get(f"{BASE}/odds", headers=H, params={"fixture": fid}, timeout=15)
    data2 = resp2.json()
    print("odds status", resp2.status_code, "results", data2.get("results"), "errors", data2.get("errors"))
else:
    print("no fixtures found to test odds against")

print()
print("=== Player statistics (proxy for squad-value-like data): sample La Liga player ===")
resp3 = requests.get(f"{BASE}/players", headers=H, params={"league": 140, "season": 2025, "page": 1}, timeout=15)
data3 = resp3.json()
print("status", resp3.status_code, "results", data3.get("results"), "errors", data3.get("errors"))
if data3.get("response"):
    p = data3["response"][0]
    print(" sample player keys:", list(p.get("player", {}).keys()))
    print(" sample statistics keys:", list((p.get("statistics") or [{}])[0].keys()) if p.get("statistics") else None)
