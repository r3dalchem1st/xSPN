import json
import os

import requests

import shadow_fit_odds
from competition_config import CompetitionConfig
from shadow_fit_odds import (ensure_shadow_file_exists, fetch_one_season_with_odds,
                              fetch_training_matches_and_odds, fit_shadow_models,
                              snapshot_shadow_and_save)

CONFIG_DATA = {
    "slug": "test_league",
    "name": "Test League",
    "format": "round_robin",
    "openfootball_repo": "openfootball/example",
    "openfootball_files": [
        {"season": "2026-27", "path": "2026-27/1-test.txt"},
        {"season": "2025-26", "path": "2025-26/1-test.txt"},
    ],
    "team_aliases": {},
    "odds_history_code": "E0",
    "odds_fit_weight": 5.0,
}

PARSED_MATCH = {"round": "Matchday 1", "date": "2025-08-14", "home": "Strong FC",
                 "away": "Weak FC", "score": (2, 0)}


def test_fetch_one_season_with_odds_joins_when_available(monkeypatch):
    config = CompetitionConfig(CONFIG_DATA)
    entry = config.openfootball_files[1]

    monkeypatch.setattr(shadow_fit_odds, "fetch_openfootball_file", lambda repo, path: "fake text")
    monkeypatch.setattr(shadow_fit_odds, "parse_openfootball_txt", lambda text: [PARSED_MATCH])
    monkeypatch.setattr(shadow_fit_odds, "fetch_season_csv", lambda code, season: "fake csv")
    monkeypatch.setattr(shadow_fit_odds, "parse_odds_rows", lambda text, cfg: (
        [{"home": "Strong FC", "away": "Weak FC", "hg": 2, "ag": 0, "odds": (1.5, 4.0, 6.0)}], 0))

    rows, mkt_probs = fetch_one_season_with_odds(config, entry)
    assert len(rows) == 1
    assert mkt_probs[0] is not None


def test_fetch_one_season_with_odds_falls_back_gracefully_on_missing_odds_file(monkeypatch):
    # e.g. the current in-progress season's odds CSV doesn't exist yet
    # (football-data.co.uk 404s) -- must not crash, just contribute no
    # odds signal for that season's matches.
    config = CompetitionConfig(CONFIG_DATA)
    entry = config.openfootball_files[0]

    monkeypatch.setattr(shadow_fit_odds, "fetch_openfootball_file", lambda repo, path: "fake text")
    monkeypatch.setattr(shadow_fit_odds, "parse_openfootball_txt", lambda text: [PARSED_MATCH])

    def raise_404(code, season):
        raise requests.RequestException("404")
    monkeypatch.setattr(shadow_fit_odds, "fetch_season_csv", raise_404)

    rows, mkt_probs = fetch_one_season_with_odds(config, entry)
    assert len(rows) == 1
    assert mkt_probs == [None]


def test_fetch_training_matches_and_odds_concatenates_every_season(monkeypatch):
    config = CompetitionConfig(CONFIG_DATA)

    def fake_fetch_one_season(cfg, entry):
        return [entry["season"]], [None]
    monkeypatch.setattr(shadow_fit_odds, "fetch_one_season_with_odds", fake_fetch_one_season)

    matches, mkt_probs = fetch_training_matches_and_odds(config)
    assert matches == ["2026-27", "2025-26"]
    assert mkt_probs == [None, None]


# Same fixture as tests/test_fit_league.py's SYNTHETIC_MATCHES (proven to
# converge cleanly with the Powell optimizer -- a first attempt with a
# smaller, hand-rolled set of scorelines failed to converge here too, same
# reason that file's own docstring gives).
# [date, home, away, hg, ag, label, neutral]
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


def test_fit_shadow_models_returns_two_distinct_converged_fits():
    mkt_probs = [(0.05, 0.05, 0.9)] * len(SYNTHETIC_MATCHES)  # contradicts the goals data heavily
    dc_baseline, dc_odds_fit = fit_shadow_models(SYNTHETIC_MATCHES, mkt_probs, odds_weight=10.0)
    assert dc_baseline["converged"] is True
    assert dc_odds_fit["converged"] is True
    assert dc_baseline["attack"] != dc_odds_fit["attack"]


def test_fit_shadow_models_odds_fit_matches_baseline_at_zero_weight():
    dc_baseline, dc_odds_fit = fit_shadow_models(SYNTHETIC_MATCHES, [None] * len(SYNTHETIC_MATCHES),
                                                   odds_weight=0.0)
    assert dc_baseline["attack"] == dc_odds_fit["attack"]


DC_A = {
    "attack": {"Strong FC": 0.8, "Weak FC": -0.6, "Mid FC": 0.0},
    "defense": {"Strong FC": -0.3, "Weak FC": 0.4, "Mid FC": 0.0},
    "home_adv": 0.2, "rho": -0.1, "teams": ["Strong FC", "Weak FC", "Mid FC"],
    "converged": True,
}
DC_B = {
    "attack": {"Strong FC": 0.2, "Weak FC": 0.1, "Mid FC": 0.0},
    "defense": {"Strong FC": -0.1, "Weak FC": 0.0, "Mid FC": 0.0},
    "home_adv": 0.2, "rho": -0.1, "teams": ["Strong FC", "Weak FC", "Mid FC"],
    "converged": True,
}


def _write_schedule(base_dir, slug, schedule):
    out_dir = os.path.join(base_dir, "competitions", slug)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "schedule.json"), "w") as f:
        json.dump(schedule, f)


def test_snapshot_shadow_locks_both_models_for_a_newly_due_fixture(tmp_path):
    config = CompetitionConfig(CONFIG_DATA)
    schedule = {"Strong FC|Weak FC": {
        "date": "2026-08-16", "status": "SCHEDULED",
        "goals": {"Strong FC": None, "Weak FC": None}, "round": "Matchday 1",
    }}
    _write_schedule(str(tmp_path), "test_league", schedule)

    added = snapshot_shadow_and_save(config, str(tmp_path), DC_A, DC_B, today="2026-08-14")
    assert added == 1

    with open(tmp_path / "competitions" / "test_league" / "shadow_predictions.json") as f:
        shadow = json.load(f)
    entry = shadow["Strong FC|Weak FC"]
    assert entry["home"] == "Strong FC"
    assert "baseline" in entry and "odds_fit" in entry
    assert set(entry["baseline"]) == {"ph", "pd", "pa", "predicted_winner", "predicted_score"}
    # The two models have very different ratings for these teams, so their
    # predictions should differ -- proof both are genuinely being used.
    assert entry["baseline"] != entry["odds_fit"]


def test_snapshot_shadow_is_append_only(tmp_path):
    config = CompetitionConfig(CONFIG_DATA)
    schedule = {"Strong FC|Weak FC": {
        "date": "2026-08-16", "status": "SCHEDULED",
        "goals": {"Strong FC": None, "Weak FC": None}, "round": "Matchday 1",
    }}
    _write_schedule(str(tmp_path), "test_league", schedule)
    snapshot_shadow_and_save(config, str(tmp_path), DC_A, DC_B, today="2026-08-14")
    added_second_time = snapshot_shadow_and_save(config, str(tmp_path), DC_A, DC_B, today="2026-08-15")
    assert added_second_time == 0


def test_snapshot_shadow_skips_fixtures_not_yet_due(tmp_path):
    config = CompetitionConfig(CONFIG_DATA)
    schedule = {"Strong FC|Weak FC": {
        "date": "2026-09-01", "status": "SCHEDULED",
        "goals": {"Strong FC": None, "Weak FC": None}, "round": "Matchday 1",
    }}
    _write_schedule(str(tmp_path), "test_league", schedule)
    added = snapshot_shadow_and_save(config, str(tmp_path), DC_A, DC_B, today="2026-08-14")
    assert added == 0


def test_ensure_shadow_file_exists_creates_an_empty_file_when_missing(tmp_path):
    config = CompetitionConfig(dict(CONFIG_DATA, odds_fit_weight=0.0))
    ensure_shadow_file_exists(config, str(tmp_path))
    path = tmp_path / "competitions" / "test_league" / "shadow_predictions.json"
    assert path.exists()
    assert json.loads(path.read_text()) == {}


def test_ensure_shadow_file_exists_never_overwrites_real_data(tmp_path):
    config = CompetitionConfig(CONFIG_DATA)
    out_dir = tmp_path / "competitions" / "test_league"
    os.makedirs(out_dir, exist_ok=True)
    real_data = {"Strong FC|Weak FC": {"home": "Strong FC"}}
    (out_dir / "shadow_predictions.json").write_text(json.dumps(real_data))

    ensure_shadow_file_exists(config, str(tmp_path))

    assert json.loads((out_dir / "shadow_predictions.json").read_text()) == real_data
