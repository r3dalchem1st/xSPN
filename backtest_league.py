"""
Out-of-sample calibration backtest for round-robin/knockout_only
competitions (League/Copa configs — anything fit_league.py fits).

Mirrors backtest.py's proven World Cup methodology exactly: fit once on an
older, fully-concluded season, score the model's probabilistic predictions
on a LATER fully-concluded season it never trained on (real, already-known
results — no simulation), then grid-search (strength_shrink, draw_inflate,
use_rho) against log-loss/Brier — never optimized against raw accuracy
directly, since a degenerate "always predict the favorite" policy can
inflate accuracy without being well-calibrated (same caution backtest.py's
own docstring gives; accuracy is reported for reference only).

Uses the POINT-ESTIMATE fit only (fit_dc, not the 60-member bootstrap
ensemble) — same simplification backtest.py itself makes for the same
reason: the bootstrap exists to give production predictions honest
uncertainty bands, not to find a calibration value, and refitting it per
grid point would be needlessly slow for no benefit to the search.

Needs a competition config with at least 3 openfootball_files entries
(index 0 = current in-progress season, excluded; index 1 = TEST, the newest
FULLY CONCLUDED season; index 2+ = TRAIN). A competition with fewer than 3
configured seasons can't be backtested this way yet.

Standalone diagnostic — NOT part of the daily GitHub Actions pipeline (same
role backtest.py's own docstring claims for the WC, even though that one
did end up wired into update.yml as a regression gate; deliberately NOT
doing that here yet — this script finds calibration values, it doesn't
enforce them).

Usage: python backtest_league.py competitions/<slug>.json [--grid|--momentum-grid]
"""
import itertools
import math
import os
import sys

import fit_league as fl
from fetch_league import build_training_rows, fetch_openfootball_file
from league_calibration import (clamp_lambda, compute_momentum, hda_probs_from_lambda,
                                 inflate_hda, shrink_lambda)
from openfootball_txt import parse_openfootball_txt

EPS = 1e-12


def load_season_matches(config, season_index):
    """Played matches from config.openfootball_files[season_index] only
    (not the whole configured history) — build_training_rows already drops
    unplayed fixtures. Returns (rows, season_label)."""
    entry = config.openfootball_files[season_index]
    text = fetch_openfootball_file(config.openfootball_repo, entry["path"])
    parsed = parse_openfootball_txt(text)
    rows, _ = build_training_rows(config, parsed)
    return rows, entry["season"]


def fit_point_estimate(train_matches, as_of_date):
    """Point-estimate Elo + Dixon-Coles fit on `train_matches`, with
    recency weighting computed AS OF `as_of_date` (not real today) so the
    fit reflects only what was knowable at that point — same days_ago()
    monkeypatch technique backtest.py uses for fit_improved.py. Restores
    the original function before returning (or on error), so a caller
    fitting multiple times in one process never leaks a stale patch."""
    orig_days_ago = fl.days_ago
    fl.days_ago = lambda ds, ref=as_of_date: orig_days_ago(ds, ref)
    try:
        elo = fl.compute_elos(train_matches)
        return fl.fit_dc(train_matches, elo)
    finally:
        fl.days_ago = orig_days_ago


def predict_match_probs(home, away, date_, neutral, dc, strength_shrink=1.0, delta=0.0,
                         use_rho=False, momentum_weight=0.0, momentum_n=5, revealed=None):
    """The model's own (ph, pd, pa) for ONE match, given a point-estimate
    fit `dc` and calibration settings -- the same per-match computation
    score_holdout() runs in its loop, factored out so a caller (e.g.
    backtest_odds.py, blending this against a bookmaker's odds) can get a
    single match's prediction without re-deriving this logic. `revealed`
    is the running match history for momentum (see score_holdout's own
    docstring); omit it if momentum_weight is 0.0."""
    atk, dfn, home_adv, rho = dc["attack"], dc["defense"], dc["home_adv"], dc["rho"]
    ah, dh = atk.get(home, 0.0), dfn.get(home, 0.0)
    aa, da = atk.get(away, 0.0), dfn.get(away, 0.0)
    if momentum_weight:
        mom_h = compute_momentum(home, date_, revealed or [], momentum_n)
        mom_a = compute_momentum(away, date_, revealed or [], momentum_n)
        ah, dh = ah + momentum_weight * mom_h, dh - momentum_weight * mom_h
        aa, da = aa + momentum_weight * mom_a, da - momentum_weight * mom_a
    bonus = 0.0 if neutral else home_adv
    lam = clamp_lambda(shrink_lambda(math.exp(ah + da + bonus), strength_shrink))
    mu = clamp_lambda(shrink_lambda(math.exp(aa + dh), strength_shrink))
    ph, pd, pa = hda_probs_from_lambda(lam, mu, rho if use_rho else 0.0)
    return inflate_hda(ph, pd, pa, delta)


def score_holdout(test_matches, dc, strength_shrink=1.0, delta=0.0, use_rho=False,
                   momentum_weight=0.0, momentum_n=5, momentum_history=None):
    """Score `test_matches` (real, already-known results — [date, home,
    away, hg, ag, label, neutral] rows) against one calibration setting,
    reusing the SAME fit `dc` for every grid point (only post-fit
    calibration varies — no refitting per point, matching backtest.py).

    `momentum_weight` (default 0.0 = no-op, identical to omitting it)
    blends each team's recent-form signal (league_calibration.compute_momentum)
    symmetrically into its effective attack/defense for that one match —
    same "boost attack, reduce goals-conceded expectation" pattern as
    model_common.py's squad-value adjustment for the WC. Matches are
    processed in chronological order and each one is REVEALED into the
    running history right after being scored, so momentum for a later
    test-season match correctly reflects earlier test-season results, not
    just the training season — this is what makes it a genuinely different
    signal from the fit's own slow 18-month recency half-life.
    `momentum_history` (typically the TRAIN matches) seeds the window so
    the very first test matches aren't scored with a bogus 0.0 momentum for
    every team; pass None for a cold start instead."""
    n = correct = 0
    brier_sum = logloss_sum = 0.0
    pred_draw_sum = act_draw_sum = 0
    revealed = list(momentum_history) if momentum_history else []
    for m in sorted(test_matches, key=lambda row: row[0]):
        date_, home, away, hg, ag, _label, neutral = m
        pred = predict_match_probs(home, away, date_, neutral, dc, strength_shrink, delta,
                                    use_rho, momentum_weight, momentum_n, revealed)
        if hg > ag:
            o, oi = (1, 0, 0), 0
        elif hg < ag:
            o, oi = (0, 0, 1), 2
        else:
            o, oi = (0, 1, 0), 1
        if pred.index(max(pred)) == oi:
            correct += 1
        brier_sum += sum((pred[k] - o[k]) ** 2 for k in range(3))
        logloss_sum += -math.log(max(pred[oi], EPS))
        pred_draw_sum += pred[1]
        act_draw_sum += 1 if hg == ag else 0
        n += 1
        revealed.append(m)
    return {
        "strength_shrink": strength_shrink, "draw_inflate": delta, "use_rho": use_rho,
        "momentum_weight": momentum_weight, "momentum_n": momentum_n,
        "n": n,
        "accuracy": correct / n if n else None,
        "brier": brier_sum / n if n else None,
        "logloss": logloss_sum / n if n else None,
        "pred_draw_rate": pred_draw_sum / n if n else None,
        "actual_draw_rate": act_draw_sum / n if n else None,
    }


def run_grid(test_matches, dc, shrinks, deltas, use_rho_options):
    return [
        score_holdout(test_matches, dc, sh, dl, ur)
        for sh, dl, ur in itertools.product(shrinks, deltas, use_rho_options)
    ]


def run_momentum_grid(test_matches, dc, momentum_weights, momentum_ns, momentum_history=None,
                       strength_shrink=1.0, delta=0.0, use_rho=False):
    """Grid-search momentum_weight/momentum_n only, holding the calibration
    params fixed (default to the already-confirmed no-calibration-helps
    values — see model_changelog-style notes in CONTEXT.md — but overridable
    for a competition whose own backtest found otherwise)."""
    return [
        score_holdout(test_matches, dc, strength_shrink, delta, use_rho,
                       mw, mn, momentum_history)
        for mw, mn in itertools.product(momentum_weights, momentum_ns)
    ]


def main():
    if len(sys.argv) < 2:
        print("usage: python backtest_league.py competitions/<slug>.json [--grid]")
        raise SystemExit(1)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from competition_config import load_competition
    config = load_competition(sys.argv[1])

    if len(config.openfootball_files) < 3:
        print(f"{config.name}: needs at least 3 configured seasons (current + 1 test + "
              f"1+ train, all fully concluded except the current one) — only "
              f"{len(config.openfootball_files)} configured. Cannot backtest yet.")
        raise SystemExit(1)

    test_matches, test_season = load_season_matches(config, 1)
    train_matches = []
    train_seasons = []
    for i in range(2, len(config.openfootball_files)):
        rows, season = load_season_matches(config, i)
        train_matches.extend(rows)
        train_seasons.append(season)

    print(f"{config.name}: training on {len(train_matches)} matches (seasons "
          f"{train_seasons}), testing on {len(test_matches)} real out-of-sample "
          f"matches ({test_season}).\n")

    as_of = min((m[0] for m in test_matches), default="2020-01-01")
    dc = fit_point_estimate(train_matches, as_of)
    print(f"Fit converged={dc['converged']}  home_adv={dc['home_adv']:.3f}  "
          f"rho={dc['rho']:.4f}\n")

    if "--grid" in sys.argv:
        shrinks = [1.0, 0.85, 0.70, 0.55, 0.40]
        deltas = [0.0, 0.15, 0.30, 0.50]
        use_rho_options = [False, True]
        results = run_grid(test_matches, dc, shrinks, deltas, use_rho_options)
        print(f"{'shrink':>7} {'delta':>6} {'rho':>6} {'logloss':>8} {'brier':>7} "
              f"{'acc':>6} {'predDraw':>9} {'actDraw':>8}")
        for r in results:
            print(f"{r['strength_shrink']:7.2f} {r['draw_inflate']:6.2f} "
                  f"{str(r['use_rho']):>6} {r['logloss']:8.4f} {r['brier']:7.4f} "
                  f"{r['accuracy']:6.3f} {r['pred_draw_rate']:9.3f} {r['actual_draw_rate']:8.3f}")
        best = min(results, key=lambda r: r["brier"])
        print(f"\nBest by Brier: strength_shrink={best['strength_shrink']} "
              f"draw_inflate={best['draw_inflate']} use_rho={best['use_rho']}  "
              f"brier={best['brier']:.4f} logloss={best['logloss']:.4f} "
              f"accuracy={best['accuracy']:.3f}")
        raise SystemExit(0)

    if "--momentum-grid" in sys.argv:
        weights = [0.0, 0.02, 0.05, 0.10, 0.15, 0.20]
        ns = [3, 5, 8]
        # Calibration held at the no-op default -- already confirmed via
        # --grid that shrink/draw-inflate/rho don't help this competition;
        # rerun --grid first for a competition that hasn't been checked.
        results = run_momentum_grid(test_matches, dc, weights, ns, momentum_history=train_matches,
                                     strength_shrink=config.strength_shrink,
                                     delta=config.draw_inflate, use_rho=config.use_rho)
        print(f"{'weight':>7} {'n':>3} {'logloss':>8} {'brier':>7} {'acc':>6}")
        for r in results:
            print(f"{r['momentum_weight']:7.2f} {r['momentum_n']:3d} "
                  f"{r['logloss']:8.4f} {r['brier']:7.4f} {r['accuracy']:6.3f}")
        best = min(results, key=lambda r: r["brier"])
        baseline = next(r for r in results if r["momentum_weight"] == 0.0 and r["momentum_n"] == ns[0])
        print(f"\nBest by Brier: momentum_weight={best['momentum_weight']} "
              f"momentum_n={best['momentum_n']}  brier={best['brier']:.4f} "
              f"(vs {baseline['brier']:.4f} with no momentum)  "
              f"logloss={best['logloss']:.4f}  accuracy={best['accuracy']:.3f}")
        raise SystemExit(0)

    # Single-run mode: score this config's OWN configured calibration AND
    # momentum values (each field's no-op default if unset) against the
    # same holdout -- an honest end-to-end check of what's actually live.
    r = score_holdout(test_matches, dc, config.strength_shrink, config.draw_inflate,
                       config.use_rho, config.momentum_weight, config.momentum_n,
                       momentum_history=train_matches)
    print(f"Configured: strength_shrink={r['strength_shrink']} draw_inflate={r['draw_inflate']} "
          f"use_rho={r['use_rho']} momentum_weight={r['momentum_weight']} "
          f"momentum_n={r['momentum_n']}")
    print(f"  accuracy={r['accuracy']:.1%}  brier={r['brier']:.4f}  "
          f"logloss={r['logloss']:.4f}  predicted draw rate={r['pred_draw_rate']:.1%} "
          f"vs actual {r['actual_draw_rate']:.1%}")


if __name__ == "__main__":
    main()
