"""Build the Andes live tour: one self-contained HTML file (no server, no build step).

The page is a guided tour on top of a clickable demo. Every view is encoded in the URL
(?step=&sit=&opt=&h=), so any view can be shared as a link (same method as Arraigo).
All numbers come from optimisation/examples (real HiGHS solves, independently validated);
the tour text pulls them from the embedded data, nothing is typed by hand.

    python -m optimisation.tour.build_tour      # writes optimisation/tour/andes-tour.html
    python -m optimisation.tour.build_tour --scenario path/to/real_day_scenario.json --out andes-tour-real-day.html
        # solves every case on that scenario (solve + validate + compare) instead of reading examples/
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parent / "examples"
FIXTURE = HERE.parent / "fixtures" / "demo_scenario.json"
OUT = HERE / "andes-tour.html"


def _case(situation: str, option: str, entry: dict) -> dict:
    sol = json.loads((EXAMPLES / entry["solution"]).read_text())
    val = json.loads((EXAMPLES / entry["validation"]).read_text())
    return _pack(sol, val, entry.get("vs_baseline"))


def _pack(sol: dict, val: dict, vs: dict | None) -> dict:
    ts = sol["timeseries"]
    T = len(sol["timestamps_utc"])
    added = [b for b in sol["assets"]["batteries"] if b.get("added_by_candidate")]
    soc = ts["battery_soc_mwh"][added[0]["id"]][1:] if added else None
    return {
        "metrics": {k: sol["metrics"][k] for k in (
            "curtailment_mwh", "unserved_mwh", "assumed_cost_proxy_usd", "battery_losses_mwh")},
        "vs": vs,
        "valid": val["passed"],
        "checks": len(val["checks_run"]),
        "caps": {ln["id"]: ln["capacity_mw"] for ln in sol["assets"]["lines"]},
        "flow": ts["line_flow_mw"],
        "curt": [round(sum(v[t] for v in ts["curtailment_mw"].values()), 3) for t in range(T)],
        "unserved": {n: v for n, v in ts["unserved_mw"].items() if any(x > 1e-6 for x in v)},
        "battery": None if not added else {
            "node": added[0]["node_id"], "energy": added[0]["energy_capacity_mwh"], "soc": soc},
        "outage": [b["hours"] for b in sol["binding_constraints"] if b["type"] == "outage"],
    }


def _solve_cases(scen: dict) -> tuple[dict, dict, dict]:
    """Solve, validate and compare every option in every situation on ``scen``."""
    from optimisation import compare, solve, validate
    from optimisation.demo import CANDIDATES, SITUATIONS

    cases, sits = {}, {}
    for sit, (desc, events) in SITUATIONS.items():
        sits[sit] = desc
        base = solve(scen, events=events)
        base_v = validate(scen, base)
        cases[sit] = {"baseline": _pack(base, base_v, None)}
        for cand in CANDIDATES:
            c = {k: v for k, v in cand.items() if k != "description"}
            sol = solve(scen, c, events)
            val = validate(scen, sol)
            cmp = compare(base, sol, base_v, val)
            cases[sit][cand["candidate_id"]] = _pack(sol, val, {k: cmp[k] for k in (
                "curtailment_reduction_mwh", "unserved_reduction_mwh", "assumed_cost_delta_usd")})
    options = {"baseline": "Grid as it is today", **{c["candidate_id"]: c["description"] for c in CANDIDATES}}
    return cases, sits, options


def build(scenario_path: Path | None = None, out: Path = OUT) -> Path:
    if scenario_path is None:
        index = json.loads((EXAMPLES / "index.json").read_text())
        scen = json.loads(FIXTURE.read_text())
        cases = {s: {o: _case(s, o, e) for o, e in v["options"].items()} for s, v in index["situations"].items()}
        sits = {s: v["description"] for s, v in index["situations"].items()}
        options = {o: e["description"] for o, e in index["situations"]["normal"]["options"].items()}
        source = ("a synthetic, illustrative 5-node grid and day shaped like Chile (not Chile's real network). "
                  "Results are the validated example outputs of the Andes optimiser")
    else:
        scen = json.loads(Path(scenario_path).read_text())
        # reserve batteries flagged standby are not dispatchable unless an operator activates them
        scen["batteries"] = [b for b in scen.get("batteries", []) if not b.get("standby")]
        cases, sits, options = _solve_cases(scen)
        source = ("real CEN demand and solar/wind shapes " + (f"for {scen['day_profile'].get('date')} " if isinstance(scen.get("day_profile"), dict) and scen["day_profile"].get("date") else "")
                  + "scaled onto a synthetic, illustrative 5-node grid (not Chile's real network). "
                  "Every case was solved by the Andes optimiser and checked by its independent validator")
    data = {
        "source": source,
        "scenario_id": scen["scenario_id"],
        "nodes": [{"id": n["id"], "label": n["label"].replace(" (illustrative)", "")} for n in scen["nodes"]],
        "lines": [{"id": ln["id"], "from": ln["from"], "to": ln["to"]} for ln in scen["lines"]],
        "plants": {n["id"]: [f"{g['technology']} {g['capacity_mw']:g}" for g in scen["generators"]
                             if g["node_id"] == n["id"]] for n in scen["nodes"]},
        "situations": sits,
        "options": options,
        "cases": cases,
    }
    html = TEMPLATE.replace("/*DATA*/null", json.dumps(data, separators=(",", ":")))
    out.write_text(html, encoding="utf-8")
    return out


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Andes Live Tour</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#f7f8fa;--card:#fff;--ink:#14171c;--muted:#6b7280;--line:#e5e7eb;--accent:#2563eb;
--solar:#f59e0b;--bad:#dc2626;--ok:#16a34a;--flow:#94a3b8;--shadow:0 1px 3px rgba(0,0,0,.06),0 8px 24px rgba(0,0,0,.05)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0f1115;--card:#171a21;--ink:#e8eaed;--muted:#9aa1ac;--line:#2a2f3a;--flow:#5b6475;--shadow:none}}
:root[data-theme="dark"]{--bg:#0f1115;--card:#171a21;--ink:#e8eaed;--muted:#9aa1ac;--line:#2a2f3a;--flow:#5b6475;--shadow:none}
*{box-sizing:border-box}html,body{margin:0}
body{background:var(--bg);color:var(--ink);font:15px/1.5 Inter,system-ui,sans-serif}
header{display:flex;align-items:center;gap:12px;padding:14px 20px;border-bottom:1px solid var(--line);background:var(--card)}
header h1{font-size:17px;margin:0;font-weight:700;letter-spacing:-.01em}
header .tag{font-size:12px;color:var(--muted);border:1px solid var(--line);border-radius:99px;padding:2px 10px}
header .sp{flex:1}
button{font:inherit;cursor:pointer;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--ink);padding:6px 12px}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
button:disabled{opacity:.4;cursor:default}
main{display:grid;grid-template-columns:minmax(260px,360px) 1fr;gap:16px;padding:16px 20px;max-width:1200px;margin:0 auto}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow);padding:14px}
.card h2{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:0 0 10px;font-weight:600}
#map svg{width:100%;height:auto;display:block}
.right{display:flex;flex-direction:column;gap:16px;min-width:0}
.controls{display:grid;gap:10px}
.seg{display:flex;flex-wrap:wrap;gap:6px}
.seg button{font-size:13px;padding:5px 10px}
.seg button.on{background:var(--ink);color:var(--card);border-color:var(--ink)}
.row{display:flex;align-items:center;gap:10px}
input[type=range]{flex:1;accent-color:var(--accent)}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.kpi .v{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums}
.kpi .l{font-size:12px;color:var(--muted)}
.kpi .d{font-size:12px;font-variant-numeric:tabular-nums}
.d.good{color:var(--ok)}.d.bad{color:var(--bad)}
.badge{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--ok);font-weight:600}
#chart svg{width:100%;height:150px;display:block}
.legend{display:flex;gap:14px;font-size:12px;color:var(--muted);margin-top:6px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.foot{font-size:12px;color:var(--muted);max-width:1200px;margin:0 auto;padding:0 20px 90px}
.hl{outline:3px solid var(--accent);outline-offset:3px;border-radius:12px;transition:outline-color .2s}
#tour{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);width:min(560px,calc(100% - 32px));
background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,.18);padding:16px 18px;z-index:10}
#tour .k{font-size:12px;color:var(--accent);font-weight:600;letter-spacing:.04em;text-transform:uppercase}
#tour h3{margin:2px 0 6px;font-size:17px}
#tour p{margin:0 0 12px;color:var(--ink)}
#tour .nav{display:flex;align-items:center;gap:8px}
#tour .dots{flex:1;display:flex;gap:5px}
#tour .dots span{width:7px;height:7px;border-radius:50%;background:var(--line)}
#tour .dots span.on{background:var(--accent)}
#tour.closed{display:none}
#tour .tags{display:flex;gap:6px;margin:0 0 10px}#tour .tags span{font-size:11px;font-weight:600;letter-spacing:.04em;border-radius:6px;padding:1px 7px;border:1px solid var(--line);color:var(--muted)}
#tour .tags span.VALIDATED{color:var(--ok);border-color:var(--ok)}#tour .tags span.SIMULATED{color:var(--solar);border-color:var(--solar)}
#tour.slide{top:50%;bottom:auto;transform:translate(-50%,-50%);width:min(640px,calc(100% - 32px));padding:34px 32px;text-align:center}
#tour.slide h3{font-size:28px;letter-spacing:-.02em}#tour.slide .tags{justify-content:center}
#veil{position:fixed;inset:0;background:var(--bg);opacity:.86;z-index:9;display:none}#veil.on{display:block}
#tour.hidden{display:none}
#reopen{display:none}
@media (max-width:760px){main{grid-template-columns:1fr}.kpis{grid-template-columns:1fr 1fr 1fr}.kpi .v{font-size:18px}}
</style>
</head>
<body>
<header>
  <h1>Andes</h1><span class="tag">Live tour · simulation</span><span class="sp"></span>
  <button id="share" title="Copy a link to exactly this view">Copy link</button>
  <button id="reopen" class="primary">Resume tour</button>
</header>
<main>
  <section class="card" id="map"><h2>Grid · north to south</h2><svg id="grid" viewBox="0 0 370 560" role="img" aria-label="Five-node grid schematic"></svg></section>
  <div class="right">
    <section class="card controls" id="controls">
      <h2>What-if</h2>
      <div class="seg" id="sit"></div>
      <div class="seg" id="opt"></div>
      <div class="row"><button id="play" aria-label="Play">▶</button><input id="hour" type="range" min="0" max="23" step="1"><b id="hlabel" style="min-width:92px;text-align:right;font-variant-numeric:tabular-nums"></b></div>
    </section>
    <section class="card" id="kpis"><h2>Result for the whole day <span class="badge" id="badge"></span></h2><div class="kpis" id="kpibox"></div></section>
    <section class="card" id="chart"><h2>Hour by hour</h2><svg id="bars" viewBox="0 0 600 150" preserveAspectRatio="none"></svg>
      <div class="legend"><span><i style="background:var(--solar)"></i>Solar/wind wasted (MW)</span><span><i style="background:var(--bad)"></i>Demand not served (MW)</span><span><i style="background:var(--accent)"></i>Selected hour</span></div></section>
  </div>
</main>
<p class="foot" id="foot"></p>
<div id="veil"></div><div id="tour" role="dialog" aria-live="polite"><div class="k" id="tk"></div><h3 id="tt"></h3><div class="tags" id="ttags"></div><p id="tp"></p>
  <div class="nav"><div class="dots" id="tdots"></div><button id="tclose">Explore freely</button><button id="tback">Back</button><button id="tnext" class="primary">Next</button></div></div>
<script>
const D=/*DATA*/null;
const fmt=(x,d=0)=>Number(x).toLocaleString("en-US",{maximumFractionDigits:d,minimumFractionDigits:d});
const C=(s,o)=>D.cases[s][o];
const OPT_LABEL={baseline:"Today's grid",north_bess:"Battery north",south_bess:"Battery south",uprate_l2:"Upgrade line L2"};
const SIT_LABEL={normal:"Normal day",sudden_outage:"Sudden crash",planned_maintenance:"Planned maintenance"};
const loc=h=>String(h).padStart(2,"0")+":00 Chile time"; // hour index 0 = 00:00 Chile (03:00 UTC)
const red=(s,o,k)=>C(s,"baseline").metrics[k]-C(s,o).metrics[k];

const STEPS=[
 {slide:true,sit:"normal",opt:"baseline",h:13,k:"Andes",t:"AI-assisted operation of Chile's grid",tags:["SIMULATED"],
  p:()=>"An optimiser computes what would happen, a validator checks it, and the AI explains it. A human decides. Use → or Space to continue."},
 {sit:"normal",opt:"baseline",h:13,hl:"map",k:"The problem",tags:["SIMULATED","MODEL"],t:"Solar is thrown away in the north",
  p:()=>`At midday the north makes more solar than line L2 can carry south. On this day ${fmt(C("normal","baseline").metrics.curtailment_mwh)} MWh of clean energy is wasted, while the centre burns gas. Watch L2 turn red.`},
 {sit:"normal",opt:"south_bess",h:13,hl:"kpis",k:"Wrong place",tags:["MODEL","VALIDATED"],get t(){return red("normal","south_bess","curtailment_mwh")<0.5?"A battery in the south does nothing":"A battery in the south barely helps"},
  p:()=>`The same battery placed south of the bottleneck reduces waste by ${fmt(red("normal","south_bess","curtailment_mwh"))} MWh: the surplus can't reach it.`},
 {sit:"normal",opt:"north_bess",h:13,hl:"kpis",k:"Right place",tags:["MODEL","VALIDATED"],t:"North of the bottleneck, it works",
  p:()=>`Placed in Norte Grande it soaks up midday solar and releases it in the evening: ${fmt(red("normal","north_bess","curtailment_mwh"))} MWh less waste. Drag the hour slider to watch it charge and discharge.`},
 {sit:"normal",opt:"uprate_l2",h:13,hl:"kpis",k:"Another option",tags:["MODEL","VALIDATED"],t:"Or upgrade the line itself",
  p:()=>`Raising L2's limit by 50% cuts waste by ${fmt(red("normal","uprate_l2","curtailment_mwh"))} MWh, the best result on a normal day. (Building costs are not modelled.)`},
 {sit:"sudden_outage",opt:"baseline",h:19,hl:"map",k:"Crisis",tags:["SIMULATED","MODEL"],t:"A 600 MW gas plant crashes at the evening peak",
  p:()=>`Nobody saw it coming, so the hours before stay exactly as planned. The grid can't cover the gap: ${fmt(C("sudden_outage","baseline").metrics.unserved_mwh)} MWh of demand goes unserved in Centro.`},
 {sit:"sudden_outage",opt:"north_bess",h:19,hl:"kpis",k:"Resilience",tags:["MODEL","VALIDATED"],t:"The north battery helps here too",
  p:()=>`It cuts unserved demand by ${fmt(red("sudden_outage","north_bess","unserved_mwh"))} MWh. The line upgrade, best on a normal day, helps by ${fmt(red("sudden_outage","uprate_l2","unserved_mwh"))} MWh here. That trade-off is what the agent has to explain.`},
 {sit:"planned_maintenance",opt:"south_bess",h:19,hl:"controls",k:"Planning ahead",tags:["MODEL","VALIDATED"],t:"Knowing in advance changes the answer",
  p:()=>`If the same outage is planned maintenance, the south battery charges up beforehand: ${fmt(red("planned_maintenance","south_bess","unserved_mwh"))} MWh less unserved, versus ${fmt(red("sudden_outage","south_bess","unserved_mwh"))} MWh when it is a surprise.`},
 {sit:"normal",opt:"north_bess",h:13,hl:"badge",k:"Why you can trust it",tags:["VALIDATED"],t:"Every number is computed, then checked",
  p:()=>`An optimiser (HiGHS) computes each result; a separate validator re-checks it from scratch (${C("normal","north_bess").checks} checks: power balance, line limits, battery physics, no hindsight). The AI explains and proposes; it never invents a number. Now explore on your own.`},
];

const TAGS={SIMULATED:"Simulation on an illustrative 5-node grid, not Chile's real network",MODEL:"Computed by the optimiser (HiGHS) under stated assumptions",VALIDATED:"Re-checked from scratch by the independent validator"};
let S={step:0,sit:"normal",opt:"baseline",h:13,tour:true},timer=null;
function readURL(){const q=new URLSearchParams(location.search);
  if(q.has("step")){S.step=Math.max(0,Math.min(STEPS.length-1,+q.get("step")||0));Object.assign(S,STEPS[S.step]);}
  if(D.cases[q.get("sit")])S.sit=q.get("sit");
  if(q.get("opt")&&D.cases[S.sit][q.get("opt")])S.opt=q.get("opt");
  if(q.has("h"))S.h=Math.max(0,Math.min(23,+q.get("h")||0));
  if(q.get("tour")==="0")S.tour=false;}
function writeURL(){const q=new URLSearchParams({sit:S.sit,opt:S.opt,h:S.h});
  if(S.tour)q.set("step",S.step);else q.set("tour","0");
  history.replaceState(null,"","?"+q.toString());}

const NY=i=>60+i*110, NX=200;
function drawMap(){const c=C(S.sit,S.opt),svg=document.getElementById("grid"),h=S.h;let s="";
  D.lines.forEach((ln,i)=>{const f=c.flow[ln.id][h],cap=c.caps[ln.id],u=cap?Math.abs(f)/cap:0;
    const col=u>=0.999?"var(--bad)":u>0.8?"var(--solar)":"var(--flow)";
    const y1=NY(i)+20,y2=NY(i+1)-20;
    s+=`<line x1="${NX}" y1="${y1}" x2="${NX}" y2="${y2}" stroke="${col}" stroke-width="${3+7*u}" stroke-linecap="round"/>`;
    s+=`<text x="${NX+18}" y="${(y1+y2)/2+4}" font-size="12" fill="var(--muted)">${ln.id} · ${fmt(Math.abs(f))}/${fmt(cap)} MW${u>=0.999?" · full":""}</text>`;});
  D.nodes.forEach((n,i)=>{const un=(c.unserved[n.id]||[])[h]||0,y=NY(i);
    if(un>1e-6)s+=`<circle cx="${NX}" cy="${y}" r="30" fill="var(--bad)" opacity=".18"/>`;
    s+=`<circle cx="${NX}" cy="${y}" r="16" fill="var(--card)" stroke="${un>1e-6?"var(--bad)":"var(--ink)"}" stroke-width="2.5"/>`;
    s+=`<text x="${NX-26}" y="${y-2}" font-size="13" font-weight="600" text-anchor="end" fill="var(--ink)">${n.label}</text>`;
    s+=`<text x="${NX-26}" y="${y+14}" font-size="11" text-anchor="end" fill="var(--muted)">${D.plants[n.id].join(" · ")||"&nbsp;"}</text>`;
    if(un>1e-6)s+=`<text x="${NX+26}" y="${y+4}" font-size="12" font-weight="600" fill="var(--bad)">${fmt(un)} MW cut</text>`;
    if(c.battery&&c.battery.node===n.id){const soc=c.battery.soc[h]/c.battery.energy;
      s+=`<g transform="translate(${NX+26},${y-26})"><rect width="36" height="16" rx="3" fill="none" stroke="var(--accent)" stroke-width="2"/><rect x="2" y="2" width="${32*soc}" height="12" rx="1.5" fill="var(--accent)"/><text x="42" y="12" font-size="11" fill="var(--accent)">battery ${fmt(100*soc)}%</text></g>`;}});
  svg.innerHTML=s;}
function drawKPIs(){const c=C(S.sit,S.opt),b=C(S.sit,"baseline"),m=c.metrics;
  const row=(l,v,base,unit)=>{const d=v-base,cls=d<-0.05?"good":d>0.05?"bad":"";
    const ds=S.opt==="baseline"?"&nbsp;":Math.abs(d)<0.5?"same as today":`${d<0?"−":"+"}${fmt(Math.abs(d))} ${unit} vs today`;
    return `<div class="kpi"><div class="v">${fmt(v)}</div><div class="l">${l}</div><div class="d ${cls}">${ds}</div></div>`;};
  document.getElementById("kpibox").innerHTML=row("MWh solar/wind wasted",m.curtailment_mwh,b.metrics.curtailment_mwh,"MWh")+
    row("MWh demand not served",m.unserved_mwh,b.metrics.unserved_mwh,"MWh")+row("USD fuel cost (assumed)",m.assumed_cost_proxy_usd,b.metrics.assumed_cost_proxy_usd,"USD");
  document.getElementById("badge").textContent=c.valid?`✓ validated · ${c.checks} checks`:"✗ failed validation";
  document.getElementById("badge").style.color=c.valid?"var(--ok)":"var(--bad)";}
function drawChart(){const c=C(S.sit,S.opt),T=24,W=600,H=150,bw=W/T;
  const un=Array.from({length:T},(_,t)=>Object.values(c.unserved).reduce((a,v)=>a+v[t],0));
  const mx=Math.max(1,...c.curt,...un);let s="";
  (c.outage||[]).flat().forEach(t=>s+=`<rect x="${t*bw}" y="0" width="${bw}" height="${H}" fill="var(--bad)" opacity=".06"/>`);
  for(let t=0;t<T;t++){const hc=H*c.curt[t]/mx,hu=H*un[t]/mx;
    s+=`<rect x="${t*bw+2}" y="${H-hc}" width="${bw/2-2}" height="${hc}" fill="var(--solar)" rx="2"/>`;
    s+=`<rect x="${t*bw+bw/2}" y="${H-hu}" width="${bw/2-2}" height="${hu}" fill="var(--bad)" rx="2"/>`;}
  s+=`<rect x="${S.h*bw}" y="0" width="${bw}" height="${H}" fill="none" stroke="var(--accent)" stroke-width="2" rx="3"/>`;
  document.getElementById("bars").innerHTML=s;}
function drawControls(){const mk=(id,obj,labels,key)=>{document.getElementById(id).innerHTML=Object.keys(obj).map(k=>
    `<button data-k="${k}" class="${S[key]===k?"on":""}">${labels[k]||k}</button>`).join("");};
  mk("sit",D.situations,SIT_LABEL,"sit");mk("opt",D.options,OPT_LABEL,"opt");
  document.getElementById("hour").value=S.h;document.getElementById("hlabel").textContent=loc(S.h);}
function drawTour(){const t=document.getElementById("tour"),st=STEPS[S.step];
  document.querySelectorAll(".hl").forEach(e=>e.classList.remove("hl"));
  t.classList.toggle("closed",!S.tour);if(!S.tour)document.getElementById("veil").classList.remove("on");document.getElementById("reopen").style.display=S.tour?"none":"inline-block";
  if(!S.tour)return;
  document.getElementById("tk").textContent=`Step ${S.step+1} of ${STEPS.length} · ${st.k}`;
  document.getElementById("tt").textContent=st.t;document.getElementById("tp").textContent=st.p();
  document.getElementById("ttags").innerHTML=(st.tags||[]).map(x=>`<span class="${x}" title="${TAGS[x]}">${x}</span>`).join("");
  t.classList.toggle("slide",!!st.slide);document.getElementById("veil").classList.toggle("on",!!st.slide);
  document.getElementById("tdots").innerHTML=STEPS.map((_,i)=>`<span class="${i===S.step?"on":""}"></span>`).join("");
  document.getElementById("tback").disabled=S.step===0;
  document.getElementById("tnext").textContent=S.step===STEPS.length-1?"Finish":"Next";
  const el=document.getElementById(st.hl);if(el)el.classList.add("hl");}
function render(){drawControls();drawMap();drawKPIs();drawChart();drawTour();writeURL();}
function go(i){S.step=i;Object.assign(S,{sit:STEPS[i].sit,opt:STEPS[i].opt,h:STEPS[i].h});render();}

document.getElementById("sit").onclick=e=>{const k=e.target.dataset.k;if(k){S.sit=k;render();}};
document.getElementById("opt").onclick=e=>{const k=e.target.dataset.k;if(k){S.opt=k;render();}};
document.getElementById("hour").oninput=e=>{S.h=+e.target.value;render();};
document.getElementById("play").onclick=e=>{if(timer){clearInterval(timer);timer=null;e.target.textContent="▶";return;}
  e.target.textContent="❚❚";timer=setInterval(()=>{S.h=(S.h+1)%24;render();},600);};
document.getElementById("tnext").onclick=()=>{if(S.step<STEPS.length-1)go(S.step+1);else{S.tour=false;render();}};
document.getElementById("tback").onclick=()=>{if(S.step>0)go(S.step-1);};
document.getElementById("tclose").onclick=()=>{S.tour=false;render();};
document.getElementById("reopen").onclick=()=>{S.tour=true;go(S.step);};
document.getElementById("share").onclick=async e=>{try{await navigator.clipboard.writeText(location.href);e.target.textContent="Link copied";}catch(_){e.target.textContent="Copy from address bar";}setTimeout(()=>e.target.textContent="Copy link",1500);};
document.addEventListener("keydown",e=>{if(e.target.tagName==="INPUT")return;const t=document.getElementById("tour");
  if(!S.tour){if(e.key==="t"||e.key==="T")document.getElementById("reopen").click();return;}
  if(["ArrowRight"," ","Enter","PageDown"].includes(e.key)){e.preventDefault();document.getElementById("tnext").click();}
  else if(["ArrowLeft","PageUp"].includes(e.key)){e.preventDefault();document.getElementById("tback").click();}
  else if(e.key==="Escape")document.getElementById("tclose").click();
  else if(e.key==="h"||e.key==="H")t.classList.toggle("hidden");});
document.getElementById("foot").textContent=`Scenario ${D.scenario_id}: ${D.source}. Results are pre-computed; money is an assumed-cost proxy, not CEN costs. Simulation only: nothing here controls a real grid.`;
readURL();render();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", type=Path, help="solve every case on this scenario instead of using examples/")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    print(f"wrote {build(a.scenario, a.out)}")
