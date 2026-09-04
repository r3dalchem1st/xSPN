"""
Shared calibration math for round-robin/cup competitions' H/D/A probability
computation. Used by sim_league.py (season Monte Carlo + lambda tables),
snapshot_league.py (pre-match locking), build_league_html.py (live bracket
previews), and backtest_league.py (grid-search validation) -- centralized
here from the start specifically to avoid the bug class this codebase has
already been bitten by once (bracket-topology constants duplicated verbatim
across sim_improved.py/bracket_predictor.py, causing a real wrong-topology
bug, fixed 17 Aug -- see CONTEXT.md).

Deliberately NOT model_common.py: that module is World-Cup-specific
(squad values, ALL_TEAMS, host nations) and importing it would transitively
execute fit_improved.py's entire module body (see fit_league.py's own
Global Constraints for why that coupling is avoided). This is the
round-robin family's own equivalent -- same formulas as model_common.py's
shrink_lambda/inflate_hda (reimplemented, not imported, per that same
constraint), scoped to what round-robin/cup actually need.

Every function here defaults to a no-op (strength_shrink=1.0, delta=0.0,
rho=0.0) so wiring these into a call site is safe before any competition
has an actual backtested value configured.
"""
import math

# Same reference anchor as the WC's model_common.py -- 1.0 = no shrink,
# <1 pulls a team's expected goals toward this common value (flatter H/D/A,
# more draws). The ANCHOR is just the point shrinkage pulls toward, not a
# league-specific fact, so it isn't re-derived per competition; the
# strength_shrink MAGNITUDE is league-specific -- see backtest_league.py.
GOAL_ANCHOR = 1.35

# Same safety clamp as model_common.py's LAMBDA_MIN/LAMBDA_MAX. sim_league.py's
# build_lambda_table() had no such clamp before this module existed -- a real
# latent gap (a big mismatch, e.g. a newly-promoted team's neutral 0.0 rating
# against a title contender, could in principle produce a nonsensically large
# lambda the same way model_common.py's own comment describes for the WC).
LAMBDA_MIN, LAMBDA_MAX = 0.20, 5.0


def shrink_lambda(x, strength_shrink, goal_anchor=GOAL_ANCHOR):
    """Compress an expected-goals value toward goal_anchor. strength_shrink
    1.0 = identity (returns x unchanged); <1 pulls toward the anchor."""
    return goal_anchor + strength_shrink * (x - goal_anchor)


def clamp_lambda(x, lo=LAMBDA_MIN, hi=LAMBDA_MAX):
    return min(max(x, lo), hi)


def inflate_hda(ph, pd, pa, delta):
    """Karlis & Ntzoufras (2003) diagonal inflation on a normalized (H, D, A)
    triple: scale the draw mass by (1+delta) and renormalize. delta<=0.0 is
    identity (returns the inputs unchanged)."""
    if delta <= 0.0:
        return ph, pd, pa
    z = 1.0 + delta * pd
    return ph / z, pd * (1.0 + delta) / z, pa / z


def hda_probs_from_lambda(lam, mu, rho=0.0, max_g=10):
    """P(home win), P(draw), P(away win) from one (lam, mu) pair under
    independent Poisson, with the Dixon-Coles low-score correlation
    adjustment applied to the 4 cells where it's defined. rho=0.0 recovers
    plain independent Poisson (fit_league.py fits rho, but nothing
    downstream ever applied it before this module -- a real gap found
    while building this backtest; kept optional here since whether applying
    it actually helps on real data is exactly what the backtest is for)."""
    elam, emu = math.exp(-lam), math.exp(-mu)
    ph = pd = pa = 0.0
    for h in range(max_g + 1):
        p_h = elam * lam**h / math.factorial(h)
        for a in range(max_g + 1):
            p = p_h * (emu * mu**a / math.factorial(a))
            if rho:
                if h == 0 and a == 0:
                    p *= max(1 - lam * mu * rho, 1e-10)
                elif h == 0 and a == 1:
                    p *= max(1 + lam * rho, 1e-10)
                elif h == 1 and a == 0:
                    p *= max(1 + mu * rho, 1e-10)
                elif h == 1 and a == 1:
                    p *= max(1 - rho, 1e-10)
            if h > a:
                ph += p
            elif h < a:
                pa += p
            else:
                pd += p
    s = ph + pd + pa
    return (ph / s, pd / s, pa / s) if s else (0.0, 0.0, 0.0)


def compute_momentum(team, as_of_date, history, n=5):
    """Average goal difference per game for `team` over its last `n`
    matches STRICTLY BEFORE as_of_date, drawn from `history` (an iterable
    of [date, home, away, hg, ag, label, neutral] rows, any order -- both
    home and away appearances count, oriented so a result is always
    goals_for - goals_against for `team`). Returns 0.0 (neutral -- neither
    hot nor cold) if the team has no qualifying match in `history`, e.g. a
    newly-promoted team or the very first matches of a season with no
    history behind it at all.

    A short rolling window is a genuinely different signal from
    fit_league.py's own recency weighting: that fit smooths ALL history
    with an 18-month half-life, which reacts far too slowly to reflect a
    team's last few weeks of form (a hot or cold streak). Whether this
    signal actually improves predictions on real data, and what window
    size / blend weight works best, is exactly what backtest_league.py's
    grid search is for -- not assumed here."""
    diffs = []
    for date_, home, away, hg, ag, _label, _neutral in history:
        if date_ >= as_of_date:
            continue
        if home == team:
            diffs.append((date_, hg - ag))
        elif away == team:
            diffs.append((date_, ag - hg))
    if not diffs:
        return 0.0
    diffs.sort(key=lambda d: d[0])
    recent = diffs[-n:]
    return sum(gd for _, gd in recent) / len(recent)
