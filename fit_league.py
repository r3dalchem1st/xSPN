"""
Dixon-Coles + Elo fit for round-robin competitions.

Deliberately self-contained rather than sharing fit_improved.py's internals:
that module's Elo/DC fitting math is numerically sensitive (vectorised
log-likelihood + Powell minimize) and feeds the live, already-scored World
Cup pipeline — refactoring it to be reusable risks a subtle regression there
for no real benefit, since round-robin's fitting needs are actually SIMPLER
(one competition, one weight for every match, no seed-Elo table, no
squad-value blending, no cross-tournament boost) rather than a superset that
would justify sharing code. If a third caller ever needs this exact same
math, extract a shared engine then — not speculatively now for two callers,
one of which must not regress.
"""
import json
import math
import os
import sys

import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln

INIT_ELO = 1500
HOME_ADV_SEED = 100     # Elo home-advantage bonus (K-factor update only; the
                         # DC fit below learns its own home_adv independently)
K_BASE = 40
HALF_LIFE_DAYS = 547.5  # 18-month recency half-life, same choice as fit_improved.py
L2_REG = 0.30           # same L2 strength as fit_improved.py — pulls sparse-data
                         # teams (newly promoted clubs) toward average


def days_ago(date_str, ref=None):
    from datetime import date
    if ref is None:
        ref = date.today().isoformat()
    y1, m1, d1 = map(int, date_str.split("-"))
    y2, m2, d2 = map(int, ref.split("-"))
    return (date(y2, m2, d2) - date(y1, m1, d1)).days


def compute_elos(matches, init_elo=INIT_ELO, home_adv=HOME_ADV_SEED,
                  k_base=K_BASE, half_life_days=HALF_LIFE_DAYS):
    """Recency-weighted Elo, every team starting at init_elo (round-robin
    leagues have no pre-existing seed-rating table the way WC teams do —
    with 2+ seasons of match history, Elo converges from a flat start)."""
    r = {}
    for row in sorted(matches, key=lambda x: x[0]):
        date_str, home, away, hs, ascore, _label, neutral = row
        if home not in r: r[home] = init_elo
        if away not in r: r[away] = init_elo
        rh, ra = r[home], r[away]
        adj = rh + (0 if neutral else home_adv)
        exp_h = 1 / (1 + 10 ** ((ra - adj) / 400))
        out_h = 1.0 if hs > ascore else (0.0 if hs < ascore else 0.5)
        gd = abs(hs - ascore)
        mov = math.log(gd + 1) * 2.2 if gd > 0 else 1.0
        d = days_ago(date_str)
        recency = 0.5 ** (d / half_life_days)
        k = min(k_base * mov * recency, 100)
        r[home] = rh + k * (out_h - exp_h)
        r[away] = ra + k * ((1 - out_h) - (1 - exp_h))
    return r


def _build_rows(matches, idx, half_life_days=HALF_LIFE_DAYS):
    rows = []
    for row in matches:
        date_str, home, away, hg, ag, _label, neutral = row
        if home not in idx or away not in idx:
            continue
        d = days_ago(date_str)
        w = 0.5 ** (d / half_life_days)
        rows.append((idx[home], idx[away], hg, ag, w, bool(neutral)))
    return rows


def _fit_rows(rows, teams, x0, l2_reg=L2_REG, maxiter=2000, w_scale=None):
    n = len(teams)
    hi = np.array([r[0] for r in rows], dtype=np.int32)
    ai = np.array([r[1] for r in rows], dtype=np.int32)
    hg = np.array([r[2] for r in rows], dtype=np.float64)
    ag = np.array([r[3] for r in rows], dtype=np.float64)
    w = np.array([r[4] for r in rows], dtype=np.float64)
    if w_scale is not None:
        w = w * w_scale
    neut = np.array([r[5] for r in rows], dtype=bool)

    glh = gammaln(hg + 1)
    gla = gammaln(ag + 1)

    m00 = (hg == 0) & (ag == 0)
    m01 = (hg == 0) & (ag == 1)
    m10 = (hg == 1) & (ag == 0)
    m11 = (hg == 1) & (ag == 1)

    def neg_ll(params):
        atk = params[:n]; dfn = params[n:2 * n]
        hadv = params[-2]; rho = params[-1]

        bonus = np.where(neut, 0.0, hadv)
        lam = np.exp(atk[hi] + dfn[ai] + bonus)
        mu = np.exp(atk[ai] + dfn[hi])
        lam = np.maximum(lam, 1e-6)
        mu = np.maximum(mu, 1e-6)

        tau = np.ones(len(rows))
        tau[m00] = np.maximum(1 - lam[m00] * mu[m00] * rho, 1e-10)
        tau[m01] = np.maximum(1 + lam[m01] * rho, 1e-10)
        tau[m10] = np.maximum(1 + mu[m10] * rho, 1e-10)
        tau[m11] = np.maximum(1 - rho, 1e-10)

        ll_h = hg * np.log(lam) - lam - glh
        ll_a = ag * np.log(mu) - mu - gla
        ll = np.sum(w * (np.log(tau) + ll_h + ll_a))

        reg = l2_reg * (np.dot(atk, atk) + np.dot(dfn, dfn))
        return -ll + reg

    return minimize(neg_ll, x0, method='Powell',
                     options={'maxiter': maxiter, 'ftol': 1e-6, 'xtol': 1e-5})


def _x0_from_elo(teams, elo_ratings):
    avg_elo = np.mean(list(elo_ratings.values()))
    x0_atk = np.array([0.1 * (elo_ratings.get(t, INIT_ELO) - avg_elo) / 400 for t in teams])
    x0_def = np.zeros(len(teams))
    return np.concatenate([x0_atk, x0_def, [0.1, -0.1]])


def _unpack(p, teams):
    n = len(teams)
    return {
        "attack": {t: float(p[i]) for i, t in enumerate(teams)},
        "defense": {t: float(p[n + i]) for i, t in enumerate(teams)},
        "home_adv": float(p[-2]),
        "rho": float(p[-1]),
    }


def fit_dc(matches, elo_ratings):
    """Point-estimate Dixon-Coles fit. Returns dict with attack/defense/
    home_adv/rho/teams/converged/fun."""
    teams = sorted({m[1] for m in matches} | {m[2] for m in matches})
    idx = {t: i for i, t in enumerate(teams)}
    rows = _build_rows(matches, idx)
    res = _fit_rows(rows, teams, _x0_from_elo(teams, elo_ratings))
    out = _unpack(res.x, teams)
    out.update(teams=teams, converged=bool(res.success), fun=float(res.fun))
    return out


def fit_dc_bootstrap(matches, elo_ratings, point_dc, B=60, seed=42):
    """Bayesian-bootstrap ensemble, same method as fit_improved.py: every
    match kept every time, weight perturbed by a Dirichlet(1) draw (mean 1)."""
    teams = point_dc["teams"]
    idx = {t: i for i, t in enumerate(teams)}
    rows = _build_rows(matches, idx)
    x0 = np.concatenate([
        [point_dc["attack"][t] for t in teams],
        [point_dc["defense"][t] for t in teams],
        [point_dc["home_adv"], point_dc["rho"]],
    ])
    rng = np.random.default_rng(seed)
    M = len(rows)
    ensemble = []
    n_failed = 0
    for _ in range(B):
        e = rng.exponential(1.0, size=M)
        w_scale = e / e.mean()
        res = _fit_rows(rows, teams, x0, maxiter=1500, w_scale=w_scale)
        if not res.success:
            n_failed += 1
        out = _unpack(res.x, teams)
        out.update(teams=teams)
        ensemble.append(out)
    fail_rate = n_failed / B
    if fail_rate > 0.05:
        print(f"  WARNING: bootstrap fail rate {fail_rate:.0%} exceeds 5% threshold")
    return ensemble


def fit_and_save(config, base_dir, bootstrap_size=60, seed=42):
    """Load <slug>/fetched_matches.json, fit Elo + Dixon-Coles, write
    <slug>/model_params.json (elo + point dc, committed) and
    <slug>/dc_ensemble.json (bootstrap ensemble, NOT committed — mirrors
    fit_improved.py's dc_ensemble.json / .gitignore pattern).
    Returns the point-estimate dc dict."""
    from competition_config import artifact_dir
    out_dir = artifact_dir(config, base_dir)
    matches_path = os.path.join(out_dir, "fetched_matches.json")
    with open(matches_path) as f:
        matches = json.load(f)
    if not matches:
        raise ValueError(f"{config.slug}: no training matches in {matches_path} — "
                          f"run fetch_league.py first")

    elo = compute_elos(matches)
    dc = fit_dc(matches, elo)
    ensemble = fit_dc_bootstrap(matches, elo, dc, B=bootstrap_size, seed=seed)

    with open(os.path.join(out_dir, "model_params.json"), "w") as f:
        json.dump({"elo": {t: round(v, 2) for t, v in elo.items()}, "dc": dc}, f, indent=2)
    with open(os.path.join(out_dir, "dc_ensemble.json"), "w") as f:
        json.dump(ensemble, f)

    return dc


def main():
    if len(sys.argv) != 2:
        print("usage: python fit_league.py competitions/<slug>.json")
        raise SystemExit(1)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from competition_config import load_competition
    config = load_competition(sys.argv[1])
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dc = fit_and_save(config, base_dir)
    top_atk = sorted(dc["attack"].items(), key=lambda x: -x[1])[:5]
    print(f"{config.name}: fit converged={dc['converged']}, teams={len(dc['teams'])}")
    print("Top 5 attack ratings:")
    for t, v in top_atk:
        print(f"  {t:<28} {v:.4f}")


if __name__ == "__main__":
    main()
