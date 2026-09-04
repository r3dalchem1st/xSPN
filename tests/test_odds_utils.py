import math

import pytest

from odds_utils import implied_probs_from_odds, overround


def test_implied_probs_sum_to_exactly_one():
    ph, pd, pa = implied_probs_from_odds(2.10, 3.40, 3.60)
    assert math.isclose(ph + pd + pa, 1.0, abs_tol=1e-9)


def test_implied_probs_favor_the_shorter_odds():
    # 2.10 is a shorter (more likely) price than 3.60 -> higher probability.
    ph, pd, pa = implied_probs_from_odds(2.10, 3.40, 3.60)
    assert ph > pa


def test_implied_probs_removes_the_overround_evenly():
    # Odds implying exactly 106% overround, split evenly across a genuine
    # 50/30/20 "fair" market (raw odds = 1/0.50*1.06, etc.) should de-vig
    # back to almost exactly 50/30/20.
    fair = (0.50, 0.30, 0.20)
    margin = 1.06
    odds = tuple(margin / p for p in fair)
    result = implied_probs_from_odds(*odds)
    for got, expected in zip(result, fair):
        assert math.isclose(got, expected, abs_tol=1e-9)


def test_implied_probs_rejects_non_positive_odds():
    with pytest.raises(ValueError, match="positive"):
        implied_probs_from_odds(0, 3.0, 3.0)
    with pytest.raises(ValueError, match="positive"):
        implied_probs_from_odds(2.0, -1.0, 3.0)


def test_overround_is_zero_for_a_perfectly_fair_market():
    # Odds with no margin at all: 1/p for a fair 50/30/20 split.
    assert math.isclose(overround(2.0, 10 / 3, 5.0), 0.0, abs_tol=1e-9)


def test_overround_is_positive_for_a_realistic_bookmaker_market():
    # A typical real bookmaker market has a few percent margin.
    assert overround(2.10, 3.40, 3.60) > 0.0
