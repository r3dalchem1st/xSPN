import json
import os

import numpy as np
import pytest

import fit_league
from competition_config import CompetitionConfig
from fit_league import compute_elos, fit_dc, fit_dc_bootstrap, fit_and_save

# Verified: converges cleanly and ranks Strong > Mid > Weak/Newcomer on both
# Elo and Dixon-Coles attack. Generated from noisy Poisson-ish scorelines
# over 6 rounds of a double round-robin — a first attempt with one fixed,
# deterministic scoreline per pairing failed to converge (NaN), which is why
# this fixture has draws and varied margins.
SYNTHETIC_MATCHES = [
    ["2025-08-05", "Strong FC", "Mid FC", 1, 1, "Test League", False],
    ["2025-08-05", "Strong FC", "Weak FC", 2, 0, "Test League", False],
    ["2025-08-05", "Strong FC", "Newcomer FC", 0, 0, "Test League", False],
    ["2025-08-05", "Mid FC", "Strong FC", 1, 0, "Test League", False],
    ["2025-08-05", "Mid FC", "Weak FC", 1, 0, "Test League", False],
    ["2025-08-05", "Mid FC", "Newcomer FC", 0, 0, "Test League", False],
    ["2025-08-05", "Weak FC", "Strong FC", 0, 2, "Test League", False],
    ["2025-08-05", "Weak FC", "Mid FC", 0, 0, "Test League", False],
    ["2025-08-05", "Weak FC", "Newcomer FC", 1, 0, "Test League", False],
    ["2025-08-05", "Newcomer FC", "Strong FC", 0, 4, "Test League", False],
    ["2025-08-05", "Newcomer FC", "Mid FC", 0, 1, "Test League", False],
    ["2025-08-05", "Newcomer FC", "Weak FC", 0, 0, "Test League", False],
    ["2025-08-13", "Strong FC", "Mid FC", 0, 0, "Test League", False],
    ["2025-08-13", "Strong FC", "Weak FC", 4, 0, "Test League", False],
    ["2025-08-13", "Strong FC", "Newcomer FC", 2, 1, "Test League", False],
    ["2025-08-13", "Mid FC", "Strong FC", 1, 0, "Test League", False],
    ["2025-08-13", "Mid FC", "Weak FC", 1, 0, "Test League", False],
    ["2025-08-13", "Mid FC", "Newcomer FC", 0, 0, "Test League", False],
    ["2025-08-13", "Weak FC", "Strong FC", 0, 0, "Test League", False],
    ["2025-08-13", "Weak FC", "Mid FC", 0, 0, "Test League", False],
    ["2025-08-13", "Weak FC", "Newcomer FC", 0, 1, "Test League", False],
    ["2025-08-13", "Newcomer FC", "Strong FC", 0, 1, "Test League", False],
    ["2025-08-13", "Newcomer FC", "Mid FC", 0, 0, "Test League", False],
    ["2025-08-13", "Newcomer FC", "Weak FC", 0, 0, "Test League", False],
    ["2025-08-21", "Strong FC", "Mid FC", 1, 1, "Test League", False],
    ["2025-08-21", "Strong FC", "Weak FC", 6, 0, "Test League", False],
    ["2025-08-21", "Strong FC", "Newcomer FC", 0, 0, "Test League", False],
    ["2025-08-21", "Mid FC", "Strong FC", 0, 0, "Test League", False],
    ["2025-08-21", "Mid FC", "Weak FC", 0, 0, "Test League", False],
    ["2025-08-21", "Mid FC", "Newcomer FC", 0, 0, "Test League", False],
    ["2025-08-21", "Weak FC", "Strong FC", 1, 1, "Test League", False],
    ["2025-08-21", "Weak FC", "Mid FC", 0, 0, "Test League", False],
    ["2025-08-21", "Weak FC", "Newcomer FC", 0, 0, "Test League", False],
    ["2025-08-21", "Newcomer FC", "Strong FC", 0, 2, "Test League", False],
    ["2025-08-21", "Newcomer FC", "Mid FC", 1, 0, "Test League", False],
    ["2025-08-21", "Newcomer FC", "Weak FC", 0, 0, "Test League", False],
    ["2025-08-29", "Strong FC", "Mid FC", 1, 2, "Test League", False],
    ["2025-08-29", "Strong FC", "Weak FC", 6, 1, "Test League", False],
    ["2025-08-29", "Strong FC", "Newcomer FC", 1, 0, "Test League", False],
    ["2025-08-29", "Mid FC", "Strong FC", 0, 1, "Test League", False],
    ["2025-08-29", "Mid FC", "Weak FC", 6, 0, "Test League", False],
    ["2025-08-29", "Mid FC", "Newcomer FC", 0, 0, "Test League", False],
    ["2025-08-29", "Weak FC", "Strong FC", 0, 0, "Test League", False],
    ["2025-08-29", "Weak FC", "Mid FC", 1, 0, "Test League", False],
    ["2025-08-29", "Weak FC", "Newcomer FC", 0, 0, "Test League", False],
    ["2025-08-29", "Newcomer FC", "Strong FC", 0, 0, "Test League", False],
    ["2025-08-29", "Newcomer FC", "Mid FC", 0, 0, "Test League", False],
    ["2025-08-29", "Newcomer FC", "Weak FC", 0, 0, "Test League", False],
    ["2025-08-09", "Strong FC", "Mid FC", 1, 0, "Test League", False],
    ["2025-08-09", "Strong FC", "Weak FC", 1, 0, "Test League", False],
    ["2025-08-09", "Strong FC", "Newcomer FC", 1, 0, "Test League", False],
    ["2025-08-09", "Mid FC", "Strong FC", 1, 2, "Test League", False],
    ["2025-08-09", "Mid FC", "Weak FC", 1, 0, "Test League", False],
    ["2025-08-09", "Mid FC", "Newcomer FC", 0, 0, "Test League", False],
    ["2025-08-09", "Weak FC", "Strong FC", 1, 1, "Test League", False],
    ["2025-08-09", "Weak FC", "Mid FC", 0, 0, "Test League", False],
    ["2025-08-09", "Weak FC", "Newcomer FC", 0, 1, "Test League", False],
    ["2025-08-09", "Newcomer FC", "Strong FC", 0, 2, "Test League", False],
    ["2025-08-09", "Newcomer FC", "Mid FC", 0, 1, "Test League", False],
    ["2025-08-09", "Newcomer FC", "Weak FC", 0, 0, "Test League", False],
    ["2025-08-17", "Strong FC", "Mid FC", 2, 0, "Test League", False],
    ["2025-08-17", "Strong FC", "Weak FC", 0, 0, "Test League", False],
    ["2025-08-17", "Strong FC", "Newcomer FC", 4, 0, "Test League", False],
    ["2025-08-17", "Mid FC", "Strong FC", 1, 6, "Test League", False],
    ["2025-08-17", "Mid FC", "Weak FC", 0, 0, "Test League", False],
    ["2025-08-17", "Mid FC", "Newcomer FC", 0, 0, "Test League", False],
    ["2025-08-17", "Weak FC", "Strong FC", 0, 2, "Test League", False],
    ["2025-08-17", "Weak FC", "Mid FC", 0, 1, "Test League", False],
    ["2025-08-17", "Weak FC", "Newcomer FC", 0, 1, "Test League", False],
    ["2025-08-17", "Newcomer FC", "Strong FC", 0, 0, "Test League", False],
    ["2025-08-17", "Newcomer FC", "Mid FC", 0, 1, "Test League", False],
    ["2025-08-17", "Newcomer FC", "Weak FC", 0, 0, "Test League", False],
]


def test_compute_elos_ranks_stronger_team_higher():
    elo = compute_elos(SYNTHETIC_MATCHES)
    assert elo["Strong FC"] > elo["Mid FC"] > elo["Weak FC"]
    assert elo["Strong FC"] > elo["Mid FC"] > elo["Newcomer FC"]


def test_fit_dc_converges_and_ranks_attack_correctly():
    elo = compute_elos(SYNTHETIC_MATCHES)
    dc = fit_dc(SYNTHETIC_MATCHES, elo)
    assert dc["converged"] is True
    assert set(dc["teams"]) == {"Strong FC", "Mid FC", "Weak FC", "Newcomer FC"}
    assert dc["attack"]["Strong FC"] > dc["attack"]["Mid FC"] > dc["attack"]["Weak FC"]
    assert dc["attack"]["Strong FC"] > dc["attack"]["Mid FC"] > dc["attack"]["Newcomer FC"]
    assert isinstance(dc["home_adv"], float)
    assert isinstance(dc["rho"], float)


def test_fit_dc_bootstrap_returns_requested_ensemble_size():
    elo = compute_elos(SYNTHETIC_MATCHES)
    dc = fit_dc(SYNTHETIC_MATCHES, elo)
    ensemble = fit_dc_bootstrap(SYNTHETIC_MATCHES, elo, dc, B=5, seed=1)
    assert len(ensemble) == 5
    for member in ensemble:
        assert set(member["teams"]) == set(dc["teams"])
        assert isinstance(member["home_adv"], float)
        assert isinstance(member["rho"], float)


class _FakeResult:
    def __init__(self, success, x):
        self.success = success
        self.x = x


def test_fit_dc_bootstrap_drops_non_converged_refits(monkeypatch):
    # Regression test for a real bug (mirrors fit_improved.py's own fix,
    # 17 Aug audit): a non-converged refit used to be kept anyway -- an
    # arbitrary, non-fitted parameter vector silently skewing the ensemble's
    # confidence bands instead of just narrowing it by one member.
    elo = compute_elos(SYNTHETIC_MATCHES)
    dc = fit_dc(SYNTHETIC_MATCHES, elo)
    n_teams = len(dc["teams"])
    x_dim = 2 * n_teams + 2
    calls = {"n": 0}

    def fake_fit_rows(rows, teams, x0, l2_reg=fit_league.L2_REG, maxiter=2000, w_scale=None):
        calls["n"] += 1
        # Every other refit "fails" to converge.
        success = calls["n"] % 2 == 0
        return _FakeResult(success, np.zeros(x_dim))

    monkeypatch.setattr(fit_league, "_fit_rows", fake_fit_rows)
    ensemble = fit_dc_bootstrap(SYNTHETIC_MATCHES, elo, dc, B=6, seed=1)
    assert len(ensemble) == 3  # only the 3 "successful" refits kept
    assert calls["n"] == 6


def test_fit_dc_bootstrap_raises_when_every_refit_fails(monkeypatch):
    elo = compute_elos(SYNTHETIC_MATCHES)
    dc = fit_dc(SYNTHETIC_MATCHES, elo)
    n_teams = len(dc["teams"])
    x_dim = 2 * n_teams + 2

    def always_fails(rows, teams, x0, l2_reg=fit_league.L2_REG, maxiter=2000, w_scale=None):
        return _FakeResult(False, np.zeros(x_dim))

    monkeypatch.setattr(fit_league, "_fit_rows", always_fails)
    with pytest.raises(RuntimeError, match="all 4 bootstrap refits failed"):
        fit_dc_bootstrap(SYNTHETIC_MATCHES, elo, dc, B=4, seed=1)


IO_CONFIG_DATA = {
    "slug": "test_league",
    "name": "Test League",
    "format": "round_robin",
    "openfootball_repo": "openfootball/example",
    "openfootball_files": [{"season": "2026-27", "path": "2026-27/1-test.txt"}],
    "team_aliases": {},
}


def _write_fetched_matches(base_dir, slug, matches):
    out_dir = os.path.join(base_dir, "competitions", slug)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "fetched_matches.json"), "w") as f:
        json.dump(matches, f)


def test_fit_and_save_writes_model_params_and_ensemble(tmp_path):
    config = CompetitionConfig(IO_CONFIG_DATA)
    _write_fetched_matches(str(tmp_path), config.slug, SYNTHETIC_MATCHES)

    dc = fit_and_save(config, str(tmp_path), bootstrap_size=3, seed=1)

    assert dc["converged"] is True
    out_dir = tmp_path / "competitions" / "test_league"
    with open(out_dir / "model_params.json") as f:
        params = json.load(f)
    assert set(params["elo"].keys()) == {"Strong FC", "Mid FC", "Weak FC", "Newcomer FC"}
    assert params["dc"]["converged"] is True
    with open(out_dir / "dc_ensemble.json") as f:
        ensemble = json.load(f)
    assert len(ensemble) == 3


def test_fit_and_save_raises_on_empty_training_data(tmp_path):
    config = CompetitionConfig(IO_CONFIG_DATA)
    _write_fetched_matches(str(tmp_path), config.slug, [])
    with pytest.raises(ValueError, match="no training matches"):
        fit_and_save(config, str(tmp_path), bootstrap_size=3)


def test_fit_dc_with_odds_weight_zero_matches_plain_fit_exactly():
    # odds_weight=0.0 (the default) must be a true no-op, even when
    # mkt_probs_by_match is supplied -- byte-identical to fit_dc's
    # pre-existing behavior until a real weight is set from a real backtest.
    elo = compute_elos(SYNTHETIC_MATCHES)
    plain = fit_dc(SYNTHETIC_MATCHES, elo)
    mkt_probs = [(0.9, 0.05, 0.05)] * len(SYNTHETIC_MATCHES)
    with_zero_weight = fit_dc(SYNTHETIC_MATCHES, elo, mkt_probs_by_match=mkt_probs, odds_weight=0.0)
    assert plain["attack"] == with_zero_weight["attack"]
    assert plain["defense"] == with_zero_weight["defense"]
    assert plain["home_adv"] == with_zero_weight["home_adv"]


def test_fit_dc_with_no_mkt_probs_matches_plain_fit_exactly():
    # Symmetric no-op check: a nonzero odds_weight with no mkt_probs at all
    # must also change nothing (has_odds never gets built).
    elo = compute_elos(SYNTHETIC_MATCHES)
    plain = fit_dc(SYNTHETIC_MATCHES, elo)
    with_weight_no_odds = fit_dc(SYNTHETIC_MATCHES, elo, odds_weight=5.0)
    assert plain["attack"] == with_weight_no_odds["attack"]


def test_fit_dc_odds_term_pulls_fit_toward_a_contradicting_market_signal():
    # Sanity check the mechanism actually does something: tell the fit that
    # the market saw Newcomer FC (the model's clear underdog on goals alone)
    # as a heavy favorite in every match, with a large odds_weight. The
    # resulting attack rating for Newcomer FC should rise relative to the
    # unweighted fit -- proof the odds term is really pulling params, not a
    # no-op silently doing nothing.
    elo = compute_elos(SYNTHETIC_MATCHES)
    plain = fit_dc(SYNTHETIC_MATCHES, elo)
    mkt_probs = []
    for _date, home, away, *_ in SYNTHETIC_MATCHES:
        if home == "Newcomer FC":
            mkt_probs.append((0.9, 0.05, 0.05))
        elif away == "Newcomer FC":
            mkt_probs.append((0.05, 0.05, 0.9))
        else:
            mkt_probs.append(None)
    pulled = fit_dc(SYNTHETIC_MATCHES, elo, mkt_probs_by_match=mkt_probs, odds_weight=10.0)
    assert pulled["attack"]["Newcomer FC"] > plain["attack"]["Newcomer FC"]


def test_build_rows_co_filters_mkt_probs_with_matches():
    idx = {"Strong FC": 0, "Mid FC": 1}
    matches = [
        ["2025-08-05", "Strong FC", "Mid FC", 1, 0, "Test League", False],
        ["2025-08-05", "Strong FC", "Unknown FC", 2, 0, "Test League", False],  # filtered out
        ["2025-08-12", "Mid FC", "Strong FC", 0, 1, "Test League", False],
    ]
    mkt_probs_by_match = [(0.5, 0.3, 0.2), (0.9, 0.05, 0.05), None]
    rows, mkt_probs = fit_league._build_rows(matches, idx, mkt_probs_by_match=mkt_probs_by_match)
    assert len(rows) == 2  # the "Unknown FC" row is dropped
    assert mkt_probs == [(0.5, 0.3, 0.2), None]  # co-filtered in lockstep, not just truncated


def test_build_rows_returns_none_mkt_probs_when_not_requested():
    idx = {"Strong FC": 0, "Mid FC": 1}
    matches = [["2025-08-05", "Strong FC", "Mid FC", 1, 0, "Test League", False]]
    rows, mkt_probs = fit_league._build_rows(matches, idx)
    assert mkt_probs is None
