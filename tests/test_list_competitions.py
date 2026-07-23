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
