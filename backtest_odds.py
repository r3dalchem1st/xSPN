"""
Does a real bookmaker's odds beat, or improve on, this project's own
Dixon-Coles model? Answers it with real data, same discipline as
backtest_league.py's calibration/momentum grids: fit on an older season,
score against a LATER season's real, already-known results, using
football-data.co.uk's free historical odds (see fetch_odds_history.py) for
the exact same test season already used to validate calibration/momentum.

Reports three scores side by side:
  - model only  -- this project's own prediction (live config: whatever
    strength_shrink/draw_inflate/use_rho/momentum_weight the competition
    already has set)
  - odds only   -- the bookmaker's de-vigged implied probability
    (odds_utils.implied_probs_from_odds), no model involved at all
  - blended     -- a weighted average of the two, grid-searched over the
    blend weight, to see whether odds add anything ON TOP of the model
    rather than just replacing it

Only matches present in BOTH the openfootball test-season data AND the
football-data.co.uk odds file are scored (an unresolved team name or a
missing odds row on either side just narrows the joined set, not an
error) -- reports how many matches out of the season that ends up being.

Usage: python backtest_odds.py competitions/<slug>.json
"""
import itertools
import math
import sys

from backtest_league import fit_point_estimate, load_season_matches, predict_match_probs
from fetch_odds_history import fetch_season_csv, parse_odds_rows
from odds_utils import implied_probs_from_odds

EPS = 1e-12


def _season_to_fd_code(season_label):
    """"2025-26" -> "2526" (football-data.co.uk's URL season format)."""
    a, b = season_label.split("-")
    return a[-2:] + b[-2:]


def join_matches_with_odds(test_matches, odds_rows):
    """Pairs openfootball test-season rows with football-data.co.uk odds
    rows sharing the same (home, away) directed key -- unique per season
    for a round-robin competition (confirmed live against real 2025-26
    data for all 3 leagues this project covers). Returns a list of
    (test_match, odds_row) tuples; a test match with no matching odds row
    (or vice versa) is simply excluded, not an error."""
    by_pair = {(o["home"], o["away"]): o for o in odds_rows}
    joined = []
    for m in test_matches:
        _date, home, away, *_ = m
        odds_row = by_pair.get((home, away))
        if odds_row is not None:
            joined.append((m, odds_row))
    return joined


def _score(pairs_and_preds):
    """pairs_and_preds: list of (actual_outcome_index, pred_triple).
    Returns {n, accuracy, brier, logloss}."""
    n = correct = 0
    brier_sum = logloss_sum = 0.0
    for oi, pred in pairs_and_preds:
        o = (1, 0, 0) if oi == 0 else ((0, 1, 0) if oi == 1 else (0, 0, 1))
        if pred.index(max(pred)) == oi:
            correct += 1
        brier_sum += sum((pred[k] - o[k]) ** 2 for k in range(3))
        logloss_sum += -math.log(max(pred[oi], EPS))
        n += 1
    return {
        "n": n,
        "accuracy": correct / n if n else None,
        "brier": brier_sum / n if n else None,
        "logloss": logloss_sum / n if n else None,
    }


def blend(pred_a, pred_b, weight_b):
    """weight_b=0.0 -> pure pred_a; 1.0 -> pure pred_b."""
    return tuple(a * (1 - weight_b) + b * weight_b for a, b in zip(pred_a, pred_b))


def main():
    if len(sys.argv) != 2:
        print("usage: python backtest_odds.py competitions/<slug>.json")
        raise SystemExit(1)
    from competition_config import load_competition
    config = load_competition(sys.argv[1])

    if not config.odds_history_code:
        print(f"{config.name}: no odds_history_code configured -- nothing to compare.")
        raise SystemExit(1)
    if len(config.openfootball_files) < 3:
        print(f"{config.name}: needs at least 3 configured seasons to backtest.")
        raise SystemExit(1)

    test_matches, test_season = load_season_matches(config, 1)
    train_matches = []
    for i in range(2, len(config.openfootball_files)):
        rows, _ = load_season_matches(config, i)
        train_matches.extend(rows)

    odds_csv = fetch_season_csv(config.odds_history_code, _season_to_fd_code(test_season))
    odds_rows, n_odds_skipped = parse_odds_rows(odds_csv, config)

    joined = join_matches_with_odds(test_matches, odds_rows)
    print(f"{config.name}: {len(test_matches)} real test matches ({test_season}), "
          f"{len(odds_rows)} odds rows parsed ({n_odds_skipped} skipped) -- "
          f"{len(joined)} matches joined on both sides.\n")
    if not joined:
        print("Nothing to score -- team-name aliasing between the two sources likely needs work.")
        raise SystemExit(1)

    as_of = min((m[0] for m in test_matches), default="2020-01-01")
    dc = fit_point_estimate(train_matches, as_of)
    print(f"Fit converged={dc['converged']}  home_adv={dc['home_adv']:.3f}\n")

    revealed = list(train_matches)
    model_preds, odds_preds, outcomes = [], [], []
    for m, odds_row in sorted(joined, key=lambda pair: pair[0][0]):
        date_, home, away, hg, ag, _label, neutral = m
        model_pred = predict_match_probs(
            home, away, date_, neutral, dc,
            config.strength_shrink, config.draw_inflate, config.use_rho,
            config.momentum_weight, config.momentum_n, revealed)
        odds_pred = implied_probs_from_odds(*odds_row["odds"])
        oi = 0 if hg > ag else (2 if hg < ag else 1)
        model_preds.append(model_pred)
        odds_preds.append(odds_pred)
        outcomes.append(oi)
        revealed.append(m)

    model_score = _score(list(zip(outcomes, model_preds)))
    odds_score = _score(list(zip(outcomes, odds_preds)))
    print(f"{'source':>10} {'n':>4} {'accuracy':>9} {'brier':>7} {'logloss':>8}")
    print(f"{'model':>10} {model_score['n']:4d} {model_score['accuracy']:9.3f} "
          f"{model_score['brier']:7.4f} {model_score['logloss']:8.4f}")
    print(f"{'odds':>10} {odds_score['n']:4d} {odds_score['accuracy']:9.3f} "
          f"{odds_score['brier']:7.4f} {odds_score['logloss']:8.4f}")

    print(f"\n{'blend_w':>8} {'brier':>7} {'logloss':>8} {'acc':>6}")
    best = None
    for w in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
        blended = [blend(mp, op, w) for mp, op in zip(model_preds, odds_preds)]
        r = _score(list(zip(outcomes, blended)))
        print(f"{w:8.1f} {r['brier']:7.4f} {r['logloss']:8.4f} {r['accuracy']:6.3f}")
        if best is None or r["brier"] < best[1]["brier"]:
            best = (w, r)
    print(f"\nBest blend: weight_on_odds={best[0]}  brier={best[1]['brier']:.4f}  "
          f"(model alone={model_score['brier']:.4f}, odds alone={odds_score['brier']:.4f})")


if __name__ == "__main__":
    main()
