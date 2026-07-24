import json
import os

import numpy as np
import pytest

from sim_cup import (build_played_ties, known_tie_winner, simulate_and_save,
                      simulate_final, simulate_knockout_stage,
                      simulate_season_and_knockout, simulate_two_legged_tie,
                      _bracket_round)


def _dc(teams, strength):
    """A minimal Dixon-Coles dict: `strength` maps team -> attack rating
    (higher = better), defense held at 0 for every team so relative
    strength is driven purely by attack, same simplification style as
    test_sim_league.py's DC_SAMPLE fixture."""
    return {
        "attack": {t: strength.get(t, 0.0) for t in teams},
        "defense": {t: 0.0 for t in teams},
        "home_adv": 0.1,
        "rho": -0.1,
        "teams": teams,
    }


def test_bracket_round_handles_both_label_conventions():
    assert _bracket_round("Playoffs, Matchday 1") == "playoff"
    assert _bracket_round("Finals, Round of 16") == "round_of_16"
    assert _bracket_round("Round of 16") == "round_of_16"
    assert _bracket_round("Finals, Quarterfinals") == "quarterfinal"
    assert _bracket_round("Quarterfinals") == "quarterfinal"
    assert _bracket_round("Finals, Semifinals") == "semifinal"
    assert _bracket_round("Semifinals") == "semifinal"
    assert _bracket_round("Finals, Final") == "final"
    assert _bracket_round("Final") == "final"
    assert _bracket_round("League, Matchday 1") is None


def test_build_played_ties_decides_a_complete_two_legged_tie():
    fixtures = [
        {"round": "Playoffs, Matchday 1", "date": "2027-02-17", "home": "A", "away": "B",
         "score": [2, 0], "pen_score": None},
        {"round": "Playoffs, Matchday 2", "date": "2027-02-24", "home": "B", "away": "A",
         "score": [1, 0], "pen_score": None},
    ]
    played = build_played_ties(fixtures)
    assert known_tie_winner("A", "B", played) == "A"  # 2 aggregate vs 1


def test_build_played_ties_uses_shootout_when_aggregate_is_level():
    fixtures = [
        {"round": "Finals, Round of 16", "date": "2027-03-10", "home": "A", "away": "B",
         "score": [1, 0], "pen_score": None},
        {"round": "Finals, Round of 16", "date": "2027-03-17", "home": "B", "away": "A",
         "score": [1, 0], "pen_score": [3, 4]},  # aggregate 1-1, decided on pens
    ]
    played = build_played_ties(fixtures)
    assert known_tie_winner("A", "B", played) == "A"  # A won the shootout 4-3


def test_build_played_ties_leaves_a_single_played_leg_undecided():
    fixtures = [
        {"round": "Playoffs, Matchday 1", "date": "2027-02-17", "home": "A", "away": "B",
         "score": [2, 0], "pen_score": None},
        # second leg not played yet
    ]
    played = build_played_ties(fixtures)
    assert known_tie_winner("A", "B", played) is None


def test_build_played_ties_decides_a_single_match_final():
    fixtures = [
        {"round": "Finals, Final", "date": "2027-05-30", "home": "A", "away": "B",
         "score": [1, 1], "pen_score": [4, 3]},
    ]
    played = build_played_ties(fixtures)
    assert known_tie_winner("A", "B", played) == "A"


def test_simulate_two_legged_tie_favors_the_better_team_on_average():
    dc = _dc(["Strong", "Weak"], {"Strong": 1.2, "Weak": -1.2})
    lg = __import__("sim_league").build_lambda_table(["Strong", "Weak"], dc)
    rng = np.random.default_rng(0)
    wins = sum(1 for _ in range(500) if simulate_two_legged_tie("Strong", "Weak", lg, rng) == "Strong")
    assert wins > 350  # clearly favored, generous stochastic tolerance


def test_simulate_two_legged_tie_coin_flips_an_identical_matchup():
    dc = _dc(["A", "B"], {"A": 0.0, "B": 0.0})
    lg = __import__("sim_league").build_lambda_table(["A", "B"], dc)
    rng = np.random.default_rng(0)
    wins_a = sum(1 for _ in range(1000) if simulate_two_legged_tie("A", "B", lg, rng) == "A")
    assert 400 < wins_a < 600  # roughly 50/50 for two identically-rated teams


def test_known_tie_winner_short_circuits_simulation():
    # "Weak" is pre-decided as the winner despite being far worse-rated --
    # proves a known result is honoured rather than re-simulated.
    dc = _dc(["Strong", "Weak"], {"Strong": 3.0, "Weak": -3.0})
    lg = __import__("sim_league").build_lambda_table(["Strong", "Weak"], dc)
    rng = np.random.default_rng(0)
    played = {frozenset(("Strong", "Weak")): "Weak"}
    for _ in range(20):
        winner = known_tie_winner("Strong", "Weak", played) or simulate_two_legged_tie("Strong", "Weak", lg, rng)
        assert winner == "Weak"


def test_simulate_knockout_stage_marks_reached_stages_correctly():
    teams = [f"T{i}" for i in range(16)]
    strength = {t: 1.0 - 0.1 * i for i, t in enumerate(teams)}  # T0 strongest .. T15 weakest
    dc = _dc(teams, strength)
    lg = __import__("sim_league").build_lambda_table(teams, dc)
    rank_of = {t: i for i, t in enumerate(teams)}
    rng = np.random.default_rng(1)
    reached, champion = simulate_knockout_stage(teams, rank_of, lg, rng, {}, {})
    assert all(reached[t]["round_of_16"] for t in teams)
    quarterfinalists = [t for t in teams if reached[t]["quarterfinal"]]
    assert len(quarterfinalists) == 8
    semifinalists = [t for t in teams if reached[t]["semifinal"]]
    assert len(semifinalists) == 4
    finalists = [t for t in teams if reached[t]["final"]]
    assert len(finalists) == 2
    assert champion in finalists


def _make_league_teams(n, strength_step=0.15):
    teams = [f"Team{i:02d}" for i in range(n)]
    strength = {t: (n - i) * strength_step for i, t in enumerate(teams)}  # Team00 strongest
    return teams, strength


def test_simulate_season_and_knockout_zone_odds_sum_to_one():
    teams, strength = _make_league_teams(28)
    dc = _dc(teams, strength)
    remaining = [(teams[i], teams[i + 1]) for i in range(0, len(teams) - 1, 2)]
    zone_odds, stage_odds, expected_pos = simulate_season_and_knockout(
        teams, {}, remaining, [dc], n_sims=300, seed=1)
    for t in teams:
        total = sum(zone_odds[t].values())
        assert abs(total - 1.0) < 1e-9


def test_simulate_season_and_knockout_expected_pos_favors_the_stronger_team():
    teams, strength = _make_league_teams(28)
    dc = _dc(teams, strength)
    remaining = [(teams[i], teams[i + 1]) for i in range(0, len(teams) - 1, 2)]
    zone_odds, stage_odds, expected_pos = simulate_season_and_knockout(
        teams, {}, remaining, [dc], n_sims=300, seed=1)
    assert expected_pos["Team00"] < expected_pos["Team27"]  # lower = better position
    assert 1.0 <= expected_pos["Team00"] <= 28.0


def test_simulate_season_and_knockout_favors_the_stronger_team_for_the_title():
    teams, strength = _make_league_teams(28)
    dc = _dc(teams, strength)
    remaining = [(teams[i], teams[i + 1]) for i in range(0, len(teams) - 1, 2)]
    zone_odds, stage_odds, expected_pos = simulate_season_and_knockout(
        teams, {}, remaining, [dc], n_sims=800, seed=1)
    assert zone_odds["Team00"]["top8"] > zone_odds["Team27"]["top8"]
    assert stage_odds["Team00"]["champion"] > stage_odds["Team27"]["champion"]


CUP_CONFIG_DATA = {
    "slug": "test_cup", "name": "Test Cup", "format": "league_phase_knockout",
    "openfootball_repo": "openfootball/example",
    "openfootball_files": [{"season": "2026-27", "path": "2026-27/cup.txt"}],
    "team_aliases": {},
}


def test_simulate_and_save_writes_cup_sim(tmp_path):
    from competition_config import CompetitionConfig
    config = CompetitionConfig(CUP_CONFIG_DATA)
    teams, strength = _make_league_teams(28)
    dc = _dc(teams, strength)
    out_dir = os.path.join(str(tmp_path), "competitions", config.slug)
    os.makedirs(out_dir, exist_ok=True)
    schedule = {}
    for i in range(0, len(teams) - 1, 2):
        schedule[f"{teams[i]}|{teams[i+1]}"] = {
            "date": "2026-12-01", "status": "SCHEDULED",
            "goals": {teams[i]: None, teams[i + 1]: None}, "round": "League, Matchday 8",
        }
    with open(os.path.join(out_dir, "league_schedule.json"), "w") as f:
        json.dump(schedule, f)
    with open(os.path.join(out_dir, "dc_ensemble.json"), "w") as f:
        json.dump([dc], f)

    result = simulate_and_save(config, str(tmp_path), n_sims=100, seed=1)

    assert set(result["zone_odds"].keys()) == set(teams)
    with open(os.path.join(out_dir, "cup_sim.json")) as f:
        saved = json.load(f)
    assert "zone_odds" in saved and "stage_odds" in saved


def test_simulate_and_save_raises_without_ensemble(tmp_path):
    from competition_config import CompetitionConfig
    config = CompetitionConfig(CUP_CONFIG_DATA)
    out_dir = os.path.join(str(tmp_path), "competitions", config.slug)
    os.makedirs(out_dir, exist_ok=True)
    teams, _ = _make_league_teams(28)
    schedule = {f"{teams[0]}|{teams[1]}": {
        "date": "2026-12-01", "status": "SCHEDULED",
        "goals": {teams[0]: None, teams[1]: None}, "round": "League, Matchday 8",
    }}
    with open(os.path.join(out_dir, "league_schedule.json"), "w") as f:
        json.dump(schedule, f)
    with pytest.raises(FileNotFoundError, match="dc_ensemble.json"):
        simulate_and_save(config, str(tmp_path))


def _two_legs(round_label, higher, lower, date1="2027-02-17", date2="2027-02-24"):
    """Two legs of a tie already decided in the higher-seeded team's favour
    (aggregate 3-0), in the exact knockout_fixtures.json shape."""
    return [
        {"round": round_label, "date": date1, "home": lower, "away": higher,
         "score": [0, 1], "pen_score": None},
        {"round": round_label, "date": date2, "home": higher, "away": lower,
         "score": [2, 0], "pen_score": None},
    ]


def test_simulate_season_and_knockout_reproduces_a_fully_known_historical_bracket():
    # Regression test for the real bug a live smoke test caught: against a
    # FULLY CONCLUDED season (every tie already decided in knockout_fixtures.json),
    # the champion must come out 100% deterministic -- not re-fought with a
    # fresh random draw that only occasionally reproduces the real bracket.
    teams, strength = _make_league_teams(28)
    dc = _dc(teams, strength)
    # standings already fully final (no remaining fixtures) -- points strictly
    # descending by team index, so the league-phase order is deterministic.
    standings = {t: {"pts": (28 - i) * 3, "gd": 0, "gf": 0} for i, t in enumerate(teams)}
    top8, playoff_zone = teams[:8], teams[8:24]

    knockout_fixtures = []
    playoff_winners = []
    for i in range(8):
        higher, lower = playoff_zone[i], playoff_zone[15 - i]  # 9v24, 10v23, ...
        knockout_fixtures += _two_legs("Playoffs, Matchday", higher, lower)
        playoff_winners.append(higher)

    r16_field = top8 + playoff_winners  # Team00..Team15
    r16_pairs = [(r16_field[i], r16_field[i + 1]) for i in range(0, 16, 2)]
    qf_field = []
    for higher, lower in r16_pairs:
        knockout_fixtures += _two_legs("Finals, Round of 16", higher, lower)
        qf_field.append(higher)  # lower-index (stronger) team always advances

    qf_pairs = [(qf_field[i], qf_field[i + 1]) for i in range(0, 8, 2)]
    sf_field = []
    for higher, lower in qf_pairs:
        knockout_fixtures += _two_legs("Finals, Quarterfinals", higher, lower)
        sf_field.append(higher)

    sf_pairs = [(sf_field[i], sf_field[i + 1]) for i in range(0, 4, 2)]
    finalists = []
    for higher, lower in sf_pairs:
        knockout_fixtures += _two_legs("Finals, Semifinals", higher, lower)
        finalists.append(higher)

    knockout_fixtures.append({"round": "Finals, Final", "date": "2027-05-30",
                               "home": finalists[0], "away": finalists[1],
                               "score": [2, 0], "pen_score": None})
    expected_champion = finalists[0]  # Team00 -- survives every deterministic round

    zone_odds, stage_odds, expected_pos = simulate_season_and_knockout(
        teams, standings, [], [dc], knockout_fixtures=knockout_fixtures, n_sims=200, seed=1)

    assert stage_odds[expected_champion]["champion"] == 1.0
    for t in teams:
        if t != expected_champion:
            assert stage_odds[t]["champion"] == 0.0


def test_simulate_and_save_raises_with_too_few_teams(tmp_path):
    from competition_config import CompetitionConfig
    config = CompetitionConfig(CUP_CONFIG_DATA)
    out_dir = os.path.join(str(tmp_path), "competitions", config.slug)
    os.makedirs(out_dir, exist_ok=True)
    schedule = {"A|B": {"date": "2026-12-01", "status": "SCHEDULED",
                         "goals": {"A": None, "B": None}, "round": "League, Matchday 1"}}
    with open(os.path.join(out_dir, "league_schedule.json"), "w") as f:
        json.dump(schedule, f)
    with open(os.path.join(out_dir, "dc_ensemble.json"), "w") as f:
        json.dump([_dc(["A", "B"], {})], f)
    with pytest.raises(ValueError, match="need at least"):
        simulate_and_save(config, str(tmp_path))
