"""
Pre-match prediction locking for league_phase_knockout competitions.

Locks each fixture's predicted H/D/A + scoreline once its real date is
within LOCK_WINDOW_DAYS, append-only -- identical mechanism to
snapshot_league.py (hda_probs/likely_score/fixture_due all reused
unmodified), just applied per MATCH rather than per TIE: a knockout leg's
own H/D/A outcome is graded the same honest way any league fixture is (a
1-1 draw that a shootout later resolves is still, correctly, a drawn
match). "Which team advances the tie" is a separate question already
served by sim_cup.py's stage-reach probabilities (cup_sim.json) -- this
module isn't trying to also predict and grade that.

Self-contained rather than sharing a "combined fixtures" helper with
score_cup.py: same sibling-independence choice snapshot_league.py/
score_league.py already made for each other.
"""
import json
import os
import sys
from datetime import date

from sim_league import build_lambda_tables
from snapshot_league import LOCK_WINDOW_DAYS, fixture_due, hda_probs, likely_score


def iter_fixtures(league_schedule, knockout_fixtures):
    """Yields (key, home, away, date, status) covering both the league
    phase (league_schedule.json, keyed "home|away") and the knockout stage
    (knockout_fixtures.json, a flat list -- keyed by "round|home|away" since
    two legs of the same tie share the same directed home/away pair)."""
    for key, entry in league_schedule.items():
        home, away = key.split("|")
        yield key, home, away, entry["date"], entry["status"]
    for fx in knockout_fixtures:
        key = f"{fx['round']}|{fx['home']}|{fx['away']}"
        status = "FINISHED" if fx["score"] is not None else "SCHEDULED"
        yield key, fx["home"], fx["away"], fx["date"], status


def snapshot_and_save(config, base_dir, dc_ensemble, today=None):
    """Load <slug>/league_schedule.json + <slug>/knockout_fixtures.json (if
    present) + existing predictions_snapshot.json, lock any newly-due
    fixture's current model prediction, and write the (possibly extended)
    snapshot back. Returns the number of newly locked entries."""
    from competition_config import artifact_dir
    out_dir = artifact_dir(config, base_dir)
    today = today or date.today().isoformat()

    with open(os.path.join(out_dir, "league_schedule.json")) as f:
        league_schedule = json.load(f)
    ko_path = os.path.join(out_dir, "knockout_fixtures.json")
    knockout_fixtures = []
    if os.path.exists(ko_path):
        with open(ko_path) as f:
            knockout_fixtures = json.load(f)

    snapshot_path = os.path.join(out_dir, "predictions_snapshot.json")
    if os.path.exists(snapshot_path):
        with open(snapshot_path) as f:
            snapshot = json.load(f)
    else:
        snapshot = {}

    teams = sorted({t for key in league_schedule for t in key.split("|")})
    lg_ens = build_lambda_tables(teams, dc_ensemble)

    added = 0
    for key, home, away, fdate, status in iter_fixtures(league_schedule, knockout_fixtures):
        if key in snapshot:
            continue
        if status != "SCHEDULED":
            continue
        if not fixture_due(fdate, today):
            continue
        ph, pd, pa = hda_probs(home, away, lg_ens)
        outcome = max([("H", ph), ("D", pd), ("A", pa)], key=lambda x: x[1])[0]
        lam, mu = lg_ens[0][(home, away)]
        hg, ag = likely_score(lam, mu, allowed={outcome})
        snapshot[key] = {
            "home": home, "away": away, "date": fdate,
            "ph": ph, "pd": pd, "pa": pa,
            "predicted_winner": outcome, "predicted_score": f"{hg}-{ag}",
            "snapped_at": today,
        }
        added += 1

    with open(snapshot_path, "w") as f:
        json.dump(snapshot, f, indent=2)
    return added


def main():
    if len(sys.argv) != 2:
        print("usage: python snapshot_cup.py competitions/<slug>.json")
        raise SystemExit(1)
    from competition_config import artifact_dir, load_competition
    config = load_competition(sys.argv[1])
    base_dir = os.path.dirname(os.path.abspath(__file__))
    out_dir = artifact_dir(config, base_dir)
    with open(os.path.join(out_dir, "dc_ensemble.json")) as f:
        dc_ensemble = json.load(f)
    added = snapshot_and_save(config, base_dir, dc_ensemble)
    print(f"{config.name}: {added} new prediction(s) locked.")


if __name__ == "__main__":
    main()
