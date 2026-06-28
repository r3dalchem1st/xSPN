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
SCHEDULE_FILE = os.path.join(DIR, 'wc_schedule.json')
LOCK_WINDOW_DAYS = 2   # lock a group match only once its real fixture is this close

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

schedule = {}
if os.path.exists(SCHEDULE_FILE):
    with open(SCHEDULE_FILE) as f:
        schedule = json.load(f)

added = 0
today_d = date.today()
today = today_d.isoformat()

def fixture_due(home, away):
    """Lock a match only once its real fixture date is within LOCK_WINDOW_DAYS.
    Unknown date → don't lock (locking weeks early with a stale model is worse
    than briefly risking a miss; the date always arrives before the match)."""
    info = schedule.get('|'.join(sorted([home, away])))
    d = info.get('date') if info else None
    if not d:
        return False
    try:
        return (date.fromisoformat(d) - today_d).days <= LOCK_WINDOW_DAYS
    except ValueError:
        return False

def lock(m, stage, winner):
    """Lock one match prediction by sorted team pair (append-only)."""
    global added
    if m.get("ph") is None:          # TBD / not-yet-resolved slot — nothing to score
        return
    key = '|'.join(sorted([m['home'], m['away']]))
    if key not in snapshot:
        snapshot[key] = {
            "home": m["home"], "away": m["away"], "group": stage,
            "predicted_score": m["score"], "predicted_winner": winner,
            "ph": m["ph"], "pd": m["pd"], "pa": m["pa"],
            "lam": m.get("lam"), "mu": m.get("mu"), "snapped_at": today,
        }
        added += 1

# Group stage (regulation H/D/A; predicted_winner is the regulation favourite)
for grp, matches in bracket['group_predictions'].items():
    for m in matches:
        if not fixture_due(m['home'], m['away']):
            continue
        lock(m, grp, m.get("likely_winner") or m.get("winner"))

# Knockout rounds — same date gate as group matches so predictions aren't locked
# weeks before the fixture with a stale model. Only pairings within LOCK_WINDOW_DAYS
# of their real date (from wc_schedule) get a snapshot; others wait until closer.
for stage, key in [("R32","r32"),("R16","r16"),("QF","qf"),("SF","sf")]:
    for m in bracket.get(key, []):
        if fixture_due(m['home'], m['away']):
            lock(m, stage, m.get("reg_winner"))
for stage, key in [("Final","final"),("3rd","third_place")]:
    m = bracket.get(key)
    if m and fixture_due(m['home'], m['away']):
        lock(m, stage, m.get("reg_winner"))

with open(SNAPSHOT_FILE, 'w') as f:
    json.dump(snapshot, f, indent=2)
if added > 5:
    print(f"WARNING: {added} new predictions locked in one run — verify this is expected.")
print(f"Snapshot: {added} new predictions locked ({len(snapshot)} total).")
