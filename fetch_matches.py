"""
Fetches new international match results from football-data.org and appends
them to fetched_matches.json so the model can pick them up.

Free API key: https://www.football-data.org/client/register
Set as GitHub secret FD_API_KEY (see README).
"""
import os, sys, json, requests
from datetime import datetime, date, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model_common import ALL_TEAMS

API_KEY = os.environ.get('FD_API_KEY', '')
if not API_KEY:
    print("No FD_API_KEY found — skipping fetch.")
    raise SystemExit(0)

BASE    = 'https://api.football-data.org/v4'
HEADERS = {'X-Auth-Token': API_KEY}

# Only football-data.org names that DIFFER from our model names need an entry
# here — any name that already matches one of the 48 WC teams passes through
# (see resolve()). This covers the spelling variants the API is known to use.
# (Previously this map omitted South Africa, Haiti, Curacao, Uzbekistan, Iraq,
# Jordan, New Zealand — so e.g. the Mexico–South Africa opener was silently
# dropped and never scored.)
TEAM_MAP = {
    'Czech Republic': 'Czechia',
    'Bosnia and Herzegovina': 'Bosnia', 'Bosnia-Herzegovina': 'Bosnia',
    "Côte d'Ivoire": 'Ivory Coast', "Cote d'Ivoire": 'Ivory Coast',
    'Cabo Verde': 'Cape Verde', 'Cape Verde Islands': 'Cape Verde',
    'Cabo Verde Islands': 'Cape Verde', 'Republic of Cabo Verde': 'Cape Verde',
    'Korea Republic': 'South Korea', 'Republic of Korea': 'South Korea',
    'Türkiye': 'Turkey', 'Turkiye': 'Turkey',
    'IR Iran': 'Iran', 'Iran (Islamic Republic of)': 'Iran',
    'United States': 'USA', 'United States of America': 'USA',
    'Curaçao': 'Curacao',
    'Congo DR': 'DR Congo', 'Democratic Republic of the Congo': 'DR Congo',
    'Republic of Ireland': 'Ireland',
}
TEAM_SET = set(ALL_TEAMS)

def resolve(raw):
    """API team name -> our model name, or None (caller logs the miss)."""
    if raw in TEAM_SET: return raw            # already our spelling (most teams)
    return TEAM_MAP.get(raw)                   # known variant, else None

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
    raw = resp.json().get('matches', [])
    finished = [m for m in raw if m.get('status') == 'FINISHED']
    print(f"  {code}: {len(raw)} matches returned, {len(finished)} FINISHED")
    matches = []
    for m in finished:
        home_raw = m.get('homeTeam', {}).get('name', '')
        away_raw = m.get('awayTeam', {}).get('name', '')
        home = resolve(home_raw); away = resolve(away_raw)
        if not home or not away:
            print(f"    ! unmapped team name(s): {home_raw!r} / {away_raw!r} — skipped")
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

def fetch_schedule():
    """Full WC fixture list (any status) -> {sorted_pair: {date,status,hg,ag}}.
    Gives real game dates (and results once played) for ordering / display in the
    All-104-Matches table. Group fixtures resolve immediately; KO fills in as teams
    are decided."""
    url = f'{BASE}/competitions/WC/matches'
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
    except Exception as e:
        print(f"  schedule request failed: {e}"); return {}
    if resp.status_code != 200:
        print(f"  schedule API {resp.status_code} (kept previous schedule)"); return {}
    sched = {}; unmapped = set()
    for m in resp.json().get('matches', []):
        hr = m.get('homeTeam', {}).get('name'); ar = m.get('awayTeam', {}).get('name')
        home = resolve(hr or ''); away = resolve(ar or '')
        if not home or not away:
            if hr and not home: unmapped.add(hr)
            if ar and not away: unmapped.add(ar)
            continue
        ft = m.get('score', {}).get('fullTime', {})
        sched['|'.join(sorted([home, away]))] = {
            "date": m.get('utcDate', '')[:10], "status": m.get('status'),
            "goals": {home: ft.get('home'), away: ft.get('away')},  # by team name (orientation-safe)
        }
    print(f"  schedule: {len(sched)} fixtures with both teams resolved")
    if unmapped:
        print(f"  schedule unmapped team names (add to TEAM_MAP): {sorted(unmapped)}")
    return sched

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

    # Schedule (dates + results for the All-104-Matches table). Keep the previous
    # file if the API hiccups, so we never blank out the dates.
    print("  Fetching full WC schedule...")
    sched = fetch_schedule()
    sched_file = os.path.join(SCRIPT_DIR, 'wc_schedule.json')
    if sched:
        with open(sched_file, 'w') as f:
            json.dump(sched, f, indent=2)
    elif not os.path.exists(sched_file):
        with open(sched_file, 'w') as f:
            json.dump({}, f)

    print(f"Done. {len(new_matches)} new matches added ({len(all_matches)} total in cache).")

if __name__ == '__main__':
    main()
