import math

from backtest_fit_odds import build_mkt_probs_by_match

# [date, home, away, hg, ag, label, neutral]
MATCH_A = ["2024-08-10", "Strong FC", "Weak FC", 2, 0, "Test League", False]
MATCH_B = ["2024-08-17", "Weak FC", "Strong FC", 1, 1, "Test League", False]
MATCH_C = ["2024-08-24", "Mid FC", "Weak FC", 0, 0, "Test League", False]
ODDS_A = {"home": "Strong FC", "away": "Weak FC", "hg": 2, "ag": 0, "odds": (1.5, 4.0, 6.0)}


def test_build_mkt_probs_by_match_aligns_and_devigs_a_matching_row():
    result = build_mkt_probs_by_match([MATCH_A], [ODDS_A])
    assert len(result) == 1
    ph, pd, pa = result[0]
    assert math.isclose(ph + pd + pa, 1.0)
    assert ph > pa  # Strong FC heavily favored at 1.5 vs 6.0


def test_build_mkt_probs_by_match_returns_none_for_unmatched_directed_pair():
    # MATCH_B is the reverse fixture (Weak FC at home) -- must not match
    # ODDS_A's directed (Strong FC, Weak FC) key.
    result = build_mkt_probs_by_match([MATCH_B], [ODDS_A])
    assert result == [None]


def test_build_mkt_probs_by_match_preserves_length_and_order_with_mixed_matches():
    result = build_mkt_probs_by_match([MATCH_A, MATCH_C, MATCH_B], [ODDS_A])
    assert len(result) == 3
    assert result[0] is not None
    assert result[1] is None
    assert result[2] is None
