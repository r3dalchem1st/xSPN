"""
Per-match xG from Understat: the xG family in experiments.py (which passed the
pre-registered rule) and, through live_xg(), the production fit.

Understat serves each league-season as one JSON document (the endpoint its own
league page calls) holding every match's goals and xG, back to 2014-15. It is
unofficial and undocumented, so the harness reads it through a local cache
(backtest_cache/, gitignored) and the live pipeline treats it as optional:
live_xg() never raises, and anything it cannot supply leaves those matches on
their real goals. 2013-14 has no Understat data, so those rows keep xG=None and
the fit falls back to their real goals.

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
JOIN_FLOOR = 0.9             # live: warn when fewer of a season's training rows than this get an xG


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


def season_of(date):
    """'2026-10-03' -> '2627': the season a match date falls in (seasons run Aug-May)."""
    y = int(date[:4]) - (int(date[5:7]) < 8)
    return f"{y % 100:02d}{(y + 1) % 100:02d}"


def live_xg(code, rows, fetch=fetch_understat_season):
    """[(hxg, axg) or None] parallel to the live training `rows` ([date, home, away, hg, ag, ...]).

    The production counterpart of attach_all, but it never raises: Understat is unofficial and
    CI may be blocked, so a season it cannot serve, a name map that will not resolve, or a
    season whose scores disagree with ours (> MAX_SCORE_MISMATCH) leaves those rows None -- the
    fit then trains them on real goals -- and prints a GitHub warning. A match the training
    data has but Understat does not (results land in different places at different times) is
    also None; it only draws a warning when a season is short by more than JOIN_FLOOR."""
    out, by_season = [None] * len(rows), defaultdict(list)
    for i, r in enumerate(rows):
        by_season[season_of(r[0])].append(i)
    warn = lambda msg: print(f"::warning::xG ({code}): {msg} -- those matches train on real goals")
    us = {}
    for season in by_season:
        try:
            us[season] = parse_understat(fetch(code, season_year(season)))
        except (OSError, ValueError, KeyError, TypeError) as e:     # network, HTTP, JSON or schema
            warn(f"Understat {season} unavailable ({type(e).__name__}: {e})")
    ours = {s: [dict(zip(("date", "home", "away", "hg", "ag"), rows[i][:5])) for i in by_season[s]] for s in us}
    try:
        mapping = learn_name_map(ours, us)
    except ValueError as e:
        warn(str(e))
        return out
    for season, us_rows in us.items():
        by_pair = {(mapping.get(u["home"]), mapping.get(u["away"])): u for u in us_rows}
        joined = {i: by_pair[(rows[i][1], rows[i][2])] for i in by_season[season] if (rows[i][1], rows[i][2]) in by_pair}
        bad = sum((u["hg"], u["ag"]) != tuple(rows[i][3:5]) for i, u in joined.items())
        if bad > MAX_SCORE_MISMATCH * len(joined):
            warn(f"{season}: {bad} of {len(joined)} joined matches have a different score in Understat")
            continue
        for i, u in joined.items():
            out[i] = (round(u["hxg"], 4), round(u["axg"], 4))
        if len(joined) < JOIN_FLOOR * len(by_season[season]):
            warn(f"{season}: only {len(joined)}/{len(by_season[season])} matches joined")
    return out


def attach_all(data, cache_dir=DEFAULT_CACHE, fetch=fetch_understat_season):
    """Attach xG to {league: {season: rows}} (the shape rolling_backtest.load_all returns)."""
    for league, by_season in data.items():
        code = UNDERSTAT_LEAGUES[league]
        us = {s: parse_understat(load_understat_season(code, s, cache_dir, fetch))
              for s in SEASONS[SEASONS.index(FIRST_SEASON):] if s in by_season}
        attach_xg(by_season, us)
    return data
