"""
Does folding historical odds into the Dixon-Coles fit itself (see
fit_league.py's odds-consistency term, `mkt_probs_by_match`/`odds_weight`)
improve real out-of-sample accuracy, beyond what the plain (odds_weight=0.0)
fit already achieves?

Same methodology as backtest_league.py: fit once on the older, fully-
concluded TRAIN season(s), score the resulting model's own predictions
against a LATER fully-concluded TEST season it never trained on (real,
already-known results). The difference from backtest_odds.py is WHERE odds
enter the pipeline -- here they only ever inform the FIT (attack/defense/
home_adv), so every scored prediction still comes purely from the model's
own fitted parameters at serving time; backtest_odds.py, by contrast,
compared swapping the bookmaker's number in directly at prediction time
(the approach this project tried and then deliberately reverted -- see
CONTEXT.md).

Odds are joined per TRAIN season only, never the test season -- using
test-season odds during fitting would leak future information into
training, the exact leak backtest_league.py's own train/test split is
designed to avoid.

Usage: python backtest_fit_odds.py competitions/<slug>.json
"""
import sys

import fit_league as fl
from backtest_league import load_season_matches, score_holdout
from backtest_odds import _season_to_fd_code
from fetch_odds_history import fetch_season_csv, parse_odds_rows
from odds_utils import implied_probs_from_odds

WEIGHTS = [0.0, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0]


def build_mkt_probs_by_match(matches, odds_rows):
    """Aligns real historical odds onto `matches` (one TRAINING season's
    rows, [date,home,away,hg,ag,label,neutral]) by directed (home,away) key
    -- returns a list PARALLEL to `matches` (same length/order), each entry
    the joined de-vigged (ph,pd,pa) triple or None for a match with no
    matching odds row. Mirrors backtest_odds.py's join_matches_with_odds,
    but preserves alignment/order instead of filtering to only the joined
    subset, since fit_dc's mkt_probs_by_match needs a slot per match, not a
    shortened list."""
    by_pair = {(o["home"], o["away"]): o for o in odds_rows}
    result = []
    for m in matches:
        _date, home, away, *_ = m
        odds_row = by_pair.get((home, away))
        result.append(implied_probs_from_odds(*odds_row["odds"]) if odds_row else None)
    return result


def fit_point_estimate_with_odds(train_matches, as_of_date, mkt_probs_by_match, odds_weight):
    """Same days_ago()-monkeypatch technique as backtest_league.py's
    fit_point_estimate, extended to thread the odds-consistency term
    through fit_dc."""
    orig_days_ago = fl.days_ago
    fl.days_ago = lambda ds, ref=as_of_date: orig_days_ago(ds, ref)
    try:
        elo = fl.compute_elos(train_matches)
        return fl.fit_dc(train_matches, elo, mkt_probs_by_match=mkt_probs_by_match,
                          odds_weight=odds_weight)
    finally:
        fl.days_ago = orig_days_ago


def main():
    if len(sys.argv) != 2:
        print("usage: python backtest_fit_odds.py competitions/<slug>.json")
        raise SystemExit(1)
    from competition_config import load_competition
    config = load_competition(sys.argv[1])

    if not config.odds_history_code:
        print(f"{config.name}: no odds_history_code configured -- nothing to backtest.")
        raise SystemExit(1)
    if len(config.openfootball_files) < 3:
        print(f"{config.name}: needs at least 3 configured seasons to backtest.")
        raise SystemExit(1)

    test_matches, test_season = load_season_matches(config, 1)

    train_matches, mkt_probs_by_match, train_seasons = [], [], []
    n_joined_total = 0
    for i in range(2, len(config.openfootball_files)):
        rows, season = load_season_matches(config, i)
        odds_csv = fetch_season_csv(config.odds_history_code, _season_to_fd_code(season))
        odds_rows, n_skipped = parse_odds_rows(odds_csv, config)
        season_mkt_probs = build_mkt_probs_by_match(rows, odds_rows)
        n_joined = sum(1 for p in season_mkt_probs if p is not None)
        n_joined_total += n_joined
        print(f"  {season}: {len(rows)} matches, {n_joined} joined with real odds "
              f"({len(odds_rows)} odds rows parsed, {n_skipped} skipped)")
        train_matches.extend(rows)
        mkt_probs_by_match.extend(season_mkt_probs)
        train_seasons.append(season)

    print(f"\n{config.name}: training on {len(train_matches)} matches (seasons "
          f"{train_seasons}), {n_joined_total} with real historical odds; testing on "
          f"{len(test_matches)} real out-of-sample matches ({test_season}).\n")
    if n_joined_total == 0:
        print("No training matches joined with real odds -- nothing for the odds term to use.")
        raise SystemExit(1)

    as_of = min((m[0] for m in test_matches), default="2020-01-01")

    print(f"{'odds_weight':>11} {'converged':>9} {'logloss':>8} {'brier':>7} {'acc':>6}")
    results = []
    for w in WEIGHTS:
        dc = fit_point_estimate_with_odds(train_matches, as_of, mkt_probs_by_match, w)
        r = score_holdout(test_matches, dc)
        r["odds_weight"], r["converged"] = w, dc["converged"]
        results.append(r)
        print(f"{w:11.1f} {str(dc['converged']):>9} {r['logloss']:8.4f} "
              f"{r['brier']:7.4f} {r['accuracy']:6.3f}")

    baseline = results[0]
    best = min(results, key=lambda r: r["brier"])
    print(f"\nBest by Brier: odds_weight={best['odds_weight']}  brier={best['brier']:.4f}  "
          f"(vs {baseline['brier']:.4f} at odds_weight=0.0)  logloss={best['logloss']:.4f}  "
          f"accuracy={best['accuracy']:.3f} (vs {baseline['accuracy']:.3f})")


if __name__ == "__main__":
    main()
