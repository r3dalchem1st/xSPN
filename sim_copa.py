"""
Single-elimination knockout Monte Carlo for knockout_only competitions
(Copa del Rey's format: 8 sequential rounds -- Preliminary round through
Round 3 in the early, minnow-heavy field, then Round of 16 -> QF -> SF ->
Final once it's almost entirely top-flight clubs). Every round is a single
match except the Semifinal, which is two-legged -- the only two-legged
round in the whole competition (confirmed against 5 real openfootball
seasons, 2020-21 through 2024-25, during planning).

Adapted from, not shared with, sim_cup.py's knockout-pairing engine, same
non-refactor posture every prior format pair in this project has used (see
fit_league.py's Global Constraints for the canonical reasoning): the round
list, which round(s) default to two-legged, and the total absence of a
league phase are different enough that a shared abstraction would need
format-specific branches risking sim_cup.py's already-live UCL/UEL
pipeline for no functional benefit.

League-average fallback: any team absent from the fitted attack/defense
table (the ~100 regional Preliminary/Round-1 minnows with zero rateable
history in any data source) gets attack=0.0/defense=0.0 via
sim_league.build_lambda_table's own existing behavior, reused unmodified
-- the same documented-limitation pattern sim_league.py already uses for
newly promoted clubs, just at much larger scale here. Early-round odds
will cluster near 50/50 as a direct, expected consequence -- see
docs/superpowers/specs/2026-07-28-copa-del-rey-design.md section 3.3.

Round-entrant derivation: a round's real entrant set (round_entrants()) is
derived from the union of home+away teams across that round's own real
fixtures whenever they exist -- this is always authoritative over a
simulated carry-forward, because it already reflects the true outcome of
every earlier round INCLUDING any bye (a team entering directly at Round 1
without playing in the Preliminary round). A round with no real fixtures
yet falls back to the previous round's simulated winners. This path is
untested against a live partial draw (none exists yet -- the 2026-27
draw isn't out until ~October); re-verify with a live smoke test once it
is, same discipline that caught two real parser bugs during the UCL/UEL
build (see the design doc's risk S3).
"""
import json
import os
import sys
from collections import defaultdict

import numpy as np

from sim_league import _poisson, build_lambda_table

ROUND_ORDER = ["preliminary", "round_1", "round_2", "round_3",
               "round_of_16", "quarterfinal", "semifinal", "final"]
TWO_LEGGED_ROUNDS = {"semifinal"}  # every other undrawn round defaults to single-match

_STAGE_LABELS = {
    "Preliminary round": "preliminary", "Round 1": "round_1", "Round 2": "round_2",
    "Round 3": "round_3", "Round of 16": "round_of_16", "Quarterfinals": "quarterfinal",
    "Semifinals": "semifinal", "Final": "final",
}


def _stage(round_label):
    return _STAGE_LABELS.get(round_label)


def _decide_single(fx, team_a, team_b):
    if fx["pen_score"] is not None:
        pen = {fx["home"]: fx["pen_score"][0], fx["away"]: fx["pen_score"][1]}
        return team_a if pen[team_a] > pen[team_b] else team_b
    goals = {fx["home"]: fx["score"][0], fx["away"]: fx["score"][1]}
    return team_a if goals[team_a] > goals[team_b] else team_b


def build_played_ties(knockout_fixtures):
    """{(stage, frozenset({team_a, team_b})): winner} for every
    ALREADY-DECIDED tie. A Semifinal tie needs BOTH legs played (aggregate,
    or a shootout on whichever leg carries a pen_score); every other round
    is a single match, decided the moment its one fixture has a score."""
    legs_by_tie = defaultdict(list)
    for fx in knockout_fixtures:
        stage = _stage(fx["round"])
        if stage is None or fx["score"] is None:
            continue
        legs_by_tie[(stage, frozenset((fx["home"], fx["away"])))].append(fx)

    winners = {}
    for (stage, pair), legs in legs_by_tie.items():
        team_a, team_b = tuple(pair)
        if stage not in TWO_LEGGED_ROUNDS:
            if len(legs) != 1:
                continue
            winners[(stage, pair)] = _decide_single(legs[0], team_a, team_b)
            continue
        if len(legs) != 2:
            continue  # tie not fully played yet -- let the sim decide it
        agg = {team_a: 0, team_b: 0}
        for fx in legs:
            agg[fx["home"]] += fx["score"][0]
            agg[fx["away"]] += fx["score"][1]
        if agg[team_a] != agg[team_b]:
            winners[(stage, pair)] = team_a if agg[team_a] > agg[team_b] else team_b
        else:
            decider = max(legs, key=lambda fx: fx["date"])
            if decider["pen_score"] is None:
                continue  # aggregate level with no shootout recorded -- malformed, don't guess
            pen = {decider["home"]: decider["pen_score"][0], decider["away"]: decider["pen_score"][1]}
            winners[(stage, pair)] = team_a if pen[team_a] > pen[team_b] else team_b
    return winners


def known_tie_winner(stage, team_a, team_b, played_ties):
    return played_ties.get((stage, frozenset((team_a, team_b))))


def round_entrants(stage, knockout_fixtures):
    """Real entrant set for one round, derived from the union of home+away
    teams across that round's own real fixtures (played or not). Returns
    None if the round has no real fixtures yet."""
    teams = {t for fx in knockout_fixtures if _stage(fx["round"]) == stage
             for t in (fx["home"], fx["away"])}
    return sorted(teams) if teams else None


def known_pairs_for_round(stage, knockout_fixtures):
    """{frozenset(pair): [leg_fixtures...]} for every real pairing already
    on record for this round, played or not."""
    by_pair = defaultdict(list)
    for fx in knockout_fixtures:
        if _stage(fx["round"]) == stage:
            by_pair[frozenset((fx["home"], fx["away"]))].append(fx)
    return dict(by_pair)


def resolve_known_tie(stage, pair, legs, decided, lg, rng):
    """`legs`: the 1 (single-match round) or 2 (Semifinal) real fixture
    dicts for one already-drawn tie. If build_played_ties() already fully
    decided it, that stands; otherwise an already-played leg's real goals
    count toward the result and a leg with score=None is simulated."""
    winner = decided.get((stage, pair))
    if winner is not None:
        return winner
    team_a, team_b = tuple(pair)
    if len(legs) == 1:
        fx = legs[0]
        if fx["score"] is not None:
            hg, ag = fx["score"]
        else:
            lam, mu = lg[(fx["home"], fx["away"])]
            hg, ag = _poisson(lam, rng), _poisson(mu, rng)
        if hg > ag: return fx["home"]
        if ag > hg: return fx["away"]
        return fx["home"] if rng.random() < 0.5 else fx["away"]

    agg = {team_a: 0, team_b: 0}
    for fx in legs:
        if fx["score"] is not None:
            hg, ag = fx["score"]
        else:
            lam, mu = lg[(fx["home"], fx["away"])]
            hg, ag = _poisson(lam, rng), _poisson(mu, rng)
        agg[fx["home"]] += hg
        agg[fx["away"]] += ag
    if agg[team_a] > agg[team_b]: return team_a
    if agg[team_b] > agg[team_a]: return team_b
    return team_a if rng.random() < 0.5 else team_b


def simulate_single_match(team_a, team_b, lg, rng):
    """A level score goes to a straight 50/50 coin flip -- no club-level
    penalty-shootout strength data exists for Spanish football, the same
    honest starting point sim_cup.py's own docstring documents for UCL/UEL."""
    lam, mu = lg[(team_a, team_b)]
    ga, gb = _poisson(lam, rng), _poisson(mu, rng)
    if ga > gb: return team_a
    if gb > ga: return team_b
    return team_a if rng.random() < 0.5 else team_b


def simulate_two_legged_tie(team_a, team_b, lg, rng):
    """Unlike sim_cup.py's version, there's no league-table rank to seed
    which side hosts the second leg (Copa has no league phase) -- the real
    draw decides it, so this picks the leg-2 host uniformly at random each
    simulation instead."""
    home2 = team_a if rng.random() < 0.5 else team_b
    away2 = team_b if home2 == team_a else team_a
    lam1, mu1 = lg[(away2, home2)]              # leg 1: away2 hosts
    g1_away2_home, g1_home2_away = _poisson(lam1, rng), _poisson(mu1, rng)
    lam2, mu2 = lg[(home2, away2)]               # leg 2: home2 hosts
    g2_home2_home, g2_away2_away = _poisson(lam2, rng), _poisson(mu2, rng)
    agg = {home2: g1_home2_away + g2_home2_home, away2: g1_away2_home + g2_away2_away}
    if agg[home2] > agg[away2]: return home2
    if agg[away2] > agg[home2]: return away2
    return home2 if rng.random() < 0.5 else away2


def league_average_lambda_table(teams, dc):
    """Thin wrapper over sim_league.build_lambda_table, exported so
    snapshot_copa.py can build lambda tables identically to this module
    without re-importing sim_league directly -- documents, at the point it
    actually matters most (Copa's ~100 unrated minnows), that any team
    missing from `dc` already defaults to a neutral league-average rating
    via that function's own existing behavior."""
    return build_lambda_table(teams, dc)


def simulate_bracket(knockout_fixtures, dc_ensemble, n_sims=10000, seed=42):
    """Monte Carlo the whole 8-round bracket. Each simulated tournament
    starts from the earliest round with real entrant data and advances
    round by round, using each round's REAL pairing whenever it's already
    drawn (resolve_known_tie) and a fresh random pairing otherwise
    (simulate_two_legged_tie for Semifinal, else simulate_single_match).
    Returns {team: {stage: reached_pct, ..., "champion": pct}}, each a
    standalone probability of REACHING that stage (not exclusive of later
    stages, same convention as every other bracket in this project)."""
    all_teams = sorted({t for fx in knockout_fixtures for t in (fx["home"], fx["away"])})
    if not all_teams:
        raise ValueError("no fixtures in knockout_fixtures.json -- nothing to simulate")

    decided = build_played_ties(knockout_fixtures)
    lg_ens = [league_average_lambda_table(all_teams, dc) for dc in dc_ensemble]
    rng = np.random.default_rng(seed)

    stage_counts = {t: {s: 0 for s in ROUND_ORDER + ["champion"]} for t in all_teams}

    # knockout_fixtures is real, already-known data -- identical on every
    # simulated iteration -- so both derivations are computed once here
    # rather than re-scanned n_sims times inside the loop below (the same
    # precompute-once fix sim_cup.py already applies to its own equivalent
    # known_pairs_by_round()).
    real_entrants_by_stage = {stage: round_entrants(stage, knockout_fixtures) for stage in ROUND_ORDER}
    known_pairs_by_stage = {stage: known_pairs_for_round(stage, knockout_fixtures) for stage in ROUND_ORDER}

    for _ in range(n_sims):
        lg = lg_ens[rng.integers(len(lg_ens))]
        field = None
        for stage in ROUND_ORDER:
            real_entrants = real_entrants_by_stage[stage]
            if real_entrants is not None:
                field = real_entrants
            if field is None:
                continue  # this stage (and every earlier one) has no real data yet
            for t in field:
                stage_counts[t][stage] += 1
            known_pairs = known_pairs_by_stage[stage]
            if known_pairs and set(t for pair in known_pairs for t in pair) == set(field):
                winners = [resolve_known_tie(stage, pair, legs, decided, lg, rng)
                           for pair, legs in known_pairs.items()]
            else:
                order = list(rng.permutation(field))
                winners = []
                for i in range(0, len(order) - 1, 2):
                    a, b = order[i], order[i + 1]
                    if stage in TWO_LEGGED_ROUNDS:
                        winners.append(simulate_two_legged_tie(a, b, lg, rng))
                    else:
                        winners.append(simulate_single_match(a, b, lg, rng))
                if len(order) % 2:
                    winners.append(order[-1])  # odd undrawn field -- bye through, defensive fallback
            field = winners
        if field is None:
            continue  # no recognisable round data at all -- shouldn't happen given the guard above
        champion = field[0]
        stage_counts[champion]["champion"] += 1

    return {t: {k: v / n_sims for k, v in c.items()} for t, c in stage_counts.items()}


def simulate_and_save(config, base_dir, n_sims=10000, seed=42):
    """Load <slug>/knockout_fixtures.json + <slug>/dc_ensemble.json, run the
    bracket Monte Carlo, and write <slug>/copa_sim.json: {team: {stage:
    pct, ..., "champion": pct}}. Requires fetch_copa.py and fit_league.py
    to have already run. Returns the same dict that gets written."""
    from competition_config import artifact_dir
    out_dir = artifact_dir(config, base_dir)

    ko_path = os.path.join(out_dir, "knockout_fixtures.json")
    with open(ko_path) as f:
        knockout_fixtures = json.load(f)
    if not knockout_fixtures:
        raise ValueError(f"{config.slug}: no fixtures in {ko_path} -- "
                          f"current season's draw may not be released yet")

    ensemble_path = os.path.join(out_dir, "dc_ensemble.json")
    if not os.path.exists(ensemble_path):
        raise FileNotFoundError(f"{ensemble_path} not found — run fit_league.py first")
    with open(ensemble_path) as f:
        dc_ensemble = json.load(f)

    stage_odds = simulate_bracket(knockout_fixtures, dc_ensemble, n_sims=n_sims, seed=seed)

    with open(os.path.join(out_dir, "copa_sim.json"), "w") as f:
        json.dump(stage_odds, f, indent=2)
    return stage_odds


def main():
    if len(sys.argv) != 2:
        print("usage: python sim_copa.py competitions/<slug>.json")
        raise SystemExit(1)
    from competition_config import load_competition
    config = load_competition(sys.argv[1])
    base_dir = os.path.dirname(os.path.abspath(__file__))
    stage_odds = simulate_and_save(config, base_dir)
    top5 = sorted(stage_odds.items(), key=lambda kv: -kv[1]["champion"])[:5]
    print(f"{config.name}: simulated {len(stage_odds)} teams")
    print("Top 5 title odds:")
    for t, odds in top5:
        print(f"  {t:<28} {odds['champion']:.1%}")


if __name__ == "__main__":
    main()
