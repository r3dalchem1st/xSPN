"""
Multi-season match results + market odds from football-data.co.uk, for
rolling-origin backtests (rolling_backtest.py, validate_sim.py).

Why this source rather than the openfootball files the live pipeline uses:
football-data.co.uk has every season back to 1993 in one consistent format,
with each match's result AND the bookmaker odds in the same row, so a
multi-season backtest needs no join and no per-season team_aliases work (the
openfootball route needed three separate alias passes for just three seasons).
Team names here are only used for identity WITHIN this dataset, so they're kept
exactly as the source writes them -- check team_name_splits() for a season
pair that changes more clubs than promotion/relegation explains.

Market column preference, best available per row: AvgH/D/A (market average,
2019-20 onward), BbAvH/D/A (Betbrain average, 2012-13 to 2018-19), B365H/D/A
(single book). The audit (8 Oct) found pre-match average, closing average and
Pinnacle closing score identically (Brier 0.5665-0.5672), so mixing eras'
columns doesn't move the benchmark.

Raw CSVs are cached under backtest_cache/ (gitignored) so a backtest is
network-free after the first run.
"""
import csv
import io
import os

from fetch_odds_history import fetch_season_csv
from odds_utils import implied_probs_from_odds

SEASONS = ["1314", "1415", "1516", "1617", "1718", "1819", "1920", "2021", "2122", "2223", "2324", "2425", "2526"]
LEAGUE_CODES = {"premier_league": "E0", "la_liga": "SP1", "bundesliga": "D1"}
MARKET_COLUMNS = [("AvgH", "AvgD", "AvgA"), ("BbAvH", "BbAvD", "BbAvA"), ("B365H", "B365D", "B365A")]
DEFAULT_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_cache")


def parse_fd_date(s):
    """"16/08/14" or "15/08/2025" -> "2014-08-16" / "2025-08-15"."""
    d, m, y = s.strip().split("/")
    y = int(y)
    y += 2000 if y < 100 else 0
    return f"{y:04d}-{int(m):02d}-{int(d):02d}"


def _market_probs(row):
    for cols in MARKET_COLUMNS:
        try:
            odds = [float(row[c]) for c in cols]
        except (KeyError, ValueError, TypeError):
            continue
        if all(o > 1.0 for o in odds):
            return implied_probs_from_odds(*odds)
    return None


def parse_season_rows(text):
    """Played matches as [{"date","home","away","hg","ag","market"}], sorted by
    date. `market` is the de-vigged (ph,pd,pa) or None when the row has no
    usable odds. A row with no full-time score (unplayed) is skipped."""
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        try:
            hg, ag = int(r["FTHG"]), int(r["FTAG"])
        except (KeyError, ValueError, TypeError):
            continue
        rows.append({"date": parse_fd_date(r["Date"]), "home": r["HomeTeam"].strip(),
                     "away": r["AwayTeam"].strip(), "hg": hg, "ag": ag, "market": _market_probs(r)})
    return sorted(rows, key=lambda x: x["date"])


def load_season_csv(code, season, cache_dir=DEFAULT_CACHE):
    path = os.path.join(cache_dir, f"{code}_{season}.csv")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    text = fetch_season_csv(code, season)
    os.makedirs(cache_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return text


def load_league(code, seasons=SEASONS, cache_dir=DEFAULT_CACHE):
    """{season: rows} for one football-data.co.uk league code."""
    return {s: parse_season_rows(load_season_csv(code, s, cache_dir)) for s in seasons}


def team_name_splits(rows_by_season):
    """{(season_a, season_b): (only_in_a, only_in_b)} for each consecutive pair.
    A healthy 20-team league changes ~3 clubs per side per season; many more
    means one club is being written two ways (the West Ham / St. Pauli bug)."""
    seasons = list(rows_by_season)
    teams = {s: {t for r in rows_by_season[s] for t in (r["home"], r["away"])} for s in seasons}
    return {(a, b): (sorted(teams[a] - teams[b]), sorted(teams[b] - teams[a]))
            for a, b in zip(seasons, seasons[1:])}


def to_fit_rows(rows, label, xg_weight=0.0):
    """Rows in fit_league.py's training format: [date, home, away, hg, ag, label, neutral].

    `xg_weight` blends each side's goals toward its xG, (1-w)*goals + w*xG, for rows that
    carry xG (xg_data.attach_all); rows without it keep their real goals. 0 -> plain goals."""
    def target(r, goals, xg):
        x = r.get(xg)
        return r[goals] if not xg_weight or x is None else (1 - xg_weight) * r[goals] + xg_weight * x
    return [[r["date"], r["home"], r["away"], target(r, "hg", "hxg"), target(r, "ag", "axg"), label, False]
            for r in rows]
