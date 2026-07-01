"""
Improved 2026 World Cup simulator v3.
Fixes applied:
  - L2-regularised Dixon-Coles (reduces Norway overfit)
  - Host nation crowd advantage for USA/Canada/Mexico group stage
  - Calibrated penalties, correct R32 bracket, recency decay
"""
import sys, json, math, random, time, warnings
import numpy as np
from collections import defaultdict
warnings.filterwarnings("ignore")

import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fit_improved import SQUAD_VALUES, INIT_ELO
from model_common import (GROUPS, ALL_TEAMS, PEN, pen_prob, build_lambda_table,
                          load_ensemble, rank_group, assign_thirds, played_group_results,
                          played_ko_results, draw_mix, sample_inflated_score, DRAW_INFLATE)

_DIR = os.path.dirname(os.path.abspath(__file__))
with open("model_params.json") as f:
    cache = json.load(f)
ELO  = cache["elo"]

# Condition the tournament on results already played: real group scores are fixed,
# only the remaining group games are simulated. Without this the sim re-predicts
# every group game each run, so standings/odds ignore what actually happened.
try:
    with open(os.path.join(_DIR, "wc_schedule.json")) as f:
        _sched_data = json.load(f)
    PLAYED = played_group_results(_sched_data)
    KO_PLAYED = played_ko_results(_sched_data)
except (FileNotFoundError, ValueError):
    _sched_data = {}
    PLAYED = {g: {} for g in GROUPS}
    KO_PLAYED = {}

# Bootstrap ensemble: one (host-aware, squad-symmetric) lambda table per refit.
# Each simulated tournament draws a random member, propagating parameter
# uncertainty into the results. build_lambda_table is shared with the bracket
# predictor so both pipelines use identical match expectations.
ENSEMBLE = load_ensemble(cache, _DIR)
LG_ENS = [build_lambda_table(m["attack"], m["defense"], m["home_adv"], ELO) for m in ENSEMBLE]
NMEM = len(LG_ENS)

# Fast scalar Poisson (Knuth) — avoids numpy isscalar overhead on scalar draws.
_rnd = random.random
_exp = math.exp
def _pois(lam):
    L = _exp(-lam); p = 1.0; k = 0
    while p > L: p *= _rnd(); k += 1
    return k - 1

# Penalty win probabilities are parameter-independent — precompute once.
PEN_PROB = {(a, b): pen_prob(a, b, ELO) for a in ALL_TEAMS for b in ALL_TEAMS if a != b}

# Diagonal draw-inflation: precompute a sampler per (ensemble member × group fixture).
GROUP_PAIRS = [(teams[i], teams[j]) for teams in GROUPS.values()
               for i in range(len(teams)) for j in range(i + 1, len(teams))]
INFL = [{(h, a): draw_mix(LG_ENS[m][(h, a)][0], LG_ENS[m][(h, a)][1], DRAW_INFLATE)
         for (h, a) in GROUP_PAIRS} for m in range(NMEM)]

def sim_score_g(lg, home, away):
    lam, mu = lg[(home, away)]
    return _pois(lam), _pois(mu)

def ko_result(lg, a, b):
    sk = '|'.join(sorted([a, b]))
    if sk in KO_PLAYED:
        return KO_PLAYED[sk]['winner']
    hg, ag = sim_score_g(lg, a, b)
    if hg > ag: return a
    if ag > hg: return b
    return a if random.random() < PEN_PROB[(a, b)] else b

# Correct R32 bracket
R32_FIXED = [("2A","2B"),("1C","2F"),("1F","2C"),("2E","2I"),
             ("1H","2J"),("1J","2H"),("2K","2L"),("2D","2G")]
R32_VAR   = [("1E",{"A","B","C","D","F"}),("1I",{"C","D","F","G","H"}),
             ("1A",{"C","E","F","H","I"}),("1L",{"E","H","I","J","K"}),
             ("1D",{"B","E","F","I","J"}),("1G",{"A","E","H","I","J"}),
             ("1B",{"E","F","G","I","J"}),("1K",{"D","E","I","J","L"})]

R16_PAIRS = [(0,2),(1,3),(4,6),(5,7),(8,9),(10,11),(12,13),(14,15)]
QF_PAIRS  = [(0,4),(2,6),(1,5),(3,7)]
SF_PAIRS  = [(0,1),(2,3)]

# The R16/QF/SF pairing above assumes a fixed bracket topology that can be
# wrong for the portion of the draw seeded from variable third-place teams
# (mirrors the R32 third-place guess issue in bracket_predictor.py — see
# resolve_round() there for the full rationale). Once the real schedule names
# a concrete fixture between two teams from the previous round, trust it over
# the guessed index pairing.
_GP_PAIRS = frozenset(frozenset([GROUPS[g][i], GROUPS[g][j]])
                      for g in GROUPS for i in range(len(GROUPS[g]))
                      for j in range(i + 1, len(GROUPS[g])))
_ROUND_WINDOWS = {"r16": ("2026-07-04", "2026-07-09"),
                  "qf":  ("2026-07-09", "2026-07-14"),
                  "sf":  ("2026-07-14", "2026-07-18")}
def _real_pairs_within(teams, window):
    ws, we = window
    real = {}
    for key, v in _sched_data.items():
        ts = key.split('|')
        if frozenset(ts) in _GP_PAIRS:
            continue
        d = v.get("date", "")
        if d < ws or d >= we:
            continue
        if ts[0] in teams and ts[1] in teams:
            real[ts[0]] = ts[1]; real[ts[1]] = ts[0]
    return real

def resolve_round(prev_winners, guessed_pairs, round_key):
    real = _real_pairs_within(prev_winners, _ROUND_WINDOWS[round_key])
    used, out = set(), []
    for i, j in guessed_pairs:
        a, b = prev_winners[i], prev_winners[j]
        if a in used or b in used:
            continue
        ra = real.get(a)
        if ra is not None and ra != b and ra not in used:
            out.append((a, ra)); used.update((a, ra))
        else:
            out.append((a, b)); used.update((a, b))
    leftover = [t for t in prev_winners if t not in used]
    for k in range(0, len(leftover) - 1, 2):
        out.append((leftover[k], leftover[k + 1]))
    return out

def sim_group(lg, teams, played, infl):
    s = {t:[0,0,0] for t in teams}; res = {}
    for i in range(len(teams)):
        for j in range(i+1,len(teams)):
            h,a = teams[i],teams[j]
            if (h,a) in played:
                hg,ag = played[(h,a)]
            else:
                hg,ag = sample_inflated_score(lg[(h,a)][0], lg[(h,a)][1], infl.get((h,a)), _pois, _rnd)
            res[(h,a)] = (hg,ag)
            if hg>ag: s[h][0]+=3
            elif ag>hg: s[a][0]+=3
            else: s[h][0]+=1; s[a][0]+=1
            s[h][1]+=hg-ag; s[a][1]+=ag-hg; s[h][2]+=hg; s[a][2]+=ag
    return rank_group(teams, s, res, random.random), s

def sim_tournament(lg, infl):
    gw,gr = {},{}; thirds=[]
    for g,teams in GROUPS.items():
        ranked,s = sim_group(lg,teams,PLAYED[g],infl)
        gw[g],gr[g] = ranked[0],ranked[1]
        t3=ranked[2]; st=s[t3]
        thirds.append((st[0],st[1],st[2],g,t3))
    thirds.sort(reverse=True)
    var = assign_thirds(thirds[:8], R32_VAR)
    def res(slot):
        if slot[0]=="1": return gw[slot[1]]
        if slot[0]=="2": return gr[slot[1]]
        return var.get(slot,"Unknown")
    r32p = [(res(a),res(b)) for a,b in R32_FIXED]
    for slot,_ in R32_VAR: r32p.append((gw[slot[1]], var.get(slot,"Unknown")))
    r32w = [ko_result(lg,a,b) for a,b in r32p]
    r16w = [ko_result(lg,a,b) for a,b in resolve_round(r32w, R16_PAIRS, "r16")]
    qfw  = [ko_result(lg,a,b) for a,b in resolve_round(r16w, QF_PAIRS,  "qf")]
    sfw  = [ko_result(lg,a,b) for a,b in resolve_round(qfw,  SF_PAIRS,  "sf")]
    champ = ko_result(lg,sfw[0],sfw[1])
    return champ, set(sfw), set(qfw), set(r16w)

def run_sims(n=100_000):
    random.seed(42); np.random.seed(42)
    wins=defaultdict(int); finals=defaultdict(int)
    sfs=defaultdict(int);  qfs=defaultdict(int)
    mem_wins=[defaultdict(int) for _ in range(NMEM)]; mem_n=[0]*NMEM
    t0=time.time()
    for i in range(n):
        if i%25000==0 and i: print(f"  {i:,}/{n:,}...")
        m = random.randrange(NMEM)
        champ,sf,qf,r16 = sim_tournament(LG_ENS[m], INFL[m])
        wins[champ]+=1; mem_wins[m][champ]+=1; mem_n[m]+=1
        for t in sf:  finals[t]+=1
        for t in qf:  sfs[t]+=1
        for t in r16: qfs[t]+=1
    print(f"  Done in {time.time()-t0:.1f}s")

    # Confidence band: spread of each team's title odds ACROSS ensemble members
    # (10th–90th percentile) — surfaces the parameter uncertainty the ensemble
    # already captures. With one member there's no spread, so band = point.
    def band(t):
        vals = sorted(mem_wins[m][t]/mem_n[m] for m in range(NMEM) if mem_n[m])
        if not vals: return 0.0, 0.0
        return vals[int(0.10*(len(vals)-1))], vals[int(0.90*(len(vals)-1))]

    out={}
    for t in ALL_TEAMS:
        lo,hi = band(t)
        out[t]={"win":wins[t]/n,"final":finals[t]/n,"sf":sfs[t]/n,"qf":qfs[t]/n,
                "win_lo":lo,"win_hi":hi}
    return out

def apply_daily_deltas(results, hist_file="win_history.json"):
    """Embed win_delta = today's win% minus the most recent PRIOR day's win%.
    Persists a small per-day snapshot so the delta is genuinely day-over-day and
    stable across the multiple runs we do each day (not just 'since last run')."""
    from datetime import datetime
    today = datetime.utcnow().strftime("%Y-%m-%d")
    try:
        hist = json.load(open(hist_file))
    except Exception:
        hist = {}
    prior = [d for d in hist if d < today]
    prev = hist[max(prior)] if prior else {}
    for t, r in results.items():
        base = prev.get(t)
        r["win_delta"] = (round(r["win"] - base, 4) if base is not None else None)
    # Record today's latest win% (overwrites earlier runs today); keep last 8 days.
    hist[today] = {t: round(r["win"], 4) for t, r in results.items()}
    for d in sorted(hist)[:-8]:
        del hist[d]
    with open(hist_file, "w") as f:
        json.dump(hist, f, indent=2)
    return results

def print_and_save(results, n, v1=None):
    ranked = sorted(results.items(),key=lambda x:-x[1]["win"])
    print("\n" + "="*74)
    print(f"  2026 WORLD CUP  --  MODEL v3   ({n:,} simulations)")
    print("  + L2 regularisation  + host advantage  + calibrated penalties")
    print("="*74)
    print(f"  {'Rk':<4}{'Team':<22}{'Win%':<8}{'vs v2':<7}{'Final%':<9}{'SF%':<8}{'QF%':<8}{'Elo'}")
    print("  "+"-"*72)
    for rank,(team,r) in enumerate(ranked,1):
        elo_v  = ELO.get(team,INIT_ELO)
        mark = ">" if rank<=6 else " "
        delta = ""
        if v1 and team in v1:
            d = r["win"]-v1[team]["win"]
            delta = f"{d:+.1%}"
        print(f"  {mark}{rank:<3}{team:<22}{r['win']:5.1%}  {delta:<6} "
              f"{r['final']:5.1%}   {r['sf']:5.1%}   {r['qf']:5.1%}   {elo_v:.0f}")
    print("\n  GROUPS")
    print("  "+"-"*72)
    for g,teams in sorted(GROUPS.items()):
        grp=sorted([(t,results[t]["win"]) for t in teams],key=lambda x:-x[1])
        print("  Grp "+g+": "+" | ".join(f"{t} {v:.1%}" for t,v in grp))
    print("\n  TOP 8")
    print("  "+"-"*72)
    for rank,(team,r) in enumerate(ranked[:8],1):
        bar="#"*int(r["win"]*300); sv=SQUAD_VALUES.get(team,0)
        print(f"  {rank}. {team:<20}{r['win']:5.1%}  squad:E{sv}M  {bar}")
    print()
    _r = lambda v: v if v is None else round(v,4)
    with open("wc2026_v2_results.json","w") as f:
        json.dump({t:{k:_r(v) for k,v in r.items()} for t,r in results.items()},f,indent=2)
    print("  Saved: wc2026_v2_results.json")
    return ranked

if __name__=="__main__":
    N = int(sys.argv[1]) if len(sys.argv)>1 else 75_000
    try:
        v1 = json.load(open("wc2026_v2_results.json"))
    except Exception:
        v1 = None
    print(f"Loaded {NMEM} bootstrap parameter set(s); lambda tables ready.")
    print(f"Running {N:,} simulations...")
    results = run_sims(N)
    results = apply_daily_deltas(results)
    print_and_save(results, N, v1)
