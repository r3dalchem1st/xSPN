"""
Sandbox for fit_league.py's odds-consistency term (see backtest_fit_odds.py
for the real backtested per-league weights, and CONTEXT.md for the full
story). Fits TWO parallel point-estimate models on the SAME real training
data every day the daily pipeline runs -- one exactly matching production
(odds_weight=0.0), one with the real config.odds_fit_weight applied -- and
locks each newly-due fixture's prediction from BOTH into a separate
shadow_predictions.json, using the exact same fixture_due()/LOCK_WINDOW_DAYS
locking rules as the real predictions_snapshot.json (imported directly, not
reimplemented, so both experiments are scored on identical timing).

This is a genuinely separate file from predictions_snapshot.json -- the
live site and its real predictions are completely untouched by this. User
asked to sandbox the odds-fit term for about 2 weeks (until enough real
fixtures with real, now-known results accumulate) before deciding whether
to promote odds_fit_weight into the real production fit_and_save() call.
Use score_shadow.py to compare the two columns once enough real results
are in.

Deliberately point-estimate only (no 60-member bootstrap) for both models
-- same simplification backtest_league.py/backtest_fit_odds.py already
make, isolating the ONE variable under test (the odds term) rather than
also paying for bootstrap uncertainty bands nobody's consuming here.

Usage: python shadow_fit_odds.py competitions/<slug>.json
"""
import json
import os
import sys
from datetime import date

import requests

import fit_league as fl
from backtest_fit_odds import build_mkt_probs_by_match
from backtest_odds import _season_to_fd_code
from competition_config import artifact_dir, load_competition
from fetch_league import build_training_rows, fetch_openfootball_file
from fetch_odds_history import fetch_season_csv, parse_odds_rows
from openfootball_txt import parse_openfootball_txt
from sim_league import build_lambda_table
from snapshot_league import fixture_due, hda_probs, likely_score


def fetch_one_season_with_odds(config, entry):
    """(rows, mkt_probs) for ONE configured season entry -- rows via the
    exact same openfootball fetch+parse fetch_league.py's real pipeline
    uses, mkt_probs a list parallel to rows (one de-vigged (ph,pd,pa)
    triple or None per match). A season with no historical odds file yet
    (most likely the current in-progress season -- football-data.co.uk
    only has it once the season's over, or not at all mid-season) falls
    back to mkt_probs=[None]*len(rows) gracefully, same "optional data
    source" discipline as every other external source in this project."""
    text = fetch_openfootball_file(config.openfootball_repo, entry["path"])
    parsed = parse_openfootball_txt(text)
    rows, _ = build_training_rows(config, parsed)
    try:
        odds_csv = fetch_season_csv(config.odds_history_code, _season_to_fd_code(entry["season"]))
        odds_rows, _ = parse_odds_rows(odds_csv, config)
        mkt_probs = build_mkt_probs_by_match(rows, odds_rows)
    except requests.RequestException:
        mkt_probs = [None] * len(rows)
    return rows, mkt_probs


def fetch_training_matches_and_odds(config):
    """Mirrors fetch_league.fetch_and_save's per-season loop over
    config.openfootball_files, extended to also fetch/join each season's
    real historical odds. Returns (matches, mkt_probs_by_match), both
    parallel lists in the same season order fetch_and_save itself uses."""
    all_matches, all_mkt_probs = [], []
    for entry in config.openfootball_files:
        rows, mkt_probs = fetch_one_season_with_odds(config, entry)
        all_matches.extend(rows)
        all_mkt_probs.extend(mkt_probs)
    return all_matches, all_mkt_probs


def fit_shadow_models(matches, mkt_probs_by_match, odds_weight):
    """Returns (dc_baseline, dc_odds_fit): two point-estimate fits on the
    SAME matches -- the only difference between them is odds_weight,
    isolating that one variable for a clean comparison."""
    elo = fl.compute_elos(matches)
    dc_baseline = fl.fit_dc(matches, elo)
    dc_odds_fit = fl.fit_dc(matches, elo, mkt_probs_by_match=mkt_probs_by_match,
                             odds_weight=odds_weight)
    return dc_baseline, dc_odds_fit


def snapshot_shadow_and_save(config, base_dir, dc_baseline, dc_odds_fit, today=None):
    """Locks BOTH models' prediction for every newly-due fixture into
    shadow_predictions.json, append-only, using the exact same
    fixture_due()/LOCK_WINDOW_DAYS rules as the real
    predictions_snapshot.json. Returns the number of newly locked entries."""
    out_dir = artifact_dir(config, base_dir)
    today = today or date.today().isoformat()

    with open(os.path.join(out_dir, "schedule.json")) as f:
        schedule = json.load(f)

    shadow_path = os.path.join(out_dir, "shadow_predictions.json")
    shadow = json.load(open(shadow_path)) if os.path.exists(shadow_path) else {}

    teams = sorted({t for key in schedule for t in key.split("|")})
    lg_baseline = [build_lambda_table(teams, dc_baseline)]
    lg_odds_fit = [build_lambda_table(teams, dc_odds_fit)]

    def predict(lg_ens, home, away):
        ph, pd, pa = hda_probs(home, away, lg_ens)
        outcome = max([("H", ph), ("D", pd), ("A", pa)], key=lambda x: x[1])[0]
        lam, mu = lg_ens[0][(home, away)]
        hg, ag = likely_score(lam, mu, allowed={outcome})
        return {"ph": ph, "pd": pd, "pa": pa,
                "predicted_winner": outcome, "predicted_score": f"{hg}-{ag}"}

    added = 0
    for key, entry in schedule.items():
        if key in shadow:
            continue
        if entry["status"] != "SCHEDULED":
            continue
        if not fixture_due(entry["date"], today):
            continue
        home, away = key.split("|")
        shadow[key] = {
            "home": home, "away": away, "date": entry["date"], "snapped_at": today,
            "baseline": predict(lg_baseline, home, away),
            "odds_fit": predict(lg_odds_fit, home, away),
        }
        added += 1

    with open(shadow_path, "w") as f:
        json.dump(shadow, f, indent=2)
    return added


def ensure_shadow_file_exists(config, base_dir):
    """Guarantees competitions/<slug>/shadow_predictions.json exists (empty
    {} is fine) so every competition's CI commit step can unconditionally
    `git add` it, same invariant every other artifact file already has --
    but never overwrites real sandboxed data already sitting there (e.g. a
    competition's odds_fit_weight got removed after the fact)."""
    shadow_path = os.path.join(artifact_dir(config, base_dir), "shadow_predictions.json")
    if not os.path.exists(shadow_path):
        with open(shadow_path, "w") as f:
            json.dump({}, f)


def main():
    if len(sys.argv) != 2:
        print("usage: python shadow_fit_odds.py competitions/<slug>.json")
        raise SystemExit(1)
    config = load_competition(sys.argv[1])
    base_dir = os.path.dirname(os.path.abspath(__file__))
    if not config.odds_fit_weight or not config.odds_history_code:
        ensure_shadow_file_exists(config, base_dir)
        print(f"{config.name}: no odds_fit_weight/odds_history_code configured -- nothing to sandbox.")
        return
    matches, mkt_probs = fetch_training_matches_and_odds(config)
    dc_baseline, dc_odds_fit = fit_shadow_models(matches, mkt_probs, config.odds_fit_weight)
    added = snapshot_shadow_and_save(config, base_dir, dc_baseline, dc_odds_fit)
    print(f"{config.name}: shadow fit -- baseline converged={dc_baseline['converged']}, "
          f"odds_fit (weight={config.odds_fit_weight}) converged={dc_odds_fit['converged']}. "
          f"{added} new shadow prediction(s) locked.")


if __name__ == "__main__":
    main()
