from validate_snapshot_cup import build_combined_schedule
from validate_snapshot_league import find_violations

LEAGUE_SCHEDULE = {
    "Strong FC|Weak FC": {"date": "2026-09-16", "status": "FINISHED",
                           "goals": {"Strong FC": 2, "Weak FC": 0}, "round": "League, Matchday 1"},
}
KNOCKOUT_FIXTURES = [
    {"round": "Finals, Final", "date": "2027-05-30", "home": "Strong FC", "away": "Weak FC",
     "score": [1, 1], "pen_score": [4, 3]},
]


def test_build_combined_schedule_covers_both_artifacts():
    schedule = build_combined_schedule(LEAGUE_SCHEDULE, KNOCKOUT_FIXTURES)
    assert schedule["Strong FC|Weak FC"]["date"] == "2026-09-16"
    assert schedule["Finals, Final|Strong FC|Weak FC"]["date"] == "2027-05-30"


def test_combined_schedule_catches_a_fabricated_knockout_lock():
    schedule = build_combined_schedule(LEAGUE_SCHEDULE, KNOCKOUT_FIXTURES)
    snapshot = {
        "Finals, Final|Strong FC|Weak FC": {
            "home": "Strong FC", "away": "Weak FC", "date": "2027-05-30",
            "ph": 0.6, "pd": 0.25, "pa": 0.15, "predicted_winner": "H",
            "predicted_score": "2-1", "snapped_at": "2027-06-01",  # AFTER the real date
        },
    }
    violations = find_violations(schedule, snapshot)
    assert len(violations) == 1
    assert "Finals, Final|Strong FC|Weak FC" in violations[0]
