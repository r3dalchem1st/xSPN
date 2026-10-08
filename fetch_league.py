"""
Fetch, parse, and write per-competition training/schedule artifacts for a
round-robin (or any openfootball-.txt-sourced) competition, driven entirely
by a CompetitionConfig — no per-league Python code required.

Usage: python fetch_league.py competitions/<slug>.json
"""
import json
import os
import sys
from collections import Counter

import requests

from competition_config import artifact_dir, load_competition
from fetch_live_scores import fetch_matches as fetch_live_matches
from fetch_live_scores import overlay_live_results
from fetch_odds_history import build_mkt_probs_by_match, fetch_season_csv, parse_odds_rows
from fetch_odds_history import season_to_fd_code as _season_to_fd_code
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


def fetch_season_mkt_probs(config, entry, rows):
    """Real historical odds for ONE season, joined against that season's OWN
    training `rows` (already fetched/parsed by the caller, so this doesn't
    re-fetch openfootball) -- returns a list parallel to `rows` (one
    (ph,pd,pa) triple or None per match). [None]*len(rows) if
    config.odds_history_code isn't set, or if that season's odds file isn't
    available yet (most likely the current in-progress season --
    football-data.co.uk only has a season once it's over or partway
    through it): graceful, not an error, same discipline as every other
    optional external source here."""
    if not config.odds_history_code:
        return [None] * len(rows)
    try:
        odds_csv = fetch_season_csv(config.odds_history_code, _season_to_fd_code(entry["season"]))
        odds_rows, _ = parse_odds_rows(odds_csv, config)
        return build_mkt_probs_by_match(rows, odds_rows)
    except requests.RequestException:
        return [None] * len(rows)


JOIN_RATE_FLOOR = 0.95


def warn_if_odds_join_gap(config, entry, rows, mkt_probs):
    """GitHub Actions warning annotation when a CLOSED season's real-odds
    join rate falls below JOIN_RATE_FLOOR -- almost always a team_aliases
    gap (a club's name differs between openfootball and football-data.co.uk).
    Found by hand three separate times before this existed: matches that
    fail to join just silently stop contributing to the odds term, with
    nothing in any log. A warning rather than a hard failure: odds are an
    optional enhancement, and aborting the whole daily pipeline over a
    partial gap would cost more than it saves. Names the most-affected
    teams so the fix has ground truth to start from. Not called for the
    in-progress season, whose odds file is expected to lag."""
    if not rows or not config.odds_history_code:
        return
    unjoined = [r for r, p in zip(rows, mkt_probs) if p is None]
    if 1 - len(unjoined) / len(rows) >= JOIN_RATE_FLOOR:
        return
    worst = Counter(t for r in unjoined for t in (r[1], r[2])).most_common(3)
    print(f"::warning::{config.name} {entry['season']}: only {len(rows) - len(unjoined)}/{len(rows)} "
          f"matches joined with historical odds -- likely a team_aliases gap; most affected: {worst}")


def overlay_training_rows(config, schedule, openfootball_rows):
    """Training rows [date, home, away, hg, ag, label, neutral] for every
    match the live overlay (fetch_live_scores.py) marked FINISHED in
    `schedule` that openfootball hasn't scored yet (no row for that directed
    pair in `openfootball_rows`). Without these the fit -- and the momentum
    signal built on the last 5-8 results -- ran on data days older than the
    Results tab itself, because the overlay only ever patched schedule.json:
    confirmed live, 26 of 34 La Liga fits had finished matches the training
    data didn't (mean 7, max 18). A directed pair is unique within one
    season, so it's a safe de-dup key."""
    have = {(r[1], r[2]) for r in openfootball_rows}
    rows = []
    for key, e in schedule.items():
        if e["status"] != "FINISHED":
            continue
        home, away = key.split("|")
        if (home, away) in have:
            continue
        hg, ag = e["goals"][home], e["goals"][away]
        if hg is None or ag is None:
            continue
        rows.append([e["date"], home, away, hg, ag, config.name, False])
    return rows


def fetch_and_save(config, base_dir):
    """Fetch every season configured for `config` (newest first), parse each,
    and write:
      competitions/<slug>/fetched_matches.json    -- training rows from EVERY
        configured season combined (played matches only, current season
        first), including any result the live overlay has that openfootball
        hasn't scored yet
      competitions/<slug>/mkt_probs_by_match.json -- real historical odds
        joined per season (see fetch_season_mkt_probs), one entry PARALLEL
        to fetched_matches.json (same length/order) -- (ph,pd,pa) or None.
        Always written (even all-None) so fit_league.py's fit_and_save() and
        every competition's CI commit step can rely on it always existing,
        same invariant every other artifact file already has.
      competitions/<slug>/schedule.json           -- ALL fixtures from the
        newest (current) season only, played + unplayed

    schedule.json is left UNTOUCHED if the current season's fetch fails: a
    transient failure must never wipe a good schedule to empty (an empty
    file still counts as "changed", so CI would happily commit and push the
    wipe over a previously-good live schedule). fetched_matches.json/
    mkt_probs_by_match.json are unaffected by this guard — losing one OLDER
    season's training rows just means slightly less training data, not a
    corrupted live artifact.

    Returns a summary dict: {"matches": int, "scheduled": int, "skipped": int,
    "failed_seasons": [path, ...], "current_season_failed": bool}."""
    out_dir = artifact_dir(config, base_dir)
    current_rows, current_entry, current_schedule = [], None, {}
    older_rows, older_mkt_probs = [], []
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
        total_skipped += n_skipped
        if i == 0:
            # Held aside until the live overlay below has had its say: it can
            # add results openfootball hasn't scored yet (see overlay_training_rows).
            current_rows, current_entry = rows, entry
            current_schedule, sched_skipped = build_schedule(config, parsed)
            total_skipped += sched_skipped
            continue
        mkt_probs = fetch_season_mkt_probs(config, entry, rows)
        warn_if_odds_join_gap(config, entry, rows, mkt_probs)
        older_rows.extend(rows)
        older_mkt_probs.extend(mkt_probs)

    if current_season_failed:
        print("  ! current-season fetch failed — leaving existing schedule.json untouched")
    elif config.football_data_code:
        raw = fetch_live_matches(config.football_data_code)
        if raw:
            _, n_overlaid, n_date_corrected, _ = overlay_live_results(config, current_schedule, raw)
            if n_overlaid or n_date_corrected:
                print(f"  live-score overlay: {n_overlaid} result(s), "
                      f"{n_date_corrected} date correction(s) from football-data.org")
        live_rows = overlay_training_rows(config, current_schedule, current_rows)
        if live_rows:
            print(f"  {len(live_rows)} live result(s) added to training data "
                  f"(openfootball hasn't scored them yet)")
        current_rows = current_rows + live_rows

    current_mkt_probs = (fetch_season_mkt_probs(config, current_entry, current_rows)
                         if current_entry else [])
    all_rows = current_rows + older_rows
    with open(os.path.join(out_dir, "fetched_matches.json"), "w") as f:
        json.dump(all_rows, f, indent=2)
    with open(os.path.join(out_dir, "mkt_probs_by_match.json"), "w") as f:
        json.dump(current_mkt_probs + older_mkt_probs, f)
    if not current_season_failed:
        with open(os.path.join(out_dir, "schedule.json"), "w") as f:
            json.dump(current_schedule, f, indent=2)

    return {"matches": len(all_rows), "scheduled": len(current_schedule),
            "skipped": total_skipped, "failed_seasons": failed,
            "current_season_failed": current_season_failed}


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
    if summary["current_season_failed"]:
        print("FATAL: current-season fetch failed — aborting so CI surfaces this loudly "
              "instead of silently leaving a stale (but intact) schedule.json in place.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
