"""
Shared constants and helpers for sim_improved.py and bracket_predictor.py.

Centralised here so the two prediction pipelines cannot drift apart (they
previously kept independent copies of GROUPS / PEN / host logic, and the two
penalty tables had already diverged). Import-only; no side effects.
"""
import math, os
from fit_improved import squad_adj, INIT_ELO

# ── Groups (2026 format: 12 groups of 4) ─────────────────────────────────────
GROUPS = {
    "A": ["Mexico","South Africa","South Korea","Czechia"],
    "B": ["Canada","Switzerland","Qatar","Bosnia"],
    "C": ["Brazil","Morocco","Haiti","Scotland"],
    "D": ["USA","Paraguay","Australia","Turkey"],
    "E": ["Germany","Curacao","Ivory Coast","Ecuador"],
    "F": ["Netherlands","Japan","Sweden","Tunisia"],
    "G": ["Belgium","Egypt","Iran","New Zealand"],
    "H": ["Spain","Cape Verde","Saudi Arabia","Uruguay"],
    "I": ["France","Senegal","Norway","Iraq"],
    "J": ["Argentina","Algeria","Austria","Jordan"],
    "K": ["Portugal","DR Congo","Uzbekistan","Colombia"],
    "L": ["England","Croatia","Ghana","Panama"],
}
ALL_TEAMS = [t for g in GROUPS.values() for t in g]

# ── Host advantage ───────────────────────────────────────────────────────────
HOST_NATIONS = {"USA", "Canada", "Mexico"}
HOST_ADV_FRACTION = 0.65   # fraction of the learned home_adv applied to hosts

# ── Squad market-value influence ─────────────────────────────────────────────
# Split the squad adjustment symmetrically across attack (+) and defence (-) so
# a stronger squad both scores more AND concedes fewer. The two halves sum to
# the same net goal-difference effect the old attack-only term had (0.5), so
# headline numbers barely move while the indefensible attack-only asymmetry is
# removed. (Defence params are added to the OPPONENT's lambda, hence the minus.)
SQUAD_W = 0.25

# Expected-goals bounds for a single team in a match. Attack/squad/Elo all add
# in log space, so for an extreme mismatch (elite vs minnow) exp(...) can blow
# up (e.g. λ≈11 for Germany–Curacao → a nonsensical "6–0" clipped at the score
# grid and win-probs that don't sum to 1). No international match has an
# expected-goals near that; clamp to a realistic range. The floor avoids λ=0.
LAMBDA_MIN, LAMBDA_MAX = 0.20, 5.0

# Strength shrinkage (calibration). The friendly/qualifier-trained model is
# over-confident on favourites and under-predicts draws (validated on the live
# group openers: Brier 0.77 > 0.667 random, 0/13 draws called vs 38% actual).
# Compress every match's expected goals toward a common anchor: 1.0 = no shrink,
# <1 pulls scorelines toward the mean → flatter H/D/A, more draws. Magnitude is
# chosen on the backtest holdout (Euro/Copa 2024), never on the live openers.
GOAL_ANCHOR = 1.35
# 0.55 chosen on the backtest holdout: log-loss 1.026→0.950, Brier 0.612→0.574
# (≈ the flat minimum at 0.45–0.55; accuracy unchanged). Conservative vs over-shrink.
STRENGTH_SHRINK = float(os.environ.get("STRENGTH_SHRINK", "0.55"))
def shrink_lambda(x):
    return GOAL_ANCHOR + STRENGTH_SHRINK * (x - GOAL_ANCHOR)

# ── Penalty-shootout conversion strengths (WC historical win rates) ──────────
# Canonical table — single source of truth for both pipelines.
PEN = {
    "Germany":0.75,"Argentina":0.67,"Portugal":0.67,"Croatia":0.75,
    "South Korea":0.67,"Uruguay":0.67,"Italy":0.67,"France":0.50,
    "Brazil":0.42,"Netherlands":0.40,"Spain":0.50,"England":0.38,
    "Mexico":0.25,"Denmark":0.33,"Switzerland":0.33,"Japan":0.50,
    "Senegal":0.50,"Colombia":0.50,"Belgium":0.50,"Morocco":0.50,
}


# How strongly long-run Elo feeds the match lambda. The Dixon-Coles fit is
# recency-weighted, so a team with little recent COMPETITIVE data (notably the
# auto-qualified hosts, who only play friendlies) is rated almost entirely on
# noisy form — e.g. the model rated host Mexico below South Africa before the
# opener. Elo carries the long memory the DC fit discards; blending a little of
# it back in corrects that. β=0.3 was chosen on the backtest holdout: it fixes
# the host under-rating while leaving out-of-sample Brier essentially unchanged
# (larger values over-correct and degrade it).
ELO_BLEND = 0.3

def eff_params(team, ATK, DEF, avg_atk, avg_def, elo=None, avg_elo=None):
    """Effective (attack, defence) for a team: Dixon-Coles + symmetric squad adj
    + an optional symmetric long-run Elo prior."""
    sa = squad_adj(team)
    e = 0.0 if elo is None else ELO_BLEND * (elo.get(team, 1500) - avg_elo) / 400.0
    atk = ATK.get(team, avg_atk) + SQUAD_W * sa + e
    dfn = DEF.get(team, avg_def) - SQUAD_W * sa - e
    return atk, dfn


def pen_prob(a, b, ELO):
    """P(a wins a shootout vs b), Elo-tilted and clamped to [0.30, 0.70]."""
    sa = PEN.get(a, 0.50); sb = PEN.get(b, 0.50)
    ea = ELO.get(a, INIT_ELO); eb = ELO.get(b, INIT_ELO)
    edge = 0.03 * math.tanh((ea - eb) / 300)
    return max(0.30, min(0.70, sa / (sa + sb) + edge))


def rank_group(teams, s, results, tiebreak):
    """Rank a group by FIFA 2026 criteria: points, goal difference, goals for
    (all matches), then HEAD-TO-HEAD among exactly-tied teams (points, GD, GF in
    matches between them), then a random draw. s: dict team->[pts,gd,gf];
    results: dict (home,away)->(hg,ag); tiebreak: zero-arg random callable."""
    def primary(t): return (s[t][0], s[t][1], s[t][2])
    order = sorted(teams, key=lambda t: (primary(t), tiebreak()), reverse=True)
    out, i = [], 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and primary(order[j + 1]) == primary(order[i]):
            j += 1
        cluster = order[i:j + 1]
        if len(cluster) > 1:                      # exact tie → head-to-head mini-table
            cs = set(cluster)
            hp = {t: 0 for t in cluster}; hd = {t: 0 for t in cluster}; hf = {t: 0 for t in cluster}
            for (h, a), (hg, ag) in results.items():
                if h in cs and a in cs:
                    hf[h] += hg; hf[a] += ag; hd[h] += hg - ag; hd[a] += ag - hg
                    if hg > ag: hp[h] += 3
                    elif ag > hg: hp[a] += 3
                    else: hp[h] += 1; hp[a] += 1
            cluster = sorted(cluster, key=lambda t: (hp[t], hd[t], hf[t], tiebreak()), reverse=True)
        out.extend(cluster); i = j + 1
    return out


def played_group_results(schedule):
    """{group: {(home,away): (hg,ag)}} for FINISHED group-stage matches, oriented to
    each group's fixture order (home=teams[i], away=teams[j]) so it lines up with
    sim_group / group_predictions. `schedule` is wc_schedule.json (keyed by sorted
    pair, goals stored by team name). Lets the sim and bracket condition on what has
    actually happened instead of re-predicting every group game from scratch."""
    out = {g: {} for g in GROUPS}
    for g, teams in GROUPS.items():
        for i in range(len(teams)):
            for j in range(i + 1, len(teams)):
                h, a = teams[i], teams[j]
                info = schedule.get('|'.join(sorted([h, a]))) or {}
                goals = info.get('goals') or {}
                # Require non-null scores: a match can be FINISHED yet carry null
                # goals (awarded/abandoned game or an API glitch) — key-presence is
                # not enough, or sim_group hits None > None.
                if info.get('status') == 'FINISHED' and goals.get(h) is not None and goals.get(a) is not None:
                    out[g][(h, a)] = (goals[h], goals[a])
    return out


def assign_thirds(best8, r32_var):
    """Assign the 8 best third-place teams to the variable R32 slots so each third
    lands in an ELIGIBLE slot, one-to-one. Each slot's eligibility set excludes its
    own group, so a complete eligible matching is guaranteed free of same-group R32
    ties. Backtracking (most-constrained slot first) always finds that matching when
    one exists — unlike the old greedy first-fit, whose fallback ignored eligibility
    and could occasionally pair e.g. 1B vs 3B (Switzerland vs Qatar)."""
    slots = [s for s, _ in r32_var]
    elig  = {s: e for s, e in r32_var}
    thirds = list(best8)                        # tuples (pts, gd, gs, grp, team)
    order = sorted(slots, key=lambda s: sum(1 for t in thirds if t[3] in elig[s]))
    asgn, used = {}, [False] * len(thirds)
    def bt(k):
        if k == len(order): return True
        s = order[k]
        for i, t in enumerate(thirds):
            if not used[i] and t[3] in elig[s]:
                used[i] = True; asgn[s] = t[4]
                if bt(k + 1): return True
                used[i] = False; del asgn[s]
        return False
    if bt(0):
        return asgn
    # Degenerate fallback (shouldn't trigger): fill remaining slots but never pair
    # a third with its OWN group's winner (slot "1X" -> group X).
    leftover = [t for i, t in enumerate(thirds) if not used[i]]
    for s in slots:
        if s in asgn:
            continue
        pick = next((j for j, t in enumerate(leftover) if t[3] != s[1]), 0 if leftover else None)
        if pick is not None:
            asgn[s] = leftover.pop(pick)[4]
    return asgn


def load_ensemble(cache, base_dir):
    """Bootstrap ensemble lives in its own (uncommitted) dc_ensemble.json,
    regenerated each run. Fall back to an inline copy or the point estimate."""
    import os, json
    p = os.path.join(base_dir, "dc_ensemble.json")
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return cache.get("dc_ensemble") or [cache["dc"]]


def build_lambda_table(atkd, defd, home_adv, elo=None):
    """(lam, mu) for every ordered WC-team pair from one parameter set.
    Squad value + long-run Elo enter symmetrically (eff_params); host nations get
    a crowd boost in EVERY round they play. Shared by sim_improved.py and
    bracket_predictor.py so both pipelines use identical match expectations."""
    avg_a = sum(atkd.values()) / len(atkd)
    avg_d = sum(defd.values()) / len(defd)
    avg_e = (sum(elo.values()) / len(elo)) if elo else None
    host_adv = home_adv * HOST_ADV_FRACTION
    eff = {t: eff_params(t, atkd, defd, avg_a, avg_d, elo, avg_e) for t in ALL_TEAMS}
    lg = {}
    for home in ALL_TEAMS:
        ah, dh = eff[home]
        hb = host_adv if home in HOST_NATIONS else 0.0
        for away in ALL_TEAMS:
            if home == away:
                continue
            aa, da = eff[away]
            ab = host_adv if away in HOST_NATIONS else 0.0
            lg[(home, away)] = (_clamp_lambda(shrink_lambda(math.exp(ah + da + hb))),
                                _clamp_lambda(shrink_lambda(math.exp(aa + dh + ab))))
    return lg


def _clamp_lambda(x):
    return min(max(x, LAMBDA_MIN), LAMBDA_MAX)


def hda_probs_ensemble(home, away, lg_ens, max_g=10):
    """Mean P(home win), P(draw), P(away win) over an ensemble of lambda tables,
    computed analytically (Dixon-Coles tau omitted — negligible for display)."""
    import math as _m
    ph = pd = pa = 0.0
    for lg in lg_ens:
        lam, mu = lg[(home, away)]
        elam, emu = _m.exp(-lam), _m.exp(-mu)
        # Poisson pmfs up to max_g
        ph_l = [elam * lam**h / _m.factorial(h) for h in range(max_g + 1)]
        pa_l = [emu * mu**a / _m.factorial(a) for a in range(max_g + 1)]
        for h in range(max_g + 1):
            for a in range(max_g + 1):
                p = ph_l[h] * pa_l[a]
                if h > a: ph += p
                elif h < a: pa += p
                else: pd += p
    s = ph + pd + pa   # normalise (the score grid drops a tiny high-score tail)
    return (ph / s, pd / s, pa / s) if s else (0.0, 0.0, 0.0)


def likely_score(lam, mu, allowed=None, max_g=6):
    """Most probable (home, away) scoreline under independent Poisson, optionally
    restricted to scorelines whose result is in `allowed` ('H'/'D'/'A'). Keeps the
    displayed score consistent with the predicted result — never '0-0' next to a
    named winner."""
    best_p, best = -1.0, (round(lam), round(mu))
    for h in range(max_g + 1):
        ph = (lam ** h * math.exp(-lam)) / math.factorial(h)
        for a in range(max_g + 1):
            res = 'H' if h > a else ('A' if h < a else 'D')
            if allowed and res not in allowed:
                continue
            p = ph * (mu ** a * math.exp(-mu)) / math.factorial(a)
            if p > best_p:
                best_p = p; best = (h, a)
    return best
