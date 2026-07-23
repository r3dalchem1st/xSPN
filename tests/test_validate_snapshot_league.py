from validate_snapshot_league import find_violations

SCHEDULE = {
    "Strong FC|Weak FC": {"date": "2026-08-15", "status": "FINISHED",
                           "goals": {"Strong FC": 2, "Weak FC": 0}, "round": "Matchday 1"},
}


def test_find_violations_catches_snapped_at_after_real_date():
    snapshot = {
        "Strong FC|Weak FC": {"home": "Strong FC", "away": "Weak FC", "date": "2026-08-15",
                                "ph": 0.9, "pd": 0.08, "pa": 0.02,
                                "predicted_winner": "H", "predicted_score": "2-0",
                                "snapped_at": "2026-08-18"},  # AFTER the real fixture date
    }
    violations = find_violations(SCHEDULE, snapshot)
    assert len(violations) == 1
    assert "Strong FC|Weak FC" in violations[0]


def test_find_violations_passes_a_legitimately_locked_entry():
    snapshot = {
        "Strong FC|Weak FC": {"home": "Strong FC", "away": "Weak FC", "date": "2026-08-15",
                                "ph": 0.9, "pd": 0.08, "pa": 0.02,
                                "predicted_winner": "H", "predicted_score": "2-0",
                                "snapped_at": "2026-08-13"},  # BEFORE the real fixture date
    }
    assert find_violations(SCHEDULE, snapshot) == []


def test_find_violations_ignores_entries_with_no_matching_schedule_key():
    snapshot = {
        "Ghost FC|Nobody FC": {"home": "Ghost FC", "away": "Nobody FC", "date": "2026-08-15",
                                 "ph": 0.5, "pd": 0.25, "pa": 0.25,
                                 "predicted_winner": "H", "predicted_score": "1-0",
                                 "snapped_at": "2026-08-20"},
    }
    assert find_violations(SCHEDULE, snapshot) == []


def test_find_violations_fails_closed_on_unparseable_snapped_at():
    # Regression test for a real bug: an unparseable date used to be
    # silently swallowed (`except ValueError: pass`), so a corrupted
    # snapped_at value passed this gate instead of failing it -- exactly
    # backwards for a gate whose entire job is catching bad data.
    snapshot = {
        "Strong FC|Weak FC": {"home": "Strong FC", "away": "Weak FC", "date": "2026-08-15",
                                "ph": 0.9, "pd": 0.08, "pa": 0.02,
                                "predicted_winner": "H", "predicted_score": "2-0",
                                "snapped_at": "not-a-real-date"},
    }
    violations = find_violations(SCHEDULE, snapshot)
    assert len(violations) == 1
    assert "Strong FC|Weak FC" in violations[0]
    assert "unparseable" in violations[0]
