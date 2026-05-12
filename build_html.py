"""
Reads wc2026_v2_results.json, bracket_data.json, model_params.json
and writes index.html — the page served by GitHub Pages.
"""
import json, os

DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(DIR, 'wc2026_v2_results.json')) as f:
    results = json.load(f)
with open(os.path.join(DIR, 'bracket_data.json')) as f:
    bracket = json.load(f)
with open(os.path.join(DIR, 'model_params.json')) as f:
    model = json.load(f)

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

from datetime import datetime
UPDATED = datetime.utcnow().strftime('%d %b %Y %H:%M UTC')

results_json = json.dumps(results)
bracket_json = json.dumps(bracket)
elo_json     = json.dumps({t: round(v, 0) for t, v in elo.items()})
squad_json   = json.dumps(SQUAD)
flags_json   = json.dumps(FLAGS)
groups_json  = json.dumps(GROUPS)

html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>xSPN — 2026 World Cup Predictions</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{{--red:#cc0000;--dark:#1a1a1a;--bg:#f0f0f0;--card:#ffffff;--border:#e0e0e0;--text:#111;--muted:#666;--hint:#999;--win:#2e7d32;--draw:#e07000;--lose:#c62828}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:'Barlow',system-ui,sans-serif;min-height:100vh}}
header{{background:var(--dark);padding:12px 20px;display:flex;align-items:center;gap:14px;border-bottom:3px solid var(--red)}}
.xspn-logo{{background:var(--red);color:#fff;font-size:1.25rem;font-weight:600;letter-spacing:2px;padding:4px 10px;border-radius:3px;flex-shrink:0;font-family:'Barlow',sans-serif}}
.xspn-logo span{{opacity:.7;font-weight:400}}
.hdr-text h1{{font-size:.98rem;font-weight:600;color:#fff;letter-spacing:.2px}}
.hdr-text p{{color:#888;font-size:.76rem;margin-top:2px}}
.updated{{font-size:.7rem;color:#555;margin-top:1px}}
.tabs{{display:flex;background:var(--dark);border-bottom:2px solid var(--red);overflow-x:auto;position:sticky;top:0;z-index:10}}
.tab{{padding:10px 16px;cursor:pointer;font-size:.82rem;font-weight:500;color:#888;white-space:nowrap;border-bottom:3px solid transparent;transition:all .15s;letter-spacing:.2px;font-family:'Barlow',sans-serif}}
.tab:hover{{color:#fff}}.tab.active{{color:#fff;background:var(--red);border-bottom-color:var(--red)}}
.pane{{display:none;padding:20px;max-width:1100px;margin:0 auto}}.pane.active{{display:block}}
table{{width:100%;border-collapse:collapse}}
th{{background:#f5f5f5;color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.5px;padding:8px 10px;text-align:left;border-bottom:2px solid var(--border);position:sticky;top:42px}}
td{{padding:8px 10px;border-bottom:1px solid var(--border);font-size:.86rem}}
tr:hover td{{background:#fafafa}}
.bar-bg{{background:#e8e8e8;border-radius:3px;height:7px;width:110px}}
.bar-fill{{height:100%;border-radius:3px;background:var(--red)}}
.pct-high{{color:#cc0000;font-weight:600}}.pct-mid{{color:#e07000;font-weight:600}}.pct-low{{color:var(--hint)}}
.groups-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:12px}}
.group-card{{background:var(--card);border:1px solid var(--border);border-radius:4px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
.group-hdr{{background:var(--dark);padding:7px 12px;font-weight:600;color:#fff;letter-spacing:1.5px;font-size:.82rem;display:flex;align-items:center;gap:7px}}
.group-hdr::before{{content:'';display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--red);flex-shrink:0}}
.match-row{{display:flex;align-items:center;justify-content:space-between;padding:5px 10px;border-bottom:1px solid var(--border);font-size:.8rem;gap:4px}}
.t{{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.t.r{{text-align:right}}
.sc{{background:var(--dark);color:#fff;padding:2px 7px;border-radius:2px;font-weight:600;font-size:.82rem;min-width:34px;text-align:center}}
.odds{{font-size:.7rem;color:var(--hint);text-align:center;padding:1px 10px 5px}}
.bracket-wrap{{overflow-x:auto}}.bracket{{display:flex;gap:0;min-width:860px}}
.br-col{{display:flex;flex-direction:column;flex:1;padding:0 5px}}
.br-title{{text-align:center;font-size:.7rem;font-weight:600;color:#fff;text-transform:uppercase;letter-spacing:.8px;padding:6px 0;background:var(--red);border-radius:3px;margin-bottom:8px}}
.br-matches{{display:flex;flex-direction:column;justify-content:space-around;flex:1}}
.bm{{background:var(--card);border:1px solid var(--border);border-radius:3px;margin:2px 0;padding:5px 7px;font-size:.75rem}}
.bm-t{{display:flex;align-items:center;gap:3px;padding:2px 0}}
.bm-t.win{{color:var(--dark);font-weight:600}}.bm-t.lose{{color:var(--hint)}}
.bm-sc{{margin-left:auto;font-weight:600}}.bm-pct{{font-size:.68rem;color:var(--hint);text-align:center;padding-top:2px}}
.filter-row{{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}}
.fb{{padding:4px 12px;border-radius:3px;border:1px solid var(--border);background:#fff;color:var(--text);cursor:pointer;font-size:.78rem;font-family:'Barlow',sans-serif;transition:all .12s}}
.fb.active{{background:var(--red);color:#fff;border-color:var(--red)}}
.sbadge{{display:inline-block;padding:1px 6px;border-radius:2px;font-size:.68rem;font-weight:600}}
.sb-g{{background:#e8f0fb;color:#1a56a0}}.sb-r32{{background:#e8f5e9;color:#2e7d32}}
.sb-r16{{background:#f3e8fd;color:#6b21a8}}.sb-qf{{background:#fff3e0;color:#b35900}}
.sb-sf{{background:#ffebee;color:#c62828}}.sb-f{{background:#1a1a1a;color:#fff}}
.sb-3{{background:#e0f7fa;color:#00838f}}.win-cell{{color:var(--red);font-weight:600}}
.podium-wrap{{max-width:560px;margin:0 auto}}
.pod-stage{{display:flex;align-items:flex-end;justify-content:center;gap:6px;margin:24px 0 16px}}
.pod{{text-align:center;display:flex;flex-direction:column;align-items:center}}
.pod-bar{{width:80px;background:#eee;border:1px solid var(--border);border-bottom:none;border-radius:3px 3px 0 0;display:flex;align-items:flex-end;justify-content:center;padding-bottom:5px}}
.pod-1 .pod-bar{{height:130px;background:#fff0f0;border-color:var(--red)}}.pod-2 .pod-bar{{height:95px}}.pod-3 .pod-bar{{height:65px}}
.pod-medal{{font-size:1.4rem}}.pod-name{{font-weight:600;font-size:.88rem;margin-top:4px}}.pod-pct{{font-size:.78rem;color:var(--muted)}}
.sec{{font-size:.82rem;font-weight:600;margin:18px 0 8px;border-bottom:2px solid var(--border);padding-bottom:5px;color:var(--dark);text-transform:uppercase;letter-spacing:.6px}}
.top10 td{{padding:7px 8px;border-bottom:1px solid var(--border)}}
.top10-bar{{height:7px;background:var(--red);border-radius:2px}}
.fin-box{{background:#fff;border:1px solid var(--border);border-left:4px solid var(--red);border-radius:3px;padding:14px;text-align:center;margin:6px 0}}
</style>
</head>
<body>
<header>
  <div class="xspn-logo">x<span>SPN</span></div>
  <div class="hdr-text">
    <h1>2026 FIFA World Cup Predictions</h1>
    <p>Dixon-Coles · L2 regularisation · host advantage · 75,000 simulations</p>
    <p class="updated">Last updated: {UPDATED}</p>
  </div>
</header>
<div class="tabs">
  <div class="tab active" onclick="show('win')">Win Odds</div>
  <div class="tab" onclick="show('stage')">Stage %</div>
  <div class="tab" onclick="show('groups')">Groups</div>
  <div class="tab" onclick="show('bracket')">Bracket</div>
  <div class="tab" onclick="show('matches')">All 104 Matches</div>
  <div class="tab" onclick="show('podium')">Podium</div>
</div>
<div id="tab-win" class="pane active"></div>
<div id="tab-stage" class="pane"></div>
<div id="tab-groups" class="pane"></div>
<div id="tab-bracket" class="pane"></div>
<div id="tab-matches" class="pane"></div>
<div id="tab-podium" class="pane"></div>
<script>
const R={results_json};
const B={bracket_json};
const ELO={elo_json};
const SQ={squad_json};
const FL={flags_json};
const GR={groups_json};
function fi(cc){{return cc?'https://flagcdn.com/20x15/'+cc+'.png':''}}
function ft(t){{const c=FL[t];return c?`<img src="${{fi(c)}}" style="vertical-align:middle;margin-right:4px;border-radius:1px"> ${{t}}`:t}}
function show(n){{
  document.querySelectorAll('.tab').forEach((e,i)=>e.classList.toggle('active',['win','stage','groups','bracket','matches','podium'][i]===n));
  document.querySelectorAll('.pane').forEach(p=>p.classList.remove('active'));
  document.getElementById('tab-'+n).classList.add('active');
}}
(function(){{
  const ranked=Object.entries(R).sort((a,b)=>b[1].win-a[1].win);
  const mx=ranked[0][1].win;
  let h=`<table><thead><tr><th>#</th><th>Team</th><th>Win%</th><th></th><th>Final%</th><th>SF%</th><th>QF%</th><th>Elo</th><th>Squad</th></tr></thead><tbody>`;
  ranked.forEach(([t,r],i)=>{{
    const m=i===0?'&#127945;':i===1?'&#129352;':i===2?'&#129353;':'';
    const bw=(r.win/mx*100).toFixed(1);
    h+=`<tr><td style="color:var(--muted);font-size:.8rem">${{i+1}}</td><td>${{ft(t)}} ${{m}}</td>
    <td><strong>${{(r.win*100).toFixed(1)}}%</strong></td>
    <td><div class="bar-bg"><div class="bar-fill" style="width:${{bw}}%"></div></div></td>
    <td>${{(r.final*100).toFixed(1)}}%</td><td>${{(r.sf*100).toFixed(1)}}%</td><td>${{(r.qf*100).toFixed(1)}}%</td>
    <td>${{Math.round(ELO[t]||1500)}}</td><td style="color:var(--muted)">&#8364;${{SQ[t]||0}}M</td></tr>`;
  }});
  document.getElementById('tab-win').innerHTML=h+'</tbody></table>';
}})();
(function(){{
  const ranked=Object.entries(R).sort((a,b)=>b[1].sf-a[1].sf);
  function pc(v){{return v>=0.3?'pct-high':v>=0.1?'pct-mid':'pct-low'}}
  let h=`<table><thead><tr><th>Team</th><th>Win</th><th>Final</th><th>Semi-Final</th><th>Quarter-Final</th></tr></thead><tbody>`;
  ranked.forEach(([t,r])=>{{
    h+=`<tr><td>${{ft(t)}}</td><td class="${{pc(r.win)}}">${{(r.win*100).toFixed(1)}}%</td>
    <td class="${{pc(r.final)}}">${{(r.final*100).toFixed(1)}}%</td>
    <td class="${{pc(r.sf)}}">${{(r.sf*100).toFixed(1)}}%</td>
    <td class="${{pc(r.qf)}}">${{(r.qf*100).toFixed(1)}}%</td></tr>`;
  }});
  document.getElementById('tab-stage').innerHTML=h+'</tbody></table>';
}})();
(function(){{
  function computeStandings(teams, ms) {{
    const pts={{}}, w={{}}, d={{}}, l={{}};
    teams.forEach(t=>{{ pts[t]=0; w[t]=0; d[t]=0; l[t]=0; }});
    ms.forEach(m=>{{
      pts[m.home]+=3*m.ph+m.pd; pts[m.away]+=3*m.pa+m.pd;
      w[m.home]+=m.ph; w[m.away]+=m.pa;
      d[m.home]+=m.pd; d[m.away]+=m.pd;
      l[m.home]+=m.pa; l[m.away]+=m.ph;
    }});
    return teams.map(t=>(({{t,pts:pts[t],w:w[t],d:d[t],l:l[t]}})))
               .sort((a,b)=>b.pts-a.pts);
  }}
  let h='<div class="groups-grid">';
  Object.entries(GR).forEach(([g,teams])=>{{
    const ms=B.group_predictions[g]||[];
    h+=`<div class="group-card"><div class="group-hdr">Group ${{g}}</div>`;
    const st=computeStandings(teams,ms);
    h+=`<table style="width:100%;border-collapse:collapse;font-size:.76rem">
      <thead><tr style="background:#0d1422">
        <th style="padding:5px 8px;text-align:left;color:var(--muted);font-weight:600;font-size:.7rem;letter-spacing:.3px">Team</th>
        <th style="padding:5px 4px;text-align:center;color:var(--muted);font-weight:600;font-size:.7rem">W</th>
        <th style="padding:5px 4px;text-align:center;color:var(--muted);font-weight:600;font-size:.7rem">D</th>
        <th style="padding:5px 4px;text-align:center;color:var(--muted);font-weight:600;font-size:.7rem">L</th>
        <th style="padding:5px 6px;text-align:center;color:var(--red);font-weight:700;font-size:.7rem">Pts</th>
      </tr></thead><tbody>`;
    st.forEach((row,i)=>{{
      const ql=i<2?'3px solid var(--red)':'3px solid transparent';
      h+=`<tr style="border-left:${{ql}};border-bottom:1px solid var(--border)}">
        <td style="padding:4px 8px">${{ft(row.t)}}</td>
        <td style="padding:4px 4px;text-align:center;color:var(--muted)">${{row.w.toFixed(1)}}</td>
        <td style="padding:4px 4px;text-align:center;color:var(--muted)">${{row.d.toFixed(1)}}</td>
        <td style="padding:4px 4px;text-align:center;color:var(--muted)">${{row.l.toFixed(1)}}</td>
        <td style="padding:4px 6px;text-align:center;font-weight:700;color:${{i<2?'var(--red)':'var(--text)'}}">${{row.pts.toFixed(1)}}</td>
      </tr>`;
    }});
    h+='</tbody></table><div style="border-top:1px solid var(--border);margin-top:2px;padding-top:4px">';
    ms.forEach(m=>{{
      const hw=(m.ph*100).toFixed(0),dw=(m.pd*100).toFixed(0),aw=(m.pa*100).toFixed(0);
      const isH=m.winner===m.home||m.likely_winner===m.home;
      h+=`<div class="match-row"><span class="t" style="${{isH?'color:var(--red);font-weight:600':''}}">${{ft(m.home)}}</span>
        <span class="sc">${{m.score}}</span>
        <span class="t r" style="${{!isH?'color:var(--red);font-weight:600':''}}">${{ft(m.away)}}</span></div>
      <div class="odds"><span style="color:var(--win)">${{hw}}%</span> &middot; <span style="color:var(--draw)">${{dw}}%</span> &middot; <span style="color:var(--lose)">${{aw}}%</span></div>`;
    }});
    h+='</div></div>';
  }});
  document.getElementById('tab-groups').innerHTML=h+'</div>';
}})();
(function(){{
  function bm(m){{
    if(!m)return'<div class="bm"><em style="color:var(--muted);font-size:.72rem">TBD</em></div>';
    const isH=m.winner===m.home;const sc=m.score.split('–');
    return`<div class="bm"><div class="bm-t ${{isH?'win':'lose'}}">${{ft(m.home)}}<span class="bm-sc">${{sc[0]||0}}</span></div>
      <div class="bm-t ${{!isH?'win':'lose'}}">${{ft(m.away)}}<span class="bm-sc">${{sc[1]||0}}</span></div>
      <div class="bm-pct">${{m.win_pct}}% ${{m.winner}}</div></div>`;
  }}
  let h='<div class="bracket-wrap"><div class="bracket">';
  [['Round of 32',B.r32],['Round of 16',B.r16],['Quarter-Finals',B.qf],['Semi-Finals',B.sf]].forEach(([title,ms])=>{{
    h+=`<div class="br-col"><div class="br-title">${{title}}</div><div class="br-matches">`;
    ms.forEach(m=>h+=bm(m));h+='</div></div>';
  }});
  h+=`<div class="br-col"><div class="br-title">Final + 3rd</div><div class="br-matches">
    ${{bm(B.final)}}<div style="font-size:.7rem;color:var(--muted);text-align:center;padding:6px 0">3rd Place</div>
    ${{bm(B.third_place)}}</div></div>`;
  document.getElementById('tab-bracket').innerHTML=h+'</div></div>';
}})();
(function(){{
  const all=[];
  Object.entries(B.group_predictions).forEach(([g,ms])=>ms.forEach(m=>all.push({{...m,stage:'Group '+g,sk:'group',badge:'sb-g'}})));
  [{{k:'r32',l:'R32',b:'sb-r32'}},{{k:'r16',l:'R16',b:'sb-r16'}},{{k:'qf',l:'QF',b:'sb-qf'}},{{k:'sf',l:'SF',b:'sb-sf'}}]
    .forEach(({{k,l,b}})=>(B[k]||[]).forEach(m=>all.push({{...m,stage:l,sk:k,badge:b}})));
  all.push({{...B.final,stage:'Final',sk:'final',badge:'sb-f'}});
  all.push({{...B.third_place,stage:'3rd Place',sk:'3rd',badge:'sb-3'}});
  window._AM=all;
  function rows(filter){{
    return(filter==='all'?all:all.filter(m=>filter==='group'?m.sk==='group':m.sk===filter)).map(m=>{{
      const pct=m.win_pct!=null?m.win_pct+'%':(m.ph?`${{(m.ph*100).toFixed(0)}}/${{(m.pd*100).toFixed(0)}}/${{(m.pa*100).toFixed(0)}}%`:'');
      const w=m.winner||m.likely_winner;
      return`<tr><td><span class="sbadge ${{m.badge}}">${{m.stage}}</span></td>
        <td>${{ft(m.home)}}</td><td style="text-align:center;font-weight:700">${{m.score}}</td>
        <td>${{ft(m.away)}}</td><td class="win-cell">${{ft(w)}}</td>
        <td style="color:var(--muted);font-size:.76rem">${{pct}}</td></tr>`;
    }}).join('');
  }}
  document.getElementById('tab-matches').innerHTML=
    '<div class="filter-row">'+['all','group','r32','r16','qf','sf','final'].map((f,i)=>
      `<button class="fb${{i===0?' active':''}}" onclick="filt('${{f}}',this)">${{['All 104','Groups','R32','R16','QF','SF','Final'][i]}}</button>`
    ).join('')+'</div>'+
    `<table><thead><tr><th>Stage</th><th>Home</th><th>Score</th><th>Away</th><th>Winner</th><th>Odds</th></tr></thead>
    <tbody id="mrows">${{rows('all')}}</tbody></table>`;
}})();
window.filt=function(f,btn){{
  document.querySelectorAll('.fb').forEach(b=>b.classList.remove('active'));btn.classList.add('active');
  document.getElementById('mrows').innerHTML=(f==='all'?window._AM:window._AM.filter(m=>f==='group'?m.sk==='group':m.sk===f))
    .map(m=>{{const pct=m.win_pct!=null?m.win_pct+'%':(m.ph?`${{(m.ph*100).toFixed(0)}}/${{(m.pd*100).toFixed(0)}}/${{(m.pa*100).toFixed(0)}}%`:'');
      const w=m.winner||m.likely_winner;
      return`<tr><td><span class="sbadge ${{m.badge}}">${{m.stage}}</span></td>
        <td>${{ft(m.home)}}</td><td style="text-align:center;font-weight:700">${{m.score}}</td>
        <td>${{ft(m.away)}}</td><td class="win-cell">${{ft(w)}}</td>
        <td style="color:var(--muted);font-size:.76rem">${{pct}}</td></tr>`;
    }}).join('');
}};
(function(){{
  const ranked=Object.entries(R).sort((a,b)=>b[1].win-a[1].win);
  const [[t1,r1],[t2,r2],[t3,r3]]=ranked;const mx=r1.win;
  let h=`<div class="podium-wrap"><div class="sec">Predicted Tournament Winner</div>
  <div style="text-align:center;margin:14px 0">
    <div>${{FL[t1]?`<img src="${{fi(FL[t1])}}" style="height:48px;border-radius:3px">`:'&#127942;'}}</div>
    <div style="font-size:1.4rem;font-weight:800;color:var(--red);margin-top:6px">${{t1}}</div>
    <div style="color:var(--muted)">${{(r1.win*100).toFixed(1)}}% win probability</div></div>
  <div class="sec">Predicted Podium</div>
  <div class="pod-stage">
    <div class="pod pod-2"><div>${{FL[t2]?`<img src="${{fi(FL[t2])}}" style="height:32px;border-radius:2px">`:''}}</div>
      <div class="pod-bar"><div class="pod-medal">&#129352;</div></div>
      <div class="pod-name">${{t2}}</div><div class="pod-pct">${{(r2.win*100).toFixed(1)}}%</div></div>
    <div class="pod pod-1"><div>${{FL[t1]?`<img src="${{fi(FL[t1])}}" 
