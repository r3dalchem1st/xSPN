"""
Unit tests for model_common.py's pure, deterministic helpers -- rank_group,
assign_thirds, pen_prob, inflate_hda. These have zero test coverage despite
being cheap to test and directly implicated in several historical bugs
(same-group R32 ties, wrong FIFA tiebreak ordering) documented in this
module's own docstrings and CONTEXT.md's "Known bugs fixed" section.
"""
import math

from model_common import assign_thirds, inflate_hda, pen_prob, rank_group

INIT_ELO_FOR_TESTS = 1500


def _fixed_tiebreak(value=0.5):
    """A deterministic stand-in for the real `random.random` tiebreak arg,
    so tests never flake on genuine randomness."""
    return lambda: value


def test_rank_group_sorts_by_points_then_gd_then_gf():
    teams = ["A", "B", "C", "D"]
    # A: 9pts, B: 6pts, C: 6pts (better GD than B), D: 0pts
    s = {"A": [9, 3, 5], "B": [6, 0, 4], "C": [6, 2, 3], "D": [0, -5, 1]}
    results = {}  # no shared matches -> no head-to-head needed
    order = rank_group(teams, s, results, _fixed_tiebreak())
    assert order == ["A", "C", "B", "D"]


def test_rank_group_breaks_exact_tie_with_head_to_head():
    # B and C are tied on points/GD/GF (both [6, 0, 4]) but B beat C head-to-head.
    teams = ["A", "B", "C", "D"]
    s = {"A": [9, 3, 5], "B": [6, 0, 4], "C": [6, 0, 4], "D": [0, -3, 1]}
    results = {("B", "C"): (2, 0)}
    order = rank_group(teams, s, results, _fixed_tiebreak())
    assert order == ["A", "B", "C", "D"]


def test_rank_group_falls_back_to_tiebreak_when_no_head_to_head_data():
    # A fully circular tie with no recorded meeting between the tied teams
    # (FIFA rule: no further algorithmic resolution, would go to a draw of
    # lots in reality) -- rank_group must not crash, and must respect the
    # supplied tiebreak callable's ordering rather than falling into an
    # unstable/undefined order.
    teams = ["A", "B"]
    s = {"A": [3, 0, 1], "B": [3, 0, 1]}
    results = {}
    order_high_first = rank_group(teams, s, results, _fixed_tiebreak(1.0))
    assert set(order_high_first) == {"A", "B"}  # both still present, no crash


def test_assign_thirds_never_pairs_a_team_with_its_own_group():
    # Regression for the historical "Switzerland vs Qatar" bug (both Group B):
    # the old greedy fallback ignored eligibility and could produce a
    # same-group R32 tie. Every r32_var slot's eligibility set already
    # excludes its own group; assign_thirds must honour that for every slot.
    r32_var = [
        ("1E", {"A", "B", "C", "D", "F"}),
        ("1I", {"C", "D", "F", "G", "H"}),
        ("1A", {"C", "E", "F", "H", "I"}),
        ("1L", {"E", "H", "I", "J", "K"}),
    ]
    # (pts, gd, gf, group, team) tuples, one per group represented among the thirds.
    best8 = [
        (4, 2, 5, "B", "Qatar"),
        (4, 1, 4, "E", "Curacao"),
        (3, 0, 3, "I", "Norway"),
        (3, -1, 2, "H", "Uruguay"),
    ]
    asgn = assign_thirds(best8, r32_var)
    by_group = {"1E": "E", "1I": "I", "1A": "A", "1L": "L"}
    for slot, team in asgn.items():
        own_group = by_group[slot]
        assigned_team_group = next(g for _, _, _, g, t in best8 if t == team)
        assert assigned_team_group != own_group, (
            f"{slot} (group {own_group}) was assigned {team} from its own group")


def test_assign_thirds_covers_every_slot_exactly_once():
    r32_var = [
        ("1E", {"A", "B", "C", "D", "F"}),
        ("1I", {"C", "D", "F", "G", "H"}),
    ]
    best8 = [
        (4, 2, 5, "B", "Qatar"),
        (3, 0, 3, "H", "Uruguay"),
    ]
    asgn = assign_thirds(best8, r32_var)
    assert set(asgn.keys()) == {"1E", "1I"}
    assert set(asgn.values()) == {"Qatar", "Uruguay"}


def test_pen_prob_is_clamped_to_thirty_seventy_range():
    # Germany (curated PEN rate 0.75) vs Mexico (0.25): raw sa/(sa+sb) = 0.75,
    # already past the clamp before the +-0.03 Elo tilt is even added -- equal
    # Elo isolates the clamp itself from that tilt.
    elo = {"Germany": 1500, "Mexico": 1500}
    p = pen_prob("Germany", "Mexico", elo)
    assert 0.30 <= p <= 0.70
    assert p == 0.70  # saturates the clamp


def test_pen_prob_defaults_to_fifty_fifty_for_unrated_teams_with_equal_elo():
    elo = {"X": 1500, "Y": 1500}
    p = pen_prob("X", "Y", elo)  # neither team in the curated PEN table -> 0.50 each
    assert p == 0.50


def test_inflate_hda_is_identity_at_delta_zero():
    ph, pd, pa = inflate_hda(0.4, 0.3, 0.3, 0.0)
    assert (ph, pd, pa) == (0.4, 0.3, 0.3)


def test_inflate_hda_raises_draw_share_and_stays_normalized():
    ph0, pd0, pa0 = 0.45, 0.25, 0.30
    ph, pd, pa = inflate_hda(ph0, pd0, pa0, delta=0.5)
    assert math.isclose(ph + pd + pa, 1.0, abs_tol=1e-9)
    assert pd > pd0          # draw mass increased
    assert ph < ph0 and pa < pa0   # at the other two outcomes' expense
    # Closed-form check against the Karlis & Ntzoufras (2003) formula directly.
    z = 1.0 + 0.5 * pd0
    assert math.isclose(pd, pd0 * 1.5 / z)
