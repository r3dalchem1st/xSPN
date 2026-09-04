"""
Scores shadow_predictions.json's two parallel prediction columns
("baseline" = odds_weight=0.0, "odds_fit" = the real config.odds_fit_weight
-- see shadow_fit_odds.py) against real, now-known results in schedule.json,
reporting accuracy/Brier/log-loss for each side. Run this any time to check
progress; the user asked to sandbox the odds-fit term for about 2 weeks
against real upcoming fixtures before deciding whether to promote it into
production -- this is how that decision gets made, on real evidence.

Usage: python score_shadow.py competitions/<slug>.json
"""
import json
import math
import os
import sys

EPS = 1e-12


def _score_column(shadow, schedule, column):
    n = correct = 0
    brier_sum = logloss_sum = 0.0
    for key, entry in shadow.items():
        sched_entry = schedule.get(key)
        if not sched_entry or sched_entry["status"] != "FINISHED":
            continue
        home, away = entry["home"], entry["away"]
        hg, ag = sched_entry["goals"][home], sched_entry["goals"][away]
        oi = 0 if hg > ag else (2 if hg < ag else 1)
        pred = entry[column]
        triple = (pred["ph"], pred["pd"], pred["pa"])
        o = (1, 0, 0) if oi == 0 else ((0, 1, 0) if oi == 1 else (0, 0, 1))
        if triple.index(max(triple)) == oi:
            correct += 1
        brier_sum += sum((triple[k] - o[k]) ** 2 for k in range(3))
        logloss_sum += -math.log(max(triple[oi], EPS))
        n += 1
    return {
        "n": n,
        "accuracy": correct / n if n else None,
        "brier": brier_sum / n if n else None,
        "logloss": logloss_sum / n if n else None,
    }


def score_shadow_predictions(base_dir, slug):
    """Returns (baseline_scores, odds_fit_scores) dicts -- {n, accuracy,
    brier, logloss} -- for every shadow-locked fixture whose real result is
    now known (schedule.json status FINISHED). A fixture not yet played is
    simply excluded, not an error."""
    out_dir = os.path.join(base_dir, "competitions", slug)
    shadow_path = os.path.join(out_dir, "shadow_predictions.json")
    shadow = json.load(open(shadow_path)) if os.path.exists(shadow_path) else {}
    schedule_path = os.path.join(out_dir, "schedule.json")
    schedule = json.load(open(schedule_path)) if os.path.exists(schedule_path) else {}
    return _score_column(shadow, schedule, "baseline"), _score_column(shadow, schedule, "odds_fit")


def main():
    if len(sys.argv) != 2:
        print("usage: python score_shadow.py competitions/<slug>.json")
        raise SystemExit(1)
    from competition_config import load_competition
    config = load_competition(sys.argv[1])
    base_dir = os.path.dirname(os.path.abspath(__file__))

    baseline, odds_fit = score_shadow_predictions(base_dir, config.slug)
    print(f"{config.name}: {baseline['n']} shadow prediction(s) graded so far "
          f"(real results now known).\n")
    if not baseline["n"]:
        print("Nothing graded yet -- check back once some locked shadow fixtures have been played.")
        return
    print(f"{'':>10} {'n':>4} {'accuracy':>9} {'brier':>7} {'logloss':>8}")
    print(f"{'baseline':>10} {baseline['n']:4d} {baseline['accuracy']:9.3f} "
          f"{baseline['brier']:7.4f} {baseline['logloss']:8.4f}")
    print(f"{'odds_fit':>10} {odds_fit['n']:4d} {odds_fit['accuracy']:9.3f} "
          f"{odds_fit['brier']:7.4f} {odds_fit['logloss']:8.4f}")


if __name__ == "__main__":
    main()
