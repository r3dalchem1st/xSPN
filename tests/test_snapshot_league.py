import json
import os

from competition_config import CompetitionConfig
from snapshot_league import LOCK_WINDOW_DAYS, fixture_due, hda_probs, likely_score, snapshot_and_save


def test_lock_window_is_wide_enough_to_survive_a_few_missed_daily_runs():
    # Regression test for a real bug: LOCK_WINDOW_DAYS=2 with a once-daily
    # workflow left almost no redundancy — a single missed/failed run could
    # let a fixture flip to FINISHED before ever being locked, permanently
    # skipping it (fixture_due() only matches SCHEDULED fixtures, so there's
    # no retroactive catch-up). Pin the default itself, not just the
    # explicit-argument test cases below, so a future accidental narrowing
    # doesn't slip through unnoticed.
    assert LOCK_WINDOW_DAYS >= 5

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


def test_hda_probs_default_args_match_explicit_no_op_args():
    # rhos=None, delta=0.0 must be exactly equivalent to omitting both --
    # every pre-calibration caller relies on this being a true no-op.
    from sim_league import build_lambda_tables
    lg_ens = build_lambda_tables(["Strong FC", "Weak FC"], [DC_SAMPLE])
    default = hda_probs("Strong FC", "Weak FC", lg_ens)
    explicit = hda_probs("Strong FC", "Weak FC", lg_ens, rhos=None, delta=0.0)
    assert default == explicit


def test_hda_probs_delta_boosts_draw_probability():
    from sim_league import build_lambda_tables
    lg_ens = build_lambda_tables(["Strong FC", "Weak FC"], [DC_SAMPLE])
    _, pd_no_inflate, _ = hda_probs("Strong FC", "Weak FC", lg_ens)
    _, pd_inflated, _ = hda_probs("Strong FC", "Weak FC", lg_ens, delta=0.5)
    assert pd_inflated > pd_no_inflate


def test_hda_probs_rhos_list_changes_the_prediction():
    from sim_league import build_lambda_tables
    lg_ens = build_lambda_tables(["Strong FC", "Weak FC"], [DC_SAMPLE, DC_SAMPLE])
    without_rho = hda_probs("Strong FC", "Weak FC", lg_ens)
    with_rho = hda_probs("Strong FC", "Weak FC", lg_ens, rhos=[-0.15, -0.15])
    assert without_rho != with_rho
    assert abs(sum(with_rho) - 1.0) < 1e-9


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


MOMENTUM_CONFIG_DATA = {
    "slug": "test_league", "name": "Test League", "format": "round_robin",
    "openfootball_repo": "openfootball/example",
    "openfootball_files": [{"season": "2026-27", "path": "2026-27/1-test.txt"}],
    "team_aliases": {},
}


def _write_league_files(base_dir, slug, schedule, matches):
    out_dir = os.path.join(base_dir, "competitions", slug)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "schedule.json"), "w") as f:
        json.dump(schedule, f)
    with open(os.path.join(out_dir, "fetched_matches.json"), "w") as f:
        json.dump(matches, f)


def test_snapshot_and_save_uses_momentum_when_configured(tmp_path):
    # Weak FC has been on a hot streak; with momentum enabled it should be
    # a stronger favorite (or at least a less lopsided underdog) at home
    # against Strong FC than with momentum off, end-to-end through
    # snapshot_and_save -- not just at the build_lambda_table unit level.
    schedule = {"Weak FC|Strong FC": {
        "date": "2026-08-16", "status": "SCHEDULED",
        "goals": {"Weak FC": None, "Strong FC": None}, "round": "Matchday 1",
    }}
    hot_streak = [
        ["2026-07-01", "Weak FC", "Strong FC", 4, 0, "Test League", False],
        ["2026-07-08", "Weak FC", "Strong FC", 3, 0, "Test League", False],
    ]

    no_momentum_dir = str(tmp_path / "no_momentum")
    _write_league_files(no_momentum_dir, "test_league", schedule, hot_streak)
    config_off = CompetitionConfig(MOMENTUM_CONFIG_DATA)
    snapshot_and_save(config_off, no_momentum_dir, [DC_SAMPLE], today="2026-08-14")
    with open(os.path.join(no_momentum_dir, "competitions", "test_league",
                            "predictions_snapshot.json")) as f:
        snap_off = json.load(f)["Weak FC|Strong FC"]

    momentum_dir = str(tmp_path / "momentum")
    _write_league_files(momentum_dir, "test_league", schedule, hot_streak)
    config_on = CompetitionConfig(dict(MOMENTUM_CONFIG_DATA, momentum_weight=0.1, momentum_n=3))
    snapshot_and_save(config_on, momentum_dir, [DC_SAMPLE], today="2026-08-14")
    with open(os.path.join(momentum_dir, "competitions", "test_league",
                            "predictions_snapshot.json")) as f:
        snap_on = json.load(f)["Weak FC|Strong FC"]

    assert snap_on["ph"] > snap_off["ph"]  # Weak FC's home win chance rises with momentum on


MARKET_CONFIG_DATA = dict(MOMENTUM_CONFIG_DATA, odds_api_sport_key="soccer_test")
DUE_SCHEDULE = {"Weak FC|Strong FC": {
    "date": "2026-08-16", "status": "SCHEDULED",
    "goals": {"Weak FC": None, "Strong FC": None}, "round": "Matchday 1",
}}


def _run_snapshot(tmp_path, name, config_data, schedule, **kwargs):
    base = str(tmp_path / name)
    _write_league_files(base, "test_league", schedule, [])
    snapshot_and_save(CompetitionConfig(config_data), base, [DC_SAMPLE], today="2026-08-14", **kwargs)
    with open(os.path.join(base, "competitions", "test_league", "predictions_snapshot.json")) as f:
        return json.load(f)


def test_snapshot_records_the_market_without_changing_the_prediction(tmp_path):
    # The market is recorded NEXT TO the model's number, never into it --
    # replacing the model's prediction with the bookmaker's was tried and
    # deliberately reverted (CONTEXT.md, 4 Sep).
    plain = _run_snapshot(tmp_path, "plain", MARKET_CONFIG_DATA, DUE_SCHEDULE, odds_lookup={})
    with_market = _run_snapshot(tmp_path, "market", MARKET_CONFIG_DATA, DUE_SCHEDULE,
                                odds_lookup={("Weak FC", "Strong FC"): (0.2, 0.3, 0.5)})
    a, b = plain["Weak FC|Strong FC"], with_market["Weak FC|Strong FC"]
    assert {k: b[k] for k in a} == a  # every pre-existing field identical
    assert b["market"] == {"ph": 0.2, "pd": 0.3, "pa": 0.5}


def test_snapshot_has_no_market_field_for_a_fixture_the_market_didnt_cover(tmp_path):
    snap = _run_snapshot(tmp_path, "gap", MARKET_CONFIG_DATA, DUE_SCHEDULE,
                         odds_lookup={("Other FC", "Another FC"): (0.4, 0.3, 0.3)})
    assert "market" not in snap["Weak FC|Strong FC"]


def _raw_odds_fixture(home, away):
    return {"home_team": home, "away_team": away, "bookmakers": [
        {"key": "b", "markets": [{"key": "h2h", "outcomes": [
            {"name": home, "price": 2.0}, {"name": away, "price": 4.0}, {"name": "Draw", "price": 3.5}]}]}]}


def test_snapshot_fetches_odds_once_when_a_fixture_is_due(tmp_path, monkeypatch):
    import snapshot_league
    calls = []
    monkeypatch.setattr(snapshot_league, "fetch_upcoming_odds",
                        lambda key: calls.append(key) or [_raw_odds_fixture("Weak FC", "Strong FC")])
    snap = _run_snapshot(tmp_path, "due", MARKET_CONFIG_DATA, DUE_SCHEDULE)
    assert calls == ["soccer_test"]
    m = snap["Weak FC|Strong FC"]["market"]
    assert abs(m["ph"] + m["pd"] + m["pa"] - 1.0) < 1e-9 and m["ph"] > m["pa"]


def test_snapshot_does_not_spend_an_odds_call_when_nothing_is_due(tmp_path, monkeypatch):
    # Free tier is 500 requests/month and the daily pipeline runs twice a day
    # per league -- odds are only needed at lock time, so don't fetch otherwise.
    import snapshot_league
    monkeypatch.setattr(snapshot_league, "fetch_upcoming_odds",
                        lambda key: (_ for _ in ()).throw(AssertionError("odds fetched with nothing due")))
    far = {"Weak FC|Strong FC": dict(DUE_SCHEDULE["Weak FC|Strong FC"], date="2026-12-01")}
    assert _run_snapshot(tmp_path, "far", MARKET_CONFIG_DATA, far) == {}


def test_snapshot_never_fetches_odds_without_a_sport_key(tmp_path, monkeypatch):
    import snapshot_league
    monkeypatch.setattr(snapshot_league, "fetch_upcoming_odds",
                        lambda key: (_ for _ in ()).throw(AssertionError("odds fetched without a sport key")))
    snap = _run_snapshot(tmp_path, "nokey", MOMENTUM_CONFIG_DATA, DUE_SCHEDULE)
    assert "market" not in snap["Weak FC|Strong FC"]
