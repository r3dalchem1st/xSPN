"""TEMPORARY diagnostic, deleted after use."""
import json
import os

import requests

AF_KEY = os.environ.get("API_FOOTBALL_KEY", "")
resp = requests.get("https://v3.football.api-sports.io/leagues",
                     headers={"x-apisports-key": AF_KEY}, params={"id": 143}, timeout=15)
data = resp.json()
print("status", resp.status_code)
for entry in data.get("response", []):
    for s in entry.get("seasons", []):
        print(s["year"], "current:", s.get("current"), "coverage:", json.dumps(s.get("coverage")))

print()
print("=== account/subscription info ===")
resp2 = requests.get("https://v3.football.api-sports.io/status",
                      headers={"x-apisports-key": AF_KEY}, timeout=15)
print(json.dumps(resp2.json(), indent=2))
