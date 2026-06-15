"""
Daily injury fetch (optional). Populates injuries.json from API-Football, valued
via a curated player -> EUR-value table (player_values.json).

The injury API gives player NAMES; their market values come from our table. Only
injured players that appear in player_values.json are written (so a benchwarmer's
knock doesn't move the model). Unmatched injured players are logged so you know
who to add to the value table.

API_FOOTBALL_KEY not set -> NO-OP: injuries.json is left exactly as-is (a manual or
empty file keeps working, and a transient API problem never wipes good data).

Quota-friendly: ONE request/day — the whole World Cup league's injuries in a single
call (league=1, season=2026, both overridable via INJ_LEAGUE / INJ_SEASON).

Run BEFORE fit_improved.py so the day's injuries flow into the squad values.
"""
import json, os, unicodedata
import requests

DIR = os.path.dirname(os.path.abspath(__file__))
VALUES_FILE = os.path.join(DIR, 'player_values.json')
INJ_FILE    = os.path.join(DIR, 'injuries.json')
API     = 'https://v3.football.api-sports.io'
LEAGUE  = os.environ.get('INJ_LEAGUE', '1')      # API-Football: 1 = World Cup
SEASON  = os.environ.get('INJ_SEASON', '2026')

# API-Football national-team names that differ from ours -> our SQUAD/value keys.
TEAM_ALIASES = {
    "united states": "USA", "usa": "USA", "south korea": "South Korea",
    "korea republic": "South Korea", "ivory coast": "Ivory Coast",
    "cote d'ivoire": "Ivory Coast", "czech republic": "Czechia",
    "czechia": "Czechia", "cape verde islands": "Cape Verde", "turkiye": "Turkey",
    "dr congo": "DR Congo", "congo dr": "DR Congo",
}

def norm(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower()
    return ' '.join(s.split())

with open(VALUES_FILE, encoding='utf-8') as f:
    VALUES = json.load(f)                         # {team: {player: value_m}}

# team-name -> our key, and per-team normalised player lookup
team_key = {norm(t): t for t in VALUES}
team_key.update({norm(k): v for k, v in TEAM_ALIASES.items()})
pl_lookup = {t: {norm(p): (p, v) for p, v in players.items()} for t, players in VALUES.items()}

# Offline test hook: read API 'response' rows from a file instead of the network.
TEST_FILE = os.environ.get('INJ_TEST_FILE')
KEY = os.environ.get('API_FOOTBALL_KEY')
if TEST_FILE:
    with open(TEST_FILE, encoding='utf-8') as f:
        rows = json.load(f)
elif not KEY:
    print("API_FOOTBALL_KEY not set — skipping injury fetch (injuries.json unchanged).")
    raise SystemExit(0)
else:
    try:
        r = requests.get(f"{API}/injuries", headers={'x-apisports-key': KEY},
                         params={'league': LEAGUE, 'season': SEASON}, timeout=20)
    except requests.RequestException as e:
        print(f"Injury fetch failed ({e}) — injuries.json unchanged."); raise SystemExit(0)
    if r.status_code != 200:
        print(f"Injury API HTTP {r.status_code} — injuries.json unchanged."); raise SystemExit(0)
    rows = r.json().get('response', [])
injuries, unmatched, seen = {}, [], set()
for row in rows:
    tname = (row.get('team') or {}).get('name', '')
    pname = (row.get('player') or {}).get('name', '')
    team  = team_key.get(norm(tname))
    if not team:
        continue
    hit = pl_lookup[team].get(norm(pname))
    if not hit:
        unmatched.append(f"{team}: {pname}"); continue
    if (team, hit[0]) in seen:
        continue
    seen.add((team, hit[0]))
    injuries.setdefault(team, []).append({"player": hit[0], "value_m": hit[1]})

with open(INJ_FILE, 'w', encoding='utf-8') as f:
    json.dump(injuries, f, indent=2, ensure_ascii=False)

n = sum(len(v) for v in injuries.values())
print(f"injuries.json written: {n} valued injuries across {len(injuries)} teams "
      f"(from {len(rows)} API rows).")
if unmatched:
    uniq = sorted(set(unmatched))
    print(f"  {len(uniq)} injured players not in player_values.json (add if relevant): {uniq[:25]}")
