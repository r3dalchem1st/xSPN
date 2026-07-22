import os

from competition_config import load_competition

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "competitions", "premier_league.json",
)


def test_premier_league_config_loads():
    config = load_competition(CONFIG_PATH)
    assert config.slug == "premier_league"
    assert config.format == "round_robin"
    assert config.openfootball_repo == "openfootball/england"


def test_premier_league_seasons_are_newest_first():
    config = load_competition(CONFIG_PATH)
    seasons = [f["season"] for f in config.openfootball_files]
    assert seasons == sorted(seasons, reverse=True)
    assert seasons[0] == "2026-27"
