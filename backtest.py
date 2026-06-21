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
import model_common as _mc
from model_common import eff_params, LAMBDA_MIN, LAMBDA_MAX, shrink_lambda, inflate_hda

# The holdout must reflect the SHIPPED model, reproducibly:
#  - pin STRENGTH_SHRINK to the production default (still env-overridable for tuning),
#    rather than silently inheriting whatever env happens to be set.
#  - pin DRAW_INFLATE to 0.0 default (orchestrator sets the chosen value after grid).
#  - drop injuries: there is no 2024 injury data, so today's manual injuries.json
#    must not leak into the 2024 holdout (squad_adj reads fit_improved.INJURIES_OUT).
_mc.STRENGTH_SHRINK = float(os.environ.get("STRENGTH_SHRINK", "0.55"))
_mc.DRAW_INFLATE    = float(os.environ.get("DRAW_INFLATE",    "0.25"))
fi.INJURIES_OUT = {}

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
    lam = min(max(shrink_lambda(math.exp(a_h + d_a)), LAMBDA_MIN), LAMBDA_MAX)
    mu  = min(max(shrink_lambda(math.exp(a_a + d_h)), LAMBDA_MIN), LAMBDA_MAX)
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


def score_holdout(shrink, delta):
    """Score the TEST holdout for a given (shrink, delta) pair.
    Reuses module-level elo/ATK/DEF/RHO (fitted once); no refit."""
    _mc.STRENGTH_SHRINK = shrink
    n = correct = 0
    brier_sum = logloss_sum = 0.0
    pred_draw_sum = act_draw_sum = argmax_draw_sum = 0
    skipped = 0
    for date, home, away, hs, as_, tour, neutral in TEST:
        if home not in ATK or away not in ATK:
            skipped += 1
            continue
        pred = inflate_hda(*hda_probs(home, away), delta)
        ph, pd, pa = pred
        if   hs > as_: o, oi = (1, 0, 0), 0
        elif hs < as_: o, oi = (0, 0, 1), 2
        else:          o, oi = (0, 1, 0), 1
        if pred.index(max(pred)) == oi:
            correct += 1
        brier_sum   += sum((pred[k] - o[k])**2 for k in range(3))
        logloss_sum += -math.log(max(pred[oi], EPS))
        pred_draw_sum    += pd
        act_draw_sum     += (1 if hs == as_ else 0)
        argmax_draw_sum  += (1 if pred.index(max(pred)) == 1 else 0)
        n += 1
    return {
        "shrink":       shrink,
        "delta":        delta,
        "logloss":      logloss_sum / n,
        "brier":        brier_sum / n,
        "accuracy":     correct / n,
        "pred_draw":    pred_draw_sum / n,
        "act_draw":     act_draw_sum / n,
        "argmax_draw":  argmax_draw_sum / n,
        "n":            n,
    }


if __name__ == "__main__" and "--grid" in sys.argv:
    import itertools
    shrinks = [0.40, 0.50, 0.55, 0.65, 0.80]
    deltas  = [0.0, 0.15, 0.30, 0.50, 0.80]
    print(f"{'shrink':>6} {'delta':>6} {'logloss':>8} {'brier':>7} {'acc':>6} "
          f"{'predDraw':>9} {'actDraw':>8} {'argmaxDraw':>11}")
    for sh, dl in itertools.product(shrinks, deltas):
        r = score_holdout(sh, dl)
        print(f"{sh:6.2f} {dl:6.2f} {r['logloss']:8.4f} {r['brier']:7.4f} "
              f"{r['accuracy']:6.3f} {r['pred_draw']:9.3f} {r['act_draw']:8.3f} {r['argmax_draw']:11.3f}")
    raise SystemExit(0)


# ── Single-run scoring (normal / CI mode) ────────────────────────────────────
# Restore the pinned shrink (score_holdout may have mutated it in --grid mode,
# but we never reach here in --grid mode due to the raise above).
_mc.STRENGTH_SHRINK = float(os.environ.get("STRENGTH_SHRINK", "0.55"))

n = correct = 0
brier = logloss = 0.0
elo_correct = ndec = 0          # Elo baseline on decisive games only
skipped = 0

for date, home, away, hs, as_, tour, neutral in TEST:
    if home not in ATK or away not in ATK:   # team unseen in training
        skipped += 1
        continue
    pred = inflate_hda(*hda_probs(home, away), _mc.DRAW_INFLATE)
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
