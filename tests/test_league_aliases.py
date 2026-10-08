import os

from competition_config import load_competition

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _config(slug):
    return load_competition(os.path.join(ROOT, "competitions", f"{slug}.json"))


def test_premier_league_name_forms_of_one_club_resolve_to_one_team():
    # openfootball's 2025-26 file drops the "FC" suffix its 2024-25 file uses;
    # unaliased, each club was trained as two separate teams AND failed to join
    # football-data.co.uk's odds (found by comparing team sets across seasons).
    config = _config("premier_league")
    for forms, canonical in [
        (["West Ham United", "West Ham United FC", "West Ham"], "West Ham United FC"),
        (["Wolverhampton Wanderers", "Wolverhampton Wanderers FC", "Wolves"], "Wolverhampton Wanderers FC"),
    ]:
        assert {config.resolve_team(f) for f in forms} == {canonical}


def test_bundesliga_st_pauli_name_forms_resolve_to_one_team():
    config = _config("bundesliga")
    assert {config.resolve_team(f) for f in ["St. Pauli", "FC St. Pauli 1910", "St Pauli"]} == {"FC St. Pauli 1910"}


def test_la_liga_oviedo_odds_name_resolves_to_the_openfootball_name():
    config = _config("la_liga")
    assert config.resolve_team("Oviedo") == config.resolve_team("Real Oviedo") == "Real Oviedo"
