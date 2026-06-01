"""
Reads JSON data files + template.html, injects data, writes index.html.
"""
import json, os
from datetime import datetime

DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(DIR, 'wc2026_v2_results.json')) as f:
    results = json.load(f)
with open(os.path.join(DIR, 'bracket_data.json')) as f:
    bracket = json.load(f)
with open(os.path.join(DIR, 'model_params.json')) as f:
    model = json.load(f)

_acc_file = os.path.join(DIR, 'results_accuracy.json')
if os.path.exists(_acc_file):
    with open(_acc_file) as f:
        accuracy = json.load(f)
else:
    accuracy = {"matches": [], "summary": {"total_matches": 0, "correct_winners": 0,
                                            "accuracy": 0, "avg_goal_error": 0, "avg_brier": 0}}

elo = model['elo']
SQUAD = {
    'England':1300,'France':1280,'Spain':920,'Brazil':1000,'Germany':850,
    'Portugal':850,'Netherlands':720,'Argentina':570,'Belgium':550,'Colombia':450,
    'Turkey':460,'Italy':730,'Norway':420,'Switzerland':280,'Japan':290,
    'South Korea':250,'Mexico':300,'USA':350,'Croatia':350,'Uruguay':280,
    'Morocco':255,'Austria':280,'Ecuador':220,'Senegal':300,'Sweden':255,
    'Egypt':200,'Australia':185,'Algeria':195,'Paraguay':140,'Tunisia':160,
    'Saudi Arabia':120,'Canada':355,'Ghana':200,'Scotland':285,'Qatar':80,
    'South Africa':100,'Bosnia':150,'Czechia':200,'Panama':60,'Iraq':50,
    'Jordan':65,'DR Congo':120,'Uzbekistan':55,'Haiti':40,'New Zealand':50,
    'Curacao':80,'Cape Verde':100,'Ivory Coast':350,
}
FLAGS = {
    'Spain':'es','France':'fr','Norway':'no','Germany':'de','Argentina':'ar',
    'Portugal':'pt','Turkey':'tr','Austria':'at','Brazil':'br','England':'gb-eng',
    'Netherlands':'nl','Switzerland':'ch','Morocco':'ma','Colombia':'co',
    'Belgium':'be','Uruguay':'uy','Italy':'it','Croatia':'hr','Senegal':'sn',
    'Denmark':'dk','Japan':'jp','South Korea':'kr','Iran':'ir','Sweden':'se',
    'Mexico':'mx','Egypt':'eg','Ecuador':'ec','Algeria':'dz','Paraguay':'py',
    'Australia':'au','South Africa':'za','USA':'us','Canada':'ca',
    'Czechia':'cz','Scotland':'gb-sct','Bosnia':'ba','Qatar':'qa',
    'Ivory Coast':'ci','DR Congo':'cd','Uzbekistan':'uz','Haiti':'ht',
    'New Zealand':'nz','Curacao':'cw','Cape Verde':'cv','Saudi Arabia':'sa',
    'Iraq':'iq','Jordan':'jo','Ghana':'gh','Panama':'pa','Tunisia':'tn',
}
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

UPDATED = datetime.utcnow().strftime('%d %b %Y %H:%M UTC')

results_json  = json.dumps(results)
bracket_json  = json.dumps(bracket)
elo_json      = json.dumps({t: round(v, 0) for t, v in elo.items()})
squad_json    = json.dumps(SQUAD)
flags_json    = json.dumps(FLAGS)
groups_json   = json.dumps(GROUPS)
accuracy_json = json.dumps(accuracy)

with open(os.path.join(DIR, 'template.html'), encoding='utf-8') as f:
    html = f.read()

html = (html
    .replace('__RESULTS__',  results_json)
    .replace('__BRACKET__',  bracket_json)
    .replace('__ELO__',      elo_json)
    .replace('__SQUAD__',    squad_json)
    .replace('__FLAGS__',    flags_json)
    .replace('__GROUPS__',   groups_json)
    .replace('__ACCURACY__', accuracy_json)
    .replace('__UPDATED__',  UPDATED)
)

out = os.path.join(DIR, 'index.html')
with open(out, 'w', encoding='utf-8') as f:
    f.write(html)
print(f"Built index.html ({len(html):,} chars) -- last updated: {UPDATED}")
