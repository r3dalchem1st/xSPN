import math

import numpy as np

from eval_stats import (base_rate_probs, brier_losses, correct_flags, improvement, logloss_losses,
                        required_n, skill_vs_baseline)

P = np.array([[0.7, 0.2, 0.1], [0.2, 0.3, 0.5]])
O = np.array([0, 2])


def test_brier_losses_match_the_hand_formula():
    out = brier_losses(P, O)
    assert math.isclose(out[0], (0.7 - 1) ** 2 + 0.2 ** 2 + 0.1 ** 2)
    assert math.isclose(out[1], 0.2 ** 2 + 0.3 ** 2 + (0.5 - 1) ** 2)


def test_logloss_losses_and_correct_flags():
    assert np.allclose(logloss_losses(P, O), [-math.log(0.7), -math.log(0.5)])
    assert list(correct_flags(P, O)) == [True, True]


def test_logloss_is_finite_on_a_zero_probability():
    assert np.isfinite(logloss_losses(np.array([[1.0, 0.0, 0.0]]), np.array([1]))).all()


def test_base_rate_probs_are_the_outcome_frequencies():
    assert base_rate_probs(np.array([0, 0, 1, 2])) == [0.5, 0.25, 0.25]


def test_improvement_ci_excludes_zero_for_a_consistently_better_candidate():
    rng = np.random.default_rng(1)
    baseline = rng.normal(0.6, 0.1, 500)
    candidate = baseline - 0.01 + rng.normal(0, 0.01, 500)
    r = improvement(candidate, baseline, seed=3)
    assert r["mean"] > 0.008 and r["lo"] > 0 and r["n"] == 500
    assert r["frac_better"] > 0.7


def test_improvement_ci_includes_zero_for_two_identical_models():
    x = np.random.default_rng(2).normal(0.6, 0.1, 400)
    r = improvement(x, x.copy(), seed=3)
    assert r["mean"] == 0 and r["lo"] <= 0 <= r["hi"]


def test_improvement_ci_includes_zero_when_the_difference_is_pure_noise():
    # Symmetric by construction (every +x gain has a matching -x loss), so the
    # true mean difference is exactly 0 -- two independent random samples would
    # exclude zero by chance ~5% of the time and make this test flaky.
    x = np.random.default_rng(4).normal(0, 0.05, 150)
    baseline = np.full(300, 0.6)
    candidate = baseline - np.concatenate([x, -x])
    r = improvement(candidate, baseline, seed=5)
    assert abs(r["mean"]) < 1e-12 and r["lo"] < 0 < r["hi"]


def test_improvement_is_deterministic_for_a_seed():
    rng = np.random.default_rng(6)
    a, b = rng.normal(0.6, 0.1, 200), rng.normal(0.6, 0.1, 200)
    assert improvement(a, b, seed=9) == improvement(a, b, seed=9)


def test_cluster_bootstrap_is_wider_when_a_whole_cluster_shifts_together():
    # Two clusters whose gains differ wildly: an iid bootstrap pretends 400
    # independent matches; resampling whole clusters shows how little evidence that is.
    base = np.zeros(400)
    cand = np.concatenate([np.full(200, -0.05), np.full(200, +0.05)])  # improvement +0.05 in one cluster, -0.05 in the other
    clusters = ["a"] * 200 + ["b"] * 200
    iid = improvement(cand, base, seed=1)
    clustered = improvement(cand, base, clusters=clusters, seed=1)
    assert (clustered["hi"] - clustered["lo"]) > 5 * (iid["hi"] - iid["lo"])


def test_skill_vs_baseline_is_positive_when_the_model_loses_less():
    r = skill_vs_baseline(np.full(100, 0.55), np.full(100, 0.65), seed=1)
    assert math.isclose(r["skill"], 1 - 0.55 / 0.65) and r["lo"] <= r["skill"] <= r["hi"]


def test_skill_vs_baseline_is_zero_for_identical_losses():
    x = np.random.default_rng(7).normal(0.6, 0.1, 100)
    assert skill_vs_baseline(x, x, seed=1)["skill"] == 0


def test_required_n_reproduces_the_hand_calculation_used_in_the_audit():
    # per-match paired Brier SD ~0.06 (La Liga sandbox), effect 0.01 -> about 280 matches
    assert 270 <= required_n(0.0594, 0.01) <= 290


def test_required_n_grows_as_the_effect_shrinks():
    assert required_n(0.06, 0.005) > required_n(0.06, 0.01) > required_n(0.06, 0.02)
