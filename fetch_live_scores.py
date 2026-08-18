"""
Optional live-result overlay for competitions covered by football-data.org's
free tier (Premier League, La Liga, Bundesliga, UEFA Champions League).

fetch_league.py / fetch_cup.py source fixtures AND results entirely from
openfootball's community-maintained .txt files -- fine for fixtures (known
far in advance), but volunteers can take days to commit a played match's
score, leaving a competition's Results tab empty long after the real match
was played (confirmed live: La Liga's Matchday 1, played 16 Aug 2026, still
unscored in the openfootball source two days later). This patches
football-data.org's much faster official results onto an already-built
openfootball schedule -- openfootball stays the source of truth for
fixtures/training data; this only fills in FINISHED status + goals for a
match openfootball hasn't caught up on yet.

No FD_API_KEY -> no-op (same optional-step convention as fetch_cards.py /
fetch_injuries.py). A competition with no football_data_code configured
(e.g. Copa del Rey, not on the free tier) is also a no-op, enforced by the
caller never invoking this module in that case.
"""
import os

import requests

API_KEY_ENV = "FD_API_KEY"
BASE = "https://api.football-data.org/v4"


def fetch_finished_matches(code, timeout=10):
    """Raw FINISHED matches for a football-data.org competition `code`.
    Empty list on no key, network failure, or non-2xx response -- a live-
    overlay hiccup must never break the openfootball-sourced pipeline it
    layers on top of."""
    api_key = os.environ.get(API_KEY_ENV, "")
    if not api_key:
        return []
    url = f"{BASE}/competitions/{code}/matches"
    try:
        resp = requests.get(url, headers={"X-Auth-Token": api_key},
                            params={"status": "FINISHED"}, timeout=timeout)
    except requests.RequestException as e:
        print(f"    ! live-score fetch failed for {code}: {e}")
        return []
    if resp.status_code != 200:
        print(f"    ! live-score API {resp.status_code} for {code} (may not be available on free tier)")
        return []
    return resp.json().get("matches", [])


def overlay_live_results(config, schedule, raw_matches):
    """Patch FINISHED status + real goals from football-data.org's
    `raw_matches` onto `schedule` (openfootball's own schedule dict, keyed
    "home|away") wherever openfootball hasn't recorded a result yet.

    Team names resolve through the SAME config.team_aliases openfootball
    parsing already uses -- a name football-data.org and openfootball
    disagree on needs an alias entry either way. A name that resolves (via
    alias or passthrough) but still doesn't match any "home|away" key in
    `schedule` is JUST AS real a miss as an outright-rejected name (caught
    live: la_liga.json ships with empty team_aliases, so football-data.org's
    shorter names for Atlético Madrid/Barcelona/Real Madrid/Celta Vigo/Real
    Betis/Real Sociedad all silently passed resolve_team() unchanged, then
    matched nothing in schedule, and were dropped with ZERO log output --
    half of Matchday 1 stayed unscored with no trace of why). Both cases are
    counted and logged here, with the raw names, so add-an-alias fixes have
    ground truth to work from (mirrors fetch_matches.py's TEAM_MAP: built up
    from real observed API responses, never guessed upfront).

    A fixture already FINISHED in `schedule` (openfootball caught up, or a
    second overlay run) is left untouched -- openfootball is the permanent
    record once it has one; this only fills gaps. Mutates and returns
    `schedule`. Returns (schedule, n_overlaid, n_unmatched)."""
    n_overlaid = n_unmatched = 0
    for m in raw_matches:
        home_raw = (m.get("homeTeam") or {}).get("name", "")
        away_raw = (m.get("awayTeam") or {}).get("name", "")
        home, away = config.resolve_team(home_raw), config.resolve_team(away_raw)
        if not home or not away:
            n_unmatched += 1
            print(f"    ! unresolved team name(s): {home_raw!r} / {away_raw!r} — add to team_aliases")
            continue
        ft = ((m.get("score") or {}).get("fullTime")) or {}
        hg, ag = ft.get("home"), ft.get("away")
        if hg is None or ag is None:
            continue
        entry = schedule.get(f"{home}|{away}")
        if entry is None:
            n_unmatched += 1
            print(f"    ! no schedule fixture for {home!r} vs {away!r} "
                  f"(raw: {home_raw!r} / {away_raw!r}) — team_aliases entry needed?")
            continue
        if entry["status"] == "FINISHED":
            continue  # openfootball already has this result
        entry["status"], entry["goals"] = "FINISHED", {home: hg, away: ag}
        n_overlaid += 1
        print(f"    + live result {home} {hg}-{ag} {away}")
    if n_unmatched:
        print(f"    ! {n_unmatched} live result(s) could not be matched to a fixture — see above")
    return schedule, n_overlaid, n_unmatched
