import json
import os

import numpy as np
import pytest

from sim_copa import (ROUND_ORDER, _stage, build_played_ties,
                       known_pairs_for_round, known_tie_winner,
                       resolve_known_tie, round_entrants,
                       simulate_and_save, simulate_bracket,
                       simulate_single_match, simulate_two_legged_tie)


def _dc(strength=None):
    strength = strength or {}
    return {"attack": strength, "defense": {}, "home_adv": 0.1, "rho": -0.1}


def test_stage_maps_all_eight_real_round_labels():
    assert _stage("Preliminary round") == "preliminary"
    assert _stage("Round 1") == "round_1"
    assert _stage("Round 2") == "round_2"
    assert _stage("Round 3") == "round_3"
    assert _stage("Round of 16") == "round_of_16"
    assert _stage("Quarterfinals") == "quarterfinal"
    assert _stage("Semifinals") == "semifinal"
    assert _stage("Final") == "final"
    assert _stage("Group Stage") is None


def test_build_played_ties_decides_a_single_match_round():
    fixtures = [{"round": "Round 1", "date": "2024-10-29", "home": "A", "away": "B",
                 "score": [2, 0], "pen_score": None}]
    played = build_played_ties(fixtures)
    assert known_tie_winner("round_1", "A", "B", played) == "A"


def test_build_played_ties_decides_a_single_match_via_shootout():
    fixtures = [{"round": "Round 1", "date": "2024-10-29", "home": "A", "away": "B",
                 "score": [1, 1], "pen_score": [4, 3]}]
    played = build_played_ties(fixtures)
    assert known_tie_winner("round_1", "A", "B", played) == "A"


def test_build_played_ties_requires_both_legs_of_a_semifinal():
    fixtures = [{"round": "Semifinals", "date": "2025-02-25", "home": "A", "away": "B",
                 "score": [2, 0], "pen_score": None}]  # second leg not played yet
    played = build_played_ties(fixtures)
    assert known_tie_winner("semifinal", "A", "B", played) is None


def test_build_played_ties_decides_a_complete_semifinal_on_aggregate():
    fixtures = [
        {"round": "Semifinals", "date": "2025-02-25", "home": "B", "away": "A",
         "score": [0, 1], "pen_score": None},
        {"round": "Semifinals", "date": "2025-03-04", "home": "A", "away": "B",
         "score": [2, 0], "pen_score": None},
    ]
    played = build_played_ties(fixtures)
    assert known_tie_winner("semifinal", "A", "B", played) == "A"  # 3 aggregate vs 0


def test_round_entrants_returns_none_when_round_has_no_fixtures():
    fixtures = [{"round": "Round 1", "date": "2024-10-29", "home": "A", "away": "B",
                 "score": None, "pen_score": None}]
    assert round_entrants("round_2", fixtures) is None
    assert round_entrants("round_1", fixtures) == ["A", "B"]


def test_known_pairs_for_round_groups_legs_by_pair():
    fixtures = [
        {"round": "Semifinals", "date": "2025-02-25", "home": "A", "away": "B",
         "score": None, "pen_score": None},
        {"round": "Semifinals", "date": "2025-03-04", "home": "B", "away": "A",
         "score": None, "pen_score": None},
    ]
    pairs = known_pairs_for_round("semifinal", fixtures)
    assert len(pairs) == 1
    assert len(pairs[frozenset(("A", "B"))]) == 2


def test_resolve_known_tie_honours_a_real_result_over_simulation():
    lg = {("A", "B"): (3.0, 0.1), ("B", "A"): (0.1, 3.0)}  # would favor B if simulated
    rng = np.random.default_rng(0)
    legs = [{"round": "Round 1", "date": "2024-10-29", "home": "B", "away": "A",
             "score": [0, 5], "pen_score": None}]
    winner = resolve_known_tie("round_1", frozenset(("A", "B")), legs, {}, lg, rng)
    assert winner == "A"  # honours the real 5-0 result, not the (misleading) lambda table


def test_simulate_single_match_favors_the_better_team_on_average():
    lg = __import__("sim_league").build_lambda_table(["Strong", "Weak"], _dc({"Strong": 1.5, "Weak": -1.5}))
    rng = np.random.default_rng(0)
    wins = sum(1 for _ in range(500) if simulate_single_match("Strong", "Weak", lg, rng) == "Strong")
    assert wins > 350


def test_simulate_two_legged_tie_favors_the_better_team_on_average():
    lg = __import__("sim_league").build_lambda_table(["Strong", "Weak"], _dc({"Strong": 1.5, "Weak": -1.5}))
    rng = np.random.default_rng(0)
    wins = sum(1 for _ in range(500) if simulate_two_legged_tie("Strong", "Weak", lg, rng) == "Strong")
    assert wins > 350


def _fully_decided_single(stage_label, winner, loser, date="2025-01-01"):
    return {"round": stage_label, "date": date, "home": winner, "away": loser,
            "score": [2, 0], "pen_score": None}


def test_simulate_bracket_reproduces_a_fully_known_historical_bracket():
    # Regression test for the same class of bug sim_cup.py's own live smoke
    # test caught against 2025-26 UCL: given a FULLY decided bracket, the
    # champion must come out 100% deterministic, not re-fought with a fresh
    # random draw that only sometimes reproduces the real result.
    champ = "Real Madrid"
    stage_labels = [
        ("Preliminary round", "Minnow A"), ("Round 1", "Minnow B"),
        ("Round 2", "Minnow C"), ("Round 3", "Minnow D"),
        ("Round of 16", "Minnow E"), ("Quarterfinals", "Minnow F"),
    ]
    knockout_fixtures = [_fully_decided_single(label, champ, loser) for label, loser in stage_labels]
    knockout_fixtures += [
        {"round": "Semifinals", "date": "2025-02-01", "home": "Minnow G", "away": champ,
         "score": [0, 1], "pen_score": None},
        {"round": "Semifinals", "date": "2025-02-08", "home": champ, "away": "Minnow G",
         "score": [2, 0], "pen_score": None},
    ]
    knockout_fixtures.append(_fully_decided_single("Final", champ, "Minnow H"))

    stage_odds = simulate_bracket(knockout_fixtures, [_dc()], n_sims=50, seed=1)

    assert stage_odds[champ]["champion"] == 1.0
    for t in stage_odds:
        if t != champ:
            assert stage_odds[t]["champion"] == 0.0


def test_simulate_bracket_reached_final_counts_both_finalists():
    knockout_fixtures = [{"round": "Final", "date": "2025-04-26", "home": "A", "away": "B",
                           "score": None, "pen_score": None}]
    stage_odds = simulate_bracket(knockout_fixtures, [_dc()], n_sims=50, seed=1)
    assert stage_odds["A"]["final"] == 1.0
    assert stage_odds["B"]["final"] == 1.0


def test_simulate_bracket_league_average_fallback_favors_the_rated_team():
    knockout_fixtures = [{"round": "Round 1", "date": "2024-10-29",
                           "home": "Rated FC", "away": "Unrated Minnow",
                           "score": None, "pen_score": None}]
    dc = _dc({"Rated FC": 2.0})  # Unrated Minnow absent entirely -> league-average fallback
    stage_odds = simulate_bracket(knockout_fixtures, [dc], n_sims=300, seed=1)
    assert 0.0 <= stage_odds["Rated FC"]["champion"] <= 1.0
    assert 0.0 <= stage_odds["Unrated Minnow"]["champion"] <= 1.0
    assert stage_odds["Rated FC"]["champion"] > stage_odds["Unrated Minnow"]["champion"]


def test_simulate_bracket_raises_with_no_fixtures():
    with pytest.raises(ValueError, match="no fixtures"):
        simulate_bracket([], [_dc()])


def test_simulate_and_save_writes_copa_sim(tmp_path):
    from competition_config import CompetitionConfig
    config = CompetitionConfig({
        "slug": "copa_del_rey", "name": "Copa del Rey", "format": "knockout_only",
        "openfootball_repo": "openfootball/espana",
        "openfootball_files": [{"season": "2024-25", "path": "2024-25/cup.txt"}],
        "team_aliases": {},
    })
    out_dir = os.path.join(str(tmp_path), "competitions", config.slug)
    os.makedirs(out_dir, exist_ok=True)
    knockout_fixtures = [{"round": "Final", "date": "2025-04-26", "home": "A", "away": "B",
                           "score": None, "pen_score": None}]
    with open(os.path.join(out_dir, "knockout_fixtures.json"), "w") as f:
        json.dump(knockout_fixtures, f)
    with open(os.path.join(out_dir, "dc_ensemble.json"), "w") as f:
        json.dump([_dc({"A": 1.0})], f)

    result = simulate_and_save(config, str(tmp_path), n_sims=100, seed=1)

    assert set(result.keys()) == {"A", "B"}
    with open(os.path.join(out_dir, "copa_sim.json")) as f:
        saved = json.load(f)
    assert "champion" in saved["A"]


def test_simulate_and_save_raises_without_ensemble(tmp_path):
    from competition_config import CompetitionConfig
    config = CompetitionConfig({
        "slug": "copa_del_rey", "name": "Copa del Rey", "format": "knockout_only",
        "openfootball_repo": "openfootball/espana",
        "openfootball_files": [{"season": "2024-25", "path": "2024-25/cup.txt"}],
        "team_aliases": {},
    })
    out_dir = os.path.join(str(tmp_path), "competitions", config.slug)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "knockout_fixtures.json"), "w") as f:
        json.dump([{"round": "Final", "date": "2025-04-26", "home": "A", "away": "B",
                     "score": None, "pen_score": None}], f)
    with pytest.raises(FileNotFoundError, match="dc_ensemble.json"):
        simulate_and_save(config, str(tmp_path))
