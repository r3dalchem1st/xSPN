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
from fit_improved import SQUAD_VALUES, squad_adj, INIT_ELO

with open("model_params.json") as f:
    cache = json.load(f)
ELO  = cache["elo"];  DC = cache["dc"]
ATK  = DC["attack"]; DEF = DC["defense"]; RHO = DC["rho"]
AVG_ATK = float(np.mean(list(ATK.values())))
AVG_DEF = float(np.mean(list(DEF.values())))

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

# Pre-compute (lam, mu) for every ordered team pair — neutral venue
LAMBDA = {}
for home in ALL_TEAMS:
    for away in ALL_TEAMS:
        if home == away: continue
        a_h = ATK.get(home, AVG_ATK) + 0.5 * squad_adj(home)
        d_h = DEF.get(home, AVG_DEF)
        a_a = ATK.get(away, AVG_ATK) + 0.5 * squad_adj(away)
        d_a = DEF.get(away, AVG_DEF)
        lam = max(math.exp(a_h + d_a), 0.20)
        mu  = max(math.exp(a_a + d_h), 0.20)
        LAMBDA[(home, away)] = (lam, mu)

# Host nation crowd advantage (USA/Canada/Mexico in group stage)
HOST_NATIONS = {"USA", "Canada", "Mexico"}
_HOST_ADV = DC["home_adv"] * 0.65   # 65% of learned home advantage

# Build LAMBDA_GROUP: same as LAMBDA but host nations get crowd boost.
# Single lookup in the hot sim loop — no branching overhead.
LAMBDA_GROUP = dict(LAMBDA)   # start from neutral copy
for _host in HOST_NATIONS:
    for _opp in ALL_TEAMS:
        if _host == _opp: continue
        _ah = ATK.get(_host, AVG_ATK) + 0.5 * squad_adj(_host)
        _dh = DEF.get(_host, AVG_DEF)
        _ao = ATK.get(_opp,  AVG_ATK) + 0.5 * squad_adj(_opp)
        _do = DEF.get(_opp,  AVG_DEF)
        # host listed first: boost host lambda
        LAMBDA_GROUP[(_host, _opp)] = (
            max(math.exp(_ah + _do + _HOST_ADV), 0.20),
            max(math.exp(_ao + _dh), 0.20),
        )
        # host listed second: boost host mu
        LAMBDA_GROUP[(_opp, _host)] = (
            max(math.exp(_ao + _dh), 0.20),
            max(math.exp(_ah + _do + _HOST_ADV), 0.20),
        )

# Fast scalar Poisson (Knuth) — avoids numpy isscalar overhead on scalar draws.
_rnd = random.random
_exp = math.exp
def _pois(lam):
    L = _exp(-lam); p = 1.0; k = 0
    while p > L: p *= _rnd(); k += 1
    return k - 1

def sim_score_group(home, away):
    lam, mu = LAMBDA_GROUP[(home, away)]
    return _pois(lam), _pois(mu)

# Penalty shootout strength (WC historical win rates)
PEN = {"Germany":0.75,"Argentina":0.67,"Portugal":0.67,"Croatia":0.75,
       "South Korea":0.67,"Uruguay":0.67,"Italy":0.67,"France":0.50,
       "Brazil":0.42,"Netherlands":0.40,"Spain":0.50,"England":0.38,
       "Mexico":0.25,"Denmark":0.33,"Switzerland":0.33,"Japan":0.50,
       "Senegal":0.50,"Colombia":0.50,"Belgium":0.50,"Morocco":0.50}

def pen_prob(a, b):
    sa = PEN.get(a, 0.50); sb = PEN.get(b, 0.50)
    ea = ELO.get(a, INIT_ELO); eb = ELO.get(b, INIT_ELO)
    edge = 0.03 * math.tanh((ea - eb) / 300)
    return max(0.30, min(0.70, sa / (sa + sb) + edge))

PEN_PROB = {(a, b): pen_prob(a, b) for a in ALL_TEAMS for b in ALL_TEAMS if a != b}

def sim_score(home, away):
    lam, mu = LAMBDA[(home, away)]
    return _pois(lam), _pois(mu)

def ko_result(a, b):
    hg, ag = sim_score(a, b)
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

def assign_thirds(best8):
    elig = {s: e for s, e in R32_VAR}
    slots = [s for s, _ in R32_VAR]
    available = list(best8)
    asgn = {}
    for slot in slots:
        for i, (pts, gd, gs, grp, team) in enumerate(available):
            if grp in elig[slot]:
                asgn[slot] = team; available.pop(i); break
    ai = 0
    for slot in slots:
        if slot not in asgn and ai < len(available):
            asgn[slot] = available[ai][4]; ai += 1
    return asgn

R16_PAIRS = [(0,2),(1,3),(4,6),(5,7),(8,10),(9,11),(12,14),(13,15)]
QF_PAIRS  = [(0,1),(2,3),(4,5),(6,7)]
SF_PAIRS  = [(0,1),(2,3)]

def sim_group(teams):
    s = {t:[0,0,0] for t in teams}
    for i in range(len(teams)):
        for j in range(i+1,len(teams)):
            h,a = teams[i],teams[j]
            hg,ag = sim_score_group(h,a)
            if hg>ag: s[h][0]+=3
            elif ag>hg: s[a][0]+=3
            else: s[h][0]+=1; s[a][0]+=1
            s[h][1]+=hg-ag; s[a][1]+=ag-hg; s[h][2]+=hg; s[a][2]+=ag
    ranked = sorted(teams,key=lambda t:(s[t][0],s[t][1],s[t][2],random.random()),reverse=True)
    return ranked, s

def sim_tournament():
    gw,gr = {},{}; thirds=[]
    for g,teams in GROUPS.items():
        ranked,s = sim_group(teams)
        gw[g],gr[g] = ranked[0],ranked[1]
        t3=ranked[2]; st=s[t3]
        thirds.append((st[0],st[1],st[2],g,t3))
    thirds.sort(reverse=True)
    var = assign_thirds(thirds[:8])
    def res(slot):
        if slot[0]=="1": return gw[slot[1]]
        if slot[0]=="2": return gr[slot[1]]
        return var.get(slot,"Unknown")
    r32p = [(res(a),res(b)) for a,b in R32_FIXED]
    for slot,_ in R32_VAR: r32p.append((gw[slot[1]], var.get(slot,"Unknown")))
    r32w = [ko_result(a,b) for a,b in r32p]
    r16w = [ko_result(r32w[p[0]],r32w[p[1]]) for p in R16_PAIRS]
    qfw  = [ko_result(r16w[p[0]],r16w[p[1]]) for p in QF_PAIRS]
    sfw  = [ko_result(qfw[p[0]], qfw[p[1]])  for p in SF_PAIRS]
    champ = ko_result(sfw[0],sfw[1])
    return champ, set(sfw), set(qfw), set(r16w)

def run_sims(n=100_000):
    random.seed(42); np.random.seed(42)
    wins=defaultdict(int); finals=defaultdict(int)
    sfs=defaultdict(int);  qfs=defaultdict(int)
    t0=time.time()
    for i in range(n):
        if i%25000==0 and i: print(f"  {i:,}/{n:,}...")
        champ,sf,qf,r16 = sim_tournament()
        wins[champ]+=1
        for t in sf:  finals[t]+=1
        for t in qf:  sfs[t]+=1
        for t in r16: qfs[t]+=1
    print(f"  Done in {time.time()-t0:.1f}s")
    return {t:{"win":wins[t]/n,"final":finals[t]/n,"sf":sfs[t]/n,"qf":qfs[t]/n}
            for t in ALL_TEAMS}

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
    with open("wc2026_v2_results.json","w") as f:
        json.dump({t:{k:round(v,4) for k,v in r.items()} for t,r in results.items()},f,indent=2)
    print("  Saved: wc2026_v2_results.json")
    return ranked

if __name__=="__main__":
    N = int(sys.argv[1]) if len(sys.argv)>1 else 75_000
    try:
        v1 = json.load(open("wc2026_v2_results.json"))
    except Exception:
        v1 = None
    print(f"Pre-computing lambdas for {len(LAMBDA)} team pairs... done.")
    print(f"Running {N:,} simulations...")
    results = run_sims(N)
    print_and_save(results, N, v1)
