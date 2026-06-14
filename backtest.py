"""
Out-of-sample backtest / calibration check.

The training set begins at the 2022 World Cup, so the only honest temporal
holdout is a later tournament. We train on every match before Euro 2024
(2024-06-14) and score the model's probabilistic predictions on the Euro 2024
and Copa America 2024 matches it never saw.

Reports argmax accuracy, multiclass Brier score, and log-loss against simple
baselines. Standalone diagnostic — NOT part of the daily GitHub Actions pipeline.

Caveats: test matches were played at host venues (Germany / USA) but are scored
as neutral, matching how the WC simulator predicts neutral games; 2025 squad
values are used as a fixed prior.

Usage:  python backtest.py
"""
import sys, os, json, math
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CUTOFF = "2024-06-14"                       # Euro 2024 kickoff
TEST_TOURNAMENTS = {"Euro", "Copa America"}

import fit_improved as fi
# Compute recency weights as-of the cutoff (not today) so the fit reflects only
# what was knowable at prediction time. fit_improved's internals call days_ago()
# by bare name, so patching the module attribute reroutes them.
_orig_days_ago = fi.days_ago
fi.days_ago = lambda ds, ref=CUTOFF: _orig_days_ago(ds, ref)

from match_data import MATCHES
from model_common import eff_params, LAMBDA_MIN, LAMBDA_MAX

TRAIN = [m for m in MATCHES if m[0] <  CUTOFF]
TEST  = [m for m in MATCHES if m[0] >= CUTOFF and m[5] in TEST_TOURNAMENTS]
print(f"Training on {len(TRAIN)} matches (< {CUTOFF}); "
      f"testing on {len(TEST)} Euro/Copa 2024 matches.\n")

elo = fi.compute_elos_improved(TRAIN)
dc  = fi.fit_dc_fast(TRAIN, elo)
ATK, DEF, RHO = dc["attack"], dc["defense"], dc["rho"]
AVG_ATK = float(np.mean(list(ATK.values())))
AVG_DEF = float(np.mean(list(DEF.values())))
AVG_ELO = float(np.mean(list(elo.values())))


def hda_probs(home, away, max_g=10):
    """P(home win), P(draw), P(away win) under Dixon-Coles, neutral venue."""
    a_h, d_h = eff_params(home, ATK, DEF, AVG_ATK, AVG_DEF, elo, AVG_ELO)
    a_a, d_a = eff_params(away, ATK, DEF, AVG_ATK, AVG_DEF, elo, AVG_ELO)
    lam = min(max(math.exp(a_h + d_a), LAMBDA_MIN), LAMBDA_MAX)
    mu  = min(max(math.exp(a_a + d_h), LAMBDA_MIN), LAMBDA_MAX)
    ph = pd = pa = 0.0
    for h in range(max_g + 1):
        p_h = math.exp(-lam) * lam**h / math.factorial(h)
        for a in range(max_g + 1):
            p = p_h * (math.exp(-mu) * mu**a / math.factorial(a))
            if   h == 0 and a == 0: p *= 1 - lam*mu*RHO
            elif h == 0 and a == 1: p *= 1 + lam*RHO
            elif h == 1 and a == 0: p *= 1 + mu*RHO
            elif h == 1 and a == 1: p *= 1 - RHO
            if   h > a: ph += p
            elif h < a: pa += p
            else:       pd += p
    s = ph + pd + pa
    return ph/s, pd/s, pa/s


EPS = 1e-12
n = correct = 0
brier = logloss = 0.0
elo_correct = ndec = 0          # Elo baseline on decisive games only
skipped = 0

for date, home, away, hs, as_, tour, neutral in TEST:
    if home not in ATK or away not in ATK:   # team unseen in training
        skipped += 1
        continue
    pred = hda_probs(home, away)
    if   hs > as_: o, oi = (1, 0, 0), 0
    elif hs < as_: o, oi = (0, 0, 1), 2
    else:          o, oi = (0, 1, 0), 1

    if pred.index(max(pred)) == oi:
        correct += 1
    brier   += sum((pred[k] - o[k])**2 for k in range(3))
    logloss += -math.log(max(pred[oi], EPS))
    if hs != as_:
        fav = home if elo.get(home, 1500) >= elo.get(away, 1500) else away
        win = home if hs > as_ else away
        elo_correct += (fav == win)
        ndec += 1
    n += 1

summary = {
    "cutoff": CUTOFF,
    "train_matches": len(TRAIN),
    "test_matches_scored": n,
    "test_matches_skipped_unseen_team": skipped,
    "accuracy": round(correct / n, 4),
    "brier": round(brier / n, 4),
    "logloss": round(logloss / n, 4),
    "elo_baseline_accuracy_decisive": round(elo_correct / ndec, 4) if ndec else None,
    "random_brier": 0.667,
    "random_logloss": round(math.log(3), 4),
}

print(f"Scored {n} matches ({skipped} skipped: team unseen in training)\n")
print(f"  Model accuracy (argmax HDA correct) : {summary['accuracy']:.1%}")
print(f"  Elo-favourite accuracy (decisive)   : "
      f"{summary['elo_baseline_accuracy_decisive']:.1%}  (n={ndec})")
print(f"  Multiclass Brier (lower=better)     : {summary['brier']:.3f}   "
      f"[random {summary['random_brier']}]")
print(f"  Log-loss (lower=better)             : {summary['logloss']:.3f}   "
      f"[random {summary['random_logloss']}]")

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "backtest_results.json"), "w") as f:
    json.dump(summary, f, indent=2)
print("\nSaved: backtest_results.json")

# Quality gate: fail CI if the model is no better than a random baseline — a
# signal that a code change broke the model. Threshold is intentionally loose
# (catastrophic-regression guard, not a tight calibration target).
GATE = float(os.environ.get("BACKTEST_MAX_BRIER", "0.667"))
if summary["brier"] >= GATE:
    print(f"QUALITY GATE FAILED: Brier {summary['brier']} >= {GATE} "
          f"(no better than random) — likely a model regression.")
    sys.exit(1)
print(f"Quality gate passed: Brier {summary['brier']} < {GATE}.")
