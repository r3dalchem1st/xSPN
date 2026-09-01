import os

# Must be set (even to nothing) before import so main()'s real fetch logic
# never has a chance to run merely by importing this module in tests --
# main() itself now guards on API_KEY (see fetch_matches.py's own comment),
# so this is just belt-and-suspenders, not strictly required anymore.
os.environ.setdefault("FD_API_KEY", "")

import fetch_matches
from fetch_matches import (_apply_openfootball, _co_host_home, reconcile,
                            resolve, resolve_of)


def test_module_imports_without_an_api_key():
    # Regression test for the real bug this file's own comment documents:
    # a module-level `raise SystemExit` on no FD_API_KEY made this file
    # (the highest-traffic, most load-bearing script in the repo)
    # untestable -- nothing could even import it without a real key or a
    # faked env var. Reaching this line at all proves the import succeeded.
    assert fetch_matches is not None


def test_resolve_passes_through_a_known_team():
    assert resolve("Spain") == "Spain"


def test_resolve_maps_a_known_variant():
    assert resolve("Czech Republic") == "Czechia"
    assert resolve("Bosnia and Herzegovina") == "Bosnia"


def test_resolve_returns_none_for_unknown_name():
    assert resolve("Atlantis") is None


def test_resolve_of_passes_through_a_known_team():
    assert resolve_of("Spain") == "Spain"


def test_resolve_of_maps_a_known_variant():
    assert resolve_of("Curaçao") == "Curacao"


def test_resolve_of_returns_none_for_unresolved_ko_placeholder():
    assert resolve_of("W83") is None


GROUP_STAGE_DATE = "2026-06-15"  # before the R32 cutoff
KO_STAGE_DATE = "2026-07-04"     # after the R32 cutoff


def test_co_host_home_swaps_when_away_team_is_the_host():
    match = [GROUP_STAGE_DATE, "Spain", "USA", 1, 2, "World Cup", True]
    swapped = _co_host_home(match)
    assert swapped == [GROUP_STAGE_DATE, "USA", "Spain", 2, 1, "World Cup", False]


def test_co_host_home_leaves_match_unchanged_when_home_already_the_host():
    match = [GROUP_STAGE_DATE, "Mexico", "Spain", 1, 0, "World Cup", True]
    assert _co_host_home(match) == [GROUP_STAGE_DATE, "Mexico", "Spain", 1, 0, "World Cup", False]


def test_co_host_home_leaves_match_unchanged_when_neither_team_is_a_host():
    match = [GROUP_STAGE_DATE, "Spain", "France", 1, 0, "World Cup", True]
    assert _co_host_home(match) == match


def test_co_host_home_does_not_apply_in_the_knockout_stage():
    # Knockout venues aren't a co-host's guaranteed home venue the way
    # group-stage fixtures are -- only the group stage gets the swap.
    match = [KO_STAGE_DATE, "Spain", "USA", 1, 2, "World Cup", True]
    assert _co_host_home(match) == match


def test_co_host_home_does_not_apply_to_a_non_wc_label():
    match = [GROUP_STAGE_DATE, "Spain", "USA", 1, 2, "Nations League", True]
    assert _co_host_home(match) == match


def test_apply_openfootball_leaves_match_unchanged_with_no_cross_check_entry():
    match = ["2026-06-15", "Spain", "France", 1, 0, "World Cup", False]
    assert _apply_openfootball(match, {}) == match


def test_apply_openfootball_leaves_non_wc_match_unchanged():
    match = ["2026-06-15", "Spain", "France", 1, 0, "Nations League", False]
    of_results = {"France|Spain": {"date": "2026-06-16", "goals": {"Spain": 9, "France": 9}}}
    assert _apply_openfootball(match, of_results) == match


def test_apply_openfootball_overrides_a_disagreeing_score():
    # Regression scenario for the real Belgium-Senegal incident this
    # function's docstring documents: football-data.org's PENALTY_SHOOTOUT
    # score can combine field + shootout goals wrongly; openfootball's
    # score.et is the authoritative true field score.
    match = ["2026-06-15", "Belgium", "Senegal", 1, 0, "World Cup", True]
    of_results = {"Belgium|Senegal": {"date": "2026-06-15", "goals": {"Belgium": 3, "Senegal": 2}}}
    assert _apply_openfootball(match, of_results) == [
        "2026-06-15", "Belgium", "Senegal", 3, 2, "World Cup", True,
    ]


def test_apply_openfootball_overrides_a_disagreeing_date():
    match = ["2026-06-15", "Spain", "France", 1, 0, "World Cup", False]
    of_results = {"France|Spain": {"date": "2026-06-16", "goals": {"Spain": 1, "France": 0}}}
    assert _apply_openfootball(match, of_results) == [
        "2026-06-16", "Spain", "France", 1, 0, "World Cup", False,
    ]


def test_apply_openfootball_no_op_when_everything_already_agrees():
    match = ["2026-06-15", "Spain", "France", 1, 0, "World Cup", False]
    of_results = {"France|Spain": {"date": "2026-06-15", "goals": {"Spain": 1, "France": 0}}}
    assert _apply_openfootball(match, of_results) == match


def test_reconcile_adds_a_new_fixture():
    existing = [["2026-06-14", "Mexico", "Poland", 1, 1, "World Cup", True]]
    fresh = [["2026-06-15", "Spain", "France", 2, 0, "World Cup", False]]
    out, added, corrected = reconcile(existing, fresh)
    assert added == 1
    assert corrected == 0
    assert len(out) == 2


def test_reconcile_corrects_a_changed_score_for_the_same_fixture():
    existing = [["2026-06-15", "Spain", "France", 1, 0, "World Cup", False]]
    fresh = [["2026-06-15", "Spain", "France", 2, 0, "World Cup", False]]
    out, added, corrected = reconcile(existing, fresh)
    assert added == 0
    assert corrected == 1
    assert out == [["2026-06-15", "Spain", "France", 2, 0, "World Cup", False]]


def test_reconcile_treats_a_home_away_flip_as_the_same_fixture():
    # Unordered-pair keying: the API can report the same fixture with
    # home/away swapped between runs -- must not duplicate it.
    existing = [["2026-06-15", "Spain", "France", 1, 0, "World Cup", False]]
    fresh = [["2026-06-15", "France", "Spain", 0, 1, "World Cup", False]]
    out, added, corrected = reconcile(existing, fresh)
    assert added == 0
    assert len(out) == 1


def test_reconcile_preserves_a_cached_match_the_fresh_fetch_no_longer_returns():
    # An aged-out-of-window match (beyond football-data.org's 90-day query)
    # must survive in the cache, not be dropped.
    existing = [["2026-03-01", "Spain", "France", 1, 0, "World Cup", False]]
    out, added, corrected = reconcile(existing, [])
    assert out == existing
    assert added == 0
    assert corrected == 0
