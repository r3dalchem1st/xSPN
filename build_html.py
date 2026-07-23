"""
Reads JSON data files + template.html, injects data, writes
competitions/world_cup_2026/index.html (moved off the repo root 23 Jul —
root now serves the site-wide hub page, see build_hub_html.py). Only Results,
Bracket, and Podium remain on the WC page (Groups/All-104/Title-Odds trimmed
the same day — day-to-day tracking tabs that made sense for a live
tournament, not a finished one); WINHIST/SCHEDULE/INJURIES/CARDS/ELO/SQUAD/
GROUPS are no longer loaded here since nothing in the trimmed template reads
them anymore (their own underlying pipelines — fetch_matches.py,
fit_improved.py, etc. — are completely unaffected; this file only stopped
FORWARDING that data into a template that no longer displays it).
"""
import json, os, re, sys
from datetime import datetime

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)
from render_nav import nav_entries, render_nav_html

with open(os.path.join(DIR, 'wc2026_v2_results.json')) as f:
    results = json.load(f)
with open(os.path.join(DIR, 'bracket_data.json')) as f:
    bracket = json.load(f)

_acc_file = os.path.join(DIR, 'results_accuracy.json')
if os.path.exists(_acc_file):
    with open(_acc_file) as f:
        accuracy = json.load(f)
else:
    accuracy = {"matches": [], "summary": {"total_matches": 0, "correct_winners": 0,
                                            "accuracy": 0, "avg_goal_error": 0, "avg_brier": 0}}

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

UPDATED = datetime.utcnow().strftime('%d %b %Y %H:%M UTC')

results_json  = json.dumps(results)
bracket_json  = json.dumps(bracket)
flags_json    = json.dumps(FLAGS)
accuracy_json = json.dumps(accuracy)
nav_html      = render_nav_html(nav_entries(DIR, active="world_cup"))

with open(os.path.join(DIR, 'template.html'), encoding='utf-8') as f:
    html = f.read()

html = (html
    .replace('__RESULTS__',  results_json)
    .replace('__BRACKET__',  bracket_json)
    .replace('__FLAGS__',    flags_json)
    .replace('__ACCURACY__', accuracy_json)
    .replace('__UPDATED__',  UPDATED)
    .replace('__NAV__',      nav_html)
)

leftover = re.findall(r"__[A-Z_]+__", html)
assert not leftover, f"unconsumed placeholder(s) in output: {leftover}"

out_dir = os.path.join(DIR, 'competitions', 'world_cup_2026')
os.makedirs(out_dir, exist_ok=True)
out = os.path.join(out_dir, 'index.html')
with open(out, 'w', encoding='utf-8') as f:
    f.write(html)
print(f"Built {out} ({len(html):,} chars) -- last updated: {UPDATED}")
