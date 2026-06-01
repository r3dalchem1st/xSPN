"""
Shared constants and helpers for sim_improved.py and bracket_predictor.py.

Centralised here so the two prediction pipelines cannot drift apart (they
previously kept independent copies of GROUPS / PEN / host logic, and the two
penalty tables had already diverged). Import-only; no side effects.
"""
import math
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

# ── Penalty-shootout conversion strengths (WC historical win rates) ──────────
# Canonical table — single source of truth for both pipelines.
PEN = {
    "Germany":0.75,"Argentina":0.67,"Portugal":0.67,"Croatia":0.75,
    "South Korea":0.67,"Uruguay":0.67,"Italy":0.67,"France":0.50,
    "Brazil":0.42,"Netherlands":0.40,"Spain":0.50,"England":0.38,
    "Mexico":0.25,"Denmark":0.33,"Switzerland":0.33,"Japan":0.50,
    "Senegal":0.50,"Colombia":0.50,"Belgium":0.50,"Morocco":0.50,
}


def eff_params(team, ATK, DEF, avg_atk, avg_def):
    """Effective (attack, defence) params for a team, incl. symmetric squad adj."""
    sa = squad_adj(team)
    atk = ATK.get(team, avg_atk) + SQUAD_W * sa
    dfn = DEF.get(team, avg_def) - SQUAD_W * sa
    return atk, dfn


def pen_prob(a, b, ELO):
    """P(a wins a shootout vs b), Elo-tilted and clamped to [0.30, 0.70]."""
    sa = PEN.get(a, 0.50); sb = PEN.get(b, 0.50)
    ea = ELO.get(a, INIT_ELO); eb = ELO.get(b, INIT_ELO)
    edge = 0.03 * math.tanh((ea - eb) / 300)
    return max(0.30, min(0.70, sa / (sa + sb) + edge))
