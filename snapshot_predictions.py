"""
Snapshot pre-match predictions before matches are played, so accuracy can
later be scored against a genuinely pre-kickoff call instead of today's model.
Run AFTER fetch_matches.py — needs today's wc_schedule.json.

Group stage: locked per-match once its real fixture is within
LOCK_WINDOW_DAYS (fixture_due()). Knockout rounds: locked a whole round at a
time, the moment every match of the PRECEDING round is FINISHED
(round_resolved()) — see that function's docstring for why this replaced the
old per-match date gate for KO stages.

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
    """Lock a match only once its real fixture date is within LOCK_WINDOW_DAYS
    (and not already in the past — a fixture whose date has already passed has
    no genuine pre-match prediction left to capture; locking it would just copy
    the now-known actual result out of bracket_data.json as a fabricated
    "prediction". Concretely hit this 6 Jul: Belgium|Senegal's snapshot entry
    was deliberately removed on 4 Jul since no legitimate pre-kickoff lock for
    it ever existed, but the missing lower bound here let a later run silently
    re-lock it 3 days after the match with the real 3-2 score baked in).
    Unknown date → don't lock (locking weeks early with a stale model is worse
    than briefly risking a miss; the date always arrives before the match).
    TBD bracket slots (ph=None) are separately guarded in lock() and never
    locked regardless of what this function returns."""
    info = schedule.get('|'.join(sorted([home, away])))
    d = info.get('date') if info else None
    if not d:
        return False
    try:
        days_until = (date.fromisoformat(d) - today_d).days
        return 0 <= days_until <= LOCK_WINDOW_DAYS
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

def finished(home, away):
    info = schedule.get('|'.join(sorted([home, away])))
    return bool(info) and info.get('status') == 'FINISHED'

def round_resolved(prev_pairs):
    """A round is lockable once every match of the PRECEDING round has an
    actual FINISHED result. Knockout rounds never overlap — R16 can't kick
    off until every R32 match (including 3rd-place tiebreakers) is decided —
    so this is a hard guarantee, not a heuristic, and it needs no fixed
    calendar date at all. Replaces the old per-match LOCK_WINDOW_DAYS check
    for KO stages (6 Jul): that per-match date logic was the root cause of
    every recent snapshot bug (locked-before-bracket-known guesses that stuck
    once they happened to match reality, the missing lower-bound that let a
    deleted entry get refabricated, orientation drift) because it treated
    each match's real date as it trickled into wc_schedule.json instead of
    gating on the one fact that actually matters: is the previous round over.
    Locking every match of a round at once also means they're all scored
    against the same day's model, instead of drifting apart if one match's
    fixture_due() window opened days before another's."""
    return all(finished(h, a) for h, a in prev_pairs)

group_pairs = [(m['home'], m['away']) for ms in bracket['group_predictions'].values() for m in ms]
r32_pairs   = [(m['home'], m['away']) for m in bracket.get('r32', [])]
r16_pairs   = [(m['home'], m['away']) for m in bracket.get('r16', [])]
qf_pairs    = [(m['home'], m['away']) for m in bracket.get('qf', [])]
sf_pairs    = [(m['home'], m['away']) for m in bracket.get('sf', [])]

for stage, key, prev_pairs in [("R32", "r32", group_pairs), ("R16", "r16", r32_pairs),
                                ("QF", "qf", r16_pairs), ("SF", "sf", qf_pairs)]:
    if not round_resolved(prev_pairs):
        continue
    for m in bracket.get(key, []):
        # round_resolved() only guards against locking too EARLY. On its own
        # it doesn't guard against locking too LATE: this loop reruns every
        # pipeline run forever, and once a round is resolved it stays resolved
        # — so any match still missing from the snapshot for *any* reason
        # (a bug, a deliberate deletion, a missed run) would otherwise get
        # backfilled from bracket_data.json's current state, which for an
        # already-decided match IS the real result. Skipping already-FINISHED
        # matches here is what actually prevents that fabrication (hit live,
        # 6 Jul: Belgium|Senegal came back a *second* time under this new
        # round-based logic during testing, for exactly this reason).
        if finished(m['home'], m['away']):
            continue
        lock(m, stage, m.get("reg_winner"))

if round_resolved(sf_pairs):
    for stage, key in [("Final", "final"), ("3rd", "third_place")]:
        m = bracket.get(key)
        if m and not finished(m['home'], m['away']):
            lock(m, stage, m.get("reg_winner"))

with open(SNAPSHOT_FILE, 'w') as f:
    json.dump(snapshot, f, indent=2)
if added > 10:
    print(f"WARNING: {added} new predictions locked in one run — verify this is expected.")
print(f"Snapshot: {added} new predictions locked ({len(snapshot)} total).")
