from score_league import score_match

PERFECT_HOME_CALL = {"home": "Strong FC", "away": "Weak FC", "date": "2026-08-15",
                       "ph": 0.9, "pd": 0.08, "pa": 0.02,
                       "predicted_winner": "H", "predicted_score": "2-0",
                       "snapped_at": "2026-08-13"}


def test_score_match_correct_winner_and_low_brier_on_a_good_call():
    result = score_match(PERFECT_HOME_CALL, actual_hg=2, actual_ag=0)
    assert result["correct_winner"] is True
    assert result["brier"] < 0.1  # (0.9-1)^2 + (0.08-0)^2 + (0.02-0)^2 = 0.0168


def test_score_match_wrong_winner_gives_high_brier():
    result = score_match(PERFECT_HOME_CALL, actual_hg=0, actual_ag=1)  # away win, not predicted
    assert result["correct_winner"] is False
    assert result["brier"] > 1.0  # (0.9-0)^2 + (0.08-0)^2 + (0.02-1)^2 = 1.7672


def test_score_match_log_loss_is_finite_even_on_a_confident_miss():
    result = score_match(PERFECT_HOME_CALL, actual_hg=0, actual_ag=1)
    import math
    assert math.isfinite(result["log_loss"])


def test_score_match_total_goal_error_is_exact_score_distance():
    # predicted_score "2-0" vs actual 2-0 -> exact match, zero error
    result = score_match(PERFECT_HOME_CALL, actual_hg=2, actual_ag=0)
    assert result["total_goal_error"] == 0


def test_score_match_total_goal_error_sums_both_legs_of_the_miss():
    # predicted_score "2-0" vs actual 4-1 -> |2-4| + |0-1| = 3
    result = score_match(PERFECT_HOME_CALL, actual_hg=4, actual_ag=1)
    assert result["total_goal_error"] == 3
