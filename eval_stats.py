"""
Statistics for judging forecasts honestly: per-match scoring rules, paired
bootstrap confidence intervals, skill scores against a baseline, and a power
calculation. Pure numpy, no I/O -- shared by rolling_backtest.py (model
experiments), validate_sim.py and score_league.py (the site's skill numbers).

Why this exists: every model decision so far was made on a single ~300-match
holdout, or on a few dozen live matches, by eyeballing two numbers. The per-
match Brier SD is about 0.06, so detecting a 0.01 improvement needs ~280
matches (required_n) -- a whole season per league. A difference nobody has put
an interval on is a rumour, not a result.

Convention throughout: LOSSES (lower is better) and IMPROVEMENT = baseline
loss minus candidate loss, so positive always means the candidate is better.
"""
import math

import numpy as np
from scipy.stats import norm

EPS = 1e-12
_CHUNK = 200  # bootstrap replicates per chunk, bounding memory for ~10k-match samples


def brier_losses(P, outcomes):
    """Per-match multi-class Brier score. P is (n,3) of H/D/A probabilities,
    outcomes an int array (0=H, 1=D, 2=A). Range 0 (perfect) to 2."""
    P = np.asarray(P, float)
    onehot = np.eye(3)[np.asarray(outcomes, int)]
    return ((P - onehot) ** 2).sum(axis=1)


def logloss_losses(P, outcomes):
    P = np.asarray(P, float)
    p = P[np.arange(len(P)), np.asarray(outcomes, int)]
    return -np.log(np.maximum(p, EPS))


def correct_flags(P, outcomes):
    return np.asarray(P, float).argmax(axis=1) == np.asarray(outcomes, int)


def base_rate_probs(outcomes):
    """The naive "always forecast the historical H/D/A frequencies" forecast --
    the honest baseline for skill (the uniform 1/3 forecast flatters a model
    in leagues where home wins are ~45% of results)."""
    o = np.asarray(outcomes, int)
    return [float((o == k).mean()) for k in range(3)]


def _boot_means(values, clusters, n_boot, seed):
    """Bootstrap replicate means of `values`, resampling matches (clusters=None)
    or whole clusters (e.g. league-seasons) with replacement."""
    rng = np.random.default_rng(seed)
    v = np.asarray(values, float)
    if clusters is None:
        n = len(v)
        out = np.empty(n_boot)
        for start in range(0, n_boot, _CHUNK):
            k = min(_CHUNK, n_boot - start)
            out[start:start + k] = v[rng.integers(0, n, size=(k, n))].mean(axis=1)
        return out
    labels = np.asarray(clusters)
    uniq, inv = np.unique(labels, return_inverse=True)
    sums = np.bincount(inv, weights=v, minlength=len(uniq))
    counts = np.bincount(inv, minlength=len(uniq)).astype(float)
    idx = rng.integers(0, len(uniq), size=(n_boot, len(uniq)))
    return sums[idx].sum(axis=1) / counts[idx].sum(axis=1)


def improvement(candidate_losses, baseline_losses, clusters=None, n_boot=5000, seed=0, alpha=0.05):
    """Paired improvement of a candidate over a baseline on the SAME matches:
    mean(baseline - candidate) with a (1-alpha) bootstrap interval. Pass
    `clusters` (one label per match, e.g. "league|season") to resample whole
    clusters instead of individual matches -- the conservative choice when
    matches within a cluster share a common shock. frac_better is the share of
    matches where the candidate scored strictly lower."""
    d = np.asarray(baseline_losses, float) - np.asarray(candidate_losses, float)
    means = _boot_means(d, clusters, n_boot, seed)
    return {"n": int(len(d)), "mean": float(d.mean()),
            "lo": float(np.quantile(means, alpha / 2)), "hi": float(np.quantile(means, 1 - alpha / 2)),
            "frac_better": float((d > 0).mean())}


def skill_vs_baseline(model_losses, baseline_losses, n_boot=5000, seed=0, alpha=0.05):
    """Skill = 1 - mean(model)/mean(baseline): 0 = no better than the baseline
    forecast, 1 = perfect. Paired bootstrap interval over matches."""
    m, b = np.asarray(model_losses, float), np.asarray(baseline_losses, float)
    n = len(m)
    rng = np.random.default_rng(seed)
    vals = np.empty(n_boot)
    for start in range(0, n_boot, _CHUNK):
        k = min(_CHUNK, n_boot - start)
        idx = rng.integers(0, n, size=(k, n))
        vals[start:start + k] = 1 - m[idx].mean(axis=1) / b[idx].mean(axis=1)
    return {"n": int(n), "skill": float(1 - m.mean() / b.mean()),
            "lo": float(np.quantile(vals, alpha / 2)), "hi": float(np.quantile(vals, 1 - alpha / 2))}


def required_n(sd, delta, alpha=0.05, power=0.8):
    """Matches needed to detect a mean paired difference of `delta` when the
    per-match SD of the difference is `sd` (two-sided test)."""
    return math.ceil(((norm.ppf(1 - alpha / 2) + norm.ppf(power)) * sd / delta) ** 2)
