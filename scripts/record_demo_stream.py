"""Record a real sequence of LiveEvent JSONL records from the deterministic solver & validator.

Used in Wave A to produce the initial `frontend/src/live/fixtures/demo-stream.jsonl`
against the frozen contract (`contracts/live.schema.json`), and re-run in Wave D
with full operational levers from the live engine.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.live.agent_loop import to_contract_solution
from backend.live.catalog import build_catalog
from optimisation import load_scenario, solve, validate
SCENARIO_PATH = ROOT / "optimisation" / "fixtures" / "demo_scenario.json"
OUT_PATH = ROOT / "frontend" / "src" / "live" / "fixtures" / "demo-stream.jsonl"
SCHEMA_PATH = ROOT / "contracts" / "live.schema.json"

NODE_META = {
    "n_norte_grande": {
        "name": "Norte Grande (Crucero)",
        "lat": -22.30,
        "lon": -69.55,
        "households_total": 380000,
        "households_per_mw": 1000,
    },
    "n_norte_chico": {
        "name": "Norte Chico (Cardones)",
        "lat": -27.45,
        "lon": -70.30,
        "households_total": 310000,
        "households_per_mw": 1000,
    },
    "n_centro": {
        "name": "Centro Metropolitano (Polpaico)",
        "lat": -33.15,
        "lon": -70.85,
        "households_total": 2650000,
        "households_per_mw": 1000,
    },
    "n_centro_sur": {
        "name": "Centro-Sur (Charrúa)",
        "lat": -36.90,
        "lon": -72.20,
        "households_total": 1150000,
        "households_per_mw": 1000,
    },
    "n_sur": {
        "name": "Sur Austral (Puerto Montt)",
        "lat": -41.45,
        "lon": -72.95,
        "households_total": 610000,
        "households_per_mw": 1000,
    },
}

EMISSION_FACTORS_T_PER_MWH = {
    "gas": 0.40,
    "coal": 0.95,
    "diesel": 0.75,
    "solar": 0.0,
    "wind": 0.0,
    "hydro": 0.0,
}

GEN_NAMES = {
    "solar_ng": "Solar Crucero Norte Grande",
    "solar_nc": "Solar Atacama Norte Chico",
    "wind_nc": "Eólica Punta Palmeras",
    "gas_ng": "Ciclo Combinado Mejillones",
    "gas_centro": "Ciclo Combinado Nehuenco Centro",
    "coal_cs": "Termoeléctrica Santa María Coronel",
    "hydro_sur": "Embalse Ralco Chapo Sur",
    "wind_sur": "Parque Eólico Llanquihue",
    "diesel_centro": "Turbina Diésel Respaldo Renca",
}

BAT_NAMES = {
    "b_centro": "BESS Polpaico Operativo",
    "b_reserve_ng": "BESS Reserva Crucero Norte Grande",
    "b_reserve_centro": "BESS Reserva Polpaico Centro",
}


def strip_digits(text: str) -> str:
    """Enforce the non-negotiable guardrail: zero digits in Gemini prose."""
    cleaned = re.sub(r"\d+", "", text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    assert not re.search(r"\d", cleaned), f"Digit remained in text: {cleaned}"
    return cleaned


def compute_option_metrics(
    no_action_sol: dict[str, Any],
    opt_sol: dict[str, Any],
    from_hour: int,
) -> dict[str, Any]:
    T = len(no_action_sol["cost_proxy_usd"])
    node_ids = list(no_action_sol["unserved_mw"].keys())

    base_peak_hh = max(
        sum(no_action_sol["households_off"][n][h] for n in node_ids) for h in range(from_hour, T)
    )
    opt_peak_hh = max(
        sum(opt_sol["households_off"][n][h] for n in node_ids) for h in range(from_hour, T)
    )
    reconnected = max(0.0, round(base_peak_hh - opt_peak_hh, 1))
    newly_off = max(0.0, round(opt_peak_hh - base_peak_hh, 1))

    base_uns_mwh = sum(sum(no_action_sol["unserved_mw"][n]) for n in node_ids)
    opt_uns_mwh = sum(sum(opt_sol["unserved_mw"][n]) for n in node_ids)
    unserved_avoided = round(base_uns_mwh - opt_uns_mwh, 3)

    cost_delta = round(sum(opt_sol["cost_proxy_usd"]) - sum(no_action_sol["cost_proxy_usd"]), 2)
    co2_delta = round(sum(opt_sol["co2_t"]) - sum(no_action_sol["co2_t"]), 3)

    base_curt = sum(sum(v) for v in no_action_sol["curtailment_mw"].values())
    opt_curt = sum(sum(v) for v in opt_sol["curtailment_mw"].values())
    curt_delta = round(opt_curt - base_curt, 3)

    max_loading = 0.0
    for lid, flows in opt_sol["line_flow_mw"].items():
        caps = opt_sol["line_capacity_mw"][lid]
        for f_val, c_val in zip(flows, caps):
            if c_val > 0:
                max_loading = max(max_loading, abs(f_val) / c_val * 100.0)

    hours_to_zero: int | None = 0
    for h in range(from_hour, T):
        tot_u = sum(opt_sol["unserved_mw"][n][h] for n in node_ids)
        if tot_u > 1e-3:
            hours_to_zero = (h - from_hour) + 1

    return {
        "households_reconnected": reconnected,
        "households_newly_off": newly_off,
        "unserved_mwh_avoided": unserved_avoided,
        "cost_delta_usd": cost_delta,
        "co2_delta_t": co2_delta,
        "curtailment_delta_mwh": curt_delta,
        "max_line_loading_pct": round(max_loading, 2),
        "hours_to_zero_unserved": hours_to_zero,
    }


def compute_impact(sol: dict[str, Any], from_hour: int, to_hour: int) -> dict[str, Any]:
    node_ids = list(sol["unserved_mw"].keys())
    unserved_peak = 0.0
    hh_peak = 0.0
    nodes_affected = []
    for n in node_ids:
        n_peak = max(sol["unserved_mw"][n][from_hour:to_hour], default=0.0)
        if n_peak > 1e-3:
            nodes_affected.append(n)
    for h in range(from_hour, to_hour):
        u_h = sum(sol["unserved_mw"][n][h] for n in node_ids)
        hh_h = sum(sol["households_off"][n][h] for n in node_ids)
        unserved_peak = max(unserved_peak, u_h)
        hh_peak = max(hh_peak, hh_h)

    lines_overloaded = []
    for lid, flows in sol["line_flow_mw"].items():
        caps = sol["line_capacity_mw"][lid]
        for h in range(from_hour, to_hour):
            if caps[h] > 0 and abs(flows[h]) >= 0.95 * caps[h] - 1e-3:
                lines_overloaded.append(lid)
                break

    return {
        "unserved_mw_peak": round(unserved_peak, 3),
        "households_off_peak": round(hh_peak, 1),
        "nodes_affected": nodes_affected,
        "lines_overloaded": lines_overloaded,
    }


def generate_stream() -> list[dict[str, Any]]:
    scen = load_scenario(SCENARIO_PATH)

    catalog = build_catalog(scen)
    session_id = "ses-live-demo-chile"
    t0 = datetime(2026, 10, 25, 11, 0, 0, tzinfo=timezone.utc)
    seq = 0
    events_out: list[dict[str, Any]] = []

    def emit(hour: float, dt_sec: float, payload: dict[str, Any]) -> None:
        nonlocal seq, t0
        t0 = t0 + timedelta(seconds=dt_sec)
        ev = {
            "seq": seq,
            "session_id": session_id,
            "hour": round(hour, 2),
            "ts_utc": t0.isoformat().replace("+00:00", "Z"),
            **payload,
        }
        events_out.append(ev)
        seq += 1

    # 1. Baseline solve at start of session (hour 12.0)
    raw_base = solve(scen)
    val_base = validate(scen, raw_base)
    assert val_base["passed"], val_base
    sol_base = to_contract_solution(scen, raw_base, val_base, "sol-baseline-normal")

    emit(
        12.0,
        0.0,
        {
            "type": "session.snapshot",
            "catalog": catalog,
            "solution": sol_base,
            "grid_state": "normal",
            "active_events": [],
            "autonomy": False,
            "clock": {"hour": 12.0, "running": True, "speed_s_per_hour": 4.0},
        },
    )

    emit(
        12.25,
        1.0,
        {
            "type": "clock.tick",
            "running": True,
        },
    )

    emit(
        12.5,
        1.0,
        {
            "type": "agent.note",
            "text_es": strip_digits(
                "Corredor Norte Chico hacia Centro opera a plena capacidad con recorte solar en el norte bajo despacho económico."
            ),
        },
    )

    # Advance to hour 18.0 -> Disruption 1: gas_centro sudden outage [18, 22)
    disruption_1 = {
        "event_id": "ev-gas-centro-outage",
        "type": "generator_outage",
        "asset_id": "gas_centro",
        "from_hour": 18,
        "to_hour": 22,
        "source": "operator",
    }
    solver_ev_1 = [
        {
            "type": "generator_outage",
            "id": "gas_centro",
            "from_hour": 18,
            "to_hour": 22,
            "mode": "sudden",
        }
    ]
    raw_inc1 = solve(scen, events=solver_ev_1)
    val_inc1 = validate(scen, raw_inc1)
    assert val_inc1["passed"], val_inc1
    sol_inc1 = to_contract_solution(scen, raw_inc1, val_inc1, "sol-inc1-no-action")
    impact_1 = compute_impact(sol_inc1, 18, 22)

    emit(
        18.0,
        1.0,
        {
            "type": "incident.detected",
            "incident_id": "inc-gas-centro",
            "disruption": disruption_1,
            "impact": impact_1,
        },
    )
    emit(
        18.0,
        0.05,
        {
            "type": "solution.updated",
            "reason": "incident",
            "solution": sol_inc1,
            "grid_state": "emergencia",
        },
    )

    # Gemini thoughts and tool calls for incident 1
    emit(
        18.05,
        0.4,
        {
            "type": "agent.thought",
            "incident_id": "inc-gas-centro",
            "delta": strip_digits(
                "Detecto salida abrupta de la central térmica de ciclo combinado en la zona central durante la rampa vespertina. "
            ),
        },
    )
    emit(
        18.08,
        0.3,
        {
            "type": "agent.tool_call",
            "incident_id": "inc-gas-centro",
            "call_id": "call-inspect-centro",
            "tool": "inspect_node",
            "args_summary_es": strip_digits("Inspeccionar déficit y enlaces en nodo Centro"),
            "status": "pass",
            "duration_ms": 14,
            "result_summary": {"node_id": "n_centro", "deficit_active": True, "corridor_congested": True},
        },
    )

    # Candidate A for incident 1: activate_reserve_bess at b_reserve_centro + emergency_rating L2 (max_hogares)
    cand_1a = {
        "candidate_id": "opt_inc1_a",
        "modifications": [
            {"type": "activate_reserve_bess", "battery_id": "b_reserve_centro", "from_hour": 18, "to_hour": 22},
            {"type": "emergency_rating", "line_id": "L2", "factor": 1.20, "from_hour": 18, "to_hour": 22},
        ],
    }
    raw_1a = solve(scen, candidate=cand_1a, events=solver_ev_1)
    val_1a = validate(scen, raw_1a)
    assert val_1a["passed"], val_1a
    sol_1a = to_contract_solution(scen, raw_1a, val_1a, "sol-inc1-opt-a")

    # Candidate B for incident 1: hydro_reserve_release at hydro_sur (min_costo / min_co2)
    cand_1b = {
        "candidate_id": "opt_inc1_b",
        "modifications": [
            {"type": "hydro_reserve_release", "generator_id": "hydro_sur", "extra_mw": 120.0, "water_value_usd_per_mwh": 120.0, "from_hour": 18, "to_hour": 22},
        ],
    }
    raw_1b = solve(scen, candidate=cand_1b, events=solver_ev_1)
    val_1b = validate(scen, raw_1b)
    assert val_1b["passed"], val_1b
    sol_1b = to_contract_solution(scen, raw_1b, val_1b, "sol-inc1-opt-b")

    emit(
        18.12,
        0.4,
        {
            "type": "agent.tool_call",
            "incident_id": "inc-gas-centro",
            "call_id": "call-sim-inc1-a",
            "tool": "simulate_plan",
            "args_summary_es": strip_digits(
                "Simular activación de batería en reserva fría en Centro combinada con límite térmico de emergencia en corredor norte"
            ),
            "status": "pass",
            "duration_ms": 18,
            "result_summary": {"passed": True, "status": "optimal"},
        },
    )
    emit(
        18.15,
        0.3,
        {
            "type": "agent.thought",
            "incident_id": "inc-gas-centro",
            "delta": strip_digits(
                "El frente de Pareto muestra un dilema claro entre maximizar la reconexión inmediata de hogares en Santiago con batería de reserva y sobrecarga temporal o liberar cota hidroeléctrica del sur."
            ),
        },
    )

    option_1a = {
        "option_id": "opt-a-max-hogares",
        "title_es": strip_digits("Activar reserva BESS central y sobrecarga térmica norte"),
        "levers": [
            {
                "type": "activate_reserve_bess",
                "target_id": "b_reserve_centro",
                "params": {},
                "from_hour": 18,
                "to_hour": 22,
            },
            {
                "type": "emergency_rating",
                "target_id": "L2",
                "params": {"factor": 1.20},
                "from_hour": 18,
                "to_hour": 22,
            },
        ],
        "rationale_es": strip_digits(
            "Habilita la batería de reserva en Polpaico y eleva temporalmente el límite térmico del corredor norte para restituir suministro residencial con rapidez."
        ),
        "tradeoff_tag": "max_hogares",
        "metrics": compute_option_metrics(sol_inc1, sol_1a, 18),
        "validation": sol_1a["validation"],
        "solution": sol_1a,
    }

    option_1b = {
        "option_id": "opt-b-min-costo",
        "title_es": strip_digits("Liberar reserva hídrica de embalse austral"),
        "levers": [
            {
                "type": "hydro_reserve_release",
                "target_id": "hydro_sur",
                "params": {"extra_mw": 120.0, "cost_usd_per_mwh": 120.0},
                "from_hour": 18,
                "to_hour": 22,
            }
        ],
        "rationale_es": strip_digits(
            "Incrementa la inyección hidroeléctrica limpia desde el sur sin exigir sobrecarga térmica en el corredor norte, aunque mantiene mayor racionamiento temporal."
        ),
        "tradeoff_tag": "min_co2",
        "metrics": compute_option_metrics(sol_inc1, sol_1b, 18),
        "validation": sol_1b["validation"],
        "solution": sol_1b,
    }

    emit(
        18.20,
        0.5,
        {
            "type": "options.ready",
            "incident_id": "inc-gas-centro",
            "diagnosis_es": strip_digits(
                "Pérdida súbita de generación térmica base en nodo Centro provoca déficit severo en horario punta vespertino y congestión de importación desde el norte."
            ),
            "options": [option_1a, option_1b],
            "recommended_id": "opt-a-max-hogares",
            "candidates_evaluated": 12,
            "candidates_passed": 12,
            "model_execution": {
                "model": "gemini-4-argon",
                "role": "decider",
                "status": "ok",
                "latency_ms": 1650,
                "response_id": "resp-live-fixture-inc1",
                "cached": True,
                "cached_at_utc": "2026-10-24T20:20:00Z",
            },
        },
    )

    # Operator applies Option A
    emit(
        18.35,
        1.5,
        {
            "type": "plan.applied",
            "incident_id": "inc-gas-centro",
            "option_id": "opt-a-max-hogares",
            "by": "operator",
        },
    )
    emit(
        18.35,
        0.05,
        {
            "type": "solution.updated",
            "reason": "plan_applied",
            "solution": sol_1a,
            "grid_state": "recuperacion",
        },
    )

    # Second disruption at hour 19.0: L3 line outage in autonomous mode with 5->0 countdown
    disruption_2 = {
        "event_id": "ev-l3-outage",
        "type": "line_outage",
        "asset_id": "L3",
        "from_hour": 19,
        "to_hour": 22,
        "source": "jury",
        "jury_name": "Jurado Londres",
    }
    solver_ev_2 = solver_ev_1 + [
        {
            "type": "line_outage",
            "id": "L3",
            "from_hour": 19,
            "to_hour": 22,
            "mode": "sudden",
        }
    ]
    raw_inc2 = solve(scen, candidate=cand_1a, events=solver_ev_2)
    val_inc2 = validate(scen, raw_inc2)
    assert val_inc2["passed"], val_inc2
    sol_inc2 = to_contract_solution(scen, raw_inc2, val_inc2, "sol-inc2-no-action")
    impact_2 = compute_impact(sol_inc2, 19, 22)

    emit(
        19.0,
        1.0,
        {
            "type": "incident.detected",
            "incident_id": "inc-l3-corridor",
            "disruption": disruption_2,
            "impact": impact_2,
        },
    )
    emit(
        19.0,
        0.05,
        {
            "type": "solution.updated",
            "reason": "incident",
            "solution": sol_inc2,
            "grid_state": "emergencia",
        },
    )

    emit(
        19.05,
        0.4,
        {
            "type": "agent.thought",
            "incident_id": "inc-l3-corridor",
            "delta": strip_digits(
                "Apertura intempestiva del enlace Centro hacia Centro-Sur separa el apoyo hidroeléctrico austral mientras continúa indisponible la térmica central."
            ),
        },
    )
    emit(
        19.10,
        0.4,
        {
            "type": "agent.tool_call",
            "incident_id": "inc-l3-corridor",
            "call_id": "call-sim-inc2",
            "tool": "simulate_plan",
            "args_summary_es": strip_digits(
                "Evaluar refuerzo de almacenamiento local y alivio de transmisión para contingencia doble"
            ),
            "status": "pass",
            "duration_ms": 19,
            "result_summary": {"passed": True, "status": "optimal"},
        },
    )

    cand_2a = {
        "candidate_id": "opt_inc2_a",
        "modifications": [
            {"type": "demand_response", "node_id": "n_centro", "max_mw": 120.0, "cost_usd_per_mwh": 300.0, "from_hour": 19, "to_hour": 22},
            {"type": "emergency_rating", "line_id": "L2", "factor": 1.20, "from_hour": 19, "to_hour": 22},
        ],
    }
    raw_2a = solve(scen, candidate=cand_2a, events=solver_ev_2)
    val_2a = validate(scen, raw_2a)
    assert val_2a["passed"], val_2a
    sol_2a = to_contract_solution(scen, raw_2a, val_2a, "sol-inc2-opt-a")

    cand_2b = {
        "candidate_id": "opt_inc2_b",
        "modifications": [
            {"type": "activate_reserve_bess", "battery_id": "b_reserve_centro", "from_hour": 18, "to_hour": 22},
            {"type": "start_peaker", "generator_id": "diesel_centro", "from_hour": 19, "to_hour": 22},
        ],
    }
    raw_2b = solve(scen, candidate=cand_2b, events=solver_ev_2)
    val_2b = validate(scen, raw_2b)
    assert val_2b["passed"], val_2b
    sol_2b = to_contract_solution(scen, raw_2b, val_2b, "sol-inc2-opt-b")

    option_2a = {
        "option_id": "opt-2a-max-hogares",
        "title_es": strip_digits("Respuesta de demanda industrial y límite de emergencia en corredor norte"),
        "levers": [
            {
                "type": "demand_response",
                "target_id": "n_centro",
                "params": {"max_mw": 120.0, "cost_usd_per_mwh": 300.0},
                "from_hour": 19,
                "to_hour": 22,
            },
            {
                "type": "emergency_rating",
                "target_id": "L2",
                "params": {"factor": 1.20},
                "from_hour": 19,
                "to_hour": 22,
            },
        ],
        "rationale_es": strip_digits(
            "Compensa la desconexión del sur activando carga industrial interrumpible voluntaria en el centro sin cortar suministro a hogares residenciales."
        ),
        "tradeoff_tag": "max_hogares",
        "metrics": compute_option_metrics(sol_inc2, sol_2a, 19),
        "validation": sol_2a["validation"],
        "solution": sol_2a,
    }

    option_2b = {
        "option_id": "opt-2b-min-riesgo",
        "title_es": strip_digits("Arranque de turbina diésel de respaldo y reserva BESS local"),
        "levers": [
            {
                "type": "start_peaker",
                "target_id": "diesel_centro",
                "params": {"startup_delay_hours": 1},
                "from_hour": 19,
                "to_hour": 22,
            },
            {
                "type": "activate_reserve_bess",
                "target_id": "b_reserve_centro",
                "params": {},
                "from_hour": 19,
                "to_hour": 22,
            },
        ],
        "rationale_es": strip_digits(
            "Sincroniza generación térmica rápida local con menor exigencia térmica en el enlace norte tras la rampa de arranque."
        ),
        "tradeoff_tag": "min_riesgo_red",
        "metrics": compute_option_metrics(sol_inc2, sol_2b, 19),
        "validation": sol_2b["validation"],
        "solution": sol_2b,
    }

    emit(
        19.20,
        0.5,
        {
            "type": "options.ready",
            "incident_id": "inc-l3-corridor",
            "diagnosis_es": strip_digits(
                "Contingencia doble por apertura del corredor Centro-Sur aisla el aporte hidroeléctrico sureño y exige reconfiguración autónoma inmediata."
            ),
            "options": [option_2a, option_2b],
            "recommended_id": "opt-2a-max-hogares",
            "candidates_evaluated": 14,
            "candidates_passed": 14,
            "model_execution": {
                "model": "gemini-4-argon",
                "role": "decider",
                "status": "ok",
                "latency_ms": 1720,
                "response_id": "resp-live-fixture-inc2",
                "cached": True,
                "cached_at_utc": "2026-10-24T20:20:00Z",
            },
        },
    )

    # Autonomous countdown 5 -> 0
    for sec_left in [5, 4, 3, 2, 1, 0]:
        emit(
            19.20 + (5 - sec_left) * 0.05,
            1.0,
            {
                "type": "autonomy.countdown",
                "incident_id": "inc-l3-corridor",
                "option_id": "opt-2a-max-hogares",
                "seconds_left": sec_left,
            },
        )

    emit(
        19.50,
        0.1,
        {
            "type": "plan.applied",
            "incident_id": "inc-l3-corridor",
            "option_id": "opt-2a-max-hogares",
            "by": "gemini_autonomous",
        },
    )
    emit(
        19.50,
        0.05,
        {
            "type": "solution.updated",
            "reason": "plan_applied",
            "solution": sol_2a,
            "grid_state": "recuperacion",
        },
    )

    # Hour 22.0 -> Both events end, grid returns to normal
    emit(
        22.0,
        2.0,
        {
            "type": "event.ended",
            "event_id": "ev-gas-centro-outage",
        },
    )
    emit(
        22.0,
        0.05,
        {
            "type": "event.ended",
            "event_id": "ev-l3-outage",
        },
    )
    emit(
        22.0,
        0.05,
        {
            "type": "solution.updated",
            "reason": "event_ended",
            "solution": sol_base,
            "grid_state": "normal",
        },
    )
    emit(
        22.1,
        0.5,
        {
            "type": "agent.note",
            "text_es": strip_digits(
                "Activos restituidos y demanda residencial completamente abastecida; el sistema retorna a estado normal bajo supervisión continua."
            ),
        },
    )

    return events_out


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    events = generate_stream()
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    print(f"Wrote {len(events)} real contract events to {OUT_PATH}")


if __name__ == "__main__":
    main()
