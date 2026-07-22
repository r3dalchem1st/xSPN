import json

import pytest

from competition_config import CompetitionConfig, load_competition

VALID_DATA = {
    "slug": "premier_league",
    "name": "Premier League",
    "format": "round_robin",
    "openfootball_repo": "openfootball/england",
    "openfootball_files": [{"season": "2026-27", "path": "2026-27/1-premierleague.txt"}],
    "team_aliases": {"Man United": "Manchester United FC"},
}


def test_load_valid_config():
    config = CompetitionConfig(VALID_DATA)
    assert config.slug == "premier_league"
    assert config.format == "round_robin"
    assert config.openfootball_files[0]["path"] == "2026-27/1-premierleague.txt"


def test_missing_required_field_raises():
    bad = {k: v for k, v in VALID_DATA.items() if k != "openfootball_repo"}
    with pytest.raises(ValueError, match="openfootball_repo"):
        CompetitionConfig(bad)


def test_invalid_format_raises():
    bad = dict(VALID_DATA, format="single_elimination_ladder")
    with pytest.raises(ValueError, match="unknown format"):
        CompetitionConfig(bad)


def test_empty_openfootball_files_raises():
    bad = dict(VALID_DATA, openfootball_files=[])
    with pytest.raises(ValueError, match="openfootball_files"):
        CompetitionConfig(bad)


def test_resolve_team_applies_alias():
    config = CompetitionConfig(VALID_DATA)
    assert config.resolve_team("Man United") == "Manchester United FC"


def test_resolve_team_passthrough_when_no_roster():
    config = CompetitionConfig(VALID_DATA)
    assert config.resolve_team("Fulham FC") == "Fulham FC"


def test_resolve_team_rejects_unknown_when_roster_set():
    data = dict(VALID_DATA, teams=["Manchester United FC", "Fulham FC"])
    config = CompetitionConfig(data)
    assert config.resolve_team("Some Random FC") is None
    assert config.resolve_team("Fulham FC") == "Fulham FC"


def test_load_competition_from_file(tmp_path):
    p = tmp_path / "premier_league.json"
    p.write_text(json.dumps(VALID_DATA))
    config = load_competition(str(p))
    assert config.name == "Premier League"
