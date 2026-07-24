from list_competitions import list_competition_slugs


def test_list_competition_slugs_finds_json_files(tmp_path):
    comp_dir = tmp_path / "competitions"
    comp_dir.mkdir()
    (comp_dir / "premier_league.json").write_text("{}")
    (comp_dir / "bundesliga.json").write_text("{}")
    slugs = list_competition_slugs(str(tmp_path))
    assert slugs == ["bundesliga", "premier_league"]  # sorted, deterministic


def test_list_competition_slugs_empty_when_no_configs(tmp_path):
    (tmp_path / "competitions").mkdir()
    assert list_competition_slugs(str(tmp_path)) == []


def test_list_competition_slugs_ignores_non_json_files(tmp_path):
    comp_dir = tmp_path / "competitions"
    comp_dir.mkdir()
    (comp_dir / "premier_league.json").write_text("{}")
    (comp_dir / "README.md").write_text("notes")
    assert list_competition_slugs(str(tmp_path)) == ["premier_league"]


def _write_config(comp_dir, filename, slug, fmt):
    import json
    (comp_dir / filename).write_text(json.dumps({
        "slug": slug, "name": slug, "format": fmt,
        "openfootball_repo": "openfootball/x", "openfootball_files": [{"season": "x", "path": "x"}],
        "team_aliases": {},
    }))


def test_list_competition_slugs_filters_by_format(tmp_path):
    comp_dir = tmp_path / "competitions"
    comp_dir.mkdir()
    _write_config(comp_dir, "premier_league.json", "premier_league", "round_robin")
    _write_config(comp_dir, "bundesliga.json", "bundesliga", "round_robin")
    _write_config(comp_dir, "champions_league.json", "champions_league", "league_phase_knockout")
    assert list_competition_slugs(str(tmp_path), fmt="round_robin") == ["bundesliga", "premier_league"]
    assert list_competition_slugs(str(tmp_path), fmt="league_phase_knockout") == ["champions_league"]
    assert list_competition_slugs(str(tmp_path), fmt="knockout_only") == []
