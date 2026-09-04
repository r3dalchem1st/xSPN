import math

from backtest_odds import _score, _season_to_fd_code, blend, join_matches_with_odds


def test_season_to_fd_code_converts_hyphenated_season():
    assert _season_to_fd_code("2025-26") == "2526"
    assert _season_to_fd_code("2024-25") == "2425"


# [date, home, away, hg, ag, label, neutral]
MATCH_A = ["2026-01-01", "Strong FC", "Weak FC", 2, 0, "Test League", False]
MATCH_B = ["2026-01-08", "Weak FC", "Strong FC", 1, 1, "Test League", False]
ODDS_A = {"home": "Strong FC", "away": "Weak FC", "hg": 2, "ag": 0, "odds": (1.5, 4.0, 6.0)}
ODDS_C = {"home": "Nobody FC", "away": "Weak FC", "hg": 1, "ag": 1, "odds": (2.0, 3.0, 4.0)}


def test_join_matches_with_odds_pairs_matching_directed_keys():
    joined = join_matches_with_odds([MATCH_A, MATCH_B], [ODDS_A, ODDS_C])
    assert len(joined) == 1
    assert joined[0] == (MATCH_A, ODDS_A)


def test_join_matches_with_odds_excludes_unmatched_fixtures():
    # MATCH_B ("Weak FC" home vs "Strong FC" away) has no odds row for that
    # exact directed pair -- must be silently excluded, not an error.
    joined = join_matches_with_odds([MATCH_B], [ODDS_A])
    assert joined == []


def test_blend_weight_zero_is_pure_first_prediction():
    assert blend((0.6, 0.2, 0.2), (0.3, 0.3, 0.4), 0.0) == (0.6, 0.2, 0.2)


def test_blend_weight_one_is_pure_second_prediction():
    result = blend((0.6, 0.2, 0.2), (0.3, 0.3, 0.4), 1.0)
    assert all(math.isclose(a, b) for a, b in zip(result, (0.3, 0.3, 0.4)))


def test_blend_halfway_averages_both():
    result = blend((0.6, 0.2, 0.2), (0.4, 0.2, 0.4), 0.5)
    assert all(math.isclose(a, b, abs_tol=1e-9) for a, b in zip(result, (0.5, 0.2, 0.3)))


def test_score_counts_correct_winners_and_computes_brier():
    # outcome index 0 = home win, predicted correctly here.
    result = _score([(0, (0.7, 0.2, 0.1))])
    assert result["n"] == 1
    assert result["accuracy"] == 1.0
    assert math.isclose(result["brier"], (0.7 - 1) ** 2 + (0.2 - 0) ** 2 + (0.1 - 0) ** 2)


def test_score_returns_none_metrics_for_empty_input():
    result = _score([])
    assert result["n"] == 0
    assert result["accuracy"] is None
    assert result["brier"] is None
