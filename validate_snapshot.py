"""
Validates predictions_snapshot.json integrity right after snapshot_predictions.py
writes it. Run AFTER snapshot_predictions.py, BEFORE build_html.py — a CI gate,
like validate_data.py's gate on training data. Exits non-zero (fails the
workflow) on any violation: shipping a fabricated or mislabeled prediction is
worse than skipping a day's update.

Catches the two failure signatures actually seen live (6 Jul):
  1. Fabricated hindsight — an entry's snapped_at is AFTER its real fixture
     date. There is no legitimate pre-match prediction to lock for a match
     that's already been decided (see Belgium|Senegal, 6 Jul: fixture_due()'s
     missing lower bound let a deleted entry get silently re-locked 3 days
     after kickoff, straight from bracket_data.json's already-known result).
  2. Stale round label — a knockout entry's `group` (round) field disagrees
     with which round bracket_data.json currently lists that pairing under
     (see France|Paraguay / Belgium|USA, 6 Jul: both were locked so early,
     before the real bracket existed, that they guessed the wrong round).
"""
import json, os, sys
from datetime import date

DIR = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT_FILE = os.path.join(DIR, 'predictions_snapshot.json')
BRACKET_FILE  = os.path.join(DIR, 'bracket_data.json')
SCHEDULE_FILE = os.path.join(DIR, 'wc_schedule.json')

if not os.path.exists(SNAPSHOT_FILE):
    print("predictions_snapshot.json not found — nothing to validate.")
    raise SystemExit(0)

with open(SNAPSHOT_FILE) as f:
    snapshot = json.load(f)

schedule = {}
if os.path.exists(SCHEDULE_FILE):
    with open(SCHEDULE_FILE) as f:
        schedule = json.load(f)

bracket = {}
if os.path.exists(BRACKET_FILE):
    with open(BRACKET_FILE) as f:
        bracket = json.load(f)

# Which round bracket_data.json currently says each knockout pairing belongs to.
KO_ROUND_KEYS = [("R32", "r32"), ("R16", "r16"), ("QF", "qf"), ("SF", "sf")]
current_round = {}
for stage, key in KO_ROUND_KEYS:
    for m in bracket.get(key, []):
        current_round['|'.join(sorted([m['home'], m['away']]))] = stage
for stage, key in [("Final", "final"), ("3rd", "third_place")]:
    m = bracket.get(key)
    if m:
        current_round['|'.join(sorted([m['home'], m['away']]))] = stage

errors = []
for pair_key, entry in snapshot.items():
    sched_info = schedule.get(pair_key)
    real_date = sched_info.get('date') if sched_info else None
    snapped_at = entry.get('snapped_at')

    if real_date and snapped_at:
        try:
            if date.fromisoformat(snapped_at) > date.fromisoformat(real_date):
                errors.append(
                    f"{pair_key}: snapped_at={snapped_at} is AFTER its real fixture "
                    f"date {real_date} — locked post-hoc, likely fabricated from an "
                    f"already-known result."
                )
        except ValueError:
            pass

    grp = entry.get('group')
    if grp in ('R32', 'R16', 'QF', 'SF', 'Final', '3rd') and pair_key in current_round:
        if current_round[pair_key] != grp:
            errors.append(
                f"{pair_key}: snapshot labels this '{grp}' but bracket_data.json "
                f"currently has it under '{current_round[pair_key]}' — stale round label."
            )

if errors:
    print(f"SNAPSHOT VALIDATION FAILED — {len(errors)} issue(s):")
    for e in errors:
        print(" -", e)
    sys.exit(1)

print(f"Snapshot validation passed: {len(snapshot)} entries checked, 0 issues.")
