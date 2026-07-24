"""
Scores actual league_phase_knockout results against their locked
predictions_snapshot.json entries — same per-match metrics as
score_league.py (score_match reused unmodified: a knockout leg decided by
penalties is still, correctly, graded as whatever its own goal-score says,
same reasoning as snapshot_cup.py's module docstring).
"""
import json
import os
import sys

from score_league import score_match
from snapshot_cup import iter_fixtures


def score_and_save(config, base_dir):
    """Load <slug>/league_schedule.json + <slug>/knockout_fixtures.json (if
    present) + predictions_snapshot.json, score every FINISHED fixture that
    has a locked snapshot entry, and write <slug>/results_accuracy.json:
    {"matches": [...], "summary": {...}}. Fixtures without a snapshot entry
    are skipped, not fabricated -- same discipline as score_league.py."""
    from competition_config import artifact_dir
    out_dir = artifact_dir(config, base_dir)

    with open(os.path.join(out_dir, "league_schedule.json")) as f:
        league_schedule = json.load(f)
    ko_path = os.path.join(out_dir, "knockout_fixtures.json")
    knockout_fixtures = []
    if os.path.exists(ko_path):
        with open(ko_path) as f:
            knockout_fixtures = json.load(f)

    snapshot_path = os.path.join(out_dir, "predictions_snapshot.json")
    snapshot = {}
    if os.path.exists(snapshot_path):
        with open(snapshot_path) as f:
            snapshot = json.load(f)

    goals_by_key = {}
    for fx in knockout_fixtures:
        if fx["score"] is not None:
            key = f"{fx['round']}|{fx['home']}|{fx['away']}"
            goals_by_key[key] = (fx["score"][0], fx["score"][1])

    matches = []
    for key, home, away, fdate, status in iter_fixtures(league_schedule, knockout_fixtures):
        if status != "FINISHED" or key not in snapshot:
            continue
        if key in goals_by_key:
            hg, ag = goals_by_key[key]
        else:
            entry = league_schedule[key]
            hg, ag = entry["goals"][home], entry["goals"][away]
        if hg is None or ag is None:
            continue
        result = score_match(snapshot[key], hg, ag)
        matches.append({"home": home, "away": away, "date": fdate, **result})

    n = len(matches)
    summary = {
        "n_scored": n,
        "accuracy": sum(m["correct_winner"] for m in matches) / n if n else None,
        "avg_brier": sum(m["brier"] for m in matches) / n if n else None,
        "avg_log_loss": sum(m["log_loss"] for m in matches) / n if n else None,
    }

    out = {"matches": matches, "summary": summary}
    with open(os.path.join(out_dir, "results_accuracy.json"), "w") as f:
        json.dump(out, f, indent=2)
    return out


def main():
    if len(sys.argv) != 2:
        print("usage: python score_cup.py competitions/<slug>.json")
        raise SystemExit(1)
    from competition_config import load_competition
    config = load_competition(sys.argv[1])
    base_dir = os.path.dirname(os.path.abspath(__file__))
    out = score_and_save(config, base_dir)
    s = out["summary"]
    print(f"{config.name}: {s['n_scored']} matches scored")
    if s["n_scored"]:
        print(f"  accuracy={s['accuracy']:.1%}  avg_brier={s['avg_brier']:.3f}  avg_log_loss={s['avg_log_loss']:.3f}")


if __name__ == "__main__":
    main()
