"""
Optional live-result overlay for competitions covered by football-data.org's
free tier (Premier League, La Liga, Bundesliga, UEFA Champions League).

fetch_league.py / fetch_cup.py source fixtures AND results entirely from
openfootball's community-maintained .txt files -- fine in principle, but two
real gaps confirmed live against La Liga's actual 2026-27 Matchday 1:

  1. Volunteers can take days to commit a played match's score, leaving a
     competition's Results tab empty long after the real match was played.
  2. openfootball's static file (frozen well before broadcast schedules were
     finalised) stamps an ENTIRE matchday with one placeholder date --
     confirmed live: it lists all 10 Matchday 1 fixtures as "2026-08-16",
     but football-data.org's real per-match dates show the round actually
     staggered across 2026-08-15 through 2026-08-27 (La Liga stages jornada
     kickoffs across many days for TV scheduling). A visitor looking at the
     Bracket tab before this fix would see 5 not-yet-played games mislabelled
     as already having happened over a week ago.

This module patches football-data.org's faster, more accurate data onto an
already-built openfootball schedule for both gaps: FINISHED status + goals
for a match openfootball hasn't caught up on yet, and a corrected `date` for
a still-unplayed fixture whose real kickoff differs from openfootball's
placeholder. openfootball stays the source of truth for which fixtures
exist and for training data; this only refines what's already there.

No FD_API_KEY -> no-op (same optional-step convention as fetch_cards.py /
fetch_injuries.py). A competition with no football_data_code configured
(e.g. Copa del Rey, not on the free tier) is also a no-op, enforced by the
caller never invoking this module in that case.
"""
import os

import requests

API_KEY_ENV = "FD_API_KEY"
BASE = "https://api.football-data.org/v4"


def fetch_matches(code, timeout=10):
    """Every match (any status) for a football-data.org competition `code`
    -- no status filter, mirroring fetch_matches.py's fetch_schedule(),
    since overlay_live_results() needs to see not-yet-played fixtures too
    (to correct their date) not just FINISHED ones. Empty list on no key,
    network failure, or non-2xx response -- a live-overlay hiccup must
    never break the openfootball-sourced pipeline it layers on top of."""
    api_key = os.environ.get(API_KEY_ENV, "")
    if not api_key:
        return []
    url = f"{BASE}/competitions/{code}/matches"
    try:
        resp = requests.get(url, headers={"X-Auth-Token": api_key}, timeout=timeout)
    except requests.RequestException as e:
        print(f"    ! live-score fetch failed for {code}: {e}")
        return []
    if resp.status_code != 200:
        print(f"    ! live-score API {resp.status_code} for {code} (may not be available on free tier)")
        return []
    return resp.json().get("matches", [])


def overlay_live_results(config, schedule, raw_matches):
    """Patch football-data.org's `raw_matches` onto `schedule` (openfootball's
    own schedule dict, keyed "home|away") wherever it's more complete or more
    accurate than what openfootball has:
      - a FINISHED match openfootball hasn't scored yet -> status + goals
        filled in.
      - a still-unplayed fixture whose football-data.org date differs from
        openfootball's -> date corrected (openfootball's placeholder date
        for an entire matchday can be badly wrong for individual fixtures --
        see module docstring).
    A fixture already FINISHED in `schedule` (openfootball caught up, or a
    prior overlay run) is left completely untouched either way -- openfootball
    is the permanent record once it has a result.

    Team names resolve through the SAME config.team_aliases openfootball
    parsing already uses -- a name football-data.org and openfootball
    disagree on needs an alias entry either way. A name that resolves (via
    alias or passthrough) but still doesn't match any "home|away" key in
    `schedule` is JUST AS real a miss as an outright-rejected name -- both
    are counted and logged with the raw names, so a fix has ground truth to
    work from (mirrors fetch_matches.py's TEAM_MAP: built up from real
    observed API responses, never guessed upfront).

    Mutates and returns `schedule`. Returns
    (schedule, n_overlaid, n_date_corrected, n_unmatched)."""
    n_overlaid = n_date_corrected = n_unmatched = 0
    for m in raw_matches:
        home_raw = (m.get("homeTeam") or {}).get("name", "")
        away_raw = (m.get("awayTeam") or {}).get("name", "")
        home, away = config.resolve_team(home_raw), config.resolve_team(away_raw)
        if not home or not away:
            n_unmatched += 1
            print(f"    ! unresolved team name(s): {home_raw!r} / {away_raw!r} — add to team_aliases")
            continue
        entry = schedule.get(f"{home}|{away}")
        if entry is None:
            n_unmatched += 1
            print(f"    ! no schedule fixture for {home!r} vs {away!r} "
                  f"(raw: {home_raw!r} / {away_raw!r}) — team_aliases entry needed?")
            continue
        if entry["status"] == "FINISHED":
            continue  # openfootball already has this result -- permanent, never touched
        if m.get("status") == "FINISHED":
            ft = ((m.get("score") or {}).get("fullTime")) or {}
            hg, ag = ft.get("home"), ft.get("away")
            if hg is None or ag is None:
                continue
            entry["status"], entry["goals"] = "FINISHED", {home: hg, away: ag}
            n_overlaid += 1
            print(f"    + live result {home} {hg}-{ag} {away}")
        else:
            fd_date = (m.get("utcDate") or "")[:10]
            if fd_date and fd_date != entry["date"]:
                print(f"    ~ date correction {home} vs {away}: {entry['date']} -> {fd_date}")
                entry["date"] = fd_date
                n_date_corrected += 1
    if n_unmatched:
        print(f"    ! {n_unmatched} live result(s) could not be matched to a fixture — see above")
    return schedule, n_overlaid, n_date_corrected, n_unmatched
