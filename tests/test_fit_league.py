import json
import os

import pytest

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
