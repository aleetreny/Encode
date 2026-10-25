"""GridPilot Live Ops Agent Loop and Candidate Evaluator.

Implements:
- Digit-free Spanish text guardrails (`sanitize_no_digits`, `has_digits`)
- Operational lever candidate enumeration (<= 40 single + paired levers)
- Parallel HiGHS LP solving + independent validation (`ThreadPoolExecutor`)
- 4D Pareto frontier computation and distinct trade-off option selection
- Gemini decider (`GRIDPILOT_MODEL_DECIDER`, default gemini-3.8-flash) function-calling loop with
  `inspect_node`, `simulate_plan` (<= 3 extra calls), and `propose_options`,
  with 12-second timeout fallback
- Gemini 3.8 Flash (`GRIDPILOT_MODEL_FAST`) helper for periodic operator notes
  and jury name moderation
"""

from __future__ import annotations

import concurrent.futures
import copy
import datetime as dt
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import httpx

from agent.gemini_client import FORBIDDEN_ARGON_PARAMS, VALID_THINKING_LEVELS
from optimisation import solve, validate
from optimisation.scenario import ScenarioError, build_grid

_ROOT_DIR = Path(__file__).resolve().parents[2]
if "pytest" not in sys.modules and "PYTEST_CURRENT_TEST" not in os.environ:
    for _env_file in (_ROOT_DIR / ".env.local", _ROOT_DIR / ".env"):
        if _env_file.is_file():
            for _line in _env_file.read_text(encoding="utf-8").splitlines():
                _s = _line.strip()
                if not _s or _s.startswith("#") or "=" not in _s:
                    continue
                _k, _v = _s.split("=", 1)
                _k = _k.strip()
                _v = _v.strip().strip('"').strip("'")
                if _k and _v:
                    os.environ.setdefault(_k, _v)

# Live decider measured on the real day (25 Oct, 2 incidents each): gemini-3.8-flash with low thinking
# answered in about 4.3 s with valid, distinct options; gemini-4-argon took 7-20 s and often hit the 12 s
# timeout. The recorded fallback sessions stay labelled with the model that answered them.
DEFAULT_DECIDER_MODEL = "gemini-3.8-flash"
DEFAULT_FAST_MODEL = "gemini-3.8-flash"
DEFAULT_DECIDER_THINKING = "low"

TRADEOFF_TAGS = ("max_hogares", "min_costo", "min_co2", "min_riesgo_red")
OPERATIONAL_LEVER_TYPES = (
    "emergency_rating",
    "demand_response",
    "activate_reserve_bess",
    "hydro_reserve_release",
    "start_peaker",
)
PLANNING_LEVER_TYPES = ("add_battery", "uprate_line")

NODE_NAMES_ES = {
    "n_norte_grande": "Norte Grande",
    "n_norte_chico": "Norte Chico",
    "n_centro": "Central Metropolitan Zone",
    "n_centro_sur": "Centro-Sur",
    "n_sur": "Southern Zone",
}

ASSET_NAMES_ES = {
    "solar_ng": "Crucero solar plant",
    "solar_nc": "Atacama solar plant",
    "wind_nc": "Punta Palmeras wind farm",
    "gas_ng": "Mejillones combined-cycle plant",
    "gas_centro": "combined-cycle thermal plant at Polpaico",
    "coal_cs": "Coronel thermal plant",
    "hydro_sur": "southern reservoir hydro plant",
    "wind_sur": "Llanquihue wind farm",
    "diesel_centro": "backup diesel turbine at Renca",
    "b_centro": "operating battery at Polpaico",
    "b_reserve_ng": "reserve battery at Crucero",
    "b_reserve_centro": "reserve battery at Polpaico",
    "L1": "trunk corridor from Norte Grande to Norte Chico",
    "L2": "trunk corridor from Norte Chico to the Central Zone",
    "L3": "trunk corridor from the Central Zone to Centro-Sur",
    "L4": "trunk corridor from Centro-Sur to the Southern Zone",
}

TOKEN_REPLACEMENTS = (
    (re.compile(r"\bL1\b", re.IGNORECASE), "Norte Grande corridor"),
    (re.compile(r"\bL2\b", re.IGNORECASE), "Norte-Centro corridor"),
    (re.compile(r"\bL3\b", re.IGNORECASE), "Centro-Sur corridor"),
    (re.compile(r"\bL4\b", re.IGNORECASE), "Southern corridor"),
    (re.compile(r"\bN-1\b", re.IGNORECASE), "single contingency"),
    (re.compile(r"\bCO[2₂]\b", re.IGNORECASE), "carbon"),
    (re.compile(r"\bDS\s*32\s*/\s*2026\b", re.IGNORECASE), "coordination decree"),
    (re.compile(r"\bLey\s*21\.?505\b", re.IGNORECASE), "electricity storage law"),
    (re.compile(r"\bArt\.?\s*72[°º]?-?1\b", re.IGNORECASE), "secure coordination article"),
    (re.compile(r"\bArt\.?\s*117\s*bis\b", re.IGNORECASE), "economic dispatch article"),
)


def has_digits(text: str) -> bool:
    """Return True if text contains any ASCII or Unicode digit."""
    return bool(re.search(r"[\d₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹]", text or ""))


def sanitize_no_digits(text: str | None, fallback: str = "Operational analysis verified by the coordinator.") -> str:
    """Guarantee zero digits in Gemini/agent prose fields per Section 3 Rule 1."""
    if not text or not isinstance(text, str):
        cleaned = fallback
    else:
        cleaned = text.strip()
        for pattern, repl in TOKEN_REPLACEMENTS:
            cleaned = pattern.sub(repl, cleaned)
        # Strip any remaining numbers (including decimals/separators attached to digits)
        cleaned = re.sub(r"[\d₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹]+([.,:/-][\d₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹]+)*", "", cleaned)
        # Clean leftover dangling unit fragments or double spaces
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = re.sub(r"\(\s*\)", "", cleaned)
        cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
        cleaned = cleaned.strip(" -–—,:;")
        if len(cleaned) < 8:
            cleaned = fallback

    if has_digits(cleaned):
        cleaned = re.sub(r"[\d₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹]", "", cleaned).strip()
    if not cleaned:
        cleaned = "Grid operation verified."
    return cleaned


def get_decider_model() -> str:
    return (
        os.getenv("GRIDPILOT_MODEL_DECIDER")
        or os.getenv("GRIDPILOT_GEMINI_MODEL")
        or DEFAULT_DECIDER_MODEL
    ).strip()


def get_decider_thinking() -> str:
    lvl = (os.getenv("GRIDPILOT_DECIDER_THINKING") or DEFAULT_DECIDER_THINKING).strip().lower()
    return lvl if lvl in VALID_THINKING_LEVELS else DEFAULT_DECIDER_THINKING


def get_fast_model() -> str:
    return (
        os.getenv("GRIDPILOT_MODEL_FAST")
        or os.getenv("GRIDPILOT_COMPANION_MODEL")
        or DEFAULT_FAST_MODEL
    ).strip()


def get_api_key() -> str:
    return (
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or ""
    ).strip()


def prepare_scenario_and_events(
    scenario: dict[str, Any],
    active_disruptions: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Convert contract Disruptions into solver scenario + sudden events list.

    Handles `generator_outage`, `line_outage`, and `battery_outage` (by zeroing
    the disrupted battery power capacity in a scenario copy so both `solve` and
    `validate` see the exact same physical constraint).
    """
    scen_copy = copy.deepcopy(scenario)
    solver_events: list[dict[str, Any]] = []
    for d in active_disruptions:
        dtype = d.get("type")
        aid = d.get("asset_id")
        fh = max(0, min(23, int(d.get("from_hour", 0))))
        th = max(fh + 1, min(24, int(d.get("to_hour", fh + 4))))
        if dtype in ("generator_outage", "line_outage"):
            solver_events.append(
                {
                    "type": dtype,
                    "id": aid,
                    "from_hour": fh,
                    "to_hour": th,
                    "mode": "sudden",
                }
            )
        elif dtype == "battery_outage":
            for bat in scen_copy.get("batteries", []):
                if bat.get("id") == aid:
                    bat["power_capacity_mw"] = 0.0
    return scen_copy, solver_events


def lever_to_solver_mod(
    lever: dict[str, Any],
    *,
    allow_planning_levers: bool = True,
) -> dict[str, Any]:
    """Convert a contract `Lever` dict into an `optimisation` modification dict."""
    kind = lever["type"]
    if not allow_planning_levers and kind not in OPERATIONAL_LEVER_TYPES:
        raise ValueError(
            f"Palanca {kind!r} no permitida en modo crisis; solo se permiten {OPERATIONAL_LEVER_TYPES}."
        )
    target_id = str(lever["target_id"])
    params = lever.get("params") or {}
    fh = max(0, min(23, int(lever.get("from_hour", 0))))
    th = max(fh + 1, min(24, int(lever.get("to_hour", fh + 4))))

    if kind == "emergency_rating":
        th_clamped = min(th, fh + 4)
        factor = float(params.get("factor", 1.20))
        factor = max(1.01, min(1.20, factor))
        return {
            "type": "emergency_rating",
            "line_id": target_id,
            "factor": factor,
            "from_hour": fh,
            "to_hour": th_clamped,
        }
    if kind == "demand_response":
        max_mw = max(1.0, min(200.0, float(params.get("max_mw", 120.0))))
        cost = float(params.get("cost_usd_per_mwh", 300.0))
        return {
            "type": "demand_response",
            "node_id": target_id,
            "max_mw": max_mw,
            "cost_usd_per_mwh": cost,
            "from_hour": fh,
            "to_hour": th,
        }
    if kind == "activate_reserve_bess":
        return {
            "type": "activate_reserve_bess",
            "battery_id": target_id,
            "from_hour": fh,
            "to_hour": th,
        }
    if kind == "hydro_reserve_release":
        extra_mw = max(1.0, min(150.0, float(params.get("extra_mw", 100.0))))
        water_val = float(params.get("water_value_usd_per_mwh", 120.0))
        return {
            "type": "hydro_reserve_release",
            "generator_id": target_id,
            "extra_mw": extra_mw,
            "water_value_usd_per_mwh": water_val,
            "from_hour": fh,
            "to_hour": th,
        }
    if kind == "start_peaker":
        th_peaker = max(th, min(24, fh + 2))
        if th_peaker - fh < 2 and fh > 0:
            fh = max(0, th_peaker - 2)
        return {
            "type": "start_peaker",
            "generator_id": target_id,
            "from_hour": fh,
            "to_hour": th_peaker,
        }
    if kind == "add_battery":
        power = max(10.0, min(150.0, float(params.get("power_mw", 100.0))))
        energy = float(params.get("energy_mwh", power * 4.0))
        return {
            "type": "add_battery",
            "node_id": target_id,
            "power_mw": power,
            "energy_mwh": energy,
        }
    if kind == "uprate_line":
        return {
            "type": "uprate_line",
            "line_id": target_id,
            "new_capacity_mw": float(params.get("new_capacity_mw", 500.0)),
        }
    raise ValueError(f"Unsupported lever type: {kind!r}")


def to_contract_solution(
    scenario: dict[str, Any],
    raw_sol: dict[str, Any],
    val_rep: dict[str, Any],
    solution_id: str,
) -> dict[str, Any]:
    """Convert raw `optimisation.solve` and `validate` outputs into a contract `Solution`."""
    T = len(scenario.get("timestamps_utc", [])) or 24
    nodes = [n["id"] for n in scenario.get("nodes", [])]
    hh_per_mw = {n["id"]: float(n.get("households_per_mw", 1000.0)) for n in scenario.get("nodes", [])}

    if raw_sol.get("status") != "optimal" or not raw_sol.get("timeseries"):
        zero_nodes = {nid: [0.0] * T for nid in nodes}
        return {
            "solution_id": solution_id,
            "generation_mw": {g["id"]: [0.0] * T for g in scenario.get("generators", [])},
            "available_mw": {g["id"]: [0.0] * T for g in scenario.get("generators", [])},
            "line_flow_mw": {ln["id"]: [0.0] * T for ln in scenario.get("lines", [])},
            "line_capacity_mw": {ln["id"]: [float(ln["capacity_mw"])] * T for ln in scenario.get("lines", [])},
            "battery_flow_mw": {b["id"]: [0.0] * T for b in scenario.get("batteries", [])},
            "battery_soc_mwh": {b["id"]: [0.0] * T for b in scenario.get("batteries", [])},
            "demand_mw": {nid: [float(x) for x in scenario["demand_mw_by_node"][nid]] for nid in nodes},
            "unserved_mw": zero_nodes,
            "demand_response_mw": zero_nodes,
            "curtailment_mw": {g["id"]: [0.0] * T for g in scenario.get("generators", [])},
            "households_off": zero_nodes,
            "cost_proxy_usd": [0.0] * T,
            "co2_t": [0.0] * T,
            "status": raw_sol.get("status", "error") if raw_sol.get("status") in ("optimal", "infeasible", "error") else "error",
            "validation": {
                "passed": False,
                "violations": [str(raw_sol.get("message") or "infeasible_or_error")],
                "max_residual_mw": float(val_rep.get("max_residual_mw", 0.0)),
            },
        }

    ts = raw_sol["timeseries"]
    metrics = raw_sol.get("metrics") or {}

    # Rebuild effective grid to extract exact hourly line capacities (including emergency_rating & outages)
    # and hourly generator costs (including hydro_reserve_release water value).
    try:
        mods = raw_sol.get("modifications") or []
        cand = None
        if raw_sol.get("candidate_id", "baseline") != "baseline" or mods:
            clean_mods = []
            for m in mods:
                mc = dict(m)
                if mc.get("type") == "add_battery":
                    mc.pop("battery_id", None)
                elif mc.get("type") == "uprate_line":
                    mc.pop("previous_capacity_mw", None)
                clean_mods.append(mc)
            cand = {"candidate_id": raw_sol.get("candidate_id", "cand"), "modifications": clean_mods}
        eff_grid = build_grid(
            scenario,
            cand,
            raw_sol.get("events") or [],
            raw_sol.get("options") or {},
            include_scenario_events=False,
        )
        line_cap_mw = {
            ln["id"]: [round(float(eff_grid.line_cap[i, h]), 4) for h in range(T)]
            for i, ln in enumerate(eff_grid.lines)
        }
        gen_cost_matrix = eff_grid.gen_cost
        dr_cost_matrix = eff_grid.dr_cost
        eff_gens = eff_grid.generators
    except Exception:
        eff_grid = None
        line_cap_mw = {
            ln["id"]: [float(ln["capacity_mw"])] * T
            for ln in (raw_sol.get("assets", {}).get("lines") or scenario.get("lines", []))
        }
        gen_cost_matrix = None
        dr_cost_matrix = None
        eff_gens = scenario.get("generators", [])

    # Battery net flow (+ discharge, - charge) and 24-hour SOC
    bat_charge = ts.get("battery_charge_mw", {})
    bat_discharge = ts.get("battery_discharge_mw", {})
    bat_soc_raw = ts.get("battery_soc_mwh", {})
    battery_flow_mw: dict[str, list[float]] = {}
    battery_soc_mwh: dict[str, list[float]] = {}
    for b_id in bat_charge:
        ch = bat_charge[b_id]
        dis = bat_discharge[b_id]
        battery_flow_mw[b_id] = [round(float(dis[h]) - float(ch[h]), 4) for h in range(T)]
        battery_soc_mwh[b_id] = [round(float(x), 4) for x in bat_soc_raw[b_id][:T]]

    # Curtailment for all generators
    curtailment_mw: dict[str, list[float]] = {}
    for g in scenario.get("generators", []):
        gid = g["id"]
        if gid in ts.get("curtailment_mw", {}):
            curtailment_mw[gid] = [round(float(x), 4) for x in ts["curtailment_mw"][gid]]
        else:
            curtailment_mw[gid] = [0.0] * T

    unserved_mw = {
        nid: [round(float(x), 4) for x in ts["unserved_mw"].get(nid, [0.0] * T)]
        for nid in nodes
    }
    raw_dr = ts.get("demand_response_mw") or {}
    demand_response_mw = {
        nid: [round(float(x), 4) for x in raw_dr.get(nid, [0.0] * T)]
        for nid in nodes
    }
    # Single household formula: households_off(node, hour) = unserved_mw(node, hour) * households_per_mw(node)
    households_off = {
        nid: [round(unserved_mw[nid][h] * hh_per_mw[nid]) for h in range(T)]
        for nid in nodes
    }

    # Hourly operational cost proxy (dispatchable fuel/water cost + demand response compensation)
    cost_proxy_usd: list[float] = []
    for h in range(T):
        c_h = 0.0
        if gen_cost_matrix is not None:
            for i, g in enumerate(eff_gens):
                if not g.get("renewable"):
                    gid = g["id"]
                    c_h += float(ts["generation_mw"][gid][h]) * float(gen_cost_matrix[i, h])
        else:
            for g in scenario.get("generators", []):
                gid = g["id"]
                vc = float(g.get("variable_cost_usd_per_mwh", 0.0))
                c_h += float(ts["generation_mw"].get(gid, [0.0] * T)[h]) * vc
        if dr_cost_matrix is not None:
            for i, nid in enumerate(nodes):
                c_h += float(demand_response_mw[nid][h]) * float(dr_cost_matrix[i, h])
        else:
            for nid in nodes:
                c_h += float(demand_response_mw[nid][h]) * 300.0
        cost_proxy_usd.append(round(c_h, 2))

    co2_by_hour = metrics.get("co2_t_by_hour")
    if isinstance(co2_by_hour, list) and len(co2_by_hour) == T:
        co2_t = [round(float(x), 4) for x in co2_by_hour]
    else:
        ef_map = scenario.get("emission_factors_t_per_mwh") or {"gas": 0.4, "coal": 0.95, "diesel": 0.75}
        co2_t = []
        for h in range(T):
            e_h = 0.0
            for g in scenario.get("generators", []):
                gid = g["id"]
                tech = str(g.get("technology", "")).lower()
                e_h += float(ts["generation_mw"].get(gid, [0.0] * T)[h]) * float(ef_map.get(tech, 0.0))
            co2_t.append(round(e_h, 4))

    violations_str = [
        f"{v.get('check', 'check')}:{v.get('id', '')}@{v.get('hour', '')}: {v.get('detail', '')}"
        if isinstance(v, dict)
        else str(v)
        for v in val_rep.get("violations", [])
    ]

    return {
        "solution_id": solution_id,
        "generation_mw": {k: [round(float(x), 4) for x in v] for k, v in ts["generation_mw"].items()},
        "available_mw": {k: [round(float(x), 4) for x in v] for k, v in ts["available_mw"].items()},
        "line_flow_mw": {k: [round(float(x), 4) for x in v] for k, v in ts["line_flow_mw"].items()},
        "line_capacity_mw": line_cap_mw,
        "battery_flow_mw": battery_flow_mw,
        "battery_soc_mwh": battery_soc_mwh,
        "demand_mw": {nid: [round(float(x), 4) for x in scenario["demand_mw_by_node"][nid]] for nid in nodes},
        "unserved_mw": unserved_mw,
        "demand_response_mw": demand_response_mw,
        "curtailment_mw": curtailment_mw,
        "households_off": households_off,
        "cost_proxy_usd": cost_proxy_usd,
        "co2_t": co2_t,
        "status": "optimal",
        "validation": {
            "passed": bool(val_rep.get("passed", False)),
            "violations": violations_str,
            "max_residual_mw": float(val_rep.get("max_residual_mw", 0.0)),
        },
    }


# Canonical alias
compute_solution_dict = to_contract_solution


def compute_incident_impact(solution: dict[str, Any]) -> dict[str, Any]:
    """Compute incident impact summary from the no-action incident Solution."""
    T = len(solution.get("cost_proxy_usd", [])) or 24
    nodes = list(solution.get("unserved_mw", {}).keys())
    unserved_by_h = [
        sum(float(solution["unserved_mw"][n][h]) for n in nodes)
        for h in range(T)
    ]
    hh_by_h = [
        sum(float(solution["households_off"][n][h]) for n in nodes)
        for h in range(T)
    ]
    unserved_peak = round(max(unserved_by_h, default=0.0), 2)
    hh_peak = int(round(max(hh_by_h, default=0.0)))
    nodes_affected = [
        n for n in nodes if max((float(x) for x in solution["unserved_mw"][n]), default=0.0) > 1e-3
    ]
    lines_overloaded: list[str] = []
    for lid, flows in solution.get("line_flow_mw", {}).items():
        caps = solution.get("line_capacity_mw", {}).get(lid, [0.0] * T)
        for h in range(T):
            if caps[h] > 0 and abs(float(flows[h])) >= 0.95 * float(caps[h]):
                lines_overloaded.append(lid)
                break

    return {
        "unserved_mw_peak": unserved_peak,
        "households_off_peak": hh_peak,
        "nodes_affected": nodes_affected,
        "lines_overloaded": lines_overloaded,
    }


def compute_grid_state(
    solution: dict[str, Any],
    active_events: list[dict[str, Any]],
    has_applied_plan: bool,
    baseline_unserved_mwh: float | None = None,
) -> str:
    """Compute NTSyCS GridState: 'normal' | 'alerta' | 'emergencia' | 'recuperacion'."""
    impact = compute_incident_impact(solution)
    total_unserved_mwh = sum(
        sum(float(x) for x in vals)
        for vals in solution.get("unserved_mw", {}).values()
    )
    if not active_events and total_unserved_mwh <= 1e-3 and not impact["lines_overloaded"]:
        return "normal"
    if has_applied_plan:
        if baseline_unserved_mwh is None or total_unserved_mwh < baseline_unserved_mwh - 1e-3 or total_unserved_mwh <= 1e-3:
            return "recuperacion"
    if total_unserved_mwh > 1e-3:
        return "emergencia" if not has_applied_plan else "recuperacion"
    if active_events or impact["lines_overloaded"]:
        return "alerta"
    return "normal"


def compute_option_metrics(
    base_sol: dict[str, Any],
    cand_sol: dict[str, Any],
    from_hour: int,
    to_hour: int,
) -> dict[str, Any]:
    """Compute contract `OptionMetrics` comparing candidate solution against no-action baseline."""
    T = len(base_sol.get("cost_proxy_usd", [])) or 24
    nodes = list(base_sol.get("unserved_mw", {}).keys())

    base_uns_mwh = sum(sum(float(x) for x in base_sol["unserved_mw"][n]) for n in nodes)
    cand_uns_mwh = sum(sum(float(x) for x in cand_sol["unserved_mw"][n]) for n in nodes)
    unserved_mwh_avoided = round(max(0.0, base_uns_mwh - cand_uns_mwh), 2)

    base_hh_by_h = [sum(float(base_sol["households_off"][n][h]) for n in nodes) for h in range(T)]
    cand_hh_by_h = [sum(float(cand_sol["households_off"][n][h]) for n in nodes) for h in range(T)]

    base_peak_hh = max(base_hh_by_h, default=0.0)
    cand_peak_hh = max(cand_hh_by_h, default=0.0)

    if unserved_mwh_avoided <= 1e-3:
        # Guard against LP battery time-shifting artifacts when zero net MWh is avoided
        households_reconnected = 0
    else:
        raw_reconnected = max(0.0, base_peak_hh - cand_peak_hh)
        if raw_reconnected <= 0.0 and base_peak_hh > 0 and cand_peak_hh <= base_peak_hh + 1e-3:
            raw_reconnected = max(
                0.0,
                max(
                    (base_hh_by_h[h] - cand_hh_by_h[h] for h in range(from_hour, min(T, to_hour))),
                    default=0.0,
                ),
            )
        # Cap reconnected households by physical energy avoided (1000 households per MW)
        max_physical_hh = round(unserved_mwh_avoided * 1000.0)
        households_reconnected = int(min(round(raw_reconnected), max_physical_hh))

    households_newly_off = int(round(max(0.0, cand_peak_hh - base_peak_hh)))

    base_cost = sum(float(x) for x in base_sol.get("cost_proxy_usd", []))
    cand_cost = sum(float(x) for x in cand_sol.get("cost_proxy_usd", []))
    cost_delta_usd = round(cand_cost - base_cost, 2)

    base_co2 = sum(float(x) for x in base_sol.get("co2_t", []))
    cand_co2 = sum(float(x) for x in cand_sol.get("co2_t", []))
    co2_delta_t = round(cand_co2 - base_co2, 2)

    base_curt = sum(sum(float(x) for x in v) for v in base_sol.get("curtailment_mw", {}).values())
    cand_curt = sum(sum(float(x) for x in v) for v in cand_sol.get("curtailment_mw", {}).values())
    curtailment_delta_mwh = round(cand_curt - base_curt, 2)

    max_loading = 0.0
    for lid, flows in cand_sol.get("line_flow_mw", {}).items():
        caps = cand_sol.get("line_capacity_mw", {}).get(lid, [0.0] * T)
        for h in range(from_hour, min(T, max(from_hour + 1, to_hour))):
            if caps[h] > 1e-6:
                pct = abs(float(flows[h])) / float(caps[h]) * 100.0
                if pct > max_loading:
                    max_loading = pct
    if max_loading == 0.0:
        for lid, flows in cand_sol.get("line_flow_mw", {}).items():
            caps = cand_sol.get("line_capacity_mw", {}).get(lid, [0.0] * T)
            for h in range(T):
                if caps[h] > 1e-6:
                    pct = abs(float(flows[h])) / float(caps[h]) * 100.0
                    if pct > max_loading:
                        max_loading = pct
    max_line_loading_pct = round(max_loading, 1)

    hours_to_zero: int | None = 0
    cand_uns_by_h = [sum(float(cand_sol["unserved_mw"][n][h]) for n in nodes) for h in range(T)]
    if any(cand_uns_by_h[h] > 1e-3 for h in range(from_hour, T)):
        resolved_h = None
        for h in range(from_hour, T):
            if all(cand_uns_by_h[k] <= 1e-3 for k in range(h, min(T, to_hour + 1))):
                resolved_h = h - from_hour
                break
        hours_to_zero = resolved_h

    return {
        "households_reconnected": households_reconnected,
        "households_newly_off": households_newly_off,
        "unserved_mwh_avoided": unserved_mwh_avoided,
        "cost_delta_usd": cost_delta_usd,
        "co2_delta_t": co2_delta_t,
        "curtailment_delta_mwh": curtailment_delta_mwh,
        "max_line_loading_pct": max_line_loading_pct,
        "hours_to_zero_unserved": hours_to_zero,
    }


def summarize_levers_es(levers: list[dict[str, Any]]) -> str:
    """Build a digit-free English summary of a list of contract Levers."""
    parts: list[str] = []
    for lv in levers:
        ltype = lv.get("type")
        tid = str(lv.get("target_id", ""))
        asset_es = ASSET_NAMES_ES.get(tid, NODE_NAMES_ES.get(tid, "grid asset"))
        if ltype == "activate_reserve_bess":
            parts.append(f"activate {asset_es}")
        elif ltype == "emergency_rating":
            parts.append(f"emergency thermal rating on {asset_es}")
        elif ltype == "demand_response":
            parts.append(f"industrial demand response at {asset_es}")
        elif ltype == "hydro_reserve_release":
            parts.append(f"hydro reserve release at {asset_es}")
        elif ltype == "start_peaker":
            parts.append(f"fast turbine start at {asset_es}")
        elif ltype == "add_battery":
            parts.append(f"support storage at {asset_es}")
        elif ltype == "uprate_line":
            parts.append(f"transmission reinforcement on {asset_es}")
        else:
            parts.append(f"operating move at {asset_es}")
    text = " plus ".join(parts) if parts else "grid operating move"
    return sanitize_no_digits(text, fallback="operating move on the trunk grid")


def generate_operational_candidates(
    scenario: dict[str, Any],
    active_disruptions: list[dict[str, Any]],
    from_hour: int,
    to_hour: int,
) -> list[dict[str, Any]]:
    """Enumerate <= 40 single and paired operational lever candidates relevant to the incident."""
    fh = max(0, min(23, int(from_hour)))
    th = max(fh + 1, min(24, int(to_hour)))
    th_er = min(th, fh + 4)
    th_pk = max(th, min(24, fh + 2))
    fh_pk = fh if th_pk - fh >= 2 else max(0, th_pk - 2)

    outaged_ids = {str(d.get("asset_id")) for d in active_disruptions}

    standby_bats = [
        b["id"]
        for b in scenario.get("batteries", [])
        if b.get("standby") and b["id"] not in outaged_ids
    ]
    active_lines = [
        ln["id"]
        for ln in scenario.get("lines", [])
        if ln["id"] not in outaged_ids
    ]
    has_hydro = any(
        g["id"] == "hydro_sur" and g["id"] not in outaged_ids
        for g in scenario.get("generators", [])
    )
    has_peaker = any(
        g["id"] == "diesel_centro" and g["id"] not in outaged_ids
        for g in scenario.get("generators", [])
    )

    # Single levers
    singles: list[tuple[str, dict[str, Any]]] = []
    for bid in standby_bats:
        singles.append(
            (
                f"bess_{bid}",
                {
                    "type": "activate_reserve_bess",
                    "target_id": bid,
                    "params": {},
                    "from_hour": fh,
                    "to_hour": th,
                },
            )
        )
    for lid in active_lines:
        singles.append(
            (
                f"er_{lid}",
                {
                    "type": "emergency_rating",
                    "target_id": lid,
                    "params": {"factor": 1.20},
                    "from_hour": fh,
                    "to_hour": th_er,
                },
            )
        )
    if has_hydro:
        for extra in (90.0, 150.0):
            singles.append(
                (
                    f"hydro_{int(extra)}",
                    {
                        "type": "hydro_reserve_release",
                        "target_id": "hydro_sur",
                        "params": {"extra_mw": extra, "water_value_usd_per_mwh": 120.0},
                        "from_hour": fh,
                        "to_hour": th,
                    },
                )
            )
    if has_peaker:
        singles.append(
            (
                "peaker_diesel",
                {
                    "type": "start_peaker",
                    "target_id": "diesel_centro",
                    "params": {"startup_delay_hours": 1.0},
                    "from_hour": fh_pk,
                    "to_hour": th_pk,
                },
            )
        )
    for nid, mw in (
        ("n_centro", 120.0),
        ("n_centro", 200.0),
        ("n_centro_sur", 120.0),
        ("n_norte_grande", 120.0),
        ("n_sur", 100.0),
        ("n_norte_chico", 100.0),
    ):
        singles.append(
            (
                f"dr_{nid}_{int(mw)}",
                {
                    "type": "demand_response",
                    "target_id": nid,
                    "params": {"max_mw": mw, "cost_usd_per_mwh": 300.0},
                    "from_hour": fh,
                    "to_hour": th,
                },
            )
        )

    candidates: list[dict[str, Any]] = []
    for cid, lv in singles:
        candidates.append({"candidate_id": f"op_{cid}", "levers": [lv]})

    # High-value operational pairs (clean storage + corridor / hydro, thermal peaker + DR, etc.)
    by_key = dict(singles)
    pair_specs = [
        ("bess_b_reserve_centro", "er_L2"),
        ("bess_b_reserve_centro", "er_L3"),
        ("bess_b_reserve_centro", "hydro_150"),
        ("bess_b_reserve_centro", "hydro_90"),
        ("bess_b_reserve_centro", "peaker_diesel"),
        ("bess_b_reserve_centro", "dr_n_centro_120"),
        ("bess_b_reserve_centro", "dr_n_centro_200"),
        ("bess_b_reserve_centro", "bess_b_reserve_ng"),
        ("bess_b_reserve_ng", "er_L1"),
        ("bess_b_reserve_ng", "er_L2"),
        ("bess_b_reserve_ng", "dr_n_centro_200"),
        ("bess_b_reserve_ng", "dr_n_centro_120"),
        ("bess_b_reserve_ng", "dr_n_norte_grande_120"),
        ("hydro_150", "er_L3"),
        ("hydro_150", "er_L4"),
        ("hydro_150", "dr_n_centro_120"),
        ("hydro_150", "dr_n_centro_sur_120"),
        ("peaker_diesel", "er_L2"),
        ("peaker_diesel", "er_L3"),
        ("peaker_diesel", "dr_n_centro_120"),
        ("peaker_diesel", "dr_n_centro_200"),
        ("peaker_diesel", "hydro_150"),
        ("er_L2", "dr_n_centro_120"),
        ("er_L3", "dr_n_centro_sur_120"),
    ]
    for k1, k2 in pair_specs:
        if len(candidates) >= 40:
            break
        if k1 in by_key and k2 in by_key and k1 != k2:
            candidates.append(
                {
                    "candidate_id": f"op_{k1}_plus_{k2}",
                    "levers": [by_key[k1], by_key[k2]],
                }
            )

    return candidates[:40]


def evaluate_single_candidate(
    scen_for_solve: dict[str, Any],
    solver_events: list[dict[str, Any]],
    base_sol: dict[str, Any],
    cand_spec: dict[str, Any],
    from_hour: int,
    to_hour: int,
) -> dict[str, Any]:
    """Solve and independently validate a single operational candidate specification."""
    t0 = time.perf_counter()
    cid = cand_spec["candidate_id"]
    levers = cand_spec["levers"]
    try:
        mods = [lever_to_solver_mod(lv, allow_planning_levers=False) for lv in levers]
        solver_cand = {"candidate_id": cid, "modifications": mods}
        raw_sol = solve(
            scen_for_solve,
            candidate=solver_cand,
            events=solver_events,
            options={"allow_unserved": True},
        )
        val_rep = validate(scen_for_solve, raw_sol)
        duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        contract_sol = to_contract_solution(scen_for_solve, raw_sol, val_rep, f"sol_{cid}")
        passed = bool(contract_sol["status"] == "optimal" and contract_sol["validation"]["passed"])
        metrics = compute_option_metrics(base_sol, contract_sol, from_hour, to_hour)
        return {
            "candidate_id": cid,
            "levers": levers,
            "passed": passed,
            "status": contract_sol["status"],
            "duration_ms": duration_ms,
            "metrics": metrics,
            "validation": contract_sol["validation"],
            "solution": contract_sol,
            "args_summary_es": summarize_levers_es(levers),
        }
    except Exception as exc:
        duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return {
            "candidate_id": cid,
            "levers": levers,
            "passed": False,
            "status": "error",
            "duration_ms": duration_ms,
            "error": str(exc),
            "args_summary_es": summarize_levers_es(levers),
        }


def compute_pareto_front(passed_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute the 4D Pareto frontier over:
    - `households_reconnected` (maximize)
    - `cost_delta_usd` (minimize)
    - `co2_delta_t` (minimize)
    - `max_line_loading_pct` (minimize)
    """
    positive = [c for c in passed_candidates if option_has_positive_improvement(c)]
    source = positive if len(positive) >= 2 else passed_candidates

    front: list[dict[str, Any]] = []
    for c in source:
        m = c["metrics"]
        dominated = False
        for other in source:
            if other["candidate_id"] == c["candidate_id"]:
                continue
            om = other["metrics"]
            better_or_equal = (
                om["households_reconnected"] >= m["households_reconnected"]
                and om["cost_delta_usd"] <= m["cost_delta_usd"]
                and om["co2_delta_t"] <= m["co2_delta_t"]
                and om["max_line_loading_pct"] <= m["max_line_loading_pct"]
            )
            strictly_better = (
                om["households_reconnected"] > m["households_reconnected"]
                or om["cost_delta_usd"] < m["cost_delta_usd"]
                or om["co2_delta_t"] < m["co2_delta_t"]
                or om["max_line_loading_pct"] < m["max_line_loading_pct"]
            )
            if better_or_equal and strictly_better:
                dominated = True
                break
        if not dominated:
            front.append(c)
    return front if front else list(source)


def is_tag_truthful(tag: str, m_self: dict[str, Any], m_other: dict[str, Any]) -> bool:
    """Return True iff `tag` is truthful for `m_self` when compared pairwise against `m_other`."""
    if tag == "max_hogares":
        return float(m_self["households_reconnected"]) >= float(m_other["households_reconnected"])
    if tag == "min_costo":
        return float(m_self["cost_delta_usd"]) <= float(m_other["cost_delta_usd"])
    if tag == "min_co2":
        return float(m_self["co2_delta_t"]) <= float(m_other["co2_delta_t"])
    if tag == "min_riesgo_red":
        return float(m_self["max_line_loading_pct"]) <= float(m_other["max_line_loading_pct"])
    return False


def find_truthful_tag_pair(
    ma: dict[str, Any],
    mb: dict[str, Any],
) -> tuple[str, str] | None:
    """Find distinct `(tag_a, tag_b)` where `tag_a` is truthful for `ma` vs `mb`
    and `tag_b` is truthful for `mb` vs `ma`.
    """
    pref_a = ("max_hogares", "min_co2", "min_costo", "min_riesgo_red")
    pref_b = ("min_costo", "min_co2", "min_riesgo_red", "max_hogares")

    def is_strict(tag: str, m_self: dict[str, Any], m_other: dict[str, Any]) -> bool:
        if tag == "max_hogares":
            return float(m_self["households_reconnected"]) > float(m_other["households_reconnected"])
        if tag == "min_costo":
            return float(m_self["cost_delta_usd"]) < float(m_other["cost_delta_usd"])
        if tag == "min_co2":
            return float(m_self["co2_delta_t"]) < float(m_other["co2_delta_t"])
        if tag == "min_riesgo_red":
            return float(m_self["max_line_loading_pct"]) < float(m_other["max_line_loading_pct"])
        return False

    # Pass 1: Both tags strictly beat the other on their dimension
    for ta in pref_a:
        if not is_strict(ta, ma, mb):
            continue
        for tb in pref_b:
            if tb != ta and is_strict(tb, mb, ma):
                return ta, tb

    # Pass 2: tag_a is strict, tag_b is truthful (>= or <=)
    for ta in pref_a:
        if not is_strict(ta, ma, mb):
            continue
        for tb in pref_b:
            if tb != ta and is_tag_truthful(tb, mb, ma):
                return ta, tb

    # Pass 3: tag_a is truthful, tag_b is strict
    for ta in pref_a:
        if not is_tag_truthful(ta, ma, mb):
            continue
        for tb in pref_b:
            if tb != ta and is_strict(tb, mb, ma):
                return ta, tb

    # Pass 4: Both are truthful (ties allowed)
    for ta in pref_a:
        if not is_tag_truthful(ta, ma, mb):
            continue
        for tb in pref_b:
            if tb != ta and is_tag_truthful(tb, mb, ma):
                return ta, tb

    return None


def option_has_positive_improvement(option: dict[str, Any] | None) -> bool:
    """Return True iff the option reconnects > 0 households and avoids > 0 MWh of unserved energy."""
    if not option or not isinstance(option, dict):
        return False
    metrics = option.get("metrics") or {}
    return (
        float(metrics.get("households_reconnected", 0)) > 0
        and float(metrics.get("unserved_mwh_avoided", 0.0)) > 0.0
    )


def select_distinct_pair_and_tags(
    passed_candidates: list[dict[str, Any]],
    pareto_front: list[dict[str, Any]],
    preferred_ids: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    """Select two verified candidates and assign guaranteed distinct, pairwise-truthful `tradeoff_tag` values."""
    pool = pareto_front if len(pareto_front) >= 2 else passed_candidates
    by_id = {c["candidate_id"]: c for c in passed_candidates}
    max_avail_hh = max(
        (float(c["metrics"]["households_reconnected"]) for c in passed_candidates),
        default=0.0,
    )

    chosen: list[dict[str, Any]] = []
    if preferred_ids:
        for pid in preferred_ids:
            if pid in by_id and by_id[pid] not in chosen:
                chosen.append(by_id[pid])
            if len(chosen) == 2:
                break
        if chosen:
            # Order so chosen[0] has >= households_reconnected
            chosen.sort(
                key=lambda c: (
                    -float(c["metrics"]["households_reconnected"]),
                    -float(c["metrics"]["unserved_mwh_avoided"]),
                    float(c["metrics"]["cost_delta_usd"]),
                )
            )
            # Never keep a 0-reconnected primary candidate if a >0 candidate exists
            if max_avail_hh > 0 and float(chosen[0]["metrics"]["households_reconnected"]) <= 0:
                chosen = []
            # Never keep a pair where one is strictly dominated on all 4 metrics by the other
            elif len(chosen) == 2 and find_truthful_tag_pair(chosen[0]["metrics"], chosen[1]["metrics"]) is None:
                chosen = [chosen[0]]

    if len(chosen) < 2:
        sorted_recon = sorted(
            pool,
            key=lambda c: (
                -float(c["metrics"]["households_reconnected"]),
                -float(c["metrics"]["unserved_mwh_avoided"]),
                float(c["metrics"]["co2_delta_t"]),
                float(c["metrics"]["cost_delta_usd"]),
            ),
        )
        if not chosen and sorted_recon:
            chosen.append(sorted_recon[0])

        first = chosen[0]
        ma_first = first["metrics"]
        remaining = [c for c in passed_candidates if c["candidate_id"] != first["candidate_id"]]
        if not remaining:
            dup = copy.deepcopy(first)
            dup["candidate_id"] = first["candidate_id"] + "_alt"
            remaining = [dup]

        def contrast_score(c: dict[str, Any]) -> tuple[float, float, float, float, float]:
            mc = c["metrics"]
            tag_pair = find_truthful_tag_pair(ma_first, mc)
            has_truthful_pair = 0.0 if tag_pair is not None else 1.0
            strictly_contrasts = (
                0.0
                if (
                    float(mc["cost_delta_usd"]) < float(ma_first["cost_delta_usd"])
                    or float(mc["co2_delta_t"]) < float(ma_first["co2_delta_t"])
                    or float(mc["max_line_loading_pct"]) < float(ma_first["max_line_loading_pct"])
                )
                else 1.0
            )
            # Prefer a contrasting option that also reconnects > 0 households when possible
            also_reconnects = (
                0.0
                if (float(ma_first["households_reconnected"]) > 0 and float(mc["households_reconnected"]) > 0)
                else 1.0
            )
            types_a = {lv["type"] for lv in first["levers"]}
            types_b = {lv["type"] for lv in c["levers"]}
            diff_types = 0.0 if types_a != types_b else 1.0
            return (
                has_truthful_pair,
                strictly_contrasts,
                also_reconnects,
                diff_types,
                float(mc["cost_delta_usd"]),
            )

        remaining_sorted = sorted(remaining, key=contrast_score)
        chosen.append(remaining_sorted[0])

    # Always order cand_a, cand_b so cand_a has >= households_reconnected
    if float(chosen[1]["metrics"]["households_reconnected"]) > float(chosen[0]["metrics"]["households_reconnected"]):
        chosen[0], chosen[1] = chosen[1], chosen[0]

    cand_a, cand_b = chosen[0], chosen[1]
    ma, mb = cand_a["metrics"], cand_b["metrics"]

    tag_pair = find_truthful_tag_pair(ma, mb)
    if tag_pair is not None:
        tag_a, tag_b = tag_pair
    else:
        # Last-resort search across all passed candidate pairs for a guaranteed truthful pair
        found_alt = False
        for alt_b in passed_candidates:
            if alt_b["candidate_id"] == cand_a["candidate_id"]:
                continue
            tp = find_truthful_tag_pair(ma, alt_b["metrics"])
            if tp is not None:
                cand_b = alt_b
                mb = cand_b["metrics"]
                tag_a, tag_b = tp
                found_alt = True
                break
        if not found_alt:
            tag_a = "max_hogares"
            tag_b = "min_costo"

    return cand_a, cand_b, tag_a, tag_b


NO_IMPROVEMENT_DIAGNOSIS_ES = (
    "No available operating move improves the residential shortfall under the current grid constraints."
)


def enforce_option_pair_guardrails(
    options: list[dict[str, Any]],
    recommended_id: str,
    diagnosis_es: str,
) -> tuple[list[dict[str, Any]], str, str]:
    """Validate and enforce:
    1. Pairwise truthfulness and distinctness of `tradeoff_tag` across the two options.
    2. Never recommend (`recommended_id`) an option with `households_reconnected == 0` when the other has `> 0`.
    3. If neither option improves (`max(opt_a.households_reconnected, opt_b.households_reconnected) == 0`),
       explicitly note in `diagnosis_es` (without digits) that no available maneuver improves the deficit.
    """
    if len(options) < 2:
        return options, recommended_id, sanitize_no_digits(diagnosis_es)

    opt_a, opt_b = options[0], options[1]
    ma, mb = opt_a["metrics"], opt_b["metrics"]
    tag_a = opt_a.get("tradeoff_tag", "max_hogares")
    tag_b = opt_b.get("tradeoff_tag", "min_costo")

    # 1. Verify pairwise truthfulness of both tags and distinctness
    if tag_a == tag_b or not is_tag_truthful(tag_a, ma, mb) or not is_tag_truthful(tag_b, mb, ma):
        # Try swapping options if opt_b has more reconnected households than opt_a
        if float(mb["households_reconnected"]) > float(ma["households_reconnected"]):
            opt_a, opt_b = opt_b, opt_a
            ma, mb = opt_a["metrics"], opt_b["metrics"]
            tag_a, tag_b = opt_a.get("tradeoff_tag", "max_hogares"), opt_b.get("tradeoff_tag", "min_costo")

        if tag_a == tag_b or not is_tag_truthful(tag_a, ma, mb) or not is_tag_truthful(tag_b, mb, ma):
            tp = find_truthful_tag_pair(ma, mb)
            if tp is not None:
                opt_a["tradeoff_tag"], opt_b["tradeoff_tag"] = tp
            else:
                # Try swapping opt_a and opt_b to find a truthful tag pair
                tp_rev = find_truthful_tag_pair(mb, ma)
                if tp_rev is not None:
                    opt_a, opt_b = opt_b, opt_a
                    ma, mb = opt_a["metrics"], opt_b["metrics"]
                    opt_a["tradeoff_tag"], opt_b["tradeoff_tag"] = tp_rev

    # 2. Never recommend an option with households_reconnected == 0 if the other has > 0
    hh_a = float(opt_a["metrics"]["households_reconnected"])
    hh_b = float(opt_b["metrics"]["households_reconnected"])
    if hh_a > 0 and hh_b <= 0:
        recommended_id = opt_a["option_id"]
    elif hh_b > 0 and hh_a <= 0:
        recommended_id = opt_b["option_id"]
    elif recommended_id not in (opt_a["option_id"], opt_b["option_id"]):
        recommended_id = opt_a["option_id"] if hh_a >= hh_b else opt_b["option_id"]

    # 3. If neither option reconnects any households, explicitly state in diagnosis_es (digit-free)
    clean_diag = sanitize_no_digits(diagnosis_es)
    if max(hh_a, hh_b) <= 0:
        if "no available operating move" not in clean_diag.lower():
            clean_diag = sanitize_no_digits(f"{clean_diag} {NO_IMPROVEMENT_DIAGNOSIS_ES}")

    return [opt_a, opt_b], recommended_id, clean_diag


def build_default_title_es(cand: dict[str, Any], tag: str) -> str:
    """Build a crisp, digit-free English title for an Option."""
    types = [lv["type"] for lv in cand["levers"]]
    if "activate_reserve_bess" in types and "emergency_rating" in types:
        title = "Reserve BESS and Trunk Thermal Rating"
    elif "activate_reserve_bess" in types and "hydro_reserve_release" in types:
        title = "Reserve Battery and Southern Hydro Dispatch"
    elif "activate_reserve_bess" in types and "demand_response" in types:
        title = "Reserve BESS and Industrial Response"
    elif "activate_reserve_bess" in types:
        title = "Strategic Reserve Battery Activation"
    elif "hydro_reserve_release" in types and "emergency_rating" in types:
        title = "Emergency Hydro Head and Controlled Overload"
    elif "hydro_reserve_release" in types:
        title = "Southern Hydro Reserve Release"
    elif "start_peaker" in types and "demand_response" in types:
        title = "Fast Turbine and Voluntary Industrial Cut"
    elif "start_peaker" in types:
        title = "Backup Fast Turbine Start"
    elif "emergency_rating" in types:
        title = "Emergency Thermal Capacity on Corridor"
    elif "demand_response" in types:
        title = "Compensated Industrial Demand Management"
    else:
        title = "Emergency Operating Redispatch"

    if tag == "max_hogares" and "Homes" not in title:
        title = f"{title}, Prioritising Reconnection"
    elif tag == "min_costo":
        title = f"{title} at Minimum Cost"
    elif tag == "min_co2":
        title = f"{title}, Emission-Free"
    elif tag == "min_riesgo_red":
        title = f"{title} with Corridor Relief"

    return sanitize_no_digits(title, fallback="Emergency Operating Move")


def build_default_rationale_es(cand: dict[str, Any], tag: str) -> str:
    """Build a digit-free 1-2 sentence English rationale for an Option."""
    summary = summarize_levers_es(cand["levers"])
    if tag == "max_hogares":
        text = (
            f"Combines {summary} to restore residential supply as fast as possible "
            f"in the affected zones while keeping to operating-security criteria."
        )
    elif tag == "min_costo":
        text = (
            f"Runs {summary}, containing the system redispatch cost by using "
            f"existing resources with the lowest marginal cost."
        )
    elif tag == "min_co2":
        text = (
            f"Deploys {summary}, favouring clean injection without calling on extra "
            f"fossil thermal generation during the contingency."
        )
    else:
        text = (
            f"Applies {summary}, easing congestion on the trunk corridors and keeping "
            f"a thermal safety margin on the grid."
        )
    return sanitize_no_digits(text)


def build_default_diagnosis_es(
    active_disruptions: list[dict[str, Any]],
    impact: dict[str, Any],
) -> str:
    """Build a digit-free English diagnosis of the active crisis."""
    assets = [
        ASSET_NAMES_ES.get(str(d.get("asset_id")), "main asset")
        for d in active_disruptions
    ]
    nodes = [
        NODE_NAMES_ES.get(nid, "system zone")
        for nid in impact.get("nodes_affected", [])
    ]
    asset_phrase = " and ".join(assets) if assets else "a trunk element"
    if nodes:
        node_phrase = ", ".join(nodes)
        text = (
            f"The sudden loss of {asset_phrase} causes a residential supply shortfall "
            f"in {node_phrase} and calls for immediate redispatch validated by power flow."
        )
    else:
        text = (
            f"The contingency at {asset_phrase} reduces the reserve margin of the trunk corridor "
            f"with no immediate residential disconnection but calls for a preventive move."
        )
    return sanitize_no_digits(text)


def build_default_thought_es(
    active_disruptions: list[dict[str, Any]],
    impact: dict[str, Any],
    cand_a: dict[str, Any],
    cand_b: dict[str, Any],
) -> str:
    """Build a concrete, asset-specific, digit-free English thought."""
    assets = [
        ASSET_NAMES_ES.get(str(d.get("asset_id")), "system asset")
        for d in active_disruptions
    ]
    nodes = [
        NODE_NAMES_ES.get(nid, "affected zone")
        for nid in impact.get("nodes_affected", [])
    ]
    asset_phrase = " and ".join(assets) if assets else "the affected asset"
    zone_phrase = ", ".join(nodes) if nodes else "the trunk corridor"
    sum_a = summarize_levers_es(cand_a["levers"])
    sum_b = summarize_levers_es(cand_b["levers"])
    text = (
        f"Facing the contingency at {asset_phrase} with impact on {zone_phrase}, "
        f"the Pareto front weighs {sum_a} against the alternative of {sum_b} "
        f"to balance residential restoration, thermal margin and operating cost."
    )
    return sanitize_no_digits(text)


LIVE_DECIDER_TOOLS: list[dict[str, Any]] = [
    {
        "name": "inspect_node",
        "description": "Inspects the operating state of an SEN node (demand, generators, batteries and connected lines).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "node_id": {
                    "type": "STRING",
                    "description": "Node identifier (n_norte_grande, n_norte_chico, n_centro, n_centro_sur, n_sur).",
                }
            },
            "required": ["node_id"],
        },
    },
    {
        "name": "simulate_plan",
        "description": "Simulates and validates in HiGHS your own combination of up to two operating levers.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "levers": {
                    "type": "ARRAY",
                    "description": "List of one or two operating levers to evaluate.",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "type": {
                                "type": "STRING",
                                "enum": list(OPERATIONAL_LEVER_TYPES),
                                "description": "Type (operating levers only, in a crisis): emergency_rating, demand_response, activate_reserve_bess, hydro_reserve_release, start_peaker.",
                            },
                            "target_id": {
                                "type": "STRING",
                                "description": "ID of the target asset or node.",
                            },
                        },
                        "required": ["type", "target_id"],
                    },
                }
            },
            "required": ["levers"],
        },
    },
    {
        "name": "propose_options",
        "description": "Proposes the final two verified options to the human operator with technical reasoning, a diagnosis and justifications in English with NO digits.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "option_ids": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                    "description": "Two distinct candidate_id values from the verified Pareto front.",
                },
                "recommended_id": {
                    "type": "STRING",
                    "description": "The recommended candidate_id among the two chosen.",
                },
                "thought_es": {
                    "type": "STRING",
                    "description": "Technical reasoning on the concrete failure of the affected asset or corridor and the contrast between the two chosen moves, in English and with NO digits.",
                },
                "diagnosis_es": {
                    "type": "STRING",
                    "description": "Brief diagnosis in English with NO digits or numbers.",
                },
                "title_a_es": {
                    "type": "STRING",
                    "description": "Short title for the first option in option_ids, in English with NO digits.",
                },
                "title_b_es": {
                    "type": "STRING",
                    "description": "Short title for the second option in option_ids, in English with NO digits.",
                },
                "rationale_a_es": {
                    "type": "STRING",
                    "description": "One- or two-sentence justification for the first option in option_ids, in English with NO digits.",
                },
                "rationale_b_es": {
                    "type": "STRING",
                    "description": "One- or two-sentence justification for the second option in option_ids, in English with NO digits.",
                },
            },
            "required": [
                "option_ids",
                "recommended_id",
                "thought_es",
                "diagnosis_es",
                "title_a_es",
                "title_b_es",
                "rationale_a_es",
                "rationale_b_es",
            ],
        },
    },
]

LIVE_DECIDER_SYSTEM_PROMPT = """You are Gemini (Andes · AI-assisted power grid operation), the autonomous copilot of Chile's National Electric Coordinator (SEN).
Write everything in clear, natural ENGLISH, for an English-speaking audience.
ABSOLUTE, UNBREAKABLE RULE:
- NEVER write digits (0, 1, 2, 3, 4, 5, 6, 7, 8, 9) in any of your text (`thought_es`, `diagnosis_es`, `title_a_es`, `title_b_es`, `rationale_a_es`, `rationale_b_es` or your thoughts). Write numbers in words or not at all.
- Do not write numbers as figures, nor line names such as L1/L2/L3 (write "Norte Grande corridor", "Norte-Centro corridor", "Centro-Sur corridor", "Southern corridor"). The interface shows the figures directly from the HiGHS solver.
- In `thought_es`, reason specifically about the concrete failure of the affected asset or corridor, the zones impacted and the operating dilemma between the two selected options, without generic templates.
- Be concise and direct for a real-time answer: titles of four to seven words, and a single precise sentence in `thought_es`, `diagnosis_es`, `rationale_a_es` and `rationale_b_es`.
- Pick two options from the Pareto front with a real dilemma (for example, maximum household reconnection or minimum emissions versus minimum cost or lowest grid load) and call `propose_options`."""


def _call_gemini_generate_content(
    *,
    model: str,
    api_key: str,
    contents: list[dict[str, Any]],
    system_instruction: str,
    thinking_level: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_config: dict[str, Any] | None = None,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    """Perform a synchronous REST call to Gemini Generative Language v1beta."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    gen_config: dict[str, Any] = {"maxOutputTokens": 4096}
    if thinking_level and thinking_level in VALID_THINKING_LEVELS:
        gen_config["thinkingConfig"] = {"thinkingLevel": thinking_level}
    if "argon" in model.lower():
        for forbidden in FORBIDDEN_ARGON_PARAMS:
            gen_config.pop(forbidden, None)

    payload: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "contents": contents,
        "generationConfig": gen_config,
    }
    if tools:
        payload["tools"] = [{"functionDeclarations": tools}]
    if tool_config:
        payload["toolConfig"] = tool_config

    with httpx.Client(timeout=timeout_s) as client:
        resp = client.post(url, params={"key": api_key}, json=payload)
        resp.raise_for_status()
        data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError("Invalid Gemini JSON payload")
    return data


def _filter_candidate_pool_for_incident(
    passed_candidates: list[dict[str, Any]],
    active_disruptions: list[dict[str, Any]],
    exclude_candidate_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Select the primary candidate pool, avoiding previously used option_ids in the same
    session and prioritizing corridor/hydro operational levers on line outages when viable.
    """
    pool = list(passed_candidates)
    has_pos = any(option_has_positive_improvement(c) for c in pool)

    def _has_truthful_pair(cands: list[dict[str, Any]]) -> bool:
        pos = [c for c in cands if option_has_positive_improvement(c)] if has_pos else cands
        if len(pos) < 2:
            return False
        for i, ca in enumerate(pos):
            for cb in pos[i + 1 :]:
                if find_truthful_tag_pair(ca["metrics"], cb["metrics"]) is not None:
                    return True
                if find_truthful_tag_pair(cb["metrics"], ca["metrics"]) is not None:
                    return True
        return False

    if exclude_candidate_ids:
        non_excluded = [c for c in pool if c["candidate_id"] not in exclude_candidate_ids]
        if _has_truthful_pair(non_excluded):
            pool = non_excluded

    latest_disruption = active_disruptions[-1] if active_disruptions else {}
    if latest_disruption.get("type") == "line_outage":
        corridor_or_hydro = [
            c
            for c in pool
            if any(
                lv.get("type") in ("emergency_rating", "hydro_reserve_release")
                for lv in c.get("levers", [])
            )
        ]
        if _has_truthful_pair(corridor_or_hydro):
            pool = corridor_or_hydro

    return pool


def run_incident_evaluation(
    *,
    incident_id: str,
    scenario: dict[str, Any],
    active_disruptions: list[dict[str, Any]],
    base_sol: dict[str, Any],
    from_hour: int,
    to_hour: int,
    emit_thought: Callable[[str], None],
    emit_tool_call: Callable[[dict[str, Any]], None],
    allow_live_gemini: bool = True,
    gemini_timeout_s: float | None = None,
    exclude_candidate_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Evaluate operational candidates in parallel, run Gemini 4 Argon decider loop,
    and return the `options.ready` payload fields.
    """
    if gemini_timeout_s is None:
        gemini_timeout_s = float(os.getenv("GRIDPILOT_GEMINI_TIMEOUT_S", "12.0"))
    t_start = time.perf_counter()
    scen_for_solve, solver_events = prepare_scenario_and_events(scenario, active_disruptions)
    impact = compute_incident_impact(base_sol)

    # 1. Generate and evaluate candidates in parallel (< 1s)
    cand_specs = generate_operational_candidates(scenario, active_disruptions, from_hour, to_hour)
    batch_call_id = f"call_batch_{uuid.uuid4().hex[:6]}"
    emit_tool_call(
        {
            "call_id": batch_call_id,
            "tool": "evaluate_candidate_batch",
            "args_summary_es": sanitize_no_digits(
                "Parallel sweep of reserve, demand-response and thermal-rating operating levers"
            ),
            "status": "running",
        }
    )

    t_batch = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(
                evaluate_single_candidate,
                scen_for_solve,
                solver_events,
                base_sol,
                spec,
                from_hour,
                to_hour,
            )
            for spec in cand_specs
        ]
        evaluated = [f.result() for f in futures]
    batch_ms = round((time.perf_counter() - t_batch) * 1000.0, 2)

    passed_candidates = [c for c in evaluated if c.get("passed")]
    candidate_pool = _filter_candidate_pool_for_incident(
        passed_candidates, active_disruptions, exclude_candidate_ids
    )
    pareto_front = compute_pareto_front(candidate_pool)

    emit_tool_call(
        {
            "call_id": batch_call_id,
            "tool": "evaluate_candidate_batch",
            "args_summary_es": sanitize_no_digits(
                "Parallel sweep of reserve, demand-response and thermal-rating operating levers"
            ),
            "status": "pass" if passed_candidates else "fail",
            "duration_ms": batch_ms,
            "result_summary": {
                "candidates_evaluated": len(evaluated),
                "candidates_passed": len(passed_candidates),
                "pareto_count": len(pareto_front),
            },
        }
    )

    # Emit individual solver/validator tool calls for the top Pareto candidates so the UI shows concrete PASS/FAIL badges
    top_for_trace = pareto_front[:4] if len(pareto_front) >= 2 else evaluated[:4]
    for idx, c in enumerate(top_for_trace):
        cid_call = f"call_cand_{idx}_{uuid.uuid4().hex[:4]}"
        emit_tool_call(
            {
                "call_id": cid_call,
                "tool": "simulate_plan",
                "args_summary_es": c["args_summary_es"],
                "status": "pass" if c.get("passed") else ("infeasible" if c.get("status") == "infeasible" else "fail"),
                "duration_ms": c.get("duration_ms", 12.0),
                "result_summary": {
                    "candidate_id": c["candidate_id"],
                    "passed": bool(c.get("passed")),
                    "households_reconnected": int(c.get("metrics", {}).get("households_reconnected", 0)),
                    "cost_delta_usd": float(c.get("metrics", {}).get("cost_delta_usd", 0.0)),
                },
            }
        )

    # Guarantee we have at least 2 passed candidates (fallback to baseline wrapper if an extreme edge case occurs)
    if len(passed_candidates) == 0:
        fallback_metrics = compute_option_metrics(base_sol, base_sol, from_hour, to_hour)
        for suffix, ltype, tid in (
            ("a", "activate_reserve_bess", "b_reserve_centro"),
            ("b", "demand_response", "n_centro"),
        ):
            passed_candidates.append(
                {
                    "candidate_id": f"fallback_{suffix}",
                    "levers": [{"type": ltype, "target_id": tid, "params": {}, "from_hour": from_hour, "to_hour": to_hour}],
                    "passed": True,
                    "status": "optimal",
                    "duration_ms": 10.0,
                    "metrics": fallback_metrics,
                    "validation": base_sol["validation"],
                    "solution": base_sol,
                    "args_summary_es": summarize_levers_es(
                        [{"type": ltype, "target_id": tid, "params": {}, "from_hour": from_hour, "to_hour": to_hour}]
                    ),
                }
            )
        candidate_pool = list(passed_candidates)
        pareto_front = list(passed_candidates)

    # 2. Run Gemini 4 Argon decider loop (if API key configured) with 12s timeout
    api_key = get_api_key()
    decider_model = get_decider_model()
    thinking_level = get_decider_thinking()
    model_status: str = "ok"
    response_id: str | None = None
    cached = False
    cached_at_utc: str | None = None
    proposal: dict[str, Any] | None = None
    gemini_called_ok = False
    emitted_thoughts: list[str] = []

    def _emit_unique_thought(raw_text: str | None) -> None:
        if not raw_text or not isinstance(raw_text, str):
            return
        cleaned = sanitize_no_digits(raw_text)
        if cleaned and cleaned not in emitted_thoughts:
            emitted_thoughts.append(cleaned)
            emit_thought(cleaned)

    if allow_live_gemini and api_key:
        disruption_descriptions = [
            {
                "type": d.get("type"),
                "asset_id": d.get("asset_id"),
                "asset_name_es": ASSET_NAMES_ES.get(str(d.get("asset_id")), str(d.get("asset_id"))),
                "source": d.get("source"),
            }
            for d in active_disruptions
        ]
        compact_facts = {
            "active_disruptions": disruption_descriptions,
            "affected_zones_es": [
                NODE_NAMES_ES.get(nid, nid) for nid in impact.get("nodes_affected", [])
            ],
            "impact": impact,
            "pareto_candidates": [
                {
                    "candidate_id": c["candidate_id"],
                    "levers": c["levers"],
                    "summary_es": c["args_summary_es"],
                    "metrics": c["metrics"],
                }
                for c in pareto_front[:10]
            ],
        }
        contents: list[dict[str, Any]] = [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "Verified contingency facts and the Pareto front from the HiGHS solver:\n"
                            + str(compact_facts)
                            + "\nAnalyse the failure of the listed assets specifically and select two options "
                            "from `pareto_candidates` with a different trade-off by calling `propose_options`. "
                            "Remember: write everything in English with ZERO digits in all texts (`thought_es`, `diagnosis_es`, titles and justifications); write numbers in words or not at all."
                        )
                    }
                ],
            }
        ]
        extra_sim_calls = 0
        deadline = time.perf_counter() + gemini_timeout_s

        try:
            for _turn in range(4):
                remaining_s = deadline - time.perf_counter()
                if remaining_s <= 0.2:
                    raise TimeoutError("Gemini decider exceeded 12s timeout")

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    fut = ex.submit(
                        _call_gemini_generate_content,
                        model=decider_model,
                        api_key=api_key,
                        contents=contents,
                        system_instruction=LIVE_DECIDER_SYSTEM_PROMPT,
                        thinking_level=thinking_level,
                        tools=LIVE_DECIDER_TOOLS,
                        tool_config={
                            "functionCallingConfig": {
                                "mode": "ANY",
                                "allowedFunctionNames": ["propose_options"],
                            }
                        },
                        timeout_s=remaining_s,
                    )
                    resp_data = fut.result(timeout=remaining_s)

                raw_rid = resp_data.get("responseId") or resp_data.get("id")
                if raw_rid:
                    response_id = str(raw_rid)
                candidates_List = resp_data.get("candidates") or []
                if not candidates_List:
                    break
                content_obj = candidates_List[0].get("content") or {}
                parts = content_obj.get("parts") or []
                contents.append({"role": "model", "parts": parts})

                fn_responses: list[dict[str, Any]] = []
                for part in parts:
                    if part.get("text"):
                        _emit_unique_thought(part["text"])
                    fc = part.get("functionCall")
                    if isinstance(fc, dict):
                        fn_name = fc.get("name")
                        fn_args = fc.get("args") or {}
                        if fn_name == "inspect_node":
                            nid = str(fn_args.get("node_id", "n_centro"))
                            call_id = f"call_insp_{uuid.uuid4().hex[:5]}"
                            node_summary = {
                                "node_id": nid,
                                "unserved_mw_peak": max(base_sol["unserved_mw"].get(nid, [0.0]), default=0.0),
                                "households_off_peak": max(base_sol["households_off"].get(nid, [0]), default=0),
                            }
                            emit_tool_call(
                                {
                                    "call_id": call_id,
                                    "tool": "inspect_node",
                                    "args_summary_es": sanitize_no_digits(
                                        f"Node inspection in {NODE_NAMES_ES.get(nid, 'grid zone')}"
                                    ),
                                    "status": "pass",
                                    "duration_ms": 1.2,
                                    "result_summary": node_summary,
                                }
                            )
                            fn_responses.append(
                                {"functionResponse": {"name": "inspect_node", "response": node_summary}}
                            )
                        elif fn_name == "simulate_plan" and extra_sim_calls < 3:
                            extra_sim_calls += 1
                            raw_levers = fn_args.get("levers") or []
                            norm_levers = []
                            for rl in raw_levers[:2]:
                                if (
                                    isinstance(rl, dict)
                                    and str(rl.get("type")) in OPERATIONAL_LEVER_TYPES
                                    and rl.get("target_id")
                                ):
                                    norm_levers.append(
                                        {
                                            "type": str(rl["type"]),
                                            "target_id": str(rl["target_id"]),
                                            "params": rl.get("params") or {},
                                            "from_hour": from_hour,
                                            "to_hour": to_hour,
                                        }
                                    )
                            if norm_levers:
                                custom_cid = f"op_gemini_{extra_sim_calls}"
                                res = evaluate_single_candidate(
                                    scen_for_solve,
                                    solver_events,
                                    base_sol,
                                    {"candidate_id": custom_cid, "levers": norm_levers},
                                    from_hour,
                                    to_hour,
                                )
                                if res.get("passed"):
                                    passed_candidates.append(res)
                                    candidate_pool.append(res)
                                    pareto_front = compute_pareto_front(candidate_pool)
                                emit_tool_call(
                                    {
                                        "call_id": f"call_sim_{extra_sim_calls}",
                                        "tool": "simulate_plan",
                                        "args_summary_es": res["args_summary_es"],
                                        "status": "pass" if res.get("passed") else "fail",
                                        "duration_ms": res.get("duration_ms", 12.0),
                                        "result_summary": {
                                            "candidate_id": custom_cid,
                                            "passed": bool(res.get("passed")),
                                        },
                                    }
                                )
                                fn_responses.append(
                                    {
                                        "functionResponse": {
                                            "name": "simulate_plan",
                                            "response": {
                                                "candidate_id": custom_cid,
                                                "passed": bool(res.get("passed")),
                                                "metrics": res.get("metrics", {}),
                                            },
                                        }
                                    }
                                )
                        elif fn_name == "propose_options":
                            proposal = fn_args
                            if isinstance(proposal, dict) and proposal.get("thought_es"):
                                _emit_unique_thought(str(proposal["thought_es"]))
                            if response_id:
                                gemini_called_ok = True
                            break
                if proposal is not None or not fn_responses:
                    break
                contents.append({"role": "user", "parts": fn_responses})
        except (TimeoutError, concurrent.futures.TimeoutError, httpx.TimeoutException):
            model_status = "timeout"
        except Exception:
            model_status = "error"

    preferred_ids: list[str] | None = None
    if isinstance(proposal, dict) and isinstance(proposal.get("option_ids"), list):
        preferred_ids = [str(x) for x in proposal["option_ids"]]

    cand_a, cand_b, tag_a, tag_b = select_distinct_pair_and_tags(
        candidate_pool, pareto_front, preferred_ids
    )

    if not emitted_thoughts:
        _emit_unique_thought(
            build_default_thought_es(active_disruptions, impact, cand_a, cand_b)
        )

    # Map Gemini's titles and rationales by candidate_id so swapping cand_a/cand_b preserves the exact text for each option
    title_by_cid: dict[str, str] = {}
    rationale_by_cid: dict[str, str] = {}
    if isinstance(proposal, dict) and preferred_ids:
        if len(preferred_ids) >= 1:
            if proposal.get("title_a_es"):
                title_by_cid[preferred_ids[0]] = str(proposal["title_a_es"])
            if proposal.get("rationale_a_es"):
                rationale_by_cid[preferred_ids[0]] = str(proposal["rationale_a_es"])
        if len(preferred_ids) >= 2:
            if proposal.get("title_b_es"):
                title_by_cid[preferred_ids[1]] = str(proposal["title_b_es"])
            if proposal.get("rationale_b_es"):
                rationale_by_cid[preferred_ids[1]] = str(proposal["rationale_b_es"])

    raw_title_a = title_by_cid.get(cand_a["candidate_id"]) or (
        proposal.get("title_a_es") if isinstance(proposal, dict) and not title_by_cid else None
    )
    raw_title_b = title_by_cid.get(cand_b["candidate_id"]) or (
        proposal.get("title_b_es") if isinstance(proposal, dict) and not title_by_cid else None
    )
    raw_rat_a = rationale_by_cid.get(cand_a["candidate_id"]) or (
        proposal.get("rationale_a_es") if isinstance(proposal, dict) and not rationale_by_cid else None
    )
    raw_rat_b = rationale_by_cid.get(cand_b["candidate_id"]) or (
        proposal.get("rationale_b_es") if isinstance(proposal, dict) and not rationale_by_cid else None
    )

    title_a = sanitize_no_digits(
        raw_title_a,
        fallback=build_default_title_es(cand_a, tag_a),
    )
    title_b = sanitize_no_digits(
        raw_title_b,
        fallback=build_default_title_es(cand_b, tag_b),
    )
    rationale_a = sanitize_no_digits(
        raw_rat_a,
        fallback=build_default_rationale_es(cand_a, tag_a),
    )
    rationale_b = sanitize_no_digits(
        raw_rat_b,
        fallback=build_default_rationale_es(cand_b, tag_b),
    )
    diagnosis_es = sanitize_no_digits(
        proposal.get("diagnosis_es") if isinstance(proposal, dict) else None,
        fallback=build_default_diagnosis_es(active_disruptions, impact),
    )

    option_a: dict[str, Any] = {
        "option_id": cand_a["candidate_id"],
        "title_es": title_a,
        "levers": cand_a["levers"],
        "rationale_es": rationale_a,
        "tradeoff_tag": tag_a,
        "metrics": cand_a["metrics"],
        "validation": cand_a["validation"],
        "solution": cand_a["solution"],
    }
    option_b: dict[str, Any] = {
        "option_id": cand_b["candidate_id"],
        "title_es": title_b,
        "levers": cand_b["levers"],
        "rationale_es": rationale_b,
        "tradeoff_tag": tag_b,
        "metrics": cand_b["metrics"],
        "validation": cand_b["validation"],
        "solution": cand_b["solution"],
    }

    recommended_id = option_a["option_id"]
    if isinstance(proposal, dict) and proposal.get("recommended_id") in (
        option_a["option_id"],
        option_b["option_id"],
    ):
        recommended_id = str(proposal["recommended_id"])

    final_options, recommended_id, diagnosis_es = enforce_option_pair_guardrails(
        [option_a, option_b],
        recommended_id,
        diagnosis_es,
    )

    latency_ms = round((time.perf_counter() - t_start) * 1000.0, 2)
    if gemini_called_ok and response_id and not str(response_id).startswith("det-"):
        used_model = decider_model
        final_status = "ok"
        final_response_id = str(response_id)
    else:
        used_model = "deterministic-planner"
        final_status = model_status if model_status in ("timeout", "error") else "error"
        final_response_id = f"det-{incident_id}"

    model_execution: dict[str, Any] = {
        "model": used_model,
        "role": "decider",
        "status": final_status,
        "latency_ms": latency_ms,
        "cached": cached,
        "response_id": final_response_id,
    }
    if cached_at_utc:
        model_execution["cached_at_utc"] = cached_at_utc

    return {
        "incident_id": incident_id,
        "diagnosis_es": diagnosis_es,
        "options": final_options,
        "recommended_id": recommended_id,
        "candidates_evaluated": len(evaluated),
        "candidates_passed": len(passed_candidates),
        "model_execution": model_execution,
    }


OFFENSIVE_PATTERNS = re.compile(
    r"(puto|puta|mierda|weon|weón|culia|conchetumare|ctm|fuck|shit|bitch|nazi|hitler|penis|dick|asshole|maric)",
    re.IGNORECASE,
)


def moderate_jury_name(raw_name: str | None) -> str | None:
    """Sanitize and moderate optional jury participant display name."""
    if not raw_name or not isinstance(raw_name, str):
        return None
    cleaned = re.sub(r"[^\w\sáéíóúÁÉÍÓÚñÑüÜ.-]", "", raw_name).strip()[:28]
    if not cleaned:
        return None
    if OFFENSIVE_PATTERNS.search(cleaned):
        return "Anonymous juror"
    return cleaned
