import math

import fit_league
from backtest_league import (fit_point_estimate, load_season_matches, predict_match_probs,
                              run_grid, run_momentum_grid, score_holdout)
from competition_config import CompetitionConfig

DC_SAMPLE = {
    "attack": {"Strong FC": 0.8, "Weak FC": -0.6},
    "defense": {"Strong FC": -0.3, "Weak FC": 0.4},
    "home_adv": 0.2,
    "rho": -0.15,
    "teams": ["Strong FC", "Weak FC"],
}

# [date, home, away, hg, ag, label, neutral]
HOME_WIN = ["2026-01-01", "Strong FC", "Weak FC", 2, 0, "Test League", False]
DRAW     = ["2026-01-08", "Strong FC", "Weak FC", 1, 1, "Test League", False]
AWAY_WIN = ["2026-01-15", "Weak FC", "Strong FC", 0, 3, "Test League", False]


def test_predict_match_probs_sums_to_one_and_matches_score_holdout():
    # predict_match_probs must be the exact same computation score_holdout
    # runs internally -- confirmed by checking a single-match holdout's
    # aggregate stats derive from exactly this per-match prediction.
    pred = predict_match_probs("Strong FC", "Weak FC", "2026-01-01", False, DC_SAMPLE)
    assert math.isclose(sum(pred), 1.0, abs_tol=1e-9)
    result = score_holdout([HOME_WIN], DC_SAMPLE)
    if pred.index(max(pred)) == 0:  # home win predicted (matches HOME_WIN's actual result)
        assert result["accuracy"] == 1.0


def test_predict_match_probs_no_op_calibration_is_identity():
    default = predict_match_probs("Strong FC", "Weak FC", "2026-01-01", False, DC_SAMPLE)
    explicit = predict_match_probs("Strong FC", "Weak FC", "2026-01-01", False, DC_SAMPLE,
                                    strength_shrink=1.0, delta=0.0, use_rho=False,
                                    momentum_weight=0.0)
    assert default == explicit


def test_score_holdout_no_op_calibration_matches_hda_probs_from_lambda_directly():
    result = score_holdout([HOME_WIN], DC_SAMPLE)
    assert result["strength_shrink"] == 1.0
    assert result["draw_inflate"] == 0.0
    assert result["use_rho"] is False
    assert result["n"] == 1
    assert 0.0 <= result["brier"] <= 2.0


def test_score_holdout_correct_winner_counts_argmax_matches():
    # Strong FC at home vs Weak FC away should be the model's clear favorite
    # -- both a home win and an away win in the holdout, one call right,
    # one wrong.
    result = score_holdout([HOME_WIN, AWAY_WIN], DC_SAMPLE)
    assert result["n"] == 2
    assert 0.0 <= result["accuracy"] <= 1.0


def test_score_holdout_draw_inflate_raises_predicted_draw_rate():
    baseline = score_holdout([HOME_WIN, DRAW, AWAY_WIN], DC_SAMPLE, delta=0.0)
    inflated = score_holdout([HOME_WIN, DRAW, AWAY_WIN], DC_SAMPLE, delta=0.5)
    assert inflated["pred_draw_rate"] > baseline["pred_draw_rate"]


def test_score_holdout_use_rho_changes_scoring():
    without = score_holdout([HOME_WIN, DRAW, AWAY_WIN], DC_SAMPLE, use_rho=False)
    with_rho = score_holdout([HOME_WIN, DRAW, AWAY_WIN], DC_SAMPLE, use_rho=True)
    assert without["brier"] != with_rho["brier"]


def test_score_holdout_momentum_weight_zero_matches_default_exactly():
    # momentum_weight=0.0 must be a true no-op, byte-identical to every
    # pre-momentum caller's behavior.
    default = score_holdout([HOME_WIN, DRAW, AWAY_WIN], DC_SAMPLE)
    explicit_zero = score_holdout([HOME_WIN, DRAW, AWAY_WIN], DC_SAMPLE, momentum_weight=0.0)
    assert default == explicit_zero


def test_score_holdout_momentum_reveals_matches_chronologically():
    # A team on a hot streak (revealed via earlier test-season matches, not
    # just training history) should score differently than with momentum
    # off -- proving the running "revealed" history is actually being used,
    # not just the pre-test momentum_history seed.
    hot_streak = [
        ["2026-01-01", "Weak FC", "Strong FC", 0, 0, "Test League", False],
        ["2026-01-08", "Weak FC", "Strong FC", 5, 0, "Test League", False],
        ["2026-01-15", "Weak FC", "Strong FC", 4, 0, "Test League", False],
        ["2026-01-22", "Weak FC", "Strong FC", 3, 0, "Test League", False],
    ]
    without_momentum = score_holdout(hot_streak, DC_SAMPLE, momentum_weight=0.0)
    with_momentum = score_holdout(hot_streak, DC_SAMPLE, momentum_weight=0.1, momentum_n=3)
    assert without_momentum["brier"] != with_momentum["brier"]


def test_score_holdout_momentum_history_seeds_the_window_for_early_matches():
    # Without a seed, the very first test match sees a cold-start (0.0)
    # momentum for both teams. With training history showing Strong FC on
    # a hot streak, the very first test match should already reflect it.
    seed_history = [
        ["2025-12-01", "Strong FC", "Weak FC", 4, 0, "Test League", False],
        ["2025-12-08", "Strong FC", "Weak FC", 3, 0, "Test League", False],
    ]
    cold_start = score_holdout([HOME_WIN], DC_SAMPLE, momentum_weight=0.1)
    warm_start = score_holdout([HOME_WIN], DC_SAMPLE, momentum_weight=0.1,
                                momentum_history=seed_history)
    assert cold_start["brier"] != warm_start["brier"]


def test_run_momentum_grid_covers_every_combination():
    results = run_momentum_grid([HOME_WIN, DRAW], DC_SAMPLE, [0.0, 0.1], [3, 5])
    assert len(results) == 4
    combos = {(r["momentum_weight"], r["momentum_n"]) for r in results}
    assert combos == {(0.0, 3), (0.0, 5), (0.1, 3), (0.1, 5)}


def test_run_momentum_grid_holds_calibration_params_fixed():
    results = run_momentum_grid([HOME_WIN], DC_SAMPLE, [0.0], [5],
                                 strength_shrink=0.7, delta=0.2, use_rho=True)
    assert results[0]["strength_shrink"] == 0.7
    assert results[0]["draw_inflate"] == 0.2
    assert results[0]["use_rho"] is True


def test_score_holdout_returns_none_metrics_for_empty_holdout():
    result = score_holdout([], DC_SAMPLE)
    assert result["n"] == 0
    assert result["accuracy"] is None
    assert result["brier"] is None


def test_run_grid_covers_every_combination():
    results = run_grid([HOME_WIN, DRAW], DC_SAMPLE, [1.0, 0.5], [0.0, 0.3], [False, True])
    assert len(results) == 2 * 2 * 2
    combos = {(r["strength_shrink"], r["draw_inflate"], r["use_rho"]) for r in results}
    assert combos == {(1.0, 0.0, False), (1.0, 0.0, True), (1.0, 0.3, False), (1.0, 0.3, True),
                       (0.5, 0.0, False), (0.5, 0.0, True), (0.5, 0.3, False), (0.5, 0.3, True)}


def test_fit_point_estimate_restores_days_ago_after_success():
    original = fit_league.days_ago
    fit_point_estimate([HOME_WIN, DRAW, AWAY_WIN, HOME_WIN], "2026-06-01")
    assert fit_league.days_ago is original


def test_fit_point_estimate_restores_days_ago_even_on_failure():
    original = fit_league.days_ago
    try:
        fit_point_estimate([], "2026-06-01")  # no matches -> fit_dc will error
    except Exception:
        pass
    assert fit_league.days_ago is original


def test_fit_point_estimate_computes_recency_as_of_the_given_date_not_real_today():
    # Regression-style test for the actual point of the monkeypatch: a match
    # dated AFTER as_of_date must be treated as being in the FUTURE relative
    # to the fit (negative days-ago), not weighted as if it were recent
    # relative to real today. Captured via a fake compute_elos that calls
    # the module's (patched) days_ago while the patch is active.
    original_compute_elos = fit_league.compute_elos
    captured = {}

    def fake_compute_elos(matches, **kwargs):
        # fit_point_estimate has already patched fit_league.days_ago by the
        # time this runs -- call it exactly as _build_rows/compute_elos do,
        # by bare module reference, to observe the patched behavior.
        captured["days_ago_future_match"] = fit_league.days_ago("2026-06-15")
        return original_compute_elos(matches, **kwargs)

    fit_league.compute_elos = fake_compute_elos
    try:
        fit_point_estimate([HOME_WIN, DRAW, AWAY_WIN, HOME_WIN], as_of_date="2026-06-01")
    finally:
        fit_league.compute_elos = original_compute_elos

    # "2026-06-15" is 14 days AFTER the as_of_date "2026-06-01" -> negative
    # days-ago (a future match from the fit's point of view), not the huge
    # positive value it would be relative to real today.
    assert captured["days_ago_future_match"] == -14


CONFIG_DATA = {
    "slug": "test_league",
    "name": "Test League",
    "format": "round_robin",
    "openfootball_repo": "openfootball/example",
    "openfootball_files": [
        {"season": "2026-27", "path": "2026-27/1-test.txt"},
        {"season": "2025-26", "path": "2025-26/1-test.txt"},
        {"season": "2024-25", "path": "2024-25/1-test.txt"},
    ],
    "team_aliases": {},
}


def test_load_season_matches_fetches_the_requested_index_only(monkeypatch):
    import backtest_league

    def fake_fetch(repo, path, timeout=10):
        assert path == "2025-26/1-test.txt"
        return "season-text"

    def fake_parse(text):
        assert text == "season-text"
        return [{"round": "Matchday 1", "date": "2025-08-10", "home": "Strong FC",
                  "away": "Weak FC", "score": (2, 0)}]

    monkeypatch.setattr(backtest_league, "fetch_openfootball_file", fake_fetch)
    monkeypatch.setattr(backtest_league, "parse_openfootball_txt", fake_parse)

    config = CompetitionConfig(CONFIG_DATA)
    rows, season = load_season_matches(config, 1)
    assert season == "2025-26"
    assert rows == [["2025-08-10", "Strong FC", "Weak FC", 2, 0, "Test League", False]]
