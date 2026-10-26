"""
Golden-master gate on the league model's real accuracy.

The other ~470 tests check mechanics (shapes, no-ops, parsing). None would
notice a refactor of the fit that quietly made predictions worse -- the 17 Aug
audit found the World Cup pipeline had a regression gate and the league
pipeline never did. This replays three REAL La Liga seasons (frozen in
tests/data/, from football-data.co.uk): train on 2022-23 and 2023-24, predict
2024-25 out of sample with monthly refits, exactly as rolling_backtest.py does.

If this fails after a deliberate model change, don't loosen the tolerance:
re-run the change through experiments.py and the pre-registered rule, and only
then update GOLDEN_BRIER / GOLDEN_LOGLOSS to the new value in the same commit.
"""
import json
import os

import numpy as np

from eval_stats import base_rate_probs, brier_losses, logloss_losses
from rolling_backtest import run_season

GOLDEN_BRIER = 0.576997
GOLDEN_LOGLOSS = 0.973097
TOLERANCE = 0.004   # ~0.7% of the Brier score; a real degradation is larger, float noise is ~1e-9

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "la_liga_2223_2425.json")


def _predictions():
    raw = json.load(open(FIXTURE))
    keys = list(raw)
    by = {k: [{"date": d, "home": h, "away": a, "hg": hg, "ag": ag, "market": None} for d, h, a, hg, ag in v]
          for k, v in raw.items()}
    return run_season(by, keys, 2, {"train_seasons": 2, "refit_days": 30}), by["2425"]


def test_the_league_model_has_not_regressed_on_three_real_la_liga_seasons():
    recs, _ = _predictions()
    P, o = np.array([r["p"] for r in recs]), np.array([r["o"] for r in recs])
    brier, logloss = brier_losses(P, o).mean(), logloss_losses(P, o).mean()
    assert len(recs) == 380
    assert abs(brier - GOLDEN_BRIER) < TOLERANCE, (
        f"out-of-sample Brier {brier:.4f} moved from the golden {GOLDEN_BRIER:.4f}; see this file's docstring")
    assert abs(logloss - GOLDEN_LOGLOSS) < 4 * TOLERANCE


def test_every_refit_converged_and_the_model_beats_the_naive_base_rate_forecast():
    recs, _ = _predictions()
    assert all(r["conv"] for r in recs)
    o = np.array([r["o"] for r in recs])
    base = np.tile(base_rate_probs(o), (len(o), 1))   # in-sample base rates: a generous baseline
    assert brier_losses(np.array([r["p"] for r in recs]), o).mean() < brier_losses(base, o).mean()
