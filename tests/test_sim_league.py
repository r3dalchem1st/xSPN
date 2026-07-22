import math

from sim_league import build_lambda_table, build_lambda_tables, compute_standings_and_remaining

DC_SAMPLE = {
    "attack": {"Strong FC": 0.8, "Weak FC": -0.6},
    "defense": {"Strong FC": -0.3, "Weak FC": 0.4},
    "home_adv": 0.2,
    "rho": -0.1,
    "teams": ["Strong FC", "Weak FC"],
}


def test_build_lambda_table_uses_fitted_params():
    lg = build_lambda_table(["Strong FC", "Weak FC"], DC_SAMPLE)
    assert set(lg.keys()) == {("Strong FC", "Weak FC"), ("Weak FC", "Strong FC")}
    lam_strong_home, mu_strong_home = lg[("Strong FC", "Weak FC")]
    assert lam_strong_home > mu_strong_home  # strong team at home should out-score weak away


def test_build_lambda_table_defaults_unrated_team_to_neutral():
    lg = build_lambda_table(["Strong FC", "Newly Promoted FC"], DC_SAMPLE)
    lam, mu = lg[("Newly Promoted FC", "Strong FC")]
    # unrated home team: attack=0, defense=0 -> lam = exp(0 + Strong.defense + home_adv)
    expected_lam = math.exp(0.0 + DC_SAMPLE["defense"]["Strong FC"] + DC_SAMPLE["home_adv"])
    assert abs(lam - expected_lam) < 1e-9
    expected_mu = math.exp(DC_SAMPLE["attack"]["Strong FC"] + 0.0)
    assert abs(mu - expected_mu) < 1e-9


def test_build_lambda_tables_returns_one_per_ensemble_member():
    tables = build_lambda_tables(["Strong FC", "Weak FC"], [DC_SAMPLE, DC_SAMPLE])
    assert len(tables) == 2


SAMPLE_SCHEDULE = {
    "Strong FC|Weak FC": {"date": "2026-08-01", "status": "FINISHED",
                           "goals": {"Strong FC": 3, "Weak FC": 1}, "round": "Matchday 1"},
    "Weak FC|Strong FC": {"date": "2026-12-01", "status": "SCHEDULED",
                           "goals": {"Weak FC": None, "Strong FC": None}, "round": "Matchday 20"},
}


def test_compute_standings_and_remaining_splits_correctly():
    standings, remaining, teams = compute_standings_and_remaining(SAMPLE_SCHEDULE)
    assert standings["Strong FC"] == {"pts": 3, "gd": 2, "gf": 3}
    assert standings["Weak FC"] == {"pts": 0, "gd": -2, "gf": 1}
    assert remaining == [("Weak FC", "Strong FC")]
    assert teams == ["Strong FC", "Weak FC"]


def test_poisson_mean_matches_lambda_over_many_draws():
    from sim_league import _poisson
    import numpy as np
    rng = np.random.default_rng(0)
    lam = 2.5
    draws = [_poisson(lam, rng) for _ in range(20000)]
    mean = sum(draws) / len(draws)
    assert abs(mean - lam) < 0.05  # generous tolerance for a stochastic check


def test_simulate_season_rank_distribution_sums_to_one():
    from sim_league import simulate_season
    rank_dist = simulate_season(["Strong FC", "Weak FC"], {}, [("Strong FC", "Weak FC")],
                                 [DC_SAMPLE], n_sims=500, seed=1)
    for team, dist in rank_dist.items():
        assert abs(sum(dist) - 1.0) < 1e-9


def test_simulate_season_favors_the_stronger_team():
    from sim_league import simulate_season
    rank_dist = simulate_season(["Strong FC", "Weak FC"], {}, [("Strong FC", "Weak FC")],
                                 [DC_SAMPLE], n_sims=2000, seed=1)
    assert rank_dist["Strong FC"][0] > rank_dist["Weak FC"][0]  # Strong finishes 1st more often


import json
import os

import pytest

from competition_config import CompetitionConfig

SIM_CONFIG_DATA = {
    "slug": "test_league",
    "name": "Test League",
    "format": "round_robin",
    "openfootball_repo": "openfootball/example",
    "openfootball_files": [{"season": "2026-27", "path": "2026-27/1-test.txt"}],
    "team_aliases": {},
}


def _write_artifacts(base_dir, slug, schedule, dc_ensemble):
    out_dir = os.path.join(base_dir, "competitions", slug)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "schedule.json"), "w") as f:
        json.dump(schedule, f)
    with open(os.path.join(out_dir, "dc_ensemble.json"), "w") as f:
        json.dump(dc_ensemble, f)


def test_simulate_and_save_writes_league_sim(tmp_path):
    from sim_league import simulate_and_save
    config = CompetitionConfig(SIM_CONFIG_DATA)
    _write_artifacts(str(tmp_path), config.slug, SAMPLE_SCHEDULE, [DC_SAMPLE])

    rank_dist = simulate_and_save(config, str(tmp_path), n_sims=200, seed=1)

    assert set(rank_dist.keys()) == {"Strong FC", "Weak FC"}
    out_dir = tmp_path / "competitions" / "test_league"
    with open(out_dir / "league_sim.json") as f:
        saved = json.load(f)
    assert set(saved.keys()) == {"Strong FC", "Weak FC"}


def test_simulate_and_save_raises_without_ensemble(tmp_path):
    from sim_league import simulate_and_save
    config = CompetitionConfig(SIM_CONFIG_DATA)
    out_dir = os.path.join(str(tmp_path), "competitions", config.slug)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "schedule.json"), "w") as f:
        json.dump(SAMPLE_SCHEDULE, f)
    # no dc_ensemble.json written
    with pytest.raises(FileNotFoundError, match="dc_ensemble.json"):
        simulate_and_save(config, str(tmp_path))


def test_simulate_and_save_raises_when_no_remaining_fixtures(tmp_path):
    from sim_league import simulate_and_save
    config = CompetitionConfig(SIM_CONFIG_DATA)
    finished_only = {
        "Strong FC|Weak FC": SAMPLE_SCHEDULE["Strong FC|Weak FC"],
    }
    _write_artifacts(str(tmp_path), config.slug, finished_only, [DC_SAMPLE])
    with pytest.raises(ValueError, match="no SCHEDULED fixtures"):
        simulate_and_save(config, str(tmp_path))
