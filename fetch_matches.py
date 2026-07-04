"""
Fetches new international match results from football-data.org and appends
them to fetched_matches.json so the model can pick them up.

Free API key: https://www.football-data.org/client/register
Set as GitHub secret FD_API_KEY (see README).
"""
import os, sys, json, requests
from datetime import datetime, date, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model_common import ALL_TEAMS, HOST_NATIONS

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

# openfootball/worldcup.json is a community-maintained cross-check source (also
# used by shadymccoy.github.io/WC26). Its score shape is unambiguous — score.et
# (or score.ft if no extra time) is always the true final field score, and a
# shootout is a separate score.p field — unlike football-data.org's
# PENALTY_SHOOTOUT fullTime, which combines field+shootout goals and has caused
# repeated wrong scores (28/30 Jun fixes, and the 2 Jul Belgium–Senegal incident
# that prompted this: fetched as 1–0, actually 3–2 in extra time). Only 3 team
# names differ from our model spelling; everything else passes through.
OPENFOOTBALL_URL = 'https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json'
OF_TEAM_MAP = {
    'Bosnia & Herzegovina': 'Bosnia',
    'Curaçao': 'Curacao',
    'Czech Republic': 'Czechia',
}

def resolve_of(raw):
    if raw in TEAM_SET: return raw
    return OF_TEAM_MAP.get(raw)

def fetch_openfootball_results():
    """Ground-truth match dates + finished-match results from openfootball, keyed by
    sorted team pair. Used to override football-data.org's score (see module docstring
    history) AND its schedule date: football-data.org only exposes a UTC timestamp, and
    truncating it to a date rolls late local kickoffs (common for 2026 US/CA/MX host
    times, e.g. 19:00 UTC-6 = 01:00 UTC the NEXT day) onto the wrong calendar day —
    this is what made R32/R16 (and some group) matches show a day late. openfootball's
    `date` field is already the local match-day FIFA schedules against (also what
    shadymccoy.github.io/WC26 shows), so it's authoritative for both. Network/schema
    failure -> empty dict (no-op; football-data.org stays authoritative on its own)."""
    try:
        resp = requests.get(OPENFOOTBALL_URL, timeout=10)
        resp.raise_for_status()
        matches = resp.json().get('matches', [])
    except Exception as e:
        print(f"  openfootball fetch failed (cross-check skipped): {e}")
        return {}
    out = {}
    for m in matches:
        home = resolve_of(m.get('team1', '')); away = resolve_of(m.get('team2', ''))
        if not home or not away:
            continue  # unresolved KO placeholder (e.g. "W83"/"L101") or unmapped name
        entry = {'date': m.get('date')}
        score = m.get('score')
        if score:
            if 'et' in score:
                hg, ag = score['et']
            elif 'ft' in score:
                hg, ag = score['ft']
            else:
                hg = ag = None
            if hg is not None:
                entry['goals'] = {home: hg, away: ag}
                pens = score.get('p')
                if pens and pens[0] != pens[1]:
                    entry['pen_winner'] = home if pens[0] > pens[1] else away
                    entry['pen_scores'] = {home: pens[0], away: pens[1]}
        out['|'.join(sorted([home, away]))] = entry
    return out

def _apply_openfootball(match, of_results):
    """Override a fetch_competition() row's score if openfootball disagrees."""
    date, home, away, hg, ag, label, neutral = match
    if label != "World Cup":
        return match
    of = of_results.get('|'.join(sorted([home, away])))
    if not of:
        return match
    of_goals = of.get('goals', {})
    of_hg, of_ag = of_goals.get(home), of_goals.get(away)
    if of_hg is None or of_ag is None or (of_hg, of_ag) == (hg, ag):
        return match
    print(f"    ~ openfootball override {date} {home} {hg}-{ag} {away} -> {of_hg}-{of_ag}")
    return [date, home, away, of_hg, of_ag, label, neutral]

_WC26_GROUP_CUTOFF = "2026-06-28"   # R32 starts here; group stage is before this

def _co_host_home(match):
    """WC 2026 group stage: co-host teams play at their home venues → neutral=False.
    If the API lists the co-host as 'away', swap home/away so they appear as home.
    Applied to fresh results before reconcile() so subsequent runs stay consistent."""
    date, home, away, hg, ag, label, neutral = match
    if label != "World Cup" or date >= _WC26_GROUP_CUTOFF:
        return match
    if home in HOST_NATIONS:
        return [date, home, away, hg, ag, label, False]
    if away in HOST_NATIONS:
        return [date, away, home, ag, hg, label, False]
    return match


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

def reconcile(existing, fresh):
    """Merge freshly-fetched results into the accumulated cache, keyed by date +
    UNORDERED pair (so a home/away flip doesn't duplicate a fixture).

    A fresh result OVERWRITES a previously-cached one for the same key: the API can
    amend a finished score (VAR / official correction, or a transient first capture),
    and keeping the stale value would diverge from wc_schedule.json (regenerated
    fresh each run) and mis-score the Results tab. New fixtures are appended; older
    cached matches the API no longer returns (aged out of the 90-day window) are
    preserved in place. Returns (all_matches, n_added, n_corrected)."""
    idx, out = {}, []
    for m in existing:
        idx[(m[0], tuple(sorted((m[1], m[2]))))] = len(out)
        out.append(m)
    added = corrected = 0
    for m in fresh:
        k = (m[0], tuple(sorted((m[1], m[2]))))
        if k in idx:
            prev = out[idx[k]]
            if prev[3:5] != m[3:5]:        # score changed -> trust the latest API value
                print(f"    ~ corrected {m[0]} {m[1]} {prev[3]}-{prev[4]} -> {m[3]}-{m[4]} {m[2]}")
                out[idx[k]] = m
                corrected += 1
        else:
            idx[k] = len(out)
            out.append(m)
            print(f"    + {m[0]} {m[1]} {m[3]}-{m[4]} {m[2]}")
            added += 1
    return out, added, corrected

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
        sc = m.get('score') or {}
        ft = sc.get('fullTime') or {}
        et = sc.get('extraTime') or {}
        duration_m = sc.get('duration')
        ft_h, ft_a = ft.get('home'), ft.get('away')
        et_h, et_a = et.get('home'), et.get('away')
        # For penalty shootouts the API returns extraTime as additional ET goals only
        # (not cumulative), so final score = fullTime + extraTime.
        # For regular/ET matches the existing cumulative-ET logic applies.
        if duration_m == 'PENALTY_SHOOTOUT':
            if ft_h is None or ft_a is None:
                print(f"    ! PENALTY_SHOOTOUT but fullTime is null on {match_date} {home}–{away} — skipped (API transient?)")
                continue
            pen_m = sc.get('penalties') or {}
            hg = max(0, ft_h - (pen_m.get('home') or 0))
            ag = max(0, ft_a - (pen_m.get('away') or 0))
        elif et_h is not None and et_a is not None:
            hg, ag = et_h, et_a
        else:
            if et_h is not None or et_a is not None:
                print(f"    ~ ET partial (home={et_h}/away={et_a}) on {match_date} {home}–{away} — using FT")
            hg, ag = ft_h, ft_a
        if hg is None or ag is None:
            continue
        is_neutral = neutral if neutral is not None else False
        matches.append([match_date, home, away, int(hg), int(ag), label, is_neutral])
    return matches

def fetch_schedule(of_results=None):
    """Full WC fixture list (any status) -> {sorted_pair: {date,status,hg,ag}}.
    Gives real game dates (and results once played) for ordering / display in the
    All-104-Matches table. Group fixtures resolve immediately; KO fills in as teams
    are decided. `of_results` (from fetch_openfootball_results()) overrides the
    score/pens whenever it disagrees with football-data.org."""
    of_results = of_results or {}
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
        sc = m.get('score') or {}
        ft = sc.get('fullTime') or {}
        et = sc.get('extraTime') or {}
        pen = sc.get('penalties') or {}
        duration = sc.get('duration')
        is_finished = m.get('status') == 'FINISHED'
        if is_finished:
            ft_h2, ft_a2 = ft.get('home'), ft.get('away')
            et_h, et_a = et.get('home'), et.get('away')
            if duration == 'PENALTY_SHOOTOUT' and ft_h2 is not None and ft_a2 is not None:
                # API stores fullTime = field_goals + pen_goals; subtract pens to get field score
                final_h = max(0, ft_h2 - (pen.get('home') or 0))
                final_a = max(0, ft_a2 - (pen.get('away') or 0))
            elif et_h is not None and et_a is not None:
                final_h, final_a = et_h, et_a
            else:
                if et_h is not None or et_a is not None:
                    print(f"    ~ ET partial (home={et_h}/away={et_a}) on {m.get('utcDate','')[:10]} {home}–{away} — using FT")
                final_h, final_a = ft_h2, ft_a2
        else:
            final_h, final_a = None, None
        of = of_results.get('|'.join(sorted([home, away])))
        # football-data.org's utcDate rolls late local kickoffs (common for 2026 host
        # cities, e.g. 19:00 UTC-6 = 01:00 UTC next day) onto the wrong calendar day —
        # openfootball's date is the local match-day, so prefer it whenever known
        # (independent of whether the match has been played yet).
        real_date = of.get('date') if of else None
        entry = {
            "date": real_date or m.get('utcDate', '')[:10], "status": m.get('status'),
            "utc": m.get('utcDate', ''),  # full timestamp, for same-day kickoff-time ordering
            "goals": {home: final_h, away: final_a},  # by team name (orientation-safe)
        }
        if is_finished and duration == 'PENALTY_SHOOTOUT' and pen.get('home') is not None:
            pen_h, pen_a = pen.get('home', 0), pen.get('away', 0)
            if pen_h != pen_a:
                entry['pen_winner'] = home if pen_h > pen_a else away
                entry['pen_scores'] = {home: pen_h, away: pen_a}
            else:
                print(f"    ~ pen equal ({pen_h}–{pen_a}) on {entry['date']} {home}–{away} — pen_winner omitted")
        if is_finished and of:
            of_goals = of.get('goals', {})
            of_h, of_a = of_goals.get(home), of_goals.get(away)
            if of_h is not None and of_a is not None and (of_h, of_a) != (final_h, final_a):
                print(f"    ~ openfootball override (schedule) {home} {final_h}-{final_a} -> {of_h}-{of_a} {away}")
                entry['goals'] = {home: of_h, away: of_a}
            if 'pen_winner' in of:
                entry['pen_winner'] = of['pen_winner']
                entry['pen_scores'] = of['pen_scores']
            elif 'pen_winner' in entry:
                # openfootball has this match resolved with no shootout —
                # trust it over a spurious PENALTY_SHOOTOUT flag from the other API
                entry.pop('pen_winner'); entry.pop('pen_scores', None)
        sched['|'.join(sorted([home, away]))] = entry
    print(f"  schedule: {len(sched)} fixtures with both teams resolved")
    if unmapped:
        print(f"  schedule unmapped team names (add to TEAM_MAP): {sorted(unmapped)}")
    return sched

def main():
    print("Fetching new match data...")
    existing = load_existing()

    # Cross-check source (see fetch_openfootball_results() docstring); reused below
    # for both the training cache and the schedule/results the UI reads.
    of_results = fetch_openfootball_results()
    print(f"  openfootball cross-check: {len(of_results)} finished results loaded")

    # World Cup 2026 group stage
    print("  Fetching World Cup 2026 matches...")
    wc = [_apply_openfootball(_co_host_home(m), of_results) for m in fetch_competition('WC', 'World Cup', True)]

    # (Nations League fetch removed: not on the free tier — it only 403'd every
    # run — and irrelevant during the World Cup, which the WC fetch above covers.)

    # Reconcile fresh results into the cache: new fixtures appended, corrected
    # scores overwritten (a stale first-capture must not stick — see reconcile()).
    all_matches, n_added, n_corrected = reconcile(existing, wc)
    with open(CACHE_FILE, 'w') as f:
        json.dump(all_matches, f, indent=2)

    # Schedule (dates + results for the All-104-Matches table). Keep the previous
    # file if the API hiccups, so we never blank out the dates.
    print("  Fetching full WC schedule...")
    sched = fetch_schedule(of_results)
    sched_file = os.path.join(SCRIPT_DIR, 'wc_schedule.json')
    if sched:
        with open(sched_file, 'w') as f:
            json.dump(sched, f, indent=2)
    else:
        if n_added > 0:
            print(f"  WARNING: schedule fetch failed but {n_added} new match(es) were added — "
                  f"wc_schedule.json is STALE and may diverge from fetched_matches.json!")
        if not os.path.exists(sched_file):
            with open(sched_file, 'w') as f:
                json.dump({}, f)

    print(f"Done. {n_added} new, {n_corrected} corrected ({len(all_matches)} total in cache).")

if __name__ == '__main__':
    main()
