"""
League-phase + knockout Monte Carlo simulation for league_phase_knockout
competitions (UEFA Champions League / Europa League's format): 36 teams
play a partial round-robin "league phase"; the top 8 advance straight to
the Round of 16; 9th-24th play two-legged play-offs for the remaining 8
Round-of-16 spots; 25th-36th are eliminated. From there it's a standard
two-legged knockout bracket (Round of 16 -> QF -> SF) to a single-match
Final.

Deliberately self-contained rather than folded into sim_league.py: the
league-phase mechanics ARE identical (reused directly -- _poisson,
build_lambda_table(s), compute_standings_and_remaining all imported
unmodified), but sim_league.simulate_season() only returns the AGGREGATE
rank distribution, discarding each simulated season's actual final order
once tallied. The knockout stage needs that per-simulation order (to seed
the play-off pairings), so this module runs its own top-level Monte Carlo
loop that layers the knockout simulation on top of the same per-iteration
league-phase mechanics, rather than trying to recover discarded detail from
sim_league's return value.

Two real simplifications, both documented rather than silently assumed:
  - A level aggregate (or a level Final) goes to a 50/50 coin flip. No
    club-level penalty-shootout strength data exists to do better than
    that -- the same honest starting point the World Cup's own per-nation
    penalty table began from, before it was curated against real shootout
    evidence it doesn't have an equivalent for here.
  - For a round whose real draw HASN'T happened yet, pairings are drawn
    uniformly at random each simulation, ignoring UEFA's real seeding
    constraints (e.g. a play-off winner can't (yet) be re-drawn against a
    team from its own league-phase group). Only which team hosts the
    second leg is seeded, by that simulation's own league-phase final rank
    -- real UEFA practice.

Whenever a round's real pairing IS already known (its fixtures already
appear in knockout_fixtures.json, played or not), that real pairing is used
instead of a random draw -- caught by a live smoke test against a fully
concluded real season (2025-26 UCL): treating every knockout tie as fair
game for a fresh random draw each iteration, rather than honouring the
season's own already-fixed real bracket, meant the eventual real champion
(PSG, 100% inevitable in hindsight) only "won" 63% of simulated
tournaments -- the other 37% were re-fighting a bracket shape that never
actually happened.
"""
import json
import os
import sys
from collections import defaultdict

import numpy as np

from sim_league import _poisson, build_lambda_tables, compute_standings_and_remaining

TOP_SEEDS = 8          # ranks 1-8: direct to the Round of 16
PLAYOFF_SIZE = 16      # ranks 9-24: two-legged play-off for the remaining 8 R16 spots
KNOCKOUT_STAGES = ["round_of_16", "quarterfinal", "semifinal", "final"]


def _bracket_round(round_label):
    """Finer-grained than fetch_cup.classify_stage()'s "final" bucket --
    that function only needs to route matches to the right artifact, but
    pairing a tie's two legs (and deciding whether it's fully played, see
    build_played_ties()) needs to know exactly which knockout round a leg
    belongs to. Handles both label conventions confirmed in real
    openfootball data: "Finals, Quarterfinals" (2025-26 UCL) and a bare
    "Quarterfinals" (2024-25 UEL)."""
    label = round_label or ""
    if label.startswith("Playoffs"):
        return "playoff"
    if "Round of 16" in label:
        return "round_of_16"
    if "Quarterfinal" in label:
        return "quarterfinal"
    if "Semifinal" in label:
        return "semifinal"
    if label.endswith("Final"):
        return "final"
    return None


def build_played_ties(knockout_fixtures):
    """{frozenset({team_a, team_b}): winner} for every ALREADY-DECIDED tie
    in knockout_fixtures.json. A two-legged tie needs BOTH legs played to
    be decided (aggregate, or a shootout on whichever leg carries a
    pen_score); the Final is a single match. A tie with only one leg played
    (real mid-season state) is deliberately left out, not guessed at --
    letting the simulation fill in the still-open leg(s) itself. Always
    empty against today's data (no current 2026-27 season exists yet to be
    partially played), but the pipeline needs this the moment a real season
    is mid-progress."""
    legs_by_tie = defaultdict(list)
    for fx in knockout_fixtures:
        rnd = _bracket_round(fx["round"])
        if rnd is None or fx["score"] is None:
            continue
        legs_by_tie[(rnd, frozenset((fx["home"], fx["away"])))].append(fx)

    winners = {}
    for (rnd, pair), legs in legs_by_tie.items():
        team_a, team_b = tuple(pair)
        if rnd == "final":
            if len(legs) != 1:
                continue
            fx = legs[0]
            if fx["pen_score"] is not None:
                pen = {fx["home"]: fx["pen_score"][0], fx["away"]: fx["pen_score"][1]}
                winners[pair] = team_a if pen[team_a] > pen[team_b] else team_b
            else:
                goals = {fx["home"]: fx["score"][0], fx["away"]: fx["score"][1]}
                winners[pair] = team_a if goals[team_a] > goals[team_b] else team_b
            continue
        if len(legs) != 2:
            continue  # tie not fully played yet -- let the sim decide it
        agg = {team_a: 0, team_b: 0}
        for fx in legs:
            agg[fx["home"]] += fx["score"][0]
            agg[fx["away"]] += fx["score"][1]
        if agg[team_a] != agg[team_b]:
            winners[pair] = team_a if agg[team_a] > agg[team_b] else team_b
        else:
            decider = max(legs, key=lambda fx: fx["date"])
            if decider["pen_score"] is None:
                continue  # aggregate level with no shootout recorded -- malformed, don't guess
            pen = {decider["home"]: decider["pen_score"][0], decider["away"]: decider["pen_score"][1]}
            winners[pair] = team_a if pen[team_a] > pen[team_b] else team_b
    return winners


def known_tie_winner(team_a, team_b, played_ties):
    return played_ties.get(frozenset((team_a, team_b)))


def known_pairs_by_round(knockout_fixtures):
    """{bracket_round: {frozenset(pair): [leg_fixtures...]}} -- every REAL
    pairing already on record for that round, played or not (a fixture with
    score=None is still a real, already-scheduled pairing, exactly like
    league_schedule.json's SCHEDULED entries). A round with no entry here
    means its real draw hasn't happened yet -- the caller falls back to
    modelling that round instead of trusting it."""
    by_round = defaultdict(lambda: defaultdict(list))
    for fx in knockout_fixtures:
        rnd = _bracket_round(fx["round"])
        if rnd is None:
            continue
        by_round[rnd][frozenset((fx["home"], fx["away"]))].append(fx)
    return {rnd: dict(pairs) for rnd, pairs in by_round.items()}


def resolve_known_tie(pair, legs, decided, lg, rng):
    """`legs`: the 1 (Final) or 2 (two-legged) real fixture dicts for one
    already-drawn tie. If build_played_ties() already fully decided it,
    that stands; otherwise an already-played leg's real goals count toward
    the aggregate and a leg with score=None is simulated -- so a tie that's
    half-played (one real leg banked, one still to come) is honoured
    rather than re-simulated from scratch."""
    winner = decided.get(pair)
    if winner is not None:
        return winner
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

    team_a, team_b = tuple(pair)
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


def simulate_two_legged_tie(better, worse, lg, rng):
    """`better` hosts the second leg (real UEFA convention: the higher
    league-phase-ranked side gets the second leg at home). See module
    docstring for the coin-flip-on-a-level-aggregate rationale."""
    lam1, mu1 = lg[(worse, better)]           # leg 1: worse hosts
    g1_worse, g1_better = _poisson(lam1, rng), _poisson(mu1, rng)
    lam2, mu2 = lg[(better, worse)]           # leg 2: better hosts
    g2_better, g2_worse = _poisson(lam2, rng), _poisson(mu2, rng)
    agg_better, agg_worse = g1_better + g2_better, g1_worse + g2_worse
    if agg_better > agg_worse:
        return better
    if agg_worse > agg_better:
        return worse
    return better if rng.random() < 0.5 else worse


def simulate_final(team_a, team_b, lg, rng):
    """Single match. Neither finalist has a modelled extra-time/shootout
    edge, so a level score after 90 goes straight to the same coin flip a
    two-legged aggregate tie would use."""
    lam, mu = lg[(team_a, team_b)]
    ga, gb = _poisson(lam, rng), _poisson(mu, rng)
    if ga > gb:
        return team_a
    if gb > ga:
        return team_b
    return team_a if rng.random() < 0.5 else team_b


def simulate_knockout_stage(qualifiers, rank_of, lg, rng, decided, known_pairs):
    """`qualifiers`: the 16 teams entering the Round of 16 (8 direct + 8
    play-off winners) -- for a given simulated iteration, MUST already
    match the real known qualifiers whenever a later round's real pairing
    exists (see simulate_season_and_knockout's membership check on the
    play-off round, which guarantees this). `rank_of`: {team: league-phase
    final position (0 = best)} for this simulated season, used to seed
    home-leg-2 advantage ONLY for a round whose real pairing isn't known
    yet. Returns ({team: {stage: reached_bool}}, champion) for this one
    simulated tournament; "reached stage X" means the team PLAYED in stage
    X (so all 16 qualifiers "reach" round_of_16, the 8 round_of_16 winners
    "reach" quarterfinal, etc.)."""
    reached = {t: {s: False for s in KNOCKOUT_STAGES} for t in qualifiers}
    field = list(qualifiers)
    for stage in KNOCKOUT_STAGES:
        for t in field:
            reached[t][stage] = True
        if stage == "final":
            break
        stage_known = known_pairs.get(stage)
        if stage_known and set(t for pair in stage_known for t in pair) == set(field):
            winners = [resolve_known_tie(pair, legs, decided, lg, rng)
                       for pair, legs in stage_known.items()]
        else:
            order = list(rng.permutation(field))
            winners = []
            for i in range(0, len(order), 2):
                a, b = order[i], order[i + 1]
                better, worse = (a, b) if rank_of[a] < rank_of[b] else (b, a)
                winners.append(simulate_two_legged_tie(better, worse, lg, rng))
        field = winners
    team_a, team_b = field[0], field[1]
    pair = frozenset((team_a, team_b))
    final_known = known_pairs.get("final")
    if final_known and pair in final_known:
        champion = resolve_known_tie(pair, final_known[pair], decided, lg, rng)
    else:
        champion = simulate_final(team_a, team_b, lg, rng)
    return reached, champion


def simulate_season_and_knockout(league_teams, league_standings, league_remaining,
                                  dc_ensemble, knockout_fixtures=None, n_sims=10000, seed=42):
    """Monte Carlo the league phase's remaining fixtures (same mechanics as
    sim_league.simulate_season) AND, per simulated season, seed and
    simulate the play-off + knockout stage from that season's own final
    standings -- using REAL already-scheduled pairings from
    knockout_fixtures.json wherever a round's real draw has already
    happened (see module docstring), falling back to a modelled random
    draw only for a round not yet drawn in reality. Returns
    (zone_odds, stage_odds):
      zone_odds:  {team: {"top8", "playoff_zone", "eliminated"}} -- always
        sums to 1 per team, straight from the league-phase final position.
      stage_odds: {team: {"round_of_16", "quarterfinal", "semifinal",
        "final", "champion"}} -- each a standalone probability (NOT
        cumulative-exclusive; reaching the final implies having reached
        every earlier stage too, same convention as the WC's own
        Bracket/Title-Odds tabs).
      expected_pos: {team: float} -- mean simulated league-phase finishing
        position (1 = best). Needed as a standings tiebreak: a preseason
        table (every team on 0 points) would otherwise fall back to
        whatever order `league_teams` happens to be in, the exact bug the
        round-robin leagues' own standings page hit and fixed (see
        build_league_html.py's build_standings_rows) -- built in here from
        the start rather than repeating that gap."""
    knockout_fixtures = knockout_fixtures or []
    decided = build_played_ties(knockout_fixtures)
    known_pairs = known_pairs_by_round(knockout_fixtures)
    lg_ens = build_lambda_tables(league_teams, dc_ensemble)
    rng = np.random.default_rng(seed)

    zone_counts = {t: {"top8": 0, "playoff_zone": 0, "eliminated": 0} for t in league_teams}
    stage_counts = {t: {s: 0 for s in KNOCKOUT_STAGES + ["champion"]} for t in league_teams}
    pos_sum = {t: 0 for t in league_teams}

    for _ in range(n_sims):
        lg = lg_ens[rng.integers(len(lg_ens))]
        table = {t: dict(league_standings.get(t, {"pts": 0, "gd": 0, "gf": 0})) for t in league_teams}
        for home, away in league_remaining:
            lam, mu = lg[(home, away)]
            hg, ag = _poisson(lam, rng), _poisson(mu, rng)
            table[home]["gf"] += hg; table[home]["gd"] += hg - ag
            table[away]["gf"] += ag; table[away]["gd"] += ag - hg
            if hg > ag: table[home]["pts"] += 3
            elif ag > hg: table[away]["pts"] += 3
            else: table[home]["pts"] += 1; table[away]["pts"] += 1
        order = sorted(league_teams, key=lambda t: (table[t]["pts"], table[t]["gd"], table[t]["gf"]), reverse=True)

        top8 = order[:TOP_SEEDS]
        playoff_zone = order[TOP_SEEDS:TOP_SEEDS + PLAYOFF_SIZE]
        eliminated = order[TOP_SEEDS + PLAYOFF_SIZE:]
        for t in top8: zone_counts[t]["top8"] += 1
        for t in playoff_zone: zone_counts[t]["playoff_zone"] += 1
        for t in eliminated: zone_counts[t]["eliminated"] += 1

        rank_of = {t: i for i, t in enumerate(order)}
        for t, i in rank_of.items(): pos_sum[t] += i
        playoff_known = known_pairs.get("playoff")
        if playoff_known and set(t for pair in playoff_known for t in pair) == set(playoff_zone):
            playoff_winners = [resolve_known_tie(pair, legs, decided, lg, rng)
                                for pair, legs in playoff_known.items()]
        else:
            n = len(playoff_zone)
            playoff_winners = []
            for i in range(n // 2):
                higher, lower = playoff_zone[i], playoff_zone[n - 1 - i]   # 9v24, 10v23, ...
                playoff_winners.append(simulate_two_legged_tie(higher, lower, lg, rng))

        qualifiers = top8 + playoff_winners
        reached, champion = simulate_knockout_stage(qualifiers, rank_of, lg, rng, decided, known_pairs)
        for t, stages in reached.items():
            for s, ok in stages.items():
                if ok:
                    stage_counts[t][s] += 1
        stage_counts[champion]["champion"] += 1

    zone_odds = {t: {k: v / n_sims for k, v in c.items()} for t, c in zone_counts.items()}
    stage_odds = {t: {k: v / n_sims for k, v in c.items()} for t, c in stage_counts.items()}
    expected_pos = {t: (s / n_sims) + 1 for t, s in pos_sum.items()}
    return zone_odds, stage_odds, expected_pos


def simulate_and_save(config, base_dir, n_sims=10000, seed=42):
    """Load <slug>/league_schedule.json, <slug>/dc_ensemble.json, and (if
    present) <slug>/knockout_fixtures.json, run the Monte Carlo, and write
    <slug>/cup_sim.json: {"zone_odds": ..., "stage_odds": ..., "expected_pos":
    ...}. Requires fetch_cup.py and fit_league.py to have already run.
    Returns the same dict that gets written."""
    from competition_config import artifact_dir
    out_dir = artifact_dir(config, base_dir)

    with open(os.path.join(out_dir, "league_schedule.json")) as f:
        league_schedule = json.load(f)

    ensemble_path = os.path.join(out_dir, "dc_ensemble.json")
    if not os.path.exists(ensemble_path):
        raise FileNotFoundError(f"{ensemble_path} not found — run fit_league.py first")
    with open(ensemble_path) as f:
        dc_ensemble = json.load(f)

    ko_fixtures_path = os.path.join(out_dir, "knockout_fixtures.json")
    knockout_fixtures = []
    if os.path.exists(ko_fixtures_path):
        with open(ko_fixtures_path) as f:
            knockout_fixtures = json.load(f)

    standings, remaining, teams = compute_standings_and_remaining(league_schedule)
    min_teams = TOP_SEEDS + PLAYOFF_SIZE
    if len(teams) < min_teams:
        raise ValueError(f"{config.slug}: only {len(teams)} teams in league_schedule.json — "
                          f"need at least {min_teams} for a knockout stage (league-phase "
                          f"draw may not be released yet)")

    zone_odds, stage_odds, expected_pos = simulate_season_and_knockout(
        teams, standings, remaining, dc_ensemble,
        knockout_fixtures=knockout_fixtures, n_sims=n_sims, seed=seed)

    result = {"zone_odds": zone_odds, "stage_odds": stage_odds, "expected_pos": expected_pos}
    with open(os.path.join(out_dir, "cup_sim.json"), "w") as f:
        json.dump(result, f, indent=2)
    return result


def main():
    if len(sys.argv) != 2:
        print("usage: python sim_cup.py competitions/<slug>.json")
        raise SystemExit(1)
    from competition_config import load_competition
    config = load_competition(sys.argv[1])
    base_dir = os.path.dirname(os.path.abspath(__file__))
    result = simulate_and_save(config, base_dir)
    top5 = sorted(result["stage_odds"].items(), key=lambda kv: -kv[1]["champion"])[:5]
    print(f"{config.name}: simulated {len(result['stage_odds'])} teams")
    print("Top 5 title odds:")
    for t, odds in top5:
        print(f"  {t:<28} {odds['champion']:.1%}")


if __name__ == "__main__":
    main()
