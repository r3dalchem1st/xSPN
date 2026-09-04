import json
import os

from score_shadow import score_shadow_predictions

SCHEDULE = {
    "Strong FC|Weak FC": {
        "date": "2026-08-16", "status": "FINISHED",
        "goals": {"Strong FC": 2, "Weak FC": 0}, "round": "Matchday 1",
    },
    "Mid FC|Strong FC": {
        "date": "2026-08-17", "status": "SCHEDULED",  # not played yet -- must be excluded
        "goals": {"Mid FC": None, "Strong FC": None}, "round": "Matchday 1",
    },
}

SHADOW = {
    "Strong FC|Weak FC": {
        "home": "Strong FC", "away": "Weak FC", "date": "2026-08-16", "snapped_at": "2026-08-14",
        "baseline": {"ph": 0.6, "pd": 0.25, "pa": 0.15, "predicted_winner": "H", "predicted_score": "2-0"},
        "odds_fit": {"ph": 0.8, "pd": 0.15, "pa": 0.05, "predicted_winner": "H", "predicted_score": "2-0"},
    },
    "Mid FC|Strong FC": {
        "home": "Mid FC", "away": "Strong FC", "date": "2026-08-17", "snapped_at": "2026-08-14",
        "baseline": {"ph": 0.3, "pd": 0.3, "pa": 0.4, "predicted_winner": "A", "predicted_score": "0-1"},
        "odds_fit": {"ph": 0.2, "pd": 0.3, "pa": 0.5, "predicted_winner": "A", "predicted_score": "0-1"},
    },
}


def _write(base_dir, slug, schedule, shadow):
    out_dir = os.path.join(base_dir, "competitions", slug)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "schedule.json"), "w") as f:
        json.dump(schedule, f)
    with open(os.path.join(out_dir, "shadow_predictions.json"), "w") as f:
        json.dump(shadow, f)


def test_score_shadow_only_grades_finished_fixtures(tmp_path):
    _write(str(tmp_path), "test_league", SCHEDULE, SHADOW)
    baseline, odds_fit = score_shadow_predictions(str(tmp_path), "test_league")
    assert baseline["n"] == 1  # Mid FC vs Strong FC excluded -- not FINISHED yet
    assert odds_fit["n"] == 1


def test_score_shadow_computes_accuracy_and_brier_per_column(tmp_path):
    _write(str(tmp_path), "test_league", SCHEDULE, SHADOW)
    baseline, odds_fit = score_shadow_predictions(str(tmp_path), "test_league")
    assert baseline["accuracy"] == 1.0  # both correctly predicted the home win
    assert odds_fit["accuracy"] == 1.0
    # odds_fit was MORE confident in the correct outcome (0.8 vs 0.6) -- lower Brier.
    assert odds_fit["brier"] < baseline["brier"]


def test_score_shadow_returns_none_metrics_when_nothing_graded(tmp_path):
    _write(str(tmp_path), "test_league", {}, {})
    baseline, odds_fit = score_shadow_predictions(str(tmp_path), "test_league")
    assert baseline["n"] == 0
    assert baseline["accuracy"] is None
