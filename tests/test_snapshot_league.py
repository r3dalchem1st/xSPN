import json
import os

from snapshot_league import fixture_due, hda_probs, likely_score

DC_SAMPLE = {
    "attack": {"Strong FC": 0.8, "Weak FC": -0.6},
    "defense": {"Strong FC": -0.3, "Weak FC": 0.4},
    "home_adv": 0.2,
    "rho": -0.1,
    "teams": ["Strong FC", "Weak FC"],
}


def test_hda_probs_sums_to_one_and_favors_stronger_team():
    from sim_league import build_lambda_tables
    lg_ens = build_lambda_tables(["Strong FC", "Weak FC"], [DC_SAMPLE])
    ph, pd, pa = hda_probs("Strong FC", "Weak FC", lg_ens)
    assert abs((ph + pd + pa) - 1.0) < 1e-9
    assert ph > pa  # Strong FC at home should be favored over Weak FC away


def test_likely_score_respects_allowed_outcomes():
    hg, ag = likely_score(2.0, 0.5, allowed={"H"})
    assert hg > ag
    hg2, ag2 = likely_score(2.0, 0.5, allowed={"D"})
    assert hg2 == ag2


def test_fixture_due_within_window():
    assert fixture_due("2026-08-15", "2026-08-13", lock_window_days=2) is True
    assert fixture_due("2026-08-20", "2026-08-13", lock_window_days=2) is False  # too far out


def test_fixture_due_rejects_past_dates():
    # A fixture whose real date has already passed must never be "due" --
    # locking it now would fabricate hindsight (copy a now-known result in
    # as a fake pre-match "prediction"). Mirrors snapshot_predictions.py's
    # fixture_due() lower bound, added after a real WC incident (6 Jul,
    # see CONTEXT.md) -- written in from day one here, not after a repeat.
    assert fixture_due("2026-08-10", "2026-08-13", lock_window_days=2) is False


def test_fixture_due_handles_malformed_date():
    assert fixture_due("not-a-date", "2026-08-13") is False
