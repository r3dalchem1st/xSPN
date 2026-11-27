"""
Fetch, parse, and write per-competition artifacts for a knockout_only
competition (Copa del Rey's format: 8 sequential single-elimination rounds,
no league phase at all, entrants staggered by division).

Deliberately a separate script from fetch_league.py/fetch_cup.py, same
non-refactor posture as every prior format pair in this project (see
fit_league.py's Global Constraints for the canonical reasoning) -- but
DOES reuse fetch_league.build_training_rows() directly, unmodified: that
function only needs (date, home, away, score) per match and doesn't care
about round labels, so it already works for both Copa's own historical
matches AND the extra_training_sources league files below.

Verified live during planning (see this plan's Global Constraints):
Copa's round labels are fixed across every available season (unlike
UCL/UEL's bare-vs-prefixed drift) and openfootball/espana's cup.txt is
only parseable from 2024-25 onward -- earlier seasons use an unsupported
older format revision and silently yield zero matches.

Usage: python fetch_copa.py competitions/<slug>.json
"""
import bisect
import json
import os
import re
import sys
from datetime import date, datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from competition_config import artifact_dir, load_competition
from fetch_league import build_training_rows, fetch_openfootball_file
from openfootball_txt import parse_openfootball_txt

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
# Wikimedia asks automated clients for a descriptive User-Agent; kept generic on purpose (no
# personal or project details go to a third party). Two requests a day is far below their limits.
WIKIPEDIA_USER_AGENT = "football-prediction-model/1.0 (non-commercial hobby project)"

# Wikipedia's round headings -> the openfootball round labels everything downstream keys on.
_WIKIPEDIA_ROUNDS = {
    "preliminary round": "Preliminary round", "first round": "Round 1", "second round": "Round 2",
    "round of 32": "Round 3", "round of 16": "Round of 16", "quarter-finals": "Quarterfinals",
    "semi-finals": "Semifinals", "final": "Final",
}
_BOX_FIELD_RE = re.compile(r"^\|\s*(date|team1|team2|score|penaltyscore)\s*=([^\n]*)", re.M)


def _wikipedia_boxes(wikitext):
    """(position, body) of every {{football box [collapsible]}} template -- found by brace
    matching, since a box nests other templates (goal lists, flags)."""
    for m in re.finditer(r"\{\{\s*football box(?: collapsible)?\s*(?=\|)", wikitext, re.I):
        depth, i = 1, m.end()
        while depth and i < len(wikitext):
            pair = wikitext[i:i + 2]
            depth += (pair == "{{") - (pair == "}}")
            i += 2 if pair in ("{{", "}}") else 1
        yield m.start(), wikitext[m.end():i - 2]


def _wikipedia_team(raw):
    """Club name from a team1/team2 field: the article title of its first [[link]] (stable,
    unlike the display text), else the plain text -- minus the '(4)' draw-pot suffix."""
    link = re.search(r"\[\[([^\]|#]+)", raw)
    return (link.group(1) if link else re.sub(r"\(\d+\)|<[^>]*>|'''|\{\{[^}]*\}\}", "", raw)).strip()


def _score_pair(text):
    m = re.search(r"(\d+)\s*[–—-]\s*(\d+)", text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _wikipedia_date(text):
    """ISO date from a box's date field: '1 December 2026' or '{{Start date|2026|4|18|df=y}}'
    (the Final's own article uses the template). None if neither."""
    d = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text)
    if d:
        return datetime.strptime(" ".join(d.groups()), "%d %B %Y").date().isoformat()
    s = re.search(r"start date\|(\d{4})\|(\d{1,2})\|(\d{1,2})", text, re.I)
    return date(*map(int, s.groups())).isoformat() if s else None


def parse_wikipedia_matches(wikitext, today=None):
    """Every match of one Copa del Rey Wikipedia page as the dict parse_openfootball_txt()
    returns ({round, date, home, away, score, pen_score}), so build_* take either source
    unchanged. `score` is the result after extra time (a shoot-out sits apart in pen_score);
    boxes with no teams yet (an undrawn round's template skeleton) are skipped.

    Wikipedia is volunteer-edited, so format drift must fail loudly, not quietly drop data:
    ValueError for a box under an unknown round heading, a box with teams but no readable
    date, a page with no matches, or most past-dated matches lacking a score (a changed score
    template). fetch_and_save treats that like a failed download and keeps the old artifacts."""
    today = (today or date.today()).isoformat()
    headings = [(m.start(), m.group(1).strip().lower())
                for m in re.finditer(r"^==([^=].*?)==\s*$", wikitext, re.M)]
    matches = []
    for pos, body in _wikipedia_boxes(wikitext):
        f = {k: v.strip() for k, v in reversed(_BOX_FIELD_RE.findall(body))}
        home, away = _wikipedia_team(f.get("team1", "")), _wikipedia_team(f.get("team2", ""))
        if not home or not away:
            continue
        before = bisect.bisect(headings, (pos, "￿"))     # headings above this box
        heading = headings[before - 1][1] if before else None
        if heading not in _WIKIPEDIA_ROUNDS:
            raise ValueError(f"match {home!r} v {away!r} sits under unrecognised heading {heading!r}")
        iso = _wikipedia_date(f.get("date", ""))
        if not iso:
            raise ValueError(f"match {home!r} v {away!r} has no readable date: {f.get('date')!r}")
        match = {"round": _WIKIPEDIA_ROUNDS[heading], "home": home, "away": away, "date": iso,
                 "score": _score_pair(f.get("score", ""))}
        if match["score"] and _score_pair(f.get("penaltyscore", "")):
            match["pen_score"] = _score_pair(f["penaltyscore"])
        matches.append(match)
    if not matches:
        raise ValueError("no matches found on the page")
    past = [m for m in matches if m["date"] < today]
    if len(past) and sum(m["score"] is None for m in past) > len(past) / 2:
        raise ValueError("most past matches have no readable score -- the score template changed?")
    return sorted(matches, key=lambda m: m["date"])


_wikipedia_session = requests.Session()     # retries a dropped connection / 5xx instead of failing the run
_wikipedia_session.mount("https://", HTTPAdapter(max_retries=Retry(
    total=3, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504))))


def _wikipedia_wikitext(page, timeout):
    resp = _wikipedia_session.get(WIKIPEDIA_API, headers={"User-Agent": WIKIPEDIA_USER_AGENT},
                                  timeout=timeout, params={"action": "parse", "page": page,
                                  "prop": "wikitext", "redirects": 1, "format": "json", "formatversion": 2})
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise requests.RequestException(f"Wikipedia: {data['error'].get('info', data['error'])}")
    return data["parse"]["wikitext"]


def fetch_wikipedia_season(page, timeout=30):
    """One Copa edition's matches from its Wikipedia page, via the MediaWiki API (CC BY-SA).
    The Final's box lives on its own article, pulled in by a {{:Title}} transclusion, so each
    one is replaced by that article's <onlyinclude> part (what a transclusion shows) before
    parsing. A missing page or failed request raises requests.RequestException; an unreadable
    page raises ValueError (see parse_wikipedia_matches)."""
    def transcluded(m):
        text = _wikipedia_wikitext(m.group(1).strip(), timeout)
        part = re.search(r"<onlyinclude>(.*?)</onlyinclude>", text, re.S)
        return part.group(1) if part else text
    wikitext = re.sub(r"\{\{:([^{}|]+)\}\}", transcluded, _wikipedia_wikitext(page, timeout))
    return parse_wikipedia_matches(wikitext)

_ROUND_LABELS = {
    "Preliminary round": "preliminary",
    "Round 1": "round_1",
    "Round 2": "round_2",
    "Round 3": "round_3",
    "Round of 16": "round_of_16",
    "Quarterfinals": "quarterfinal",
    "Semifinals": "semifinal",
    "Final": "final",
}


def classify_round(round_label):
    """Copa del Rey's 8 real rounds -> canonical stage key. Confirmed
    byte-identical across every available season (2020-21 through
    2024-25) via live curl during planning -- unlike UCL/UEL's openfootball
    files, there's no bare-vs-prefixed label drift to guard against here,
    so an exact-match lookup is correct (not a prefix match). Returns None
    for anything else (an unexpected heading), so the caller skips it
    rather than misclassifying it."""
    return _ROUND_LABELS.get(round_label)


def build_knockout_fixtures(config, parsed_matches):
    """Every fixture from one parsed Copa season (all 8 rounds -- unlike
    fetch_cup.py's playoff/final-only version, there's no league phase to
    exclude), as a flat chronological list: {round, date, home, away,
    score, pen_score}. `round` is kept as openfootball's own raw label
    ("Quarterfinals", not the canonical "quarterfinal") -- sim_copa.py owns
    the raw-label -> canonical-stage mapping, same division of
    responsibility as fetch_cup.py/sim_cup.py. Returns (fixtures, n_skipped)."""
    fixtures, n_skipped = [], 0
    for m in parsed_matches:
        if classify_round(m["round"]) is None:
            continue
        home, away = config.resolve_team(m["home"]), config.resolve_team(m["away"])
        if not home or not away:
            n_skipped += 1
            continue
        fixtures.append({
            "round": m["round"], "date": m["date"], "home": home, "away": away,
            "score": list(m["score"]) if m["score"] is not None else None,
            "pen_score": list(m["pen_score"]) if m.get("pen_score") is not None else None,
        })
    return fixtures, n_skipped


def fetch_and_save(config, base_dir):
    """Fetch Copa's own configured season(s) (newest first) plus every
    file in config.extra_training_sources (La Liga + Segunda history, per
    the design doc), and write:
      competitions/<slug>/fetched_matches.json -- training rows from EVERY
        played match in Copa's own season(s) AND every extra_training_sources
        file, merged into one shared rating space so fit_league.py rates
        every club that plays in any of the three competitions.
      competitions/<slug>/knockout_fixtures.json -- Copa's own newest
        season's fixtures only (all 8 rounds), played + unplayed.

    knockout_fixtures.json is left UNTOUCHED if Copa's own current-season
    fetch fails -- same transient-failure safety rule fetch_league.py/
    fetch_cup.py already follow. A failed extra_training_sources fetch is
    NOT fatal and does not block writing knockout_fixtures.json -- it only
    means slightly fewer rated teams (graceful degradation, not a
    corrupted live artifact), same tolerance fetch_league.py already
    extends to a failed OLDER season of its own history.

    Returns a summary dict: {"matches": int, "knockout_fixtures": int,
    "skipped": int, "failed_seasons": [path,...], "current_season_failed": bool}."""
    out_dir = artifact_dir(config, base_dir)
    all_rows, current_ko_fixtures = [], []
    total_skipped, failed = 0, []
    current_season_failed = False

    # Newest first, as ever: the config's Wikipedia editions (if any), then openfootball's files.
    sources = [(f"Wikipedia {entry['page']}", lambda page=entry["page"]: fetch_wikipedia_season(page))
               for entry in config.wikipedia_pages]
    sources += [(entry["path"],
                 lambda path=entry["path"]: parse_openfootball_txt(
                     fetch_openfootball_file(config.openfootball_repo, path)))
                for entry in config.openfootball_files]

    for i, (label, load) in enumerate(sources):
        try:
            parsed = load()
        except (requests.RequestException, ValueError) as e:   # ValueError: an unreadable Wikipedia page
            print(f"  ! failed to fetch {label}: {e}")
            failed.append(label)
            if i == 0:
                current_season_failed = True
            continue
        rows, n_skipped = build_training_rows(config, parsed)
        all_rows.extend(rows)
        total_skipped += n_skipped
        if i == 0:
            current_ko_fixtures, sk = build_knockout_fixtures(config, parsed)
            total_skipped += sk

    for entry in config.extra_training_sources:
        try:
            text = fetch_openfootball_file(entry["repo"], entry["path"])
        except requests.RequestException as e:
            print(f"  ! failed to fetch extra training source {entry['path']}: {e}")
            failed.append(entry["path"])
            continue
        parsed = parse_openfootball_txt(text)
        rows, n_skipped = build_training_rows(config, parsed)
        all_rows.extend(rows)
        total_skipped += n_skipped

    with open(os.path.join(out_dir, "fetched_matches.json"), "w") as f:
        json.dump(all_rows, f, indent=2)

    if current_season_failed:
        print("  ! current-season fetch failed — leaving existing knockout_fixtures.json untouched")
    else:
        with open(os.path.join(out_dir, "knockout_fixtures.json"), "w") as f:
            json.dump(current_ko_fixtures, f, indent=2)

    return {"matches": len(all_rows), "knockout_fixtures": len(current_ko_fixtures),
            "skipped": total_skipped, "failed_seasons": failed,
            "current_season_failed": current_season_failed}


def main():
    if len(sys.argv) != 2:
        print("usage: python fetch_copa.py competitions/<slug>.json")
        raise SystemExit(1)
    config = load_competition(sys.argv[1])
    base_dir = os.path.dirname(os.path.abspath(__file__))
    summary = fetch_and_save(config, base_dir)
    print(f"{config.name}: {summary['matches']} training rows, "
          f"{summary['knockout_fixtures']} current-season fixtures, "
          f"{summary['skipped']} skipped, "
          f"{len(summary['failed_seasons'])} source(s) failed to fetch.")
    if summary["current_season_failed"]:
        print("FATAL: current-season fetch failed — aborting so CI surfaces this loudly "
              "instead of silently leaving stale (but intact) artifacts in place.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
