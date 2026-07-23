"""
CI-style integrity gate on a round-robin competition's
predictions_snapshot.json — mirrors validate_snapshot.py's WC gate. Fails
(non-zero exit) if any entry was locked after its real fixture date
(fabricated hindsight: copying a now-known result in as a fake pre-match
"prediction").
"""
import json
import os
import sys
from datetime import date


def find_violations(schedule, snapshot):
    """List of human-readable violation strings, one per snapshot entry
    whose snapped_at postdates its real fixture date. Entries with no
    matching schedule key are ignored (a stale/orphaned entry for a fixture
    that no longer exists is a separate, lower-priority concern, same as
    the WC's validate_snapshot.py leaving pre-28-Jun orphaned guesses
    alone)."""
    violations = []
    for key, entry in snapshot.items():
        sched_info = schedule.get(key)
        real_date = sched_info.get("date") if sched_info else None
        snapped_at = entry.get("snapped_at")
        if real_date and snapped_at:
            try:
                if date.fromisoformat(snapped_at) > date.fromisoformat(real_date):
                    violations.append(
                        f"{key}: snapped_at={snapped_at} is AFTER its real fixture "
                        f"date {real_date} — locked post-hoc, likely fabricated."
                    )
            except ValueError:
                pass
    return violations


def main():
    if len(sys.argv) != 2:
        print("usage: python validate_snapshot_league.py competitions/<slug>.json")
        raise SystemExit(1)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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
    with open(os.path.join(out_dir, "schedule.json")) as f:
        schedule = json.load(f)

    violations = find_violations(schedule, snapshot)
    if violations:
        print(f"SNAPSHOT VALIDATION FAILED — {len(violations)} issue(s):")
        for v in violations:
            print(" -", v)
        raise SystemExit(1)
    print(f"Snapshot validation passed: {len(snapshot)} entries checked, 0 issues.")


if __name__ == "__main__":
    main()
