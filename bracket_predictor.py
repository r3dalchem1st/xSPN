"""
Full match-by-match WC 2026 predictor.
Outputs: group stage (72 matches) + knockout bracket (32 matches) with
predicted winner and most-likely score for every match.
"""
import sys, json, math, random
import numpy as np
from collections import defaultdict, Counter
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fit_improved import SQUAD_VALUES, squad_adj, INIT_ELO

with open("model_params.json") as f:
    cache = json.load(f)
ELO = cache["elo"]
DC  = cache["dc"]
ATK = DC["attack"]; DEF = DC["defense"]
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

HOST_NATIONS = {"USA", "Canada", "Mexico"}
_HOST_ADV = DC["home_adv"] * 0.65   # 65% of learned home advantage for hosts

def get_lambdas(home, away, host_group=False):
    a_h = ATK.get(home, AVG_ATK) + 0.5 * squad_adj(home)
    d_h = DEF.get(home, AVG_DEF)
    a_a = ATK.get(away, AVG_ATK) + 0.5 * squad_adj(away)
    d_a = DEF.get(away, AVG_DEF)
    if host_group and home in HOST_NATIONS:
        lam = max(math.exp(a_h + d_a + _HOST_ADV), 0.20)
    else:
        lam = max(math.exp(a_h + d_a), 0.20)
    if host_group and away in HOST_NATIONS:
        mu  = max(math.exp(a_a + d_h + _HOST_ADV), 0.20)
    else:
        mu  = max(math.exp(a_a + d_h), 0.20)
    return lam, mu

def likely_score(lam, mu, max_g=6):
    """Most probable (home, away) score pair under Poisson."""
    best_p, best = 0.0, (round(lam), round(mu))
    from math import exp, factorial
    for h in range(max_g+1):
        for a in range(max_g+1):
            ph = (lam**h * exp(-lam)) / factorial(h)
            pa = (mu**a  * exp(-mu))  / factorial(a)
            if ph*pa > best_p:
                best_p = ph*pa; best = (h, a)
    return best

def win_prob(lam, mu, n=4000):
    """P(home win), P(draw), P(away win) via simulation."""
    hg = np.random.poisson(lam, n); ag = np.random.poisson(mu, n)
    ph = (hg > ag).mean(); pa = (ag > hg).mean()
    return ph, 1-ph-pa, pa

PEN = {"Germany":0.75,"Argentina":0.67,"Portugal":0.67,"Croatia":0.75,
       "South Korea":0.67,"Uruguay":0.67,"France":0.50,"Brazil":0.42,
       "Netherlands":0.40,"Spain":0.50,"England":0.38,"Japan":0.50}

def ko_win_prob(a, b):
    lam, mu = get_lambdas(a, b)
    ph, pd, pa = win_prob(lam, mu)
    sa = PEN.get(a, 0.50); sb = PEN.get(b, 0.50)
    ea = ELO.get(a, INIT_ELO); eb = ELO.get(b, INIT_ELO)
    pen_a = max(0.30, min(0.70, sa/(sa+sb) + 0.03*math.tanh((ea-eb)/300)))
    # Probability a wins = ph + pd * pen_a
    return ph + pd * pen_a

# ── Group stage ────────────────────────────────────────────────────────────────
GROUP_FIXTURES = {}  # group -> list of (home, away, match_num)
for g, teams in GROUPS.items():
    fixtures = []
    n = 0
    for i in range(len(teams)):
        for j in range(i+1, len(teams)):
            n += 1
            fixtures.append((teams[i], teams[j], n))
    GROUP_FIXTURES[g] = fixtures

# Compute predicted score + probabilities for every group match
group_predictions = {}  # group -> list of match dicts
for g, fixtures in GROUP_FIXTURES.items():
    preds = []
    for home, away, mn in fixtures:
        lam, mu = get_lambdas(home, away, host_group=True)
        hs, as_ = likely_score(lam, mu)
        ph, pd, pa = win_prob(lam, mu)
        preds.append({
            "home": home, "away": away,
            "lam": round(lam,2), "mu": round(mu,2),
            "score": f"{hs}–{as_}",
            "ph": round(ph,3), "pd": round(pd,3), "pa": round(pa,3),
            "likely_winner": home if ph>pa else (away if pa>ph else "Draw"),
        })
    group_predictions[g] = preds

# ── Simulate 50k tournaments to find modal knockout path ──────────────────────
random.seed(42); np.random.seed(42)

# Track who wins each slot in the bracket
R32_WINS   = defaultdict(Counter)  # slot_idx -> Counter of teams
R16_WINS   = defaultdict(Counter)
QF_WINS    = defaultdict(Counter)
SF_WINS    = defaultdict(Counter)
FINAL_WINS = Counter()
CHAMPION   = Counter()

R32_FIXED = [("2A","2B"),("1C","2F"),("1F","2C"),("2E","2I"),
             ("1H","2J"),("1J","2H"),("2K","2L"),("2D","2G")]
R32_VAR   = [("1E",{"A","B","C","D","F"}),("1I",{"C","D","F","G","H"}),
             ("1A",{"C","E","F","H","I"}),("1L",{"E","H","I","J","K"}),
             ("1D",{"B","E","F","I","J"}),("1G",{"A","E","H","I","J"}),
             ("1B",{"E","F","G","I","J"}),("1K",{"D","E","I","J","L"})]
R16_PAIRS = [(0,2),(1,3),(4,6),(5,7),(8,10),(9,11),(12,14),(13,15)]
QF_PAIRS  = [(0,1),(2,3),(4,5),(6,7)]
SF_PAIRS  = [(0,1),(2,3)]

def sim_score(h, a, host_group=False):
    lam, mu = get_lambdas(h, a, host_group=host_group)
    return int(np.random.poisson(lam)), int(np.random.poisson(mu))

def ko_result(a, b):
    hg, ag = sim_score(a, b)
    if hg > ag: return a
    if ag > hg: return b
    sa = PEN.get(a, 0.50); sb = PEN.get(b, 0.50)
    ea = ELO.get(a, INIT_ELO); eb = ELO.get(b, INIT_ELO)
    pen = max(0.30, min(0.70, sa/(sa+sb) + 0.03*math.tanh((ea-eb)/300)))
    return a if random.random() < pen else b

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

def sim_group(teams):
    s = {t:[0,0,0] for t in teams}
    for i in range(len(teams)):
        for j in range(i+1, len(teams)):
            h, a = teams[i], teams[j]
            hg, ag = sim_score(h, a, host_group=True)  # host crowd boost
            if hg>ag: s[h][0]+=3
            elif ag>hg: s[a][0]+=3
            else: s[h][0]+=1; s[a][0]+=1
            s[h][1]+=hg-ag; s[a][1]+=ag-hg; s[h][2]+=hg; s[a][2]+=ag
    ranked = sorted(teams, key=lambda t:(s[t][0],s[t][1],s[t][2],random.random()), reverse=True)
    return ranked, s

N = 50000
for _ in range(N):
    gw, gr = {}, {}; thirds = []
    for g, teams in GROUPS.items():
        ranked, s = sim_group(teams)
        gw[g], gr[g] = ranked[0], ranked[1]
        t3 = ranked[2]; st = s[t3]
        thirds.append((st[0],st[1],st[2],g,t3))
    thirds.sort(reverse=True)
    var = assign_thirds(thirds[:8])

    def res(slot):
        if slot[0]=="1": return gw[slot[1]]
        if slot[0]=="2": return gr[slot[1]]
        return var.get(slot, "Unknown")

    r32p = [(res(a),res(b)) for a,b in R32_FIXED]
    for slot,_ in R32_VAR: r32p.append((gw[slot[1]], var.get(slot,"Unknown")))
    r32w = [ko_result(a,b) for a,b in r32p]
    for i,w in enumerate(r32w): R32_WINS[i][w] += 1
    r16w = [ko_result(r32w[p[0]],r32w[p[1]]) for p in R16_PAIRS]
    for i,w in enumerate(r16w): R16_WINS[i][w] += 1
    qfw  = [ko_result(r16w[p[0]],r16w[p[1]]) for p in QF_PAIRS]
    for i,w in enumerate(qfw):  QF_WINS[i][w]  += 1
    sfw  = [ko_result(qfw[p[0]],qfw[p[1]])   for p in SF_PAIRS]
    for i,w in enumerate(sfw):  SF_WINS[i][w]  += 1
    champ = ko_result(sfw[0], sfw[1])
    CHAMPION[champ] += 1

def top(ctr, pct=True):
    if not ctr: return "TBD", 0
    team, cnt = ctr.most_common(1)[0]
    return team, round(cnt/N*100, 1) if pct else cnt

# ── Build group winner/runner-up predictions ──────────────────────────────────
GROUP_ADVANCE = {}
for g, teams in GROUPS.items():
    # Simulate group standing distribution
    win_cnt   = Counter(); ru_cnt = Counter(); t3_cnt = Counter()
    for _ in range(20000):
        ranked, _ = sim_group(teams)
        win_cnt[ranked[0]] += 1; ru_cnt[ranked[1]] += 1; t3_cnt[ranked[2]] += 1
    GROUP_ADVANCE[g] = {
        "winner": win_cnt.most_common(1)[0],
        "runner": ru_cnt.most_common(1)[0],
        "third":  t3_cnt.most_common(1)[0],
        "win_pct": {t: round(win_cnt[t]/20000*100,1) for t in teams},
        "ru_pct":  {t: round(ru_cnt[t]/20000*100,1) for t in teams},
    }

# ── Build knockout bracket ────────────────────────────────────────────────────
def get_bracket_match(round_wins, match_idx):
    team, pct = top(round_wins[match_idx])
    lam, mu = get_lambdas(team, "Spain")  # dummy — score shown differently
    return team, pct

# Most likely bracket path
r32_teams = [top(R32_WINS[i]) for i in range(16)]
r16_teams = [top(R16_WINS[i]) for i in range(8)]
qf_teams  = [top(QF_WINS[i])  for i in range(4)]
sf_teams  = [top(SF_WINS[i])  for i in range(2)]
champion  = top(CHAMPION)

# Build KO match predictions
def ko_match_pred(team_a_info, team_b_info):
    a, a_pct = team_a_info
    b, b_pct = team_b_info
    if a == "TBD" or b == "TBD":
        return {"home":a,"away":b,"score":"?–?","winner":"TBD","pct":0}
    lam, mu = get_lambdas(a, b)
    hs, as_ = likely_score(lam, mu)
    pw = ko_win_prob(a, b)
    winner = a if pw >= 0.5 else b
    wp = pw if pw >= 0.5 else 1-pw
    return {"home":a,"away":b,"lam":round(lam,2),"mu":round(mu,2),
            "score":f"{hs}–{as_}","winner":winner,"win_pct":round(wp*100,1)}

# Build all R32 matches (use modal teams from simulations for opponent slots)
# Compute R32 matchups from the modal group finishes
modal_gw = {g: GROUP_ADVANCE[g]["winner"][0] for g in GROUPS}
modal_gr = {g: GROUP_ADVANCE[g]["runner"][0] for g in GROUPS}
modal_t3 = {g: GROUP_ADVANCE[g]["third"][0]  for g in GROUPS}

def modal_res(slot, var_asgn):
    if slot[0]=="1": return modal_gw[slot[1]]
    if slot[0]=="2": return modal_gr[slot[1]]
    return var_asgn.get(slot, "TBD")

# Modal third-place assignment (simplified — use top 8 groups by third-place strength)
var_asgn = {slot: modal_t3[sorted(elig)[0]] for slot, elig in R32_VAR}

r32_matchups = [(modal_res(a, var_asgn), modal_res(b, var_asgn)) for a,b in R32_FIXED]
for slot,_ in R32_VAR:
    r32_matchups.append((modal_gw[slot[1]], var_asgn.get(slot, "TBD")))

r32_preds = [ko_match_pred((a,0),(b,0)) for a,b in r32_matchups]
r32w_modal = [p["winner"] for p in r32_preds]

r16_matchups = [(r32w_modal[p[0]], r32w_modal[p[1]]) for p in R16_PAIRS]
r16_preds = [ko_match_pred((a,0),(b,0)) for a,b in r16_matchups]
r16w_modal = [p["winner"] for p in r16_preds]

qf_matchups = [(r16w_modal[p[0]], r16w_modal[p[1]]) for p in QF_PAIRS]
qf_preds = [ko_match_pred((a,0),(b,0)) for a,b in qf_matchups]
qfw_modal = [p["winner"] for p in qf_preds]

sf_matchups = [(qfw_modal[p[0]], qfw_modal[p[1]]) for p in SF_PAIRS]
sf_preds = [ko_match_pred((a,0),(b,0)) for a,b in sf_matchups]
sfw_modal = [p["winner"] for p in sf_preds]

final_pred = ko_match_pred((sfw_modal[0],0),(sfw_modal[1],0))
sf1_loser = sf_matchups[0][1] if sfw_modal[0] == sf_matchups[0][0] else sf_matchups[0][0]
sf2_loser = sf_matchups[1][1] if sfw_modal[1] == sf_matchups[1][0] else sf_matchups[1][0]
third_pred = ko_match_pred((sf1_loser, 0), (sf2_loser, 0))

# ── Output ─────────────────────────────────────────────────────────────────────
output = {
    "group_predictions": group_predictions,
    "group_advance": {g: {
        "winner": GROUP_ADVANCE[g]["winner"][0],
        "runner": GROUP_ADVANCE[g]["runner"][0],
        "win_pct": GROUP_ADVANCE[g]["win_pct"],
        "ru_pct":  GROUP_ADVANCE[g]["ru_pct"],
    } for g in GROUPS},
    "r32": [{"home": p["home"], "away": p["away"], "score": p["score"],
             "winner": p["winner"], "win_pct": p.get("win_pct",50)} for p in r32_preds],
    "r16": [{"home": p["home"], "away": p["away"], "score": p["score"],
             "winner": p["winner"], "win_pct": p.get("win_pct",50)} for p in r16_preds],
    "qf":  [{"home": p["home"], "away": p["away"], "score": p["score"],
             "winner": p["winner"], "win_pct": p.get("win_pct",50)} for p in qf_preds],
    "sf":  [{"home": p["home"], "away": p["away"], "score": p["score"],
             "winner": p["winner"], "win_pct": p.get("win_pct",50)} for p in sf_preds],
    "final": {"home": final_pred["home"], "away": final_pred["away"],
              "score": final_pred["score"], "winner": final_pred["winner"],
              "win_pct": final_pred.get("win_pct",50)},
    "third_place": {"home": third_pred["home"], "away": third_pred["away"],
                    "score": third_pred["score"], "winner": third_pred["winner"],
                    "win_pct": third_pred.get("win_pct",50)},
    "champion": champion[0],
    "champion_pct": champion[1],
}

with open("bracket_data.json","w") as f:
    json.dump(output, f, indent=2)

print("Done.")
print(f"Champion: {champion[0]} ({champion[1]}%)")
print(f"Final: {final_pred['home']} vs {final_pred['away']} → {final_pred['winner']} {final_pred['score']}")
for i, p in enumerate(sf_preds):
    print(f"SF{i+1}: {p['home']} vs {p['away']} → {p['winner']} {p['score']}")
