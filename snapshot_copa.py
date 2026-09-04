"""
Pre-match prediction locking for knockout_only competitions (Copa del Rey).

Locks each fixture's predicted H/D/A + scoreline once its real date is
within LOCK_WINDOW_DAYS, mirroring snapshot_league.py's per-match date-gate
discipline exactly (fixture_due/hda_probs/likely_score reused unmodified).
No league_schedule.json half to also iterate (unlike snapshot_cup.py) --
this format has no league phase at all, so knockout_fixtures.json is the
only fixture source.
"""
import json
import os
import sys
from datetime import date

from sim_copa import build_match_lambda_tables
from snapshot_league import LOCK_WINDOW_DAYS, fixture_due, hda_probs, likely_score


def iter_fixtures(knockout_fixtures):
    """Yields (key, home, away, date, status) for every real fixture,
    keyed "round|home|away" -- a two-legged Semifinal tie's two legs share
    the same round label but opposite home/away, so this key is unique per
    leg, same convention fetch_cup.py's family already uses."""
    for fx in knockout_fixtures:
        key = f"{fx['round']}|{fx['home']}|{fx['away']}"
        status = "FINISHED" if fx["score"] is not None else "SCHEDULED"
        yield key, fx["home"], fx["away"], fx["date"], status


def snapshot_and_save(config, base_dir, dc_ensemble, today=None):
    """Load <slug>/knockout_fixtures.json + existing predictions_snapshot.json
    (if any), lock any newly-due fixture's current model prediction, and
    write the (possibly extended) snapshot back. Returns the number of
    newly locked entries."""
    from competition_config import artifact_dir
    out_dir = artifact_dir(config, base_dir)
    today = today or date.today().isoformat()

    with open(os.path.join(out_dir, "knockout_fixtures.json")) as f:
        knockout_fixtures = json.load(f)

    snapshot_path = os.path.join(out_dir, "predictions_snapshot.json")
    if os.path.exists(snapshot_path):
        with open(snapshot_path) as f:
            snapshot = json.load(f)
    else:
        snapshot = {}

    matches_path = os.path.join(out_dir, "fetched_matches.json")
    matches = json.load(open(matches_path)) if os.path.exists(matches_path) else []

    teams = sorted({t for fx in knockout_fixtures for t in (fx["home"], fx["away"])})
    lg_ens = build_match_lambda_tables(config, teams, dc_ensemble, matches, today)
    rhos = [dc.get("rho", 0.0) for dc in dc_ensemble] if config.use_rho else None

    added = 0
    for key, home, away, fdate, status in iter_fixtures(knockout_fixtures):
        if key in snapshot:
            continue
        if status != "SCHEDULED":
            continue
        if not fixture_due(fdate, today):
            continue
        ph, pd, pa = hda_probs(home, away, lg_ens, rhos=rhos, delta=config.draw_inflate)
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
        print("usage: python snapshot_copa.py competitions/<slug>.json")
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
