"""
Per-match xG from Understat, for the xG family in experiments.py.

Understat serves each league-season as one JSON document (the endpoint its own
league page calls) holding every match's goals and xG, back to 2014-15. It is
unofficial and undocumented, so this is research tooling: it feeds the
experiment harness through a local cache (backtest_cache/, gitignored) and is
NOT wired into the live pipeline. If the xG family passes the pre-registered
rule, fetching it in CI is a separate decision (rate limits, endpoint stability).
2013-14 has no Understat data, so those rows keep xG=None and the fit falls
back to their real goals.

Joining to the football-data.co.uk rows: the sources write clubs differently
("Manchester United" / "Man United"). Rather than a hand-kept alias table, the
name mapping is learned from matches that are unambiguous on (date, score) in
both sources, then every match is joined on its (home, away) pair, which is
unique within a double round-robin season. A club that won't map, or a season
that doesn't join one-to-one, raises: a silent partial join would quietly turn
some training rows back into plain goals.
"""
import gzip
import json
import os
import urllib.request
from collections import Counter, defaultdict

from multiseason_data import DEFAULT_CACHE, SEASONS

UNDERSTAT_LEAGUES = {"premier_league": "EPL", "la_liga": "La_liga", "bundesliga": "Bundesliga"}
FIRST_SEASON = "1415"        # Understat's first season
MAX_SCORE_MISMATCH = 0.02    # share of a season's matches whose score may differ between sources
NAME_VOTE_SHARE = 0.9        # a club's mapping must win this share of its votes


def season_year(season):
    """'1415' -> 2014: the year Understat's URL uses for a season."""
    return 2000 + int(season[:2])


def fetch_understat_season(league_code, year):
    req = urllib.request.Request(
        f"https://understat.com/getLeagueData/{league_code}/{year}",
        headers={"X-Requested-With": "XMLHttpRequest", "User-Agent": "Mozilla/5.0 (xSPN research)",
                 "Accept-Encoding": "gzip", "Referer": f"https://understat.com/league/{league_code}/{year}"})
    raw = urllib.request.urlopen(req, timeout=40).read()
    try:
        raw = gzip.decompress(raw)
    except OSError:
        pass                  # served uncompressed
    return json.loads(raw)["dates"]


def load_understat_season(league_code, season, cache_dir=DEFAULT_CACHE, fetch=fetch_understat_season):
    path = os.path.join(cache_dir, f"understat_{league_code}_{season}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    matches = fetch(league_code, season_year(season))
    os.makedirs(cache_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(matches, f)
    return matches


def parse_understat(matches):
    """Played matches as [{"date","home","away","hg","ag","hxg","axg"}]."""
    return [{"date": m["datetime"][:10], "home": m["h"]["title"], "away": m["a"]["title"],
             "hg": int(m["goals"]["h"]), "ag": int(m["goals"]["a"]),
             "hxg": float(m["xG"]["h"]), "axg": float(m["xG"]["a"])}
            for m in matches if m.get("isResult")]


def learn_name_map(fd_by_season, us_by_season):
    """{understat_name: football-data_name}, from matches unique on (date, score) in both sources."""
    votes = defaultdict(Counter)
    for season, us_rows in us_by_season.items():
        fd_idx, us_idx = defaultdict(list), defaultdict(list)
        for r in fd_by_season[season]:
            fd_idx[(r["date"], r["hg"], r["ag"])].append(r)
        for r in us_rows:
            us_idx[(r["date"], r["hg"], r["ag"])].append(r)
        for key, us in us_idx.items():
            if len(us) == 1 and len(fd_idx.get(key, [])) == 1:
                fd = fd_idx[key][0]
                votes[us[0]["home"]][fd["home"]] += 1
                votes[us[0]["away"]][fd["away"]] += 1
    mapping = {}
    for name, c in votes.items():
        best, n = c.most_common(1)[0]
        if n < NAME_VOTE_SHARE * sum(c.values()):
            raise ValueError(f"Understat club {name!r} maps ambiguously to football-data names: {dict(c)}")
        mapping[name] = best
    clash = [n for n, v in Counter(mapping.values()).items() if v > 1]
    if clash:
        raise ValueError(f"two Understat clubs map to the same football-data name: {clash}")
    return mapping


def attach_xg(rows_by_season, us_by_season):
    """Add "hxg"/"axg" to every football-data row in place (None where the source has no
    season), and return the rows. Raises unless each Understat season joins one-to-one."""
    mapping = learn_name_map(rows_by_season, us_by_season)
    for rows in rows_by_season.values():
        for r in rows:
            r.setdefault("hxg", None)
            r.setdefault("axg", None)
    for season, us_rows in us_by_season.items():
        unmapped = {t for r in us_rows for t in (r["home"], r["away"])} - set(mapping)
        if unmapped:
            raise ValueError(f"{season}: no football-data name learned for {sorted(unmapped)}")
        by_pair = {(mapping[r["home"]], mapping[r["away"]]): r for r in us_rows}
        rows, mismatched = rows_by_season[season], 0
        for r in rows:
            u = by_pair.get((r["home"], r["away"]))
            if u is None:
                raise ValueError(f"{season}: no Understat match for {r['home']} v {r['away']}")
            r["hxg"], r["axg"] = u["hxg"], u["axg"]
            mismatched += (u["hg"], u["ag"]) != (r["hg"], r["ag"])
        if len(by_pair) != len(rows) or mismatched > MAX_SCORE_MISMATCH * len(rows):
            raise ValueError(f"{season}: {len(rows)} football-data rows vs {len(by_pair)} Understat matches, "
                             f"{mismatched} with a different score")
    return rows_by_season


def attach_all(data, cache_dir=DEFAULT_CACHE, fetch=fetch_understat_season):
    """Attach xG to {league: {season: rows}} (the shape rolling_backtest.load_all returns)."""
    for league, by_season in data.items():
        code = UNDERSTAT_LEAGUES[league]
        us = {s: parse_understat(load_understat_season(code, s, cache_dir, fetch))
              for s in SEASONS[SEASONS.index(FIRST_SEASON):] if s in by_season}
        attach_xg(by_season, us)
    return data
