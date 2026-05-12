"""
Fetches new international match results from football-data.org and appends
them to fetched_matches.json so the model can pick them up.

Free API key: https://www.football-data.org/client/register
Set as GitHub secret FD_API_KEY (see README).
"""
import os, json, requests
from datetime import datetime, date, timedelta

API_KEY = os.environ.get('FD_API_KEY', '')
if not API_KEY:
    print("No FD_API_KEY found — skipping fetch.")
    raise SystemExit(0)

BASE    = 'https://api.football-data.org/v4'
HEADERS = {'X-Auth-Token': API_KEY}

# Map football-data.org names → our model names
TEAM_MAP = {
    'Spain': 'Spain', 'France': 'France', 'Germany': 'Germany',
    'Argentina': 'Argentina', 'Brazil': 'Brazil', 'England': 'England',
    'Portugal': 'Portugal', 'Netherlands': 'Netherlands', 'Belgium': 'Belgium',
    'Italy': 'Italy', 'Croatia': 'Croatia', 'Uruguay': 'Uruguay',
    'Denmark': 'Denmark', 'Switzerland': 'Switzerland', 'Mexico': 'Mexico',
    'Colombia': 'Colombia', 'Norway': 'Norway', 'Austria': 'Austria',
    'Turkey': 'Turkey', 'Japan': 'Japan', 'South Korea': 'South Korea',
    'Morocco': 'Morocco', 'Senegal': 'Senegal', 'Iran': 'Iran',
    'Ecuador': 'Ecuador', 'USA': 'USA', 'Canada': 'Canada',
    'Australia': 'Australia', 'Poland': 'Poland', 'Sweden': 'Sweden',
    'Serbia': 'Serbia', 'Ukraine': 'Ukraine', 'Czech Republic': 'Czechia',
    'Bosnia and Herzegovina': 'Bosnia', 'Scotland': 'Scotland',
    'Paraguay': 'Paraguay', 'Chile': 'Chile', 'Peru': 'Peru',
    'Ghana': 'Ghana', 'Tunisia': 'Tunisia', 'Egypt': 'Egypt',
    'Saudi Arabia': 'Saudi Arabia', 'Qatar': 'Qatar',
    'Algeria': 'Algeria', 'DR Congo': 'DR Congo', 'Ivory Coast': 'Ivory Coast',
    "Côte d'Ivoire": 'Ivory Coast', 'Cape Verde': 'Cape Verde',
    'Costa Rica': 'Costa Rica', 'Panama': 'Panama', 'Jamaica': 'Jamaica',
}

# Competitions to watch — football-data.org codes
COMPETITIONS = [
    ('WC',         'World Cup',        True),   # WC 2026 group stage — neutral venue
    ('CL',         None,               None),   # not relevant, skip
    ('UEFA_NL',    'Nations League',   False),  # Nations League — home/away
]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(SCRIPT_DIR, 'fetched_matches.json')

def load_existing():
    if os.path.exists(CACHE_FILE):
        return json.load(open(CACHE_FILE))
    return []

def existing_keys(existing):
    return {(m[0], m[1], m[2]) for m in existing}  # (date, home, away)

def fetch_competition(code, label, neutral):
    """Fetch finished matches for a competition in the last 90 days."""
    today = date.today()
    date_from = (today - timedelta(days=90)).isoformat()
    date_to   = today.isoformat()
    url = f'{BASE}/competitions/{code}/matches'
    try:
        resp = requests.get(url, headers=HEADERS,
                            params={'status': 'FINISHED',
                                    'dateFrom': date_from,
                                    'dateTo': date_to}, timeout=10)
    except Exception as e:
        print(f"  Request failed for {code}: {e}")
        return []
    if resp.status_code == 404:
        print(f"  {code} not found in API (may not be available on free tier)")
        return []
    if resp.status_code != 200:
        print(f"  API error {resp.status_code} for {code}: {resp.text[:120]}")
        return []
    matches = []
    for m in resp.json().get('matches', []):
        if m.get('status') != 'FINISHED':
            continue
        home_raw = m.get('homeTeam', {}).get('name', '')
        away_raw = m.get('awayTeam', {}).get('name', '')
        home = TEAM_MAP.get(home_raw)
        away = TEAM_MAP.get(away_raw)
        if not home or not away:
            continue
        match_date = m.get('utcDate', '')[:10]
        score = m.get('score', {}).get('fullTime', {})
        hg = score.get('home')
        ag = score.get('away')
        if hg is None or ag is None:
            continue
        is_neutral = neutral if neutral is not None else False
        matches.append([match_date, home, away, int(hg), int(ag), label, is_neutral])
    return matches

def main():
    print("Fetching new match data...")
    existing   = load_existing()
    known_keys = existing_keys(existing)
    new_matches = []

    # World Cup 2026 group stage
    print("  Fetching World Cup 2026 matches...")
    wc = fetch_competition('WC', 'World Cup', True)
    for m in wc:
        k = (m[0], m[1], m[2])
        if k not in known_keys:
            new_matches.append(m)
            known_keys.add(k)
            print(f"    + {m[0]} {m[1]} {m[3]}-{m[4]} {m[2]}")

    # Nations League (if available on free tier)
    print("  Fetching UEFA Nations League...")
    nl = fetch_competition('UNL', 'Nations League', False)
    for m in nl:
        k = (m[0], m[1], m[2])
        if k not in known_keys:
            new_matches.append(m)
            known_keys.add(k)
            print(f"    + {m[0]} {m[1]} {m[3]}-{m[4]} {m[2]}")

    all_matches = existing + new_matches
    with open(CACHE_FILE, 'w') as f:
        json.dump(all_matches, f, indent=2)

    print(f"Done. {len(new_matches)} new matches added ({len(all_matches)} total in cache).")

if __name__ == '__main__':
    main()
