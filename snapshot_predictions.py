"""
Snapshot current group stage predictions before matches are played.
Run BEFORE fetch_matches.py — predictions are locked in once saved.
Keys by sorted team pair so API home/away reversal doesn't break matching.
"""
import json, os
from datetime import date

DIR = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT_FILE = os.path.join(DIR, 'predictions_snapshot.json')
BRACKET_FILE  = os.path.join(DIR, 'bracket_data.json')

if not os.path.exists(BRACKET_FILE):
    print("bracket_data.json not found — skipping snapshot.")
    raise SystemExit(0)

if os.path.exists(SNAPSHOT_FILE):
    with open(SNAPSHOT_FILE) as f:
        snapshot = json.load(f)
else:
    snapshot = {}

with open(BRACKET_FILE) as f:
    bracket = json.load(f)

added = 0
today = date.today().isoformat()
for grp, matches in bracket['group_predictions'].items():
    for m in matches:
        # Sort alphabetically so key matches regardless of home/away API ordering
        key = '|'.join(sorted([m['home'], m['away']]))
        if key not in snapshot:
            snapshot[key] = {
                "home": m["home"],
                "away": m["away"],
                "group": grp,
                "predicted_score": m["score"],
                "predicted_winner": m.get("likely_winner") or m.get("winner"),
                "ph": m["ph"], "pd": m["pd"], "pa": m["pa"],
                "lam": m["lam"], "mu": m["mu"],
                "snapped_at": today,
            }
            added += 1

with open(SNAPSHOT_FILE, 'w') as f:
    json.dump(snapshot, f, indent=2)
print(f"Snapshot: {added} new predictions locked ({len(snapshot)} total).")
