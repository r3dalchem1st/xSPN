"""
Daily booking (yellow/red card) fetch (optional). Populates cards.json from
API-Football's per-fixture statistics for the World Cup, so the Groups tab can
show real YC/RC totals per team.

football-data.org (our results source) does NOT expose cards on the free tier, but
API-Football — the same service fetch_injuries.py already uses — does, under
league=1, season=2026. This script reuses the same API_FOOTBALL_KEY secret.

API_FOOTBALL_KEY not set -> NO-OP: cards.json is left exactly as-is (a transient API
problem never wipes good data).

Quota-friendly: ONE request lists the fixtures, then ONE request per newly-finished
fixture that isn't already cached (capped at CARDS_MAX_NEW per run). Played fixtures
are cached forever, so steady state is only the handful that finished since last run
— comfortably under API-Football's free 100 req/day cap.

Display-only: cards do NOT feed the model. Run any time before build_html.py.
"""
import json, os, unicodedata
import requests
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model_common import ALL_TEAMS

DIR        = os.path.dirname(os.path.abspath(__file__))
CARDS_FILE = os.path.join(DIR, 'cards.json')
API     = 'https://v3.football.api-sports.io'
LEAGUE  = os.environ.get('CARDS_LEAGUE', '1')     # API-Football: 1 = World Cup
SEASON  = os.environ.get('CARDS_SEASON', '2026')
MAX_NEW = int(os.environ.get('CARDS_MAX_NEW', '50'))
FINISHED = {'FT', 'AET', 'PEN'}                    # API-Football short status codes

# API-Football national-team names that differ from ours -> our team keys. Names
# that already match one of the 48 pass through (built from ALL_TEAMS below).
TEAM_ALIASES = {
    "united states": "USA", "usa": "USA",
    "south korea": "South Korea", "korea republic": "South Korea",
    "ivory coast": "Ivory Coast", "cote d'ivoire": "Ivory Coast",
    "czech republic": "Czechia", "czechia": "Czechia",
    "bosnia and herzegovina": "Bosnia", "bosnia-herzegovina": "Bosnia",
    "cape verde islands": "Cape Verde", "cabo verde": "Cape Verde",
    "turkiye": "Turkey", "dr congo": "DR Congo", "congo dr": "DR Congo",
    "curacao": "Curacao",
}

def norm(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower()
    return ' '.join(s.split())

team_key = {norm(t): t for t in ALL_TEAMS}
team_key.update({norm(k): v for k, v in TEAM_ALIASES.items()})

def resolve(raw):
    return team_key.get(norm(raw))

def load_cards():
    if os.path.exists(CARDS_FILE):
        with open(CARDS_FILE) as f:
            return json.load(f)
    return {}

# Offline test hook: {"fixtures":[...api rows...], "stats":{fixture_id:[...api rows...]}}.
TEST_FILE = os.environ.get('CARDS_TEST_FILE')
KEY = os.environ.get('API_FOOTBALL_KEY')
HEADERS = {'x-apisports-key': KEY or ''}

def api_get(path, params):
    r = requests.get(f"{API}{path}", headers=HEADERS, params=params, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return r.json().get('response', [])

def fixture_cards(stat_rows):
    """API-Football /fixtures/statistics response -> {our_team: {'YC':n,'RC':n}}."""
    out = {}
    for row in stat_rows:
        team = resolve((row.get('team') or {}).get('name', ''))
        if not team:
            continue
        yc = rc = 0
        for s in row.get('statistics', []):
            t = (s.get('type') or '').lower()
            v = s.get('value') or 0
            if t == 'yellow cards': yc = int(v)
            elif t == 'red cards':  rc = int(v)
        out[team] = {'YC': yc, 'RC': rc}
    return out

def main():
    if TEST_FILE:
        data = json.load(open(TEST_FILE, encoding='utf-8'))
        fixtures, stats_for = data.get('fixtures', []), (lambda fid: data.get('stats', {}).get(str(fid), []))
    elif not KEY:
        print("API_FOOTBALL_KEY not set — skipping card fetch (cards.json unchanged).")
        return
    else:
        try:
            fixtures = api_get('/fixtures', {'league': LEAGUE, 'season': SEASON})
        except (requests.RequestException, RuntimeError) as e:
            print(f"Card fetch failed listing fixtures ({e}) — cards.json unchanged."); return
        stats_for = lambda fid: api_get('/fixtures/statistics', {'fixture': fid})

    cards = load_cards()
    added = skipped = 0
    for fx in fixtures:
        if (fx.get('fixture') or {}).get('status', {}).get('short') not in FINISHED:
            continue
        teams = fx.get('teams') or {}
        home = resolve((teams.get('home') or {}).get('name', ''))
        away = resolve((teams.get('away') or {}).get('name', ''))
        if not home or not away:
            continue
        pair = '|'.join(sorted([home, away]))
        if pair in cards:
            continue                                  # already cached — don't re-spend quota
        if added >= MAX_NEW:
            skipped += 1; continue
        fid = (fx.get('fixture') or {}).get('id')
        try:
            fc = fixture_cards(stats_for(fid))
        except (requests.RequestException, RuntimeError) as e:
            print(f"  stats fetch failed for fixture {fid} ({e}) — skipped this run"); continue
        cards[pair] = {
            'YC': {home: (fc.get(home) or {}).get('YC', 0), away: (fc.get(away) or {}).get('YC', 0)},
            'RC': {home: (fc.get(home) or {}).get('RC', 0), away: (fc.get(away) or {}).get('RC', 0)},
        }
        added += 1
        print(f"  + cards {home} {cards[pair]['YC'][home]}🟨/{cards[pair]['RC'][home]}🟥 "
              f"vs {away} {cards[pair]['YC'][away]}🟨/{cards[pair]['RC'][away]}🟥")

    with open(CARDS_FILE, 'w', encoding='utf-8') as f:
        json.dump(cards, f, indent=2, ensure_ascii=False)
    print(f"cards.json written: {len(cards)} fixtures cached ({added} new this run"
          + (f", {skipped} deferred to next run — raise CARDS_MAX_NEW" if skipped else "") + ").")

if __name__ == '__main__':
    main()
