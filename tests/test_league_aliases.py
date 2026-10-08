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


# Team names exactly as The Odds API returned them on 2026-09-04 (one list
# per league's sport_key). Every one must resolve to a team in that league's
# real, committed 2026-27 schedule -- an unresolved name silently drops that
# fixture's market odds. Revisit at season rollover, when the team set changes.
ODDS_API_NAMES = {
    "premier_league": ["Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton and Hove Albion",
                       "Chelsea", "Coventry City", "Crystal Palace", "Everton", "Fulham", "Hull City",
                       "Ipswich Town", "Leeds United", "Liverpool", "Manchester City", "Manchester United",
                       "Newcastle United", "Nottingham Forest", "Sunderland", "Tottenham Hotspur"],
    "la_liga": ["Alavés", "Athletic Bilbao", "Atlético Madrid", "Barcelona", "CA Osasuna", "Celta Vigo",
                "Deportivo La Coruña", "Elche CF", "Espanyol", "Getafe", "Levante", "Málaga",
                "Rayo Vallecano", "Real Betis", "Real Madrid", "Real Racing Club de Santander",
                "Real Sociedad", "Sevilla", "Valencia", "Villarreal"],
    "bundesliga": ["1. FC Köln", "Augsburg", "Bayer Leverkusen", "Bayern Munich", "Borussia Dortmund",
                   "Borussia Monchengladbach", "Eintracht Frankfurt", "Elversberg", "FC Schalke 04",
                   "FSV Mainz 05", "Hamburger SV", "RB Leipzig", "SC Freiburg", "SC Paderborn",
                   "TSG Hoffenheim", "Union Berlin", "VfB Stuttgart", "Werder Bremen"],
}


def test_every_odds_api_team_name_resolves_to_a_real_team_in_the_schedule():
    import json
    for slug, names in ODDS_API_NAMES.items():
        config = _config(slug)
        with open(os.path.join(ROOT, "competitions", slug, "schedule.json"), encoding="utf-8") as f:
            teams = {t for key in json.load(f) for t in key.split("|")}
        unresolved = [n for n in names if config.resolve_team(n) not in teams]
        assert unresolved == [], f"{slug}: {unresolved}"


def test_odds_api_sport_keys_are_set_for_the_three_leagues():
    assert _config("premier_league").odds_api_sport_key == "soccer_epl"
    assert _config("la_liga").odds_api_sport_key == "soccer_spain_la_liga"
    assert _config("bundesliga").odds_api_sport_key == "soccer_germany_bundesliga"
