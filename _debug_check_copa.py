"""TEMPORARY diagnostic, deleted after use."""
import os

import requests

AF_KEY = os.environ.get("API_FOOTBALL_KEY", "")
H = {"x-apisports-key": AF_KEY}

for label, params in [
    ("no season param", {"league": 143}),
    ("season 2024", {"league": 143, "season": 2024}),
    ("season 2023", {"league": 143, "season": 2023}),
]:
    resp = requests.get("https://v3.football.api-sports.io/fixtures",
                         headers=H, params=params, timeout=15)
    data = resp.json()
    print(label, "-> status", resp.status_code, "results", data.get("results"),
          "errors", data.get("errors"))
