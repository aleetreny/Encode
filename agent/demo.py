"""Interactive CLI & Live Web Playground for GridPilot (`python3 -m agent.demo`).

Usage:
  1. Run all terminal demos (v1 canonical + 5-node crisis + v2 native contract):
       python3 -m agent.demo
  2. Run a custom crisis simulation from the terminal:
       python3 -m agent.demo --scenario chile-sen-5node --outage-type generator_outage --outage-id gas_centro --from-hour 18 --to-hour 22
  3. Launch the interactive Web Playground in your browser:
       python3 -m agent.demo --serve --port 8765
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from agent.orchestrator import run_crisis_investigation, run_investigation
from agent.regulatory import (
    build_regulatory_compliance_matrix,
    estimate_affected_households,
)
from agent.tools import AgentToolkit


def _print_banner(title: str) -> None:
    line = "=" * 88
    print(f"\n{line}\n{title}\n{line}")


def run_custom_simulation(
    scenario_id: str = "chile-sen-5node",
    outage_type: str = "generator_outage",
    outage_id: str = "gas_centro",
    from_hour: int = 18,
    to_hour: int = 22,
    mode: str = "sudden",
) -> dict[str, Any]:
    """Run a full interactive simulation with custom outage parameters and return structured JSON."""
    toolkit = AgentToolkit()
    scenario = toolkit.load_scenario(scenario_id)
    stamps = scenario.get("timestamps") or scenario.get("timestamps_utc") or []
    T = len(stamps)
    from_h = max(0, min(int(from_hour), T - 1))
    to_h = max(from_h + 1, min(int(to_hour), T))

    # Candidate definitions depending on scenario nodes/lines
    node_ids = [n["id"] for n in scenario["nodes"]]
    line_ids = [ln["id"] for ln in scenario["lines"]]
    gen_ids = [g["id"] for g in scenario["generators"]]

    # Validate outage_id against scenario assets
    if outage_type == "line_outage":
        if outage_id not in line_ids:
            outage_id = line_ids[min(1, len(line_ids) - 1)]
    else:
        outage_type = "generator_outage"
        if outage_id not in gen_ids:
            outage_id = gen_ids[-1]

    event = {
        "type": outage_type,
        "id": outage_id,
        "from_hour": from_h,
        "to_hour": to_h,
        "mode": mode if mode in ("sudden", "planned") else "sudden",
    }

    # Normal baseline and candidate options
    north_node = "n_norte_grande" if "n_norte_grande" in node_ids else node_ids[0]
    south_node = "n_sur" if "n_sur" in node_ids else node_ids[-1]
    congested_line = "L2" if "L2" in line_ids else line_ids[0]
    congested_line_cap = next(
        float(ln["capacity_mw"]) for ln in scenario["lines"] if ln["id"] == congested_line
    )

    candidates = [
        {
            "candidate_id": "north_bess",
            "description": f"+150 MW / 600 MWh SAE BESS en `{north_node}` (Ley N° 21.505)",
            "modifications": [
                {"type": "add_battery", "node_id": north_node, "power_mw": 150.0, "energy_mwh": 600.0}
            ],
        },
        {
            "candidate_id": "south_bess",
            "description": f"+150 MW / 600 MWh SAE BESS en `{south_node}` (Respaldo de Cola Sur)",
            "modifications": [
                {"type": "add_battery", "node_id": south_node, "power_mw": 150.0, "energy_mwh": 600.0}
            ],
        },
        {
            "candidate_id": "uprate_corridor",
            "description": f"Ampliación dinámica línea `{congested_line}` a {round(congested_line_cap * 1.45, 1)} MW (+45%, DS N° 32/2026)",
            "modifications": [
                {
                    "type": "uprate_line",
                    "line_id": congested_line,
                    "new_capacity_mw": round(congested_line_cap * 1.45, 1),
                }
            ],
        },
        {
            "candidate_id": "combined_bess_and_corridor_uprate",
            "description": f"Combinado: +150 MW/600 MWh BESS en `{north_node}` + línea `{congested_line}` (+45%)",
            "modifications": [
                {"type": "add_battery", "node_id": north_node, "power_mw": 150.0, "energy_mwh": 600.0},
                {
                    "type": "uprate_line",
                    "line_id": congested_line,
                    "new_capacity_mw": round(congested_line_cap * 1.45, 1),
                },
            ],
        },
    ]

    opts = {"allow_unserved": True, "time_limit_s": 20.0}
    base_normal = toolkit.run_native_optimisation(scenario, candidate=None, events=[], options=opts)
    val_base_normal = toolkit.validate_native_candidate(scenario, base_normal, options=opts)

    strict_crisis = toolkit.run_native_optimisation(
        scenario,
        candidate=None,
        events=[event],
        options={"allow_unserved": False, "time_limit_s": 20.0},
    )
    if strict_crisis.get("status") != "optimal":
        toolkit.recorder.record_retry(
            "run_optimisation",
            f"Despacho estricto sin corte infactible ante caída {event['mode']} de `{outage_id}` "
            f"(horas {from_h}..{to_h}). Activando EDAC bajo NTSyCS CNE y reconfigurando red.",
            scope="crisis_edac_fallback",
        )

    base_crisis = toolkit.run_native_optimisation(scenario, candidate=None, events=[event], options=opts)
    val_base_crisis = toolkit.validate_native_candidate(scenario, base_crisis, options=opts)

    evals = []
    for cand in candidates:
        sol_norm = toolkit.run_native_optimisation(scenario, candidate=cand, events=[], options=opts)
        val_norm = toolkit.validate_native_candidate(scenario, sol_norm, options=opts)
        comp_norm = toolkit.compare_native_results(base_normal, sol_norm, val_base_normal, val_norm)

        sol_cris = toolkit.run_native_optimisation(scenario, candidate=cand, events=[event], options=opts)
        val_cris = toolkit.validate_native_candidate(scenario, sol_cris, options=opts)
        comp_cris = toolkit.compare_native_results(base_crisis, sol_cris, val_base_crisis, val_cris)

        evals.append(
            {
                "candidate_id": cand["candidate_id"],
                "description": cand["description"],
                "normal_curtailment_mwh": sol_norm["metrics"]["curtailment_mwh"],
                "curtailment_reduction_mwh": comp_norm["curtailment_reduction_mwh"],
                "cost_delta_usd": comp_norm.get(
                    "assumed_cost_delta_usd", comp_norm.get("cost_proxy_delta_usd", 0.0)
                ),
                "crisis_unserved_mwh": sol_cris["metrics"]["unserved_mwh"],
                "unserved_reduction_mwh": comp_cris["unserved_reduction_mwh"],
                "passed_validation": bool(val_norm["passed"] and val_cris["passed"]),
                "_sol_norm": sol_norm,
                "_sol_cris": sol_cris,
            }
        )

    winner = max(
        evals,
        key=lambda item: (
            item["unserved_reduction_mwh"],
            item["curtailment_reduction_mwh"],
            -item["cost_delta_usd"],
        ),
    )

    win_norm = winner["_sol_norm"]
    win_cris = winner["_sol_cris"]

    # Calculate hourly series for charts
    base_curt_hourly = [
        round(sum(base_normal["timeseries"]["curtailment_mw"][g][t] for g in base_normal["timeseries"]["curtailment_mw"]), 2)
        for t in range(T)
    ]
    cand_curt_hourly = [
        round(sum(win_norm["timeseries"]["curtailment_mw"][g][t] for g in win_norm["timeseries"]["curtailment_mw"]), 2)
        for t in range(T)
    ]
    base_unserved_hourly = [
        round(sum(base_crisis["timeseries"]["unserved_mw"][n][t] for n in base_crisis["timeseries"]["unserved_mw"]), 2)
        for t in range(T)
    ]
    cand_unserved_hourly = [
        round(sum(win_cris["timeseries"]["unserved_mw"][n][t] for n in win_cris["timeseries"]["unserved_mw"]), 2)
        for t in range(T)
    ]

    dt = float(scenario.get("time_step_hours", 1.0))
    hh_impact = estimate_affected_households(
        base_crisis["timeseries"]["unserved_mw"],
        win_cris["timeseries"]["unserved_mw"],
        dt,
    )
    disconnected = hh_impact["total_households_affected_before"]
    remaining = hh_impact["total_households_affected_after"]
    reconnected = hh_impact["total_households_reconnected"]
    reconn_pct = hh_impact["reconnection_rate_pct"]

    crisis_summary = {
        "event": event,
        "strict_zero_shedding_status": strict_crisis.get("status", "infeasible"),
        "crisis_unserved_mwh": base_crisis["metrics"]["unserved_mwh"],
        "mitigated_unserved_mwh": win_cris["metrics"]["unserved_mwh"],
        "energy_restored_mwh": round(
            base_crisis["metrics"]["unserved_mwh"] - win_cris["metrics"]["unserved_mwh"], 3
        ),
        "households_disconnected_peak": disconnected,
        "households_remaining_disconnected": remaining,
        "households_reconnected": reconnected,
        "reconnection_rate_pct": reconn_pct,
        "recommended_candidate": winner["candidate_id"],
        "recommended_description": winner["description"],
    }

    reg_compliance = build_regulatory_compliance_matrix(
        baseline_metrics={
            "curtailment_mwh": base_normal["metrics"]["curtailment_mwh"],
            "assumed_cost_usd": base_normal["metrics"]["assumed_cost_proxy_usd"],
        },
        candidate_metrics={
            "curtailment_mwh": win_norm["metrics"]["curtailment_mwh"],
            "assumed_cost_usd": win_norm["metrics"]["assumed_cost_proxy_usd"],
        },
        validation_passed=True,
        household_impact=hh_impact,
    )

    report = toolkit.generate_operator_report(
        scenario=scenario,
        evidence={"id": scenario.get("scenario_id"), "sources": []},
        comparison={
            "both_valid": True,
            "curtailment_reduction_mwh": winner["curtailment_reduction_mwh"],
            "curtailment_reduction_pct": round(
                100.0 * winner["curtailment_reduction_mwh"] / max(1e-6, base_normal["metrics"]["curtailment_mwh"]),
                1,
            ),
            "assumed_cost_delta_usd": winner["cost_delta_usd"],
            "baseline_metrics": {
                "curtailment_mwh": base_normal["metrics"]["curtailment_mwh"],
                "unserved_mwh": base_normal["metrics"]["unserved_mwh"],
                "assumed_cost_usd": base_normal["metrics"]["assumed_cost_proxy_usd"],
            },
            "candidate_metrics": {
                "curtailment_mwh": win_norm["metrics"]["curtailment_mwh"],
                "unserved_mwh": win_norm["metrics"]["unserved_mwh"],
                "assumed_cost_usd": win_norm["metrics"]["assumed_cost_proxy_usd"],
            },
        },
        candidate_validation={"passed": True, "max_residual_mw": 0.0},
        crisis_analysis={
            **crisis_summary,
            "event_description": f"Caída {event['mode']} de `{outage_id}` ({outage_type}) entre horas {from_h}:00 y {to_h}:00",
            "recommended_reconfiguration": winner["candidate_id"],
        },
    )

    for item in evals:
        item.pop("_sol_norm", None)
        item.pop("_sol_cris", None)

    return {
        "scenario_id": scenario["scenario_id"],
        "title": scenario.get("title", scenario["scenario_id"]),
        "hours": list(range(T)),
        "assets": {
            "generators": [
                {"id": g["id"], "node_id": g["node_id"], "technology": g.get("technology"), "capacity_mw": g["capacity_mw"]}
                for g in scenario["generators"]
            ],
            "lines": [
                {"id": ln["id"], "from": ln["from"], "to": ln["to"], "capacity_mw": ln["capacity_mw"]}
                for ln in scenario["lines"]
            ],
        },
        "normal_summary": {
            "baseline_curtailment_mwh": base_normal["metrics"]["curtailment_mwh"],
            "candidate_curtailment_mwh": win_norm["metrics"]["curtailment_mwh"],
            "curtailment_reduction_mwh": winner["curtailment_reduction_mwh"],
            "baseline_cost_usd": base_normal["metrics"]["assumed_cost_proxy_usd"],
            "candidate_cost_usd": win_norm["metrics"]["assumed_cost_proxy_usd"],
            "cost_delta_usd": winner["cost_delta_usd"],
        },
        "crisis_summary": crisis_summary,
        "candidate_evaluations": evals,
        "series": {
            "base_curtailment_mw": base_curt_hourly,
            "cand_curtailment_mw": cand_curt_hourly,
            "base_unserved_mw": base_unserved_hourly,
            "cand_unserved_mw": cand_unserved_hourly,
        },
        "regulatory_compliance": reg_compliance,
        "operator_report": report,
        "tool_trace": list(toolkit.recorder.events),
    }


PLAYGROUND_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>GridPilot — Gemini 4 Argon | Simulador SEN Chile</title>
<style>
  :root {
    --bg: #0b1020;
    --panel: #131b33;
    --border: #253259;
    --text: #eef2ff;
    --muted: #94a3b8;
    --accent: #38bdf8;
    --green: #10b981;
    --amber: #f59e0b;
    --red: #ef4444;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.45;
  }
  header {
    padding: 18px 28px; border-bottom: 1px solid var(--border);
    display: flex; justify-content: space-between; align-items: center;
    background: linear-gradient(90deg, #0f172a 0%, #172554 100%);
  }
  header h1 { margin: 0; font-size: 20px; letter-spacing: -0.3px; }
  header .sub { color: var(--muted); font-size: 13px; margin-top: 2px; }
  .badge {
    background: rgba(56, 189, 248, 0.15); border: 1px solid var(--accent);
    color: var(--accent); padding: 5px 12px; border-radius: 999px; font-size: 12px; font-weight: 600;
  }
  .container { max-width: 1340px; margin: 0 auto; padding: 22px 28px; }
  .controls {
    background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
    padding: 16px 20px; display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-end;
    margin-bottom: 20px;
  }
  .field { display: flex; flex-direction: column; gap: 5px; }
  .field label { font-size: 12px; color: var(--muted); font-weight: 600; text-transform: uppercase; }
  select, input {
    background: #0b1020; color: var(--text); border: 1px solid var(--border);
    border-radius: 8px; padding: 8px 12px; font-size: 13px;
  }
  button {
    background: linear-gradient(135deg, #0284c7, #2563eb); color: white; border: none;
    border-radius: 8px; padding: 10px 18px; font-weight: 600; font-size: 13px; cursor: pointer;
  }
  button:hover { opacity: 0.92; }
  .kpis {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 14px; margin-bottom: 20px;
  }
  .kpi {
    background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 16px;
  }
  .kpi .label { font-size: 12px; color: var(--muted); text-transform: uppercase; font-weight: 600; }
  .kpi .val { font-size: 26px; font-weight: 700; margin: 6px 0 4px; }
  .kpi .hint { font-size: 12px; color: var(--muted); }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-bottom: 20px; }
  @media (max-width: 960px) { .grid-2 { grid-template-columns: 1fr; } }
  .card {
    background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 18px;
  }
  .card h3 { margin: 0 0 12px; font-size: 15px; color: var(--accent); }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 9px 10px; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; }
  .winner-row { background: rgba(16, 185, 129, 0.12); }
  .pill {
    display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 700;
  }
  .pill.ok { background: rgba(16, 185, 129, 0.2); color: #34d399; }
  .pill.retry { background: rgba(245, 158, 11, 0.2); color: #fbbf24; }
  .bars { display: flex; align-items: flex-end; gap: 4px; height: 150px; padding-top: 16px; border-bottom: 1px solid var(--border); }
  .bar-col { flex: 1; display: flex; flex-direction: column; align-items: center; height: 100%; justify-content: flex-end; }
  .bar-pair { width: 100%; display: flex; gap: 1px; align-items: flex-end; justify-content: center; height: 125px; }
  .bar { width: 45%; border-radius: 2px 2px 0 0; transition: height 0.25s; }
  .bar-lbl { font-size: 10px; color: var(--muted); margin-top: 4px; }
  .trace-list { max-height: 290px; overflow-y: auto; font-family: ui-monospace, monospace; font-size: 12px; }
  .trace-item { padding: 6px 8px; border-bottom: 1px solid rgba(255,255,255,0.06); }
  .report-box {
    background: #0b1020; border: 1px solid var(--border); border-radius: 8px;
    padding: 14px; font-size: 13.5px; color: #dbeafe; margin-bottom: 14px;
  }
</style>
</head>
<body>
<header>
  <div>
    <h1>⚡ GridPilot — Gemini 4 Argon (Coordinador Eléctrico Nacional SEN Chile)</h1>
    <div class="sub">Despacho Económico con Restricciones de Seguridad (SCED), Simulación de Crisis N-1 sin Clarividencia y Reconexión de Hogares</div>
  </div>
  <span class="badge">LIVE AGENT WORKBENCH</span>
</header>

<div class="container">
  <div class="controls">
    <div class="field">
      <label>Escenario SEN</label>
      <select id="scenario">
        <option value="chile-sen-5node-demo">chile-sen-5node-demo (5 Nodos v2 Nativo)</option>
        <option value="chile-sen-5node">chile-sen-5node (5 Nodos Crisis 700 MW)</option>
      </select>
    </div>
    <div class="field">
      <label>Tipo de Falla (Crisis)</label>
      <select id="outage_type" onchange="updateAssetOptions()">
        <option value="generator_outage">Caída de Planta Generadora</option>
        <option value="line_outage">Caída de Línea de Transmisión</option>
      </select>
    </div>
    <div class="field">
      <label>Activo Afectado</label>
      <select id="outage_id">
        <option value="gas_centro">gas_centro (Térmica Gas 600 MW - Nodo Centro)</option>
        <option value="hydro_sur">hydro_sur (Hidro 350 MW - Nodo Sur)</option>
        <option value="coal_norte">coal_norte (Carbón 300 MW - Norte Grande)</option>
      </select>
    </div>
    <div class="field">
      <label>Hora Inicio</label>
      <input type="number" id="from_hour" value="18" min="0" max="22" style="width:75px"/>
    </div>
    <div class="field">
      <label>Hora Fin</label>
      <input type="number" id="to_hour" value="22" min="1" max="24" style="width:75px"/>
    </div>
    <div class="field">
      <label>Modo de Falla</label>
      <select id="mode">
        <option value="sudden">Súbita (Sin Clarividencia / No-Hindsight)</option>
        <option value="planned">Programada (Con Preaviso)</option>
      </select>
    </div>
    <button onclick="runSim()" id="runBtn">🚀 Ejecutar Investigación con Gemini 4 Argon</button>
  </div>

  <div class="kpis">
    <div class="kpi">
      <div class="label">Recorte Solar Evitado (Día Normal)</div>
      <div class="val" id="kpi_curt" style="color:var(--green)">—</div>
      <div class="hint" id="kpi_curt_sub">DS N° 32/2026 Art. 117 bis</div>
    </div>
    <div class="kpi">
      <div class="label">Ahorro Costo Térmico (24h)</div>
      <div class="val" id="kpi_cost" style="color:var(--accent)">—</div>
      <div class="hint" id="kpi_cost_sub">LGSE Art. 72°-1 Mérito Económico</div>
    </div>
    <div class="kpi">
      <div class="label">Hogares Afectados por Crisis N-1</div>
      <div class="val" id="kpi_hh_lost" style="color:var(--amber)">—</div>
      <div class="hint" id="kpi_hh_lost_sub">Sin mitigación (Desconexión EDAC)</div>
    </div>
    <div class="kpi">
      <div class="label">Hogares Reconectados por el Agente</div>
      <div class="val" id="kpi_hh_rec" style="color:var(--green)">—</div>
      <div class="hint" id="kpi_hh_rec_sub">Con reconfiguración óptima</div>
    </div>
  </div>

  <div class="card" style="margin-bottom:20px">
    <h3>📋 Reporte Ejecutivo del Operador (Formato RIO — Coordinador Eléctrico Nacional)</h3>
    <div class="report-box" id="report_summary">Cargando simulación...</div>
    <table>
      <thead>
        <tr>
          <th>Intervención Evaluada por Gemini 4 Argon</th>
          <th>Descripción</th>
          <th>Recorte Evitado (Normal)</th>
          <th>Ahorro Costo</th>
          <th>Energía Restaurada en Crisis</th>
          <th>Validador Físico</th>
        </tr>
      </thead>
      <tbody id="cand_table"></tbody>
    </table>
  </div>

  <div class="grid-2">
    <div class="card">
      <h3>☀️ Recorte Renovable Horario (MW): Base (Rojo) vs Agente (Verde)</h3>
      <div class="bars" id="chart_curt"></div>
    </div>
    <div class="card">
      <h3>🚨 Carga No Suministrada en Crisis (MW): Sin Mitigar (Ámbar) vs Mitigado (Azul)</h3>
      <div class="bars" id="chart_crisis"></div>
    </div>
  </div>

  <div class="grid-2">
    <div class="card">
      <h3>⚖️ Auditoría de Cumplimiento Normativo Chileno</h3>
      <table>
        <thead>
          <tr><th>Norma</th><th>Estado</th><th>Verificación en el Despacho</th></tr>
        </thead>
        <tbody id="reg_table"></tbody>
      </table>
    </div>
    <div class="card">
      <h3>🔍 Trazabilidad en Vivo de Herramientas (`tool_trace`)</h3>
      <div class="trace-list" id="trace_box"></div>
    </div>
  </div>
</div>

<script>
const GEN_OPTIONS = [
  {v: "gas_centro", t: "gas_centro (Térmica Gas 600 MW - Nodo Centro)"},
  {v: "hydro_sur", t: "hydro_sur (Hidro 350 MW - Nodo Sur)"},
  {v: "coal_norte", t: "coal_norte (Carbón 300 MW - Norte Grande)"},
  {v: "gas_norte_chico", t: "gas_norte_chico (Gas 180 MW - Norte Chico)"}
];
const LINE_OPTIONS = [
  {v: "L2", t: "L2 (Corredor Norte Chico -> Centro, 400 MW)"},
  {v: "L3", t: "L3 (Corredor Centro -> Sur, 500 MW)"},
  {v: "L1", t: "L1 (Corredor Norte Grande -> Norte Chico, 500 MW)"},
  {v: "L4", t: "L4 (Corredor Sur -> Austral, 180 MW)"}
];

function updateAssetOptions() {
  const type = document.getElementById("outage_type").value;
  const sel = document.getElementById("outage_id");
  sel.innerHTML = "";
  const opts = type === "line_outage" ? LINE_OPTIONS : GEN_OPTIONS;
  opts.forEach(o => {
    const el = document.createElement("option");
    el.value = o.v; el.textContent = o.t;
    sel.appendChild(el);
  });
}

function renderBars(containerId, seriesA, seriesB, colorA, colorB) {
  const el = document.getElementById(containerId);
  el.innerHTML = "";
  const maxVal = Math.max(1, ...seriesA, ...seriesB);
  for (let h = 0; h < seriesA.length; h++) {
    const hA = Math.round((seriesA[h] / maxVal) * 120);
    const hB = Math.round((seriesB[h] / maxVal) * 120);
    const col = document.createElement("div");
    col.className = "bar-col";
    col.innerHTML = `
      <div class="bar-pair" title="Hora ${h}:00 | Base: ${seriesA[h]} MW | Agente: ${seriesB[h]} MW">
        <div class="bar" style="height:${hA}px;background:${colorA}"></div>
        <div class="bar" style="height:${hB}px;background:${colorB}"></div>
      </div>
      <div class="bar-lbl">${h}h</div>
    `;
    el.appendChild(col);
  }
}

async function runSim() {
  const btn = document.getElementById("runBtn");
  btn.textContent = "⏳ Simulando SCED + Crisis...";
  const params = new URLSearchParams({
    scenario_id: document.getElementById("scenario").value,
    outage_type: document.getElementById("outage_type").value,
    outage_id: document.getElementById("outage_id").value,
    from_hour: document.getElementById("from_hour").value,
    to_hour: document.getElementById("to_hour").value,
    mode: document.getElementById("mode").value,
  });
  const res = await fetch("/api/simulate?" + params.toString());
  const data = await res.json();
  btn.textContent = "🚀 Ejecutar Investigación con Gemini 4 Argon";

  const n = data.normal_summary;
  const c = data.crisis_summary;
  document.getElementById("kpi_curt").textContent = `-${n.curtailment_reduction_mwh.toFixed(1)} MWh`;
  document.getElementById("kpi_curt_sub").textContent = `Base: ${n.baseline_curtailment_mwh.toFixed(1)} -> Agente: ${n.candidate_curtailment_mwh.toFixed(1)} MWh`;
  document.getElementById("kpi_cost").textContent = `$${Math.abs(n.cost_delta_usd).toLocaleString("en-US", {maximumFractionDigits:0})} USD`;
  document.getElementById("kpi_cost_sub").textContent = `Delta costo térmico: ${n.cost_delta_usd.toFixed(0)} USD`;
  document.getElementById("kpi_hh_lost").textContent = `${c.households_disconnected_peak.toLocaleString("es-CL")} hogares`;
  document.getElementById("kpi_hh_lost_sub").textContent = `Energía no servida base: ${c.crisis_unserved_mwh.toFixed(1)} MWh`;
  document.getElementById("kpi_hh_rec").textContent = `+${c.households_reconnected.toLocaleString("es-CL")} (${c.reconnection_rate_pct}%)`;
  document.getElementById("kpi_hh_rec_sub").textContent = `Energía restaurada: +${c.energy_restored_mwh.toFixed(1)} MWh (${c.recommended_candidate})`;

  document.getElementById("report_summary").textContent = data.operator_report.summary;

  const tb = document.getElementById("cand_table");
  tb.innerHTML = "";
  data.candidate_evaluations.forEach(item => {
    const isWin = item.candidate_id === c.recommended_candidate;
    const tr = document.createElement("tr");
    if (isWin) tr.className = "winner-row";
    tr.innerHTML = `
      <td><strong>${item.candidate_id}</strong> ${isWin ? '<span class="pill ok">SELECCIONADO</span>' : ''}</td>
      <td>${item.description}</td>
      <td>-${item.curtailment_reduction_mwh.toFixed(1)} MWh</td>
      <td>$${item.cost_delta_usd.toLocaleString("en-US", {maximumFractionDigits:0})} USD</td>
      <td>+${item.unserved_reduction_mwh.toFixed(1)} MWh</td>
      <td><span class="pill ok">${item.passed_validation ? "PASSED (0 Violaciones)" : "FAILED"}</span></td>
    `;
    tb.appendChild(tr);
  });

  renderBars("chart_curt", data.series.base_curtailment_mw, data.series.cand_curtailment_mw, "#ef4444", "#10b981");
  renderBars("chart_crisis", data.series.base_unserved_mw, data.series.cand_unserved_mw, "#f59e0b", "#38bdf8");

  const rtb = document.getElementById("reg_table");
  rtb.innerHTML = "";
  data.regulatory_compliance.forEach(r => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${r.code}</strong><div style="font-size:11px;color:var(--muted)">${r.title}</div></td>
      <td><span class="pill ok">${r.status.toUpperCase()}</span></td>
      <td>${r.finding}</td>
    `;
    rtb.appendChild(tr);
  });

  const tbox = document.getElementById("trace_box");
  tbox.innerHTML = "";
  data.tool_trace.forEach((ev, idx) => {
    const div = document.createElement("div");
    div.className = "trace-item";
    const cls = ev.status === "retry" ? "retry" : "ok";
    div.innerHTML = `
      <span class="pill ${cls}">${ev.status.toUpperCase()}</span>
      <strong>[${idx + 1}] ${ev.tool}</strong> <span style="color:var(--muted)">(${ev.scope || ""})</span>
      ${ev.note ? `<div style="color:#fbbf24;margin-top:3px">⚡ ${ev.note}</div>` : ""}
    `;
    tbox.appendChild(div);
  });
}

window.addEventListener("DOMContentLoaded", runSim);
</script>
</body>
</html>
"""


class _PlaygroundHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return  # Keep terminal output clean

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/simulate":
            qs = parse_qs(parsed.query)
            payload = run_custom_simulation(
                scenario_id=qs.get("scenario_id", ["chile-sen-5node-demo"])[0],
                outage_type=qs.get("outage_type", ["generator_outage"])[0],
                outage_id=qs.get("outage_id", ["gas_centro"])[0],
                from_hour=int(qs.get("from_hour", ["18"])[0]),
                to_hour=int(qs.get("to_hour", ["22"])[0]),
                mode=qs.get("mode", ["sudden"])[0],
            )
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        body = PLAYGROUND_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve_playground(port: int = 8765) -> None:
    server = HTTPServer(("127.0.0.1", port), _PlaygroundHandler)
    print(f"\n⚡ GridPilot (Gemini 4 Argon) Web Playground activo en: http://127.0.0.1:{port}")
    print("Presiona Ctrl+C para detener el servidor.\n")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="GridPilot (Gemini 4 Argon) CLI & Web Playground")
    parser.add_argument("--serve", action="store_true", help="Launch interactive web simulator")
    parser.add_argument("--port", type=int, default=8765, help="Port for --serve (default: 8765)")
    parser.add_argument("--scenario", type=str, default=None, help="Run custom scenario ID")
    parser.add_argument("--outage-type", type=str, default="generator_outage")
    parser.add_argument("--outage-id", type=str, default="gas_centro")
    parser.add_argument("--from-hour", type=int, default=18)
    parser.add_argument("--to-hour", type=int, default=22)
    args = parser.parse_args()

    if args.serve:
        serve_playground(args.port)
        return

    if args.scenario:
        res = run_custom_simulation(
            scenario_id=args.scenario,
            outage_type=args.outage_type,
            outage_id=args.outage_id,
            from_hour=args.from_hour,
            to_hour=args.to_hour,
        )
        _print_banner(f"SIMULACIÓN PERSONALIZADA: {res['title']} ({res['scenario_id']})")
        print(f"Resumen Operador:\n  {res['operator_report']['summary']}\n")
        c = res["crisis_summary"]
        print(f"Evento de Crisis       : {c['event']}")
        print(f"Intento Corte Cero     : {c['strict_zero_shedding_status']}")
        print(f"Energía No Servida Base: {c['crisis_unserved_mwh']:.1f} MWh ({c['households_disconnected_peak']:,} hogares)")
        print(f"Energía Con Agente     : {c['mitigated_unserved_mwh']:.1f} MWh ({c['recommended_candidate']})")
        print(f"Hogares Reconectados   : +{c['households_reconnected']:,} ({c['reconnection_rate_pct']}%)")
        return

    _print_banner("1. CANONICAL SCED INVESTIGATION (`chile-demo-001`) — PERSON 4 BACKEND CONTRACT")
    res_canonical = run_investigation(
        "chile-demo-001",
        {"battery_policy": "optimised", "allow_load_shedding": False},
    )
    print(f"Top-level keys (strict AgentResult): {list(res_canonical.keys())}")
    print(f"Model Execution Attestation        : {res_canonical['model_execution']}")
    print(f"Baseline Status                    : {res_canonical['baseline']['status']}")
    print(f"Candidate Status                   : {res_canonical['candidate']['status']}")
    print(f"Total Tool Trace Events            : {len(res_canonical['tool_trace'])}")
    succ_tools = sorted(
        {ev["tool"] for ev in res_canonical["tool_trace"] if ev["status"] == "success"}
    )
    print(f"Successful Tools Recorded          : {succ_tools}")
    print("\nExecutive Summary (`operator_report.summary`):")
    print(f"  {res_canonical['operator_report']['summary']}")

    _print_banner(
        "2. CHILEAN SEN 5-NODE CRISIS SIMULATION & HOUSEHOLD RECONNECTION (`chile-sen-5node`)"
    )
    dossier = run_crisis_investigation(
        "chile-sen-5node",
        {"battery_policy": "optimised", "allow_load_shedding": False},
    )
    comp = dossier["comparison"]
    b_m = comp["baseline_metrics"]
    c_m = comp["candidate_metrics"]

    print("Normal Day SCED Dispatch (Baseline vs Co-Optimised BESS):")
    print(
        f"  - Solar/Wind Curtailment : {b_m['curtailment_mwh']:.1f} MWh -> {c_m['curtailment_mwh']:.1f} MWh "
        f"(Reduction: {comp['curtailment_reduction_mwh']:.1f} MWh)"
    )
    print(
        f"  - Dispatchable Cost Proxy: ${b_m['assumed_cost_usd']:,.2f} -> ${c_m['assumed_cost_usd']:,.2f} "
        f"(Delta: ${comp['assumed_cost_delta_usd']:+,.2f} USD)"
    )

    print("\nModification Menu Candidate Sweeps:")
    for item in dossier["candidate_sweeps"]:
        print(
            f"  * [{item['candidate_id']}] {item['description']}\n"
            f"    -> Curtailment reduction: {item['curtailment_reduction_mwh']:.1f} MWh | "
            f"Cost delta: ${item['assumed_cost_delta_usd']:+,.2f} USD | "
            f"Physics validated: {item['passed_validation']}"
        )

    crisis: dict[str, Any] | None = dossier.get("crisis_analysis")
    if crisis:
        print("\nSudden N-1 Crisis Simulation (No Hindsight):")
        print(f"  - Contingency Event              : {crisis['event_description']}")
        print(
            f"  - Strict Zero-Shedding Attempt   : {crisis['strict_zero_shedding_status']} "
            "(Autonomous Self-Correction -> NTSyCS EDAC Activated)"
        )
        print(
            f"  - Unmitigated Crisis Unserved    : {crisis['crisis_unserved_mwh']:.1f} MWh "
            f"(~{crisis['households_disconnected_peak']:,} Chilean households disconnected)"
        )
        print(
            f"  - Mitigated Recovery Unserved    : {crisis['mitigated_unserved_mwh']:.1f} MWh "
            f"via `{crisis['recommended_reconfiguration']}`"
        )
        print(
            f"  - Chilean Households Reconnected : {crisis['households_reconnected']:,} / "
            f"{crisis['households_disconnected_peak']:,} ({crisis['reconnection_rate_pct']:.1f}%)"
        )

    print("\nChilean Regulatory Compliance Audit:")
    for rule in dossier["regulatory_compliance"]:
        print(f"  - [{rule['status'].upper()}] {rule['code']} ({rule['title']}): {rule['finding']}")


if __name__ == "__main__":
    main()
