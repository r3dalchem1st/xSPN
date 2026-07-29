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
import json
import os
import sys

import requests

from competition_config import artifact_dir, load_competition
from fetch_league import build_training_rows, fetch_openfootball_file
from openfootball_txt import parse_openfootball_txt

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

    for i, entry in enumerate(config.openfootball_files):
        try:
            text = fetch_openfootball_file(config.openfootball_repo, entry["path"])
        except requests.RequestException as e:
            print(f"  ! failed to fetch {entry['path']}: {e}")
            failed.append(entry["path"])
            if i == 0:
                current_season_failed = True
            continue
        parsed = parse_openfootball_txt(text)
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
