"""
CI-style integrity gate on a league_phase_knockout competition's
predictions_snapshot.json — reuses validate_snapshot_league.py's
find_violations() unmodified (it's already schedule-shape-agnostic: just
{key: {"date": ...}}), fed a schedule dict merged from both
league_schedule.json and knockout_fixtures.json.
"""
import json
import os
import sys

from snapshot_cup import iter_fixtures
from validate_snapshot_league import find_violations


def build_combined_schedule(league_schedule, knockout_fixtures):
    return {key: {"date": fdate} for key, _, _, fdate, _
            in iter_fixtures(league_schedule, knockout_fixtures)}


def main():
    if len(sys.argv) != 2:
        print("usage: python validate_snapshot_cup.py competitions/<slug>.json")
        raise SystemExit(1)
    from competition_config import artifact_dir, load_competition
    config = load_competition(sys.argv[1])
    base_dir = os.path.dirname(os.path.abspath(__file__))
    out_dir = artifact_dir(config, base_dir)

    snapshot_path = os.path.join(out_dir, "predictions_snapshot.json")
    if not os.path.exists(snapshot_path):
        print(f"{snapshot_path} not found — nothing to validate.")
        return
    with open(snapshot_path) as f:
        snapshot = json.load(f)
    with open(os.path.join(out_dir, "league_schedule.json")) as f:
        league_schedule = json.load(f)
    ko_path = os.path.join(out_dir, "knockout_fixtures.json")
    knockout_fixtures = []
    if os.path.exists(ko_path):
        with open(ko_path) as f:
            knockout_fixtures = json.load(f)

    schedule = build_combined_schedule(league_schedule, knockout_fixtures)
    violations = find_violations(schedule, snapshot)
    if violations:
        print(f"SNAPSHOT VALIDATION FAILED — {len(violations)} issue(s):")
        for v in violations:
            print(" -", v)
        raise SystemExit(1)
    print(f"Snapshot validation passed: {len(snapshot)} entries checked, 0 issues.")


if __name__ == "__main__":
    main()
