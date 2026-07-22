"""
Fetch, parse, and write per-competition training/schedule artifacts for a
round-robin (or any openfootball-.txt-sourced) competition, driven entirely
by a CompetitionConfig — no per-league Python code required.

Usage: python fetch_league.py competitions/<slug>.json
"""
import json
import os
import sys

import requests

from competition_config import artifact_dir, load_competition
from openfootball_txt import parse_openfootball_txt


def fetch_openfootball_file(repo, path, timeout=10):
    """Raw GET of one openfootball .txt fixture file. Returns decoded text.
    Raises requests.RequestException on network failure or non-2xx status."""
    url = f"https://raw.githubusercontent.com/{repo}/master/{path}"
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def build_training_rows(config, parsed_matches):
    """Convert parsed openfootball matches (from parse_openfootball_txt) into
    training rows [date, home, away, hg, ag, label, neutral] for played
    matches only. Returns (rows, n_skipped) where n_skipped counts matches
    dropped for an unresolved team name."""
    rows, n_skipped = [], 0
    for m in parsed_matches:
        if m["score"] is None:
            continue
        home = config.resolve_team(m["home"])
        away = config.resolve_team(m["away"])
        if not home or not away:
            print(f"    ! unmapped team name(s): {m['home']!r} / {m['away']!r} — skipped")
            n_skipped += 1
            continue
        hg, ag = m["score"]
        rows.append([m["date"], home, away, hg, ag, config.name, False])
    return rows, n_skipped


def build_schedule(config, parsed_matches):
    """All fixtures (played + unplayed) from one parsed season, keyed by
    DIRECTED team pair "home|away": {pair_key: {date, status, goals, round}}.
    A directed key (not a sorted one) is required here: unlike the World
    Cup's single round-robin group stage, a league plays every pair TWICE
    (home leg + away leg) — a sorted key would collide the two legs and
    silently drop one. Returns (schedule, n_skipped)."""
    sched, n_skipped = {}, 0
    for m in parsed_matches:
        home = config.resolve_team(m["home"])
        away = config.resolve_team(m["away"])
        if not home or not away:
            n_skipped += 1
            continue
        if m["score"] is not None:
            status, goals = "FINISHED", {home: m["score"][0], away: m["score"][1]}
        else:
            status, goals = "SCHEDULED", {home: None, away: None}
        sched[f"{home}|{away}"] = {
            "date": m["date"], "status": status, "goals": goals, "round": m["round"],
        }
    return sched, n_skipped


def fetch_and_save(config, base_dir):
    """Fetch every season configured for `config` (newest first), parse each,
    and write:
      competitions/<slug>/fetched_matches.json  -- training rows from EVERY
        configured season combined (played matches only)
      competitions/<slug>/schedule.json         -- ALL fixtures from the
        newest (current) season only, played + unplayed

    Returns a summary dict: {"matches": int, "scheduled": int, "skipped": int,
    "failed_seasons": [path, ...]}."""
    out_dir = artifact_dir(config, base_dir)
    all_rows, current_schedule = [], {}
    total_skipped, failed = 0, []

    for i, entry in enumerate(config.openfootball_files):
        try:
            text = fetch_openfootball_file(config.openfootball_repo, entry["path"])
        except requests.RequestException as e:
            print(f"  ! failed to fetch {entry['path']}: {e}")
            failed.append(entry["path"])
            continue
        parsed = parse_openfootball_txt(text)
        rows, n_skipped = build_training_rows(config, parsed)
        all_rows.extend(rows)
        total_skipped += n_skipped
        if i == 0:
            current_schedule, sched_skipped = build_schedule(config, parsed)
            total_skipped += sched_skipped

    with open(os.path.join(out_dir, "fetched_matches.json"), "w") as f:
        json.dump(all_rows, f, indent=2)
    with open(os.path.join(out_dir, "schedule.json"), "w") as f:
        json.dump(current_schedule, f, indent=2)

    return {"matches": len(all_rows), "scheduled": len(current_schedule),
            "skipped": total_skipped, "failed_seasons": failed}


def main():
    if len(sys.argv) != 2:
        print("usage: python fetch_league.py competitions/<slug>.json")
        raise SystemExit(1)
    config = load_competition(sys.argv[1])
    base_dir = os.path.dirname(os.path.abspath(__file__))
    summary = fetch_and_save(config, base_dir)
    print(f"{config.name}: {summary['matches']} training rows, "
          f"{summary['scheduled']} current-season fixtures, "
          f"{summary['skipped']} skipped, "
          f"{len(summary['failed_seasons'])} season(s) failed to fetch.")


if __name__ == "__main__":
    main()
