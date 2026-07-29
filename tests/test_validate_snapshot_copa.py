from validate_snapshot_copa import build_schedule_for_validation


def test_build_schedule_for_validation_maps_every_fixture_to_its_date():
    fixtures = [
        {"round": "Round 1", "date": "2024-10-29", "home": "A", "away": "B",
         "score": [2, 0], "pen_score": None},
        {"round": "Semifinals", "date": "2025-02-25", "home": "C", "away": "D",
         "score": None, "pen_score": None},
    ]
    schedule = build_schedule_for_validation(fixtures)
    assert schedule == {
        "Round 1|A|B": {"date": "2024-10-29"},
        "Semifinals|C|D": {"date": "2025-02-25"},
    }
