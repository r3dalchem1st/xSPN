import math

from league_calibration import (GOAL_ANCHOR, clamp_lambda, compute_momentum,
                                 hda_probs_from_lambda, inflate_hda, shrink_lambda)


def test_shrink_lambda_is_identity_at_strength_1():
    assert shrink_lambda(2.5, 1.0) == 2.5
    assert shrink_lambda(0.4, 1.0) == 0.4


def test_shrink_lambda_pulls_toward_anchor_below_1():
    # A value above the anchor gets pulled down toward it; below stays below.
    shrunk = shrink_lambda(3.0, 0.5)
    assert GOAL_ANCHOR < shrunk < 3.0


def test_shrink_lambda_zero_collapses_to_the_anchor():
    assert shrink_lambda(5.0, 0.0) == GOAL_ANCHOR
    assert shrink_lambda(0.1, 0.0) == GOAL_ANCHOR


def test_clamp_lambda_bounds_extreme_values():
    assert clamp_lambda(11.0) == 5.0
    assert clamp_lambda(0.01) == 0.20
    assert clamp_lambda(1.5) == 1.5


def test_inflate_hda_is_identity_at_delta_zero():
    assert inflate_hda(0.5, 0.3, 0.2, 0.0) == (0.5, 0.3, 0.2)


def test_inflate_hda_boosts_draw_mass_and_stays_normalized():
    ph, pd, pa = inflate_hda(0.5, 0.3, 0.2, 0.5)
    assert pd > 0.3
    assert math.isclose(ph + pd + pa, 1.0, abs_tol=1e-9)
    # Home and away shrink proportionally, preserving their original ratio.
    assert math.isclose(ph / pa, 0.5 / 0.2, rel_tol=1e-9)


def test_hda_probs_from_lambda_sums_to_one():
    ph, pd, pa = hda_probs_from_lambda(1.6, 1.1)
    assert math.isclose(ph + pd + pa, 1.0, abs_tol=1e-6)


def test_hda_probs_from_lambda_favors_the_higher_lambda_team():
    ph, pd, pa = hda_probs_from_lambda(2.5, 0.8)
    assert ph > pa


def test_hda_probs_from_lambda_symmetric_when_lambdas_equal():
    ph, pd, pa = hda_probs_from_lambda(1.4, 1.4)
    assert math.isclose(ph, pa, abs_tol=1e-9)


def test_hda_probs_from_lambda_rho_zero_matches_independent_poisson():
    with_rho_zero = hda_probs_from_lambda(1.6, 1.1, rho=0.0)
    default_rho = hda_probs_from_lambda(1.6, 1.1)
    assert with_rho_zero == default_rho


def test_hda_probs_from_lambda_rho_shifts_low_score_mass():
    # A negative rho (the historically typical DC sign) suppresses 1-1 and
    # boosts 0-0 relative to independent Poisson -- net effect on P(draw)
    # for two evenly-matched low-scoring teams should differ from rho=0.
    baseline = hda_probs_from_lambda(1.0, 1.0, rho=0.0)
    adjusted = hda_probs_from_lambda(1.0, 1.0, rho=-0.15)
    assert baseline != adjusted
    # Still a valid probability triple.
    assert math.isclose(sum(adjusted), 1.0, abs_tol=1e-6)
    assert all(0.0 <= p <= 1.0 for p in adjusted)


# [date, home, away, hg, ag, label, neutral]
STRONG_FORM = [
    ["2026-01-01", "Team A", "Team B", 3, 0, "Test League", False],
    ["2026-01-08", "Team C", "Team A", 0, 2, "Test League", False],
    ["2026-01-15", "Team A", "Team D", 1, 0, "Test League", False],
]
COLD_FORM = [
    ["2026-01-01", "Team A", "Team B", 0, 3, "Test League", False],
    ["2026-01-08", "Team C", "Team A", 2, 0, "Test League", False],
]


def test_compute_momentum_returns_zero_with_no_history():
    assert compute_momentum("Team A", "2026-01-01", []) == 0.0


def test_compute_momentum_returns_zero_for_a_team_absent_from_history():
    assert compute_momentum("Team Z", "2026-02-01", STRONG_FORM) == 0.0


def test_compute_momentum_averages_goal_difference_home_and_away():
    # Team A: +3 (home win 3-0), +2 (away win, 0-2 as away means +2 for A),
    # +1 (home win 1-0) -> average (3+2+1)/3 = 2.0
    momentum = compute_momentum("Team A", "2026-02-01", STRONG_FORM)
    assert momentum == 2.0


def test_compute_momentum_only_counts_matches_strictly_before_as_of_date():
    # Cutting off before the 3rd match should only see the first two.
    momentum = compute_momentum("Team A", "2026-01-15", STRONG_FORM)
    assert momentum == (3 + 2) / 2


def test_compute_momentum_excludes_matches_on_or_after_as_of_date_exactly():
    # A match dated exactly as_of_date must not count (it hasn't been
    # played "before" this prediction from the model's point of view).
    momentum = compute_momentum("Team A", "2026-01-01", STRONG_FORM)
    assert momentum == 0.0  # no qualifying matches before the very first one


def test_compute_momentum_negative_for_a_cold_streak():
    momentum = compute_momentum("Team A", "2026-02-01", COLD_FORM)
    assert momentum < 0.0


def test_compute_momentum_window_limits_to_last_n_matches():
    long_history = [
        ["2026-01-01", "Team A", "Team B", 5, 0, "Test League", False],  # +5, outside window
        ["2026-01-08", "Team A", "Team B", 0, 0, "Test League", False],  # 0
        ["2026-01-15", "Team A", "Team B", 0, 0, "Test League", False],  # 0
    ]
    momentum = compute_momentum("Team A", "2026-02-01", long_history, n=2)
    assert momentum == 0.0  # only the last 2 (0, 0) counted, not the +5
