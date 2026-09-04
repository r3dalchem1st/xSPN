import math

from league_calibration import (GOAL_ANCHOR, clamp_lambda, hda_probs_from_lambda,
                                 inflate_hda, shrink_lambda)


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
