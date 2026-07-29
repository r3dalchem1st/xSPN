"""
CI-style integrity gate on a knockout_only competition's
predictions_snapshot.json -- reuses validate_snapshot_league.py's
find_violations() unmodified, fed a schedule dict built from
knockout_fixtures.json alone (no league_schedule.json for this format).
"""
import json
import os
import sys

from snapshot_copa import iter_fixtures
from validate_snapshot_league import find_violations


def build_schedule_for_validation(knockout_fixtures):
    return {key: {"date": fdate} for key, _, _, fdate, _ in iter_fixtures(knockout_fixtures)}


def main():
    if len(sys.argv) != 2:
        print("usage: python validate_snapshot_copa.py competitions/<slug>.json")
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
    with open(os.path.join(out_dir, "knockout_fixtures.json")) as f:
        knockout_fixtures = json.load(f)

    schedule = build_schedule_for_validation(knockout_fixtures)
    violations = find_violations(schedule, snapshot)
    if violations:
        print(f"SNAPSHOT VALIDATION FAILED — {len(violations)} issue(s):")
        for v in violations:
            print(" -", v)
        raise SystemExit(1)
    print(f"Snapshot validation passed: {len(snapshot)} entries checked, 0 issues.")


if __name__ == "__main__":
    main()
