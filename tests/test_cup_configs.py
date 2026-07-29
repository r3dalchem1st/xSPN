import os

from competition_config import load_competition

COMPETITIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "competitions",
)


def test_champions_league_config_loads():
    config = load_competition(os.path.join(COMPETITIONS_DIR, "champions_league.json"))
    assert config.slug == "champions_league"
    assert config.format == "league_phase_knockout"
    assert config.openfootball_repo == "openfootball/champions-league"
    seasons = [f["season"] for f in config.openfootball_files]
    assert seasons == sorted(seasons, reverse=True)


def test_copa_del_rey_config_loads():
    config = load_competition(os.path.join(COMPETITIONS_DIR, "copa_del_rey.json"))
    assert config.slug == "copa_del_rey"
    assert config.format == "knockout_only"
    assert config.openfootball_repo == "openfootball/espana"
    assert config.extra_training_sources  # non-empty, per the design doc
