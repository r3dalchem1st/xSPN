"""
Fetches real historical match odds from football-data.co.uk -- free, no
API key, no registration (confirmed live: plain CSV over HTTP). Unlike
football-data.org/API-Football's odds endpoints (paid-tier only on both),
this genuinely free source includes real historical odds back to 2000/01
for the big-5 European leagues, which is what makes backtest_odds.py's
comparison possible at all without paying for anything.

CSV format confirmed against real 2025-26 season files for all 3 leagues
this project covers: one row per played match, "DD/MM/YYYY" dates, team
names in the site's OWN short-form convention (a THIRD naming style,
different from both openfootball's long-form and its newer short-form --
e.g. "Nott'm Forest", "Man City", "Ath Bilbao") -- resolved through each
competition's existing team_aliases, extended with this source's own
short forms (see competitions/<slug>.json).

Odds columns used: AvgH/AvgD/AvgA (the market average across every
bookmaker the site tracks, not one single bookmaker's line) -- a broader,
more representative "wisdom of the crowd" signal than picking one
bookmaker (e.g. B365H/D/A). A row missing any of the three (rare, but
happens for a postponed-and-unusual fixture) is skipped, not fabricated.

Usage: python fetch_odds_history.py <football_data_co_uk_code> <season, e.g. 2526>
"""
import csv
import io
import sys

import requests

BASE = "https://www.football-data.co.uk/mmz4281"


def fetch_season_csv(code, season):
    """Raw CSV text for one football-data.co.uk league code (e.g. "E0" for
    the Premier League) and season (e.g. "2526" for 2025-26). Raises
    requests.RequestException on network failure or non-2xx status --
    no silent no-op here, unlike the live-score overlay's optional-feature
    convention, since this module has no "skip if unavailable" caller yet
    (backtest_odds.py is a manual diagnostic, not a daily pipeline step)."""
    url = f"{BASE}/{season}/{code}.csv"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.text


def _to_iso_date(dd_mm_yyyy):
    """"15/08/2025" -> "2025-08-15"."""
    d, m, y = dd_mm_yyyy.split("/")
    return f"{y}-{m}-{d}"


def parse_odds_rows(text, config):
    """Parse football-data.co.uk CSV `text` into a list of {"date", "home",
    "away", "hg", "ag", "odds": (home, draw, away)} dicts -- one per played
    match with a resolvable team pair AND a complete AvgH/AvgD/AvgA triple.
    A row failing either check is skipped (not fabricated), same
    discipline every other fetch script in this project already follows.
    Returns (rows, n_skipped)."""
    reader = csv.DictReader(io.StringIO(text))
    rows, n_skipped = [], 0
    for r in reader:
        home = config.resolve_team(r.get("HomeTeam", ""))
        away = config.resolve_team(r.get("AwayTeam", ""))
        if not home or not away:
            n_skipped += 1
            continue
        try:
            ph, pd_, pa = float(r["AvgH"]), float(r["AvgD"]), float(r["AvgA"])
            hg, ag = int(r["FTHG"]), int(r["FTAG"])
        except (KeyError, ValueError):
            n_skipped += 1
            continue
        rows.append({
            "date": _to_iso_date(r["Date"]), "home": home, "away": away,
            "hg": hg, "ag": ag, "odds": (ph, pd_, pa),
        })
    return rows, n_skipped


def main():
    if len(sys.argv) != 3:
        print("usage: python fetch_odds_history.py <football_data_co_uk_code> <season, e.g. 2526>")
        raise SystemExit(1)
    code, season = sys.argv[1], sys.argv[2]
    text = fetch_season_csv(code, season)
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    print(f"{code} {season}: {len(rows)} rows fetched, "
          f"{sum(1 for r in rows if r.get('AvgH'))} with AvgH/AvgD/AvgA odds present.")


if __name__ == "__main__":
    main()
