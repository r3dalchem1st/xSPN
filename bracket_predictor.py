"""
Full match-by-match WC 2026 predictor.
Outputs: group stage (72 matches) + knockout bracket (32 matches) with
predicted winner and most-likely score for every match.
"""
import sys, json, random
import numpy as np
from collections import defaultdict, Counter
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model_common import GROUPS, pen_prob, build_lambda_table, hda_probs_ensemble, load_ensemble, rank_group, assign_thirds, likely_score, played_group_results, played_ko_results, draw_mix, sample_inflated_score, DRAW_INFLATE

_DIR = os.path.dirname(os.path.abspath(__file__))
with open("model_params.json") as f:
    cache = json.load(f)
ELO = cache["elo"]
ENSEMBLE = load_ensemble(cache, _DIR)

# Use the SAME bootstrap-ensemble lambda tables as the simulator, so the
# bracket / groups / podium tabs are consistent with the Win Odds tab (both
# reflect parameter uncertainty and the same host-aware, squad-symmetric model).
LG_ENS = [build_lambda_table(m["attack"], m["defense"], m["home_adv"], ELO) for m in ENSEMBLE]
NMEM = len(LG_ENS)
# Ensemble-mean (lam, mu) per ordered pair — for the displayed most-likely score.
LG_MEAN = {k: (sum(lg[k][0] for lg in LG_ENS)/NMEM, sum(lg[k][1] for lg in LG_ENS)/NMEM)
           for k in LG_ENS[0]}

# Condition on results already played: group scores are fixed for standing
# computation; KO actual results are locked as the bracket fills in.
try:
    with open(os.path.join(_DIR, "wc_schedule.json")) as f:
        _sched_data = json.load(f)
    PLAYED = played_group_results(_sched_data)
    KO_PLAYED = played_ko_results(_sched_data)
except (FileNotFoundError, ValueError):
    _sched_data = {}
    PLAYED = {g: {} for g in GROUPS}
    KO_PLAYED = {}

# Real R32 draw, when known: the schedule carries the actual cross-group KO
# fixtures (with real dates) as they're drawn. A group winner's EARLIEST KO-window
# fixture is its R32 game, so we can seed the variable third-place slots from the
# real draw instead of guessing the third→slot mapping with assign_thirds — FIFA's
# official mapping depends on WHICH thirds qualify and a bare eligible matching can
# pick a different (valid-but-wrong) pairing (e.g. Belgium–Algeria instead of the
# real Belgium–Senegal, which also let Senegal advance against the wrong opponent).
_GP_PAIRS = frozenset(frozenset([GROUPS[g][i], GROUPS[g][j]])
                      for g in GROUPS for i in range(len(GROUPS[g]))
                      for j in range(i + 1, len(GROUPS[g])))
def _real_r32_opponent(winner):
    cand = []
    for key, v in _sched_data.items():
        ts = key.split('|')
        if winner not in ts or frozenset(ts) in _GP_PAIRS:
            continue
        if v.get("date", "") < "2026-06-28":
            continue
        cand.append((v["date"], ts[0] if ts[1] == winner else ts[1]))
    return min(cand)[1] if cand else None

# Post-R32 rounds (R16/QF/SF) also have a fixed guessed pairing (R16_PAIRS etc.
# below) that assumes a specific bracket topology. Like the R32 third-place
# slots, this guess can be wrong for the portion of the draw seeded from
# variable third-place teams — e.g. the guess paired Paraguay-Mexico/France-
# England in R16, but the real schedule (once both legs of a pairing are
# decided) confirmed France-Paraguay/Canada-Morocco, which by elimination
# means Mexico-England, not the guessed pairing. Once the real fixture list
# names a concrete match between two teams from `prev_winners`, trust it over
# the guess; any winner not confirmed either way keeps its guessed partner.
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
    """Pair up `prev_winners` (slot order) for this round, preferring a
    confirmed real fixture over the index-based `guessed_pairs` fallback."""
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

if KO_PLAYED:
    print("  KO results locked: " + ", ".join(
        f"{v['home']} {v['score']} {v['away']} → {v['winner']}"
        for v in KO_PLAYED.values()))

def _all_played(g):
    """True when every fixture in group g has a real result in PLAYED[g]."""
    n = len(GROUPS[g])
    return len(PLAYED[g]) >= n * (n - 1) // 2

def _actual_group_rank(g):
    """Rank group g by its actual results (only call when _all_played(g))."""
    s = {t: [0, 0, 0] for t in GROUPS[g]}
    res = {}
    for (h, a), (hg, ag) in PLAYED[g].items():
        res[(h, a)] = (hg, ag)
        if hg > ag: s[h][0] += 3
        elif ag > hg: s[a][0] += 3
        else: s[h][0] += 1; s[a][0] += 1
        s[h][1] += hg - ag; s[a][1] += ag - hg; s[h][2] += hg; s[a][2] += ag
    return rank_group(GROUPS[g], s, res, random.random)

_POIS_NP = lambda x: int(np.random.poisson(x))
GROUP_PAIRS = [(teams[i], teams[j]) for teams in GROUPS.values()
               for i in range(len(teams)) for j in range(i + 1, len(teams))]
INFL = [{(h, a): draw_mix(LG_ENS[m][(h, a)][0], LG_ENS[m][(h, a)][1], DRAW_INFLATE)
         for (h, a) in GROUP_PAIRS} for m in range(NMEM)]

# Everything below is deterministic — seed the RNG once, up front.
random.seed(42); np.random.seed(42)

def hda(home, away, group=False):
    """Mean (P home win, draw, away win) over the ensemble — analytic, no RNG."""
    return hda_probs_ensemble(home, away, LG_ENS, group=group)

def ko_win_prob(a, b):
    ph, pd, pa = hda(a, b)
    # a advances by winning in regulation, or drawing then winning the shootout
    return ph + pd * pen_prob(a, b, ELO)

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
        lam, mu = LG_MEAN[(home, away)]
        ph, pd, pa = hda(home, away, group=True)
        # Predicted result = the single most likely OUTCOME, argmax(P_home, P_draw,
        # P_away) — so the winner always agrees with the H/D/A odds shown beside it.
        # The displayed score is then the most likely scoreline CONSISTENT with that
        # outcome (likely_score restricts to it), so "winner" and score never clash.
        # Note: for a goal model a draw is rarely the modal outcome even at ~50/50
        # (≈0.38/0.24/0.38), so a predicted draw is rare though ~30% of games end
        # level — that draw mass lives in the visible pd%, not in the point pick.
        oc = max((ph, 'H'), (pd, 'D'), (pa, 'A'), key=lambda x: x[0])[1]
        hs, as_ = likely_score(lam, mu, allowed={oc}, group=True)
        preds.append({
            "home": home, "away": away,
            "lam": round(lam,2), "mu": round(mu,2),
            "score": f"{hs}–{as_}",
            "ph": round(ph,3), "pd": round(pd,3), "pa": round(pa,3),
            "likely_winner": home if oc=='H' else (away if oc=='A' else "Draw"),
        })
    group_predictions[g] = preds

# Self-check (guards against re-introducing a winner that disagrees with the odds,
# e.g. the old MAP-scoreline rule calling "Draw" next to a clear favourite): the
# named winner's OWN probability must be the maximum of H/D/A. A small tolerance
# absorbs 3-dp rounding and genuine near-ties (where either side is a fair pick)
# while still catching a real regression (a misnamed draw trails by ~0.1+).
for g, preds in group_predictions.items():
    for m in preds:
        wp = m['pd'] if m['likely_winner'] == 'Draw' else (
             m['ph'] if m['likely_winner'] == m['home'] else m['pa'])
        if wp < max(m['ph'], m['pd'], m['pa']) - 0.005:
            raise AssertionError(
                f"Group {g} {m['home']} v {m['away']}: winner {m['likely_winner']!r} "
                f"(p={wp}) is not the most-likely outcome (ph/pd/pa="
                f"{m['ph']}/{m['pd']}/{m['pa']})")

# ── Simulate 50k tournaments to find modal knockout path ──────────────────────
# Track who wins each slot in the bracket
SF_WINS  = defaultdict(Counter)  # slot_idx -> Counter (feeds reach_final)
CHAMPION = Counter()             # modal champion across the sim

R32_FIXED = [("2A","2B"),("1C","2F"),("1F","2C"),("2E","2I"),
             ("1H","2J"),("1J","2H"),("2K","2L"),("2D","2G")]
R32_VAR   = [("1E",{"A","B","C","D","F"}),("1I",{"C","D","F","G","H"}),
             ("1A",{"C","E","F","H","I"}),("1L",{"E","H","I","J","K"}),
             ("1D",{"B","E","F","I","J"}),("1G",{"A","E","H","I","J"}),
             ("1B",{"E","F","G","I","J"}),("1K",{"D","E","I","J","L"})]
R16_PAIRS = [(0,2),(1,3),(4,6),(5,7),(8,10),(9,11),(12,14),(13,15)]
QF_PAIRS  = [(0,1),(2,3),(4,5),(6,7)]
SF_PAIRS  = [(0,1),(2,3)]

def sim_score(lg, h, a):
    lam, mu = lg[(h, a)]
    return int(np.random.poisson(lam)), int(np.random.poisson(mu))

def ko_result(lg, a, b):
    sk = '|'.join(sorted([a, b]))
    if sk in KO_PLAYED:
        return KO_PLAYED[sk]['winner']
    hg, ag = sim_score(lg, a, b)
    if hg > ag: return a
    if ag > hg: return b
    return a if random.random() < pen_prob(a, b, ELO) else b

def sim_group(lg, teams, played, infl):
    s = {t:[0,0,0] for t in teams}; res = {}
    for i in range(len(teams)):
        for j in range(i+1, len(teams)):
            h, a = teams[i], teams[j]
            if (h,a) in played:
                hg, ag = played[(h,a)]
            else:
                hg, ag = sample_inflated_score(lg[(h,a)][0], lg[(h,a)][1], infl.get((h,a)), _POIS_NP, random.random)
            res[(h,a)] = (hg,ag)
            if hg>ag: s[h][0]+=3
            elif ag>hg: s[a][0]+=3
            else: s[h][0]+=1; s[a][0]+=1
            s[h][1]+=hg-ag; s[a][1]+=ag-hg; s[h][2]+=hg; s[a][2]+=ag
    return rank_group(teams, s, res, random.random), s

N = 50000
for _ in range(N):
    m = random.randrange(NMEM)
    lg = LG_ENS[m]                        # draw a bootstrap member per tournament
    gw, gr = {}, {}; thirds = []
    for g, teams in GROUPS.items():
        ranked, s = sim_group(lg, teams, PLAYED[g], INFL[m])
        gw[g], gr[g] = ranked[0], ranked[1]
        t3 = ranked[2]; st = s[t3]
        thirds.append((st[0],st[1],st[2],g,t3))
    thirds.sort(reverse=True)
    var = assign_thirds(thirds[:8], R32_VAR)

    def res(slot):
        if slot[0]=="1": return gw[slot[1]]
        if slot[0]=="2": return gr[slot[1]]
        return var.get(slot, "Unknown")

    r32p = [(res(a),res(b)) for a,b in R32_FIXED]
    for slot,_ in R32_VAR: r32p.append((gw[slot[1]], var.get(slot,"Unknown")))
    r32w = [ko_result(lg,a,b) for a,b in r32p]
    r16w = [ko_result(lg,a,b) for a,b in resolve_round(r32w, R16_PAIRS, "r16")]
    qfw  = [ko_result(lg,a,b) for a,b in resolve_round(r16w, QF_PAIRS,  "qf")]
    sfw  = [ko_result(lg,a,b) for a,b in resolve_round(qfw,  SF_PAIRS,  "sf")]
    for i,w in enumerate(sfw):  SF_WINS[i][w]  += 1   # only SF_WINS is consumed (reach_final)
    champ = ko_result(lg,sfw[0], sfw[1])
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
        _m = random.randrange(NMEM)
        ranked, _ = sim_group(LG_ENS[_m], teams, PLAYED[g], INFL[_m])
        win_cnt[ranked[0]] += 1; ru_cnt[ranked[1]] += 1; t3_cnt[ranked[2]] += 1
    GROUP_ADVANCE[g] = {
        "winner": win_cnt.most_common(1)[0],
        "runner": ru_cnt.most_common(1)[0],
        "third":  t3_cnt.most_common(1)[0],
        "win_pct": {t: round(win_cnt[t]/20000*100,1) for t in teams},
        "ru_pct":  {t: round(ru_cnt[t]/20000*100,1) for t in teams},
    }

# ── Build knockout bracket ────────────────────────────────────────────────────
champion = top(CHAMPION)   # modal champion across the sim (used in output below)

# Build KO match predictions
def ko_match_pred(team_a_info, team_b_info):
    a, a_pct = team_a_info
    b, b_pct = team_b_info
    if a == "TBD" or b == "TBD":
        return {"home":a,"away":b,"score":"?–?","winner":"TBD","win_pct":0}
    lam, mu = LG_MEAN[(a, b)]
    ph, pd, pa = hda(a, b)
    pw = ko_win_prob(a, b)
    reg = a if ph > pa else (b if pa > ph else "Draw")
    sk = '|'.join(sorted([a, b]))
    if sk in KO_PLAYED:
        # Match already played — lock actual result; keep model probs for reference.
        # KO_PLAYED's own home/away is an arbitrary alphabetical pair, not this
        # bracket slot's (a, b) order, so re-derive the score from goals-by-NAME
        # rather than reusing its score string (which was oriented to ITS h/a and
        # would show swapped digits whenever alphabetical order != slot order).
        actual = KO_PLAYED[sk]
        ag_, bg_ = actual['goals'][a], actual['goals'][b]
        score = f"{ag_}–{bg_}" + (" (p)" if ag_ == bg_ else "")
        return {"home":a,"away":b,"lam":round(lam,2),"mu":round(mu,2),
                "score":score,"winner":actual['winner'],
                "win_pct":round(max(pw,1-pw)*100,1),
                "ph":round(ph,3),"pd":round(pd,3),"pa":round(pa,3),"reg_winner":reg}
    winner = a if pw >= 0.5 else b
    wp = pw if pw >= 0.5 else 1-pw
    win_oc = 'H' if winner == a else 'A'
    hs, as_ = likely_score(lam, mu, allowed={win_oc, 'D'})
    score = f"{hs}–{as_}" + (" (p)" if hs == as_ else "")
    return {"home":a,"away":b,"lam":round(lam,2),"mu":round(mu,2),
            "score":score,"winner":winner,"win_pct":round(wp*100,1),
            "ph":round(ph,3),"pd":round(pd,3),"pa":round(pa,3),"reg_winner":reg}

# Build all R32 matches (use modal teams from simulations for opponent slots)
# Compute R32 matchups from the modal group finishes
# Rank each group 1-2-3-4 by expected points — the SAME metric the Groups-tab
# standings use (3·P(win)+1·P(draw)). Using one consistent ordering for
# winner/runner/third makes them mutually distinct, so the R32 ends up with 32
# distinct teams (the old code derived winner/runner from a frequency sim but
# thirds from expected points, so a modal runner-up could also be picked as a
# best third and the team appeared in the bracket twice).
def _expected_standings(g):
    """Group standings [pts, goal-diff, goals-for] mixing ACTUAL results for played
    matches with model expectations (3·P + E[goals]) for the rest — so the seeded
    bracket reflects the real table, not a from-scratch re-prediction."""
    s = {t: [0.0, 0.0, 0.0] for t in GROUPS[g]}
    res = {}
    for m in group_predictions[g]:
        h, a = m["home"], m["away"]
        if (h, a) in PLAYED[g]:
            hg, ag = PLAYED[g][(h, a)]
            res[(h, a)] = (hg, ag)
            if hg > ag: s[h][0] += 3
            elif ag > hg: s[a][0] += 3
            else: s[h][0] += 1; s[a][0] += 1
            s[h][1] += hg - ag; s[a][1] += ag - hg; s[h][2] += hg; s[a][2] += ag
        else:
            s[h][0] += 3*m["ph"] + m["pd"]; s[a][0] += 3*m["pa"] + m["pd"]
            s[h][1] += m["lam"] - m["mu"];  s[a][1] += m["mu"] - m["lam"]
            s[h][2] += m["lam"];            s[a][2] += m["mu"]
    return s, res

# Single source for the displayed finish order so the named group winner/runner
# MATCH the win%/ru% shown beside them (previously the winner came from expected
# points while the %s came from the frequency sim, so they could name different
# teams). 1st/2nd = the frequency sim's MODAL (argmax win%/ru%); 3rd = best REMAINING
# team by expected standings. Distinct 1/2/3 per group -> 32 distinct R32 teams.
_stand = {g: _expected_standings(g)[0] for g in GROUPS}
def _skey(g, t): v = _stand[g][t]; return (v[0], v[1], v[2])
modal_gw, modal_gr, modal_g3 = {}, {}, {}
for g in GROUPS:
    if _all_played(g):
        # Group is finished — use actual standings so the bracket seeds correct teams.
        # Without this, a mismatched opponent in a KO slot lets eliminated teams advance.
        ranked = _actual_group_rank(g)
        modal_gw[g], modal_gr[g], modal_g3[g] = ranked[0], ranked[1], ranked[2]
    else:
        wp, rp = GROUP_ADVANCE[g]["win_pct"], GROUP_ADVANCE[g]["ru_pct"]
        gw = max(GROUPS[g], key=lambda t: wp[t])
        gr = max((t for t in GROUPS[g] if t != gw), key=lambda t: rp[t])
        g3 = max((t for t in GROUPS[g] if t not in (gw, gr)), key=lambda t: _skey(g, t))
        modal_gw[g], modal_gr[g], modal_g3[g] = gw, gr, g3

def modal_res(slot, var_asgn):
    if slot[0]=="1": return modal_gw[slot[1]]
    if slot[0]=="2": return modal_gr[slot[1]]
    return var_asgn.get(slot, "TBD")

# Best-8 third-place qualifiers, assigned to the variable R32 slots via the
# simulation's eligibility logic (each team used exactly once).
_thirds = sorted(((_stand[g][modal_g3[g]][0], _stand[g][modal_g3[g]][1],
                   _stand[g][modal_g3[g]][2], g, modal_g3[g]) for g in GROUPS), reverse=True)
var_asgn = assign_thirds(_thirds[:8], R32_VAR)

r32_matchups = [(modal_res(a, var_asgn), modal_res(b, var_asgn)) for a,b in R32_FIXED]
for slot,_ in R32_VAR:
    w = modal_gw[slot[1]]
    # Prefer the actual drawn opponent (real fixture in the schedule); fall back to
    # the assign_thirds guess only for slots not yet drawn.
    r32_matchups.append((w, _real_r32_opponent(w) or var_asgn.get(slot, "TBD")))

r32_preds = [ko_match_pred((a,0),(b,0)) for a,b in r32_matchups]
r32w_modal = [p["winner"] for p in r32_preds]

r16_matchups = resolve_round(r32w_modal, R16_PAIRS, "r16")
r16_preds = [ko_match_pred((a,0),(b,0)) for a,b in r16_matchups]
r16w_modal = [p["winner"] for p in r16_preds]

qf_matchups = resolve_round(r16w_modal, QF_PAIRS, "qf")
qf_preds = [ko_match_pred((a,0),(b,0)) for a,b in qf_matchups]
qfw_modal = [p["winner"] for p in qf_preds]

sf_matchups = resolve_round(qfw_modal, SF_PAIRS, "sf")
sf_preds = [ko_match_pred((a,0),(b,0)) for a,b in sf_matchups]
sfw_modal = [p["winner"] for p in sf_preds]

final_pred = ko_match_pred((sfw_modal[0],0),(sfw_modal[1],0))
sf1_loser = sf_matchups[0][1] if sfw_modal[0] == sf_matchups[0][0] else sf_matchups[0][0]
sf2_loser = sf_matchups[1][1] if sfw_modal[1] == sf_matchups[1][0] else sf_matchups[1][0]
third_pred = ko_match_pred((sf1_loser, 0), (sf2_loser, 0))

# Probability each team REACHES the final (wins either semi-final slot), from
# the 50k sim. Lets the UI explain why the single modal path can look odd —
# co-favourites drawn into the same half can't both reach the final.
reach_final = {}
for slot in (0, 1):
    for t, c in SF_WINS[slot].items():
        reach_final[t] = reach_final.get(t, 0) + c
reach_final = {t: round(c / N * 100, 1) for t, c in sorted(reach_final.items(), key=lambda x: -x[1])}

# ── Output ─────────────────────────────────────────────────────────────────────
def _ko_out(p):
    """Serialise a KO match, carrying H/D/A scoring fields when present (TBD slots have none)."""
    return {"home": p["home"], "away": p["away"], "score": p["score"],
            "winner": p["winner"], "win_pct": p.get("win_pct", 50),
            "ph": p.get("ph"), "pd": p.get("pd"), "pa": p.get("pa"),
            "reg_winner": p.get("reg_winner"), "lam": p.get("lam"), "mu": p.get("mu")}

output = {
    "group_predictions": group_predictions,
    "group_advance": {g: {
        "winner": modal_gw[g],   # expected-points ordering — matches bracket + standings
        "runner": modal_gr[g],
        "win_pct": GROUP_ADVANCE[g]["win_pct"],
        "ru_pct":  GROUP_ADVANCE[g]["ru_pct"],
    } for g in GROUPS},
    "r32": [_ko_out(p) for p in r32_preds],
    "r16": [_ko_out(p) for p in r16_preds],
    "qf":  [_ko_out(p) for p in qf_preds],
    "sf":  [_ko_out(p) for p in sf_preds],
    "final": _ko_out(final_pred),
    "third_place": _ko_out(third_pred),
    "champion": champion[0],
    "champion_pct": champion[1],
    "reach_final": reach_final,
}

with open("bracket_data.json","w") as f:
    json.dump(output, f, indent=2)

print("Done.")
print(f"Champion: {champion[0]} ({champion[1]}%)")
print(f"Final: {final_pred['home']} vs {final_pred['away']} → {final_pred['winner']} {final_pred['score']}")
for i, p in enumerate(sf_preds):
    print(f"SF{i+1}: {p['home']} vs {p['away']} → {p['winner']} {p['score']}")
