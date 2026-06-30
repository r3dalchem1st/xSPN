"""
Compare actual WC results to pre-match predictions.
Reads:  predictions_snapshot.json + fetched_matches.json
Writes: results_accuracy.json
Regenerates from scratch each run (idempotent).
"""
import json, os, math, re, sys
from datetime import date as _date
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model_common import likely_score, DRAW_INFLATE, STRENGTH_SHRINK, HOST_ADV_FRACTION

DIR = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT_FILE  = os.path.join(DIR, 'predictions_snapshot.json')
FETCHED_FILE   = os.path.join(DIR, 'fetched_matches.json')
ACCURACY_FILE  = os.path.join(DIR, 'results_accuracy.json')
HISTORY_FILE   = os.path.join(DIR, 'accuracy_history.json')
SCHEDULE_FILE  = os.path.join(DIR, 'wc_schedule.json')

EMPTY_SUMMARY = {"total_matches": 0, "correct_winners": 0,
                 "accuracy": 0, "avg_goal_error": 0, "avg_brier": 0,
                 "avg_logloss": 0, "reliability": [],
                 "predicted_draw_rate": 0, "actual_draw_rate": 0, "ece": 0}

# Reliability bins: model confidence in its most-likely outcome vs how often it
# actually happened. A well-calibrated model's "predicted" ≈ "actual" per bin.
REL_BINS = [(0.34, 0.45), (0.45, 0.55), (0.55, 0.65), (0.65, 0.75), (0.75, 1.01)]
REL_LABELS = ["34–45%", "45–55%", "55–65%", "65–75%", "75%+"]

def reliability(calib):
    """calib: list of (confidence, hit_bool). Returns per-bin predicted/actual/n."""
    out = []
    for (lo, hi), label in zip(REL_BINS, REL_LABELS):
        pts = [(c, h) for c, h in calib if lo <= c < hi]
        if pts:
            out.append({"bin": label, "n": len(pts),
                        "predicted": round(sum(c for c, _ in pts) / len(pts), 3),
                        "actual": round(sum(1 for _, h in pts if h) / len(pts), 3)})
    return out

def brier(ph, pd, pa, outcome):
    """Brier score for 3-outcome prediction. outcome: 'H', 'D', or 'A'."""
    oh, od, oa = (1,0,0) if outcome=='H' else ((0,1,0) if outcome=='D' else (0,0,1))
    return (ph-oh)**2 + (pd-od)**2 + (pa-oa)**2

def save(scored, summary):
    with open(ACCURACY_FILE, 'w') as f:
        json.dump({"matches": scored, "summary": summary}, f, indent=2)
    print(f"Saved: {ACCURACY_FILE}")

if not os.path.exists(SNAPSHOT_FILE) or not os.path.exists(FETCHED_FILE):
    print("Missing snapshot or fetched data — writing empty results.")
    save([], EMPTY_SUMMARY)
    raise SystemExit(0)

with open(SNAPSHOT_FILE) as f:
    snapshot = json.load(f)
with open(FETCHED_FILE) as f:
    fetched = json.load(f)
schedule = json.load(open(SCHEDULE_FILE)) if os.path.exists(SCHEDULE_FILE) else {}

scored = []
for match in fetched:
    date_, home, away, hg, ag, tournament, neutral = match
    if 'World Cup' not in tournament:
        continue

    key = '|'.join(sorted([home, away]))
    if key not in snapshot:
        continue

    pred = snapshot[key]

    # Resolve goals by team name — robust to API home/away ordering
    goals = {home: hg, away: ag}
    pred_home_goals = goals[pred['home']]
    pred_away_goals = goals[pred['away']]

    if pred_home_goals > pred_away_goals:   actual_outcome = 'H'
    elif pred_home_goals < pred_away_goals: actual_outcome = 'A'
    else:                                   actual_outcome = 'D'

    pw = pred.get('predicted_winner', '')
    if pw == pred['home']:   pred_outcome = 'H'
    elif pw == pred['away']: pred_outcome = 'A'
    else:                    pred_outcome = 'D'

    # ph/pd/pa were locked in SNAPSHOT orientation (home = pred['home']), and
    # actual_outcome is computed in that same orientation (goals are resolved by
    # team name). The API's home/away ordering is irrelevant here, so NO swap — a
    # swap would mis-assign P(home)/P(away) and corrupt Brier/log-loss/reliability.
    ph, pd_val, pa = pred['ph'], pred['pd'], pred['pa']

    # Use the LOCKED scoreline verbatim — a pre-match prediction must stay frozen.
    # ONE exception: a few group snapshots locked before the score↔winner consistency
    # fix carry a draw scoreline (e.g. "0–0") next to a decisive winner. Only those
    # genuine contradictions are recomputed from the locked lam/mu to be consistent;
    # every consistent snapshot (and KO "x–x (p)") is left exactly as locked.
    predicted_score = pred['predicted_score']
    nums = re.findall(r'\d+', predicted_score)       # robust to "1–1 (p)" etc.
    is_group = bool(re.fullmatch(r'[A-L]', pred.get('group', '')))
    lam, mu = pred.get('lam'), pred.get('mu')
    if len(nums) < 2 and not (is_group and lam is not None and mu is not None):
        # Malformed locked score and no lam/mu to recompute from — skip rather than
        # invent a 0–0 and score goal error against a fabricated draw.
        print(f"  skip {pred['home']} vs {pred['away']}: unparseable predicted_score {predicted_score!r}")
        continue
    pred_hg = int(nums[0]) if len(nums) >= 2 else 0
    pred_ag = int(nums[1]) if len(nums) >= 2 else 0
    stored_oc = 'H' if pred_hg > pred_ag else ('A' if pred_hg < pred_ag else 'D')
    if is_group and lam is not None and mu is not None and stored_oc != pred_outcome:
        pred_hg, pred_ag = likely_score(lam, mu, allowed={pred_outcome}, group=True)
        predicted_score = f"{pred_hg}–{pred_ag}"

    home_err = abs(pred_home_goals - pred_hg)
    away_err = abs(pred_away_goals - pred_ag)

    sched_key = '|'.join(sorted([home, away]))
    pen_w = (schedule.get(sched_key) or {}).get('pen_winner')
    is_ko = not re.match(r'^[A-L]$', pred.get('group', ''))
    if actual_outcome == 'H':         actual_winner = pred['home']
    elif actual_outcome == 'A':       actual_winner = pred['away']
    elif is_ko and pen_w:             actual_winner = pen_w
    else:                             actual_winner = 'Draw'

    # Log-loss + calibration use the model's probability for the ACTUAL outcome
    probs = {'H': ph, 'D': pd_val, 'A': pa}
    p_actual = probs[actual_outcome]
    logloss = -math.log(max(p_actual, 1e-12))
    pred_argmax = max(probs, key=probs.get)          # most-likely outcome
    confidence = probs[pred_argmax]

    scored.append({
        "date": date_,
        "home": pred['home'],
        "away": pred['away'],
        "group": pred.get("group", ""),
        "predicted_score": predicted_score,
        "actual_score": f"{pred_home_goals}\u2013{pred_away_goals}",
        "predicted_winner": pw,
        # Locked pre-match H/D/A (snapshot orientation: home=pred['home']) so the
        # All-104 tab can freeze a played match's odds instead of re-predicting it.
        "ph": pred['ph'], "pd": pred['pd'], "pa": pred['pa'],
        "actual_winner": actual_winner,
        "actual_outcome": actual_outcome,
        # KO stage: correct = model backed the team that actually advanced.
        # Group stage: correct = model got the 90-min H/D/A right.
        "correct_winner": bool(pw == actual_winner) if (is_ko and actual_winner != 'Draw') else bool(actual_outcome == pred_outcome),
        "home_error": home_err,
        "away_error": away_err,
        "total_goal_error": home_err + away_err,
        "brier": round(brier(ph, pd_val, pa, actual_outcome), 4),
        "logloss": round(logloss, 4),
        "_conf": confidence,                          # internal, for reliability
        "_hit": bool(pred_argmax == actual_outcome),
    })

scored.sort(key=lambda x: x["date"])
n = len(scored)

if n:
    correct = sum(1 for m in scored if m["correct_winner"])
    calib = [(m.pop("_conf"), m.pop("_hit")) for m in scored]
    summary = {
        "total_matches": n,
        "correct_winners": correct,
        "accuracy": round(correct / n, 4),
        "avg_goal_error": round(sum(m["total_goal_error"] for m in scored) / n, 3),
        "avg_brier": round(sum(m["brier"] for m in scored) / n, 4),
        "avg_logloss": round(sum(m["logloss"] for m in scored) / n, 4),
        "reliability": reliability(calib),
    }
    summary["predicted_draw_rate"] = round(sum(m["pd"] for m in scored) / n, 4)
    summary["actual_draw_rate"]    = round(sum(1 for m in scored if m["actual_outcome"] == "D") / n, 4)
    # ECE = bin-count-weighted mean |predicted-actual|; divide by the BINNED count,
    # not n, so near-tie matches (confidence < the lowest bin edge) don't bias it low.
    _binned = sum(b["n"] for b in summary["reliability"])
    summary["ece"] = round(
        sum(b["n"] * abs(b["predicted"] - b["actual"]) for b in summary["reliability"]) / _binned, 4
    ) if _binned else 0.0
    print(f"Scored {n} matches: {correct}/{n} correct ({correct/n:.1%}), "
          f"avg goal error {summary['avg_goal_error']:.2f}, "
          f"avg Brier {summary['avg_brier']:.4f}, "
          f"avg log-loss {summary['avg_logloss']:.4f}")
else:
    print("No WC matches scored yet.")
    summary = EMPTY_SUMMARY

for m in scored:                       # drop any leftover internal keys
    m.pop("_conf", None); m.pop("_hit", None)
save(scored, summary)

# Append summary to accuracy_history.json (date-keyed, never overwrites past entries).
# Lets you compare metrics before/after parameter changes without relying on git diff.
if n:
    history = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE) as f:
                history = json.load(f)
        except (json.JSONDecodeError, ValueError):
            pass
    history[_date.today().isoformat()] = {
        **summary,
        "params": {
            "DRAW_INFLATE":      DRAW_INFLATE,
            "STRENGTH_SHRINK":   STRENGTH_SHRINK,
            "HOST_ADV_FRACTION": HOST_ADV_FRACTION,
        },
    }
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=2)
    print(f"History: {HISTORY_FILE} updated ({len(history)} entries)")
