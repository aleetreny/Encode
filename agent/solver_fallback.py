"""Deterministic LP Dispatch, Sudden-Outage Crisis Solver & Independent Validator.

Uses ``scipy.optimize.linprog(method="highs")`` (or delegates to ``optimisation`` /
``backend`` when installed in the integrated runtime) so ``agent/`` runs 100%
deterministically standalone on ``feature/agent`` as well as inside the merged
FastAPI backend.
"""

from __future__ import annotations

import copy
import math
import time
from typing import Any

import numpy as np
from scipy.optimize import linprog

TOL = 1e-6
TOL_MW = 1e-4

CANONICAL_FIELDS = {
    "generation_mw_by_generator": "generation_mw",
    "curtailment_mw_by_generator": "curtailment_mw",
    "line_flows_mw_by_line": "line_flow_mw",
    "charge_mw_by_battery": "battery_charge_mw",
    "discharge_mw_by_battery": "battery_discharge_mw",
    "soc_mwh_by_battery": "battery_soc_mwh",
    "load_shedding_mw_by_node": "unserved_mw",
}


def _normalise_to_native_scenario(scenario: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Convert either a P4 canonical scenario or a P3 native scenario into a unified native dict."""
    opts = options or {}
    s = copy.deepcopy(scenario)
    s.pop("schema_version", None)
    s.pop("network_model", None)
    curtail_pen = s.pop("curtailment_penalty_usd_per_mwh", None)
    shed_pen = s.pop("load_shedding_penalty_usd_per_mwh", None)
    s.setdefault("display_timezone", "America/Santiago")

    if "objective" not in s:
        s["objective"] = {
            "unserved_energy_penalty_usd_per_mwh": float(shed_pen if shed_pen is not None else 10000.0),
            "curtailment_penalty_usd_per_mwh": float(curtail_pen if curtail_pen is not None else 0.0),
            "battery_throughput_cost_usd_per_mwh": 0.0,
            "transmission_tiebreak_usd_per_mwh": 0.0,
        }
    else:
        s["objective"].setdefault("unserved_energy_penalty_usd_per_mwh", 10000.0)
        s["objective"].setdefault("curtailment_penalty_usd_per_mwh", 0.0)
        s["objective"].setdefault("battery_throughput_cost_usd_per_mwh", 0.5)
        s["objective"].setdefault("transmission_tiebreak_usd_per_mwh", 0.01)

    batteries = []
    battery_policy = opts.get("battery_policy", "optimised")
    for b in s.get("batteries", []):
        item = copy.deepcopy(b)
        rte = item.pop("round_trip_efficiency", None)
        final_soc = item.pop("final_soc_mwh", None)
        item.setdefault("min_soc_mwh", 0.0)
        if "charge_efficiency" not in item or "discharge_efficiency" not in item:
            eta = math.sqrt(float(rte)) if rte is not None else 0.95
            item["charge_efficiency"] = eta
            item["discharge_efficiency"] = eta
        if final_soc is not None:
            item["_exact_final_soc_mwh"] = float(final_soc)
        if battery_policy == "disabled":
            item["power_capacity_mw"] = 0.0
        batteries.append(item)
    s["batteries"] = batteries
    return s


def modification_menu(scenario: dict[str, Any]) -> dict[str, Any]:
    """Return allowed candidate asset modifications and bounds for the scenario."""
    limits = scenario.get("modification_limits") or {}
    return {
        "scenario_id": scenario.get("scenario_id", "unknown"),
        "max_modifications_per_candidate": 2,
        "allowed_types": [
            {
                "type": "add_battery",
                "allowed_nodes": [n["id"] for n in scenario.get("nodes", [])],
                "power_mw_range": list(limits.get("battery_power_mw_range", [10.0, 150.0])),
                "duration_hours_range": list(limits.get("battery_duration_h_range", [1.0, 6.0])),
            },
            {
                "type": "uprate_line",
                "allowed_lines": [
                    {
                        "id": ln["id"],
                        "from": ln["from"],
                        "to": ln["to"],
                        "current_capacity_mw": float(ln["capacity_mw"]),
                        "max_capacity_mw": round(float(ln["capacity_mw"]) * 1.5, 3),
                    }
                    for ln in scenario.get("lines", [])
                ],
            },
        ],
    }


get_modification_menu = modification_menu


def _apply_candidate_and_events(
    native_scen: dict[str, Any],
    candidate: dict[str, Any] | None,
    events: list[dict[str, Any]] | None,
) -> tuple[dict[str, Any], str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply candidate asset modifications and normalise outage events."""
    eff = copy.deepcopy(native_scen)
    cand_id = "baseline"
    applied_mods: list[dict[str, Any]] = []
    node_ids = {n["id"] for n in eff["nodes"]}
    lines_by_id = {ln["id"]: ln for ln in eff["lines"]}

    if candidate and candidate.get("modifications"):
        cand_id = str(candidate.get("candidate_id") or "candidate")
        mods = candidate.get("modifications") or []
        if len(mods) > 2:
            raise ValueError("At most 2 modifications are allowed per candidate")
        uprated_lines: set[str] = set()
        bat_idx = 0
        for m in mods:
            mtype = m.get("type")
            if mtype in ("add_battery", "add_battery_capacity"):
                nid = m.get("node_id")
                if nid not in node_ids:
                    raise ValueError(f"Unknown node_id {nid!r} in add_battery")
                p_mw = float(m.get("power_mw", m.get("added_power_mw", 0)))
                e_mwh = float(m.get("energy_mwh", m.get("added_energy_mwh", 0)))
                if not (10.0 - TOL <= p_mw <= 150.0 + TOL):
                    raise ValueError(f"Battery power_mw {p_mw} outside allowed [10, 150] MW range")
                dur = e_mwh / p_mw if p_mw > 0 else 0.0
                if not (1.0 - TOL <= dur <= 6.0 + TOL):
                    raise ValueError(f"Battery duration {dur:.2f}h outside allowed [1, 6] h range")
                bat_idx += 1
                bid = f"{cand_id}_bat{bat_idx}"
                eff["batteries"].append(
                    {
                        "id": bid,
                        "node_id": nid,
                        "power_capacity_mw": p_mw,
                        "energy_capacity_mwh": e_mwh,
                        "min_soc_mwh": 0.0,
                        "initial_soc_mwh": 0.5 * e_mwh,
                        "charge_efficiency": 0.95,
                        "discharge_efficiency": 0.95,
                    }
                )
                applied_mods.append(
                    {
                        "type": "add_battery",
                        "node_id": nid,
                        "power_mw": p_mw,
                        "energy_mwh": e_mwh,
                        "battery_id": bid,
                    }
                )
            elif mtype == "uprate_line":
                lid = m.get("line_id")
                if lid not in lines_by_id:
                    raise ValueError(f"Unknown line_id {lid!r} in uprate_line")
                if lid in uprated_lines:
                    raise ValueError(f"Line {lid!r} uprated more than once")
                uprated_lines.add(lid)
                ln = lines_by_id[lid]
                prev_cap = float(ln["capacity_mw"])
                if "new_capacity_mw" in m:
                    new_cap = float(m["new_capacity_mw"])
                else:
                    pct = float(m.get("pct_increase", 25.0))
                    new_cap = round(prev_cap * (1.0 + pct / 100.0), 3)
                if new_cap <= prev_cap or new_cap > 1.5 * prev_cap + TOL:
                    raise ValueError(
                        f"Line {lid} new_capacity_mw {new_cap} must be in ({prev_cap}, {1.5 * prev_cap}]"
                    )
                ln["capacity_mw"] = new_cap
                applied_mods.append(
                    {
                        "type": "uprate_line",
                        "line_id": lid,
                        "previous_capacity_mw": prev_cap,
                        "new_capacity_mw": new_cap,
                    }
                )
            else:
                raise ValueError(f"Unsupported modification type {mtype!r}")

    merged_events: list[dict[str, Any]] = []
    for ev in list(eff.get("events") or []) + list(events or []):
        norm_ev = {
            "type": ev["type"],
            "id": ev["id"],
            "from_hour": int(ev["from_hour"]),
            "to_hour": int(ev["to_hour"]),
            "mode": ev.get("mode", "planned"),
        }
        if norm_ev not in merged_events:
            merged_events.append(norm_ev)

    return eff, cand_id, applied_mods, merged_events


def _solve_lp_window(
    eff: dict[str, Any],
    active_events: list[dict[str, Any]],
    allow_unserved: bool,
    fixed_before_hour: int = 0,
    locked_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Solve the multi-hour LP over t = 0..T-1 (locking hours < fixed_before_hour if given)."""
    timestamps = eff["timestamps_utc"]
    T = len(timestamps)
    dt = float(eff["time_step_hours"])
    nodes = eff["nodes"]
    node_ids = [n["id"] for n in nodes]
    node_idx = {nid: i for i, nid in enumerate(node_ids)}
    lines = eff["lines"]
    gens = eff["generators"]
    bats = eff["batteries"]
    ren_avail = eff.get("renewable_availability_mw_by_generator") or {}
    obj_cfg = eff["objective"]

    c_unserved = float(obj_cfg.get("unserved_energy_penalty_usd_per_mwh", 10000.0))
    c_curt = float(obj_cfg.get("curtailment_penalty_usd_per_mwh", 0.0))
    c_thr = float(obj_cfg.get("battery_throughput_cost_usd_per_mwh", 0.5))
    c_tx = float(obj_cfg.get("transmission_tiebreak_usd_per_mwh", 0.01))

    G = len(gens)
    B = len(bats)
    L = len(lines)
    N = len(nodes)

    # Variable layout:
    # 1. p[g, t]        : G * T
    # 2. ch[b, t]       : B * T
    # 3. dis[b, t]      : B * T
    # 4. soc[b, t]      : B * (T + 1)
    # 5. f_pos[l, t]    : L * T
    # 6. f_neg[l, t]    : L * T
    # 7. u[n, t]        : N * T
    off_p = 0
    off_ch = off_p + G * T
    off_dis = off_ch + B * T
    off_soc = off_dis + B * T
    off_fp = off_soc + B * (T + 1)
    off_fn = off_fp + L * T
    off_u = off_fn + L * T
    n_vars = off_u + N * T

    def idx_p(g: int, t: int) -> int:
        return off_p + g * T + t

    def idx_ch(b: int, t: int) -> int:
        return off_ch + b * T + t

    def idx_dis(b: int, t: int) -> int:
        return off_dis + b * T + t

    def idx_soc(b: int, t: int) -> int:
        return off_soc + b * (T + 1) + t

    def idx_fp(l: int, t: int) -> int:
        return off_fp + l * T + t

    def idx_fn(l: int, t: int) -> int:
        return off_fn + l * T + t

    def idx_u(n: int, t: int) -> int:
        return off_u + n * T + t

    c = np.zeros(n_vars, dtype=float)
    bounds: list[tuple[float, float]] = [(0.0, 0.0)] * n_vars

    # Outage masks
    gen_online = np.ones((G, T), dtype=bool)
    line_online = np.ones((L, T), dtype=bool)
    gen_map = {g["id"]: i for i, g in enumerate(gens)}
    line_map = {ln["id"]: i for i, ln in enumerate(lines)}
    for ev in active_events:
        fh, th = int(ev["from_hour"]), int(ev["to_hour"])
        if ev["type"] == "generator_outage" and ev["id"] in gen_map:
            gen_online[gen_map[ev["id"]], fh:th] = False
        elif ev["type"] == "line_outage" and ev["id"] in line_map:
            line_online[line_map[ev["id"]], fh:th] = False

    # Generator bounds & costs
    raw_locked = locked_plan.get("_raw") if locked_plan is not None else None
    avail_matrix = np.zeros((G, T), dtype=float)
    for g_i, g in enumerate(gens):
        gid = g["id"]
        is_ren = gid in ren_avail
        var_cost = float(g.get("variable_cost_usd_per_mwh", 0.0))
        for t in range(T):
            av = float(ren_avail[gid][t]) if is_ren else float(g["capacity_mw"])
            if not gen_online[g_i, t]:
                av = 0.0
            avail_matrix[g_i, t] = av
            if t < fixed_before_hour and raw_locked is not None:
                val = float(raw_locked["p"][g_i, t])
                bounds[idx_p(g_i, t)] = (val, val)
            else:
                bounds[idx_p(g_i, t)] = (0.0, av)
            # For renewables, curtailment = avail - p, so cost contribution on p is (var_cost - c_curt)*dt
            c[idx_p(g_i, t)] = (var_cost - (c_curt if is_ren else 0.0)) * dt

    # Battery bounds & costs (use eff_c_thr in LP objective so battery never simultaneously
    # charges & discharges in the same hour to dissipate curtailed energy via round-trip loss)
    eff_c_thr = max(c_thr, 0.25 * max(1.0, c_curt))
    for b_i, b in enumerate(bats):
        bid = b["id"]
        p_cap = float(b["power_capacity_mw"])
        e_cap = float(b["energy_capacity_mwh"])
        min_soc = float(b.get("min_soc_mwh", 0.0))
        soc0 = float(b["initial_soc_mwh"])
        exact_final = b.get("_exact_final_soc_mwh")
        for t in range(T):
            if t < fixed_before_hour and raw_locked is not None:
                ch_v = float(raw_locked["ch"][b_i, t])
                dis_v = float(raw_locked["dis"][b_i, t])
                bounds[idx_ch(b_i, t)] = (ch_v, ch_v)
                bounds[idx_dis(b_i, t)] = (dis_v, dis_v)
            else:
                bounds[idx_ch(b_i, t)] = (0.0, p_cap)
                bounds[idx_dis(b_i, t)] = (0.0, p_cap)
            c[idx_ch(b_i, t)] = eff_c_thr * dt
            c[idx_dis(b_i, t)] = eff_c_thr * dt

        for t in range(T + 1):
            if t == 0:
                bounds[idx_soc(b_i, t)] = (soc0, soc0)
            elif t == T:
                if exact_final is not None:
                    bounds[idx_soc(b_i, t)] = (exact_final, exact_final)
                else:
                    bounds[idx_soc(b_i, t)] = (soc0, e_cap)
            else:
                bounds[idx_soc(b_i, t)] = (min_soc, e_cap)

    # Line flow bounds & costs
    for l_i, ln in enumerate(lines):
        lid = ln["id"]
        cap = float(ln["capacity_mw"])
        for t in range(T):
            eff_cap = cap if line_online[l_i, t] else 0.0
            if t < fixed_before_hour and raw_locked is not None:
                fp_v = float(raw_locked["fp"][l_i, t])
                fn_v = float(raw_locked["fn"][l_i, t])
                bounds[idx_fp(l_i, t)] = (fp_v, fp_v)
                bounds[idx_fn(l_i, t)] = (fn_v, fn_v)
            else:
                bounds[idx_fp(l_i, t)] = (0.0, eff_cap)
                bounds[idx_fn(l_i, t)] = (0.0, eff_cap)
            c[idx_fp(l_i, t)] = c_tx * dt
            c[idx_fn(l_i, t)] = c_tx * dt

    # Unserved energy bounds & costs
    demand_by_node = eff["demand_mw_by_node"]
    for n_i, nid in enumerate(node_ids):
        dem_series = demand_by_node.get(nid, [0.0] * T)
        for t in range(T):
            dem = float(dem_series[t])
            if t < fixed_before_hour and raw_locked is not None:
                uv = float(raw_locked["u"][n_i, t])
                bounds[idx_u(n_i, t)] = (uv, uv)
            else:
                bounds[idx_u(n_i, t)] = (0.0, dem if allow_unserved else 0.0)
            c[idx_u(n_i, t)] = c_unserved * dt

    # Equality constraints: Nodal balance (N * T) + Battery SOC recursion (B * T)
    n_eq = N * T + B * T
    A_eq = np.zeros((n_eq, n_vars), dtype=float)
    b_eq = np.zeros(n_eq, dtype=float)
    row = 0

    for n_i, nid in enumerate(node_ids):
        dem_series = demand_by_node.get(nid, [0.0] * T)
        for t in range(T):
            for g_i, g in enumerate(gens):
                if g["node_id"] == nid:
                    A_eq[row, idx_p(g_i, t)] = 1.0
            for b_i, b in enumerate(bats):
                if b["node_id"] == nid:
                    A_eq[row, idx_dis(b_i, t)] = 1.0
                    A_eq[row, idx_ch(b_i, t)] = -1.0
            for l_i, ln in enumerate(lines):
                if ln["to"] == nid:
                    A_eq[row, idx_fp(l_i, t)] = 1.0
                    A_eq[row, idx_fn(l_i, t)] = -1.0
                if ln["from"] == nid:
                    A_eq[row, idx_fp(l_i, t)] = -1.0
                    A_eq[row, idx_fn(l_i, t)] = 1.0
            A_eq[row, idx_u(n_i, t)] = 1.0
            b_eq[row] = float(dem_series[t])
            row += 1

    for b_i, b in enumerate(bats):
        eta_c = float(b["charge_efficiency"])
        eta_d = float(b["discharge_efficiency"])
        for t in range(T):
            # soc[b, t+1] - soc[b, t] - eta_c*dt*ch[b,t] + (dt/eta_d)*dis[b,t] = 0
            A_eq[row, idx_soc(b_i, t + 1)] = 1.0
            A_eq[row, idx_soc(b_i, t)] = -1.0
            A_eq[row, idx_ch(b_i, t)] = -eta_c * dt
            A_eq[row, idx_dis(b_i, t)] = dt / eta_d
            b_eq[row] = 0.0
            row += 1

    # Inequality constraints: Generator ramp rates
    ub_rows: list[np.ndarray] = []
    ub_vals: list[float] = []
    for g_i, g in enumerate(gens):
        ramp = g.get("ramp_rate_mw_per_h")
        if ramp is None or g["id"] in ren_avail:
            continue
        max_delta = float(ramp) * dt
        for t in range(max(1, fixed_before_hour), T):
            if not gen_online[g_i, t]:
                continue
            r_up = np.zeros(n_vars, dtype=float)
            r_up[idx_p(g_i, t)] = 1.0
            r_up[idx_p(g_i, t - 1)] = -1.0
            ub_rows.append(r_up)
            ub_vals.append(max_delta)

            r_dn = np.zeros(n_vars, dtype=float)
            r_dn[idx_p(g_i, t - 1)] = 1.0
            r_dn[idx_p(g_i, t)] = -1.0
            ub_rows.append(r_dn)
            ub_vals.append(max_delta)

    A_ub = np.vstack(ub_rows) if ub_rows else None
    b_ub = np.array(ub_vals, dtype=float) if ub_vals else None

    res = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
    if not res.success or res.x is None:
        return {
            "status": "infeasible",
            "message": "No feasible dispatch satisfies nodal demand, line capacities, and ramp limits without load shedding.",
        }

    x = res.x

    def clean(arr: np.ndarray) -> list[float]:
        out = np.where(np.abs(arr) < 1e-9, 0.0, np.round(arr, 6))
        return [float(v) for v in out]

    gen_mw = {g["id"]: clean(x[off_p + i * T : off_p + (i + 1) * T]) for i, g in enumerate(gens)}
    avail_mw = {g["id"]: clean(avail_matrix[i]) for i, g in enumerate(gens)}
    curt_mw = {
        g["id"]: clean(avail_matrix[i] - x[off_p + i * T : off_p + (i + 1) * T])
        for i, g in enumerate(gens)
        if g["id"] in ren_avail
    }
    ch_mw = {b["id"]: clean(x[off_ch + i * T : off_ch + (i + 1) * T]) for i, b in enumerate(bats)}
    dis_mw = {b["id"]: clean(x[off_dis + i * T : off_dis + (i + 1) * T]) for i, b in enumerate(bats)}
    soc_mwh = {
        b["id"]: clean(x[off_soc + i * (T + 1) : off_soc + (i + 1) * (T + 1)]) for i, b in enumerate(bats)
    }
    flow_mw = {
        ln["id"]: clean(
            x[off_fp + i * T : off_fp + (i + 1) * T] - x[off_fn + i * T : off_fn + (i + 1) * T]
        )
        for i, ln in enumerate(lines)
    }
    unserved_mw = {
        nid: clean(x[off_u + i * T : off_u + (i + 1) * T]) for i, nid in enumerate(node_ids)
    }

    # Compute exact metrics matching Person 3's validate.py
    curt_by_gen = {gid: round(sum(vals) * dt, 6) for gid, vals in curt_mw.items()}
    unserved_by_node = {nid: round(sum(vals) * dt, 6) for nid, vals in unserved_mw.items()}
    curt_total = round(sum(curt_by_gen.values()), 6)
    unserved_total = round(sum(unserved_by_node.values()), 6)
    ren_used = round(sum(sum(gen_mw[g["id"]]) for g in gens if g["id"] in ren_avail) * dt, 6)
    disp_used = round(sum(sum(gen_mw[g["id"]]) for g in gens if g["id"] not in ren_avail) * dt, 6)
    dem_total = round(sum(sum(demand_by_node.get(nid, [0.0] * T)) for nid in node_ids) * dt, 6)
    ch_total = round(sum(sum(v) for v in ch_mw.values()) * dt, 6)
    dis_total = round(sum(sum(v) for v in dis_mw.values()) * dt, 6)
    losses_total = round(
        sum(
            sum(ch_mw[b["id"]]) * dt * (1.0 - float(b["charge_efficiency"]))
            + sum(dis_mw[b["id"]]) * dt * (1.0 / float(b["discharge_efficiency"]) - 1.0)
            for b in bats
        ),
        6,
    )
    disp_cost = round(
        sum(
            sum(gen_mw[g["id"]]) * dt * float(g.get("variable_cost_usd_per_mwh", 0.0))
            for g in gens
            if g["id"] not in ren_avail
        ),
        6,
    )
    line_hours_at_limit = {
        ln["id"]: sum(
            1
            for t, fl in enumerate(flow_mw[ln["id"]])
            if line_online[l_i, t] and abs(abs(fl) - float(ln["capacity_mw"])) <= 1e-3
        )
        for l_i, ln in enumerate(lines)
    }

    # Binding constraints summary
    binding: list[dict[str, Any]] = []
    for l_i, ln in enumerate(lines):
        lid = ln["id"]
        cap = float(ln["capacity_mw"])
        hrs = [t for t, fl in enumerate(flow_mw[lid]) if line_online[l_i, t] and abs(abs(fl) - cap) <= 1e-3]
        if hrs:
            binding.append(
                {"type": "line_limit", "id": lid, "hours": hrs, "detail": f"flow at ±{cap:g} MW thermal limit"}
            )
    for gid, vals in curt_mw.items():
        hrs = [t for t, v in enumerate(vals) if v > 1e-3]
        if hrs:
            binding.append(
                {
                    "type": "renewable_curtailed",
                    "id": gid,
                    "hours": hrs,
                    "detail": f"{sum(vals) * dt:.1f} MWh curtailed due to export congestion",
                }
            )
    for nid, vals in unserved_mw.items():
        hrs = [t for t, v in enumerate(vals) if v > 1e-3]
        if hrs:
            binding.append(
                {
                    "type": "unserved_energy",
                    "id": nid,
                    "hours": hrs,
                    "detail": f"{sum(vals) * dt:.1f} MWh unserved load (EDAC household disconnection)",
                }
            )
    for ev in active_events:
        binding.append(
            {
                "type": "outage",
                "id": ev["id"],
                "hours": list(range(int(ev["from_hour"]), int(ev["to_hour"]))),
                "detail": f"{ev['mode']} {ev['type']} ({ev['from_hour']}h–{ev['to_hour']}h)",
            }
        )

    terms = {
        "dispatchable_cost_usd": disp_cost,
        "unserved_penalty_usd": round(unserved_total * c_unserved, 6),
        "curtailment_penalty_usd": round(curt_total * c_curt, 6),
        "battery_throughput_cost_usd": round((ch_total + dis_total) * c_thr, 6),
        "transmission_tiebreak_usd": round(
            sum(sum(abs(v) for v in vals) for vals in flow_mw.values()) * dt * c_tx, 6
        ),
    }

    return {
        "status": "optimal",
        "_raw": {
            "p": x[off_p:off_ch].reshape(G, T).copy(),
            "ch": x[off_ch:off_dis].reshape(B, T).copy(),
            "dis": x[off_dis:off_soc].reshape(B, T).copy(),
            "fp": x[off_fp:off_fn].reshape(L, T).copy(),
            "fn": x[off_fn:off_u].reshape(L, T).copy(),
            "u": x[off_u:].reshape(N, T).copy(),
        },
        "timeseries": {
            "generation_mw": gen_mw,
            "available_mw": avail_mw,
            "curtailment_mw": curt_mw,
            "battery_charge_mw": ch_mw,
            "battery_discharge_mw": dis_mw,
            "battery_soc_mwh": soc_mwh,
            "line_flow_mw": flow_mw,
            "unserved_mw": unserved_mw,
        },
        "metrics": {
            "curtailment_mwh": curt_total,
            "curtailment_mwh_by_generator": curt_by_gen,
            "unserved_mwh": unserved_total,
            "unserved_mwh_by_node": unserved_by_node,
            "renewable_used_mwh": ren_used,
            "dispatchable_mwh": disp_used,
            "demand_mwh": dem_total,
            "battery_charge_mwh": ch_total,
            "battery_discharge_mwh": dis_total,
            "battery_losses_mwh": losses_total,
            "assumed_cost_proxy_usd": disp_cost,
            "line_hours_at_limit": line_hours_at_limit,
        },
        "objective": {
            "total_usd": round(sum(terms.values()), 6),
            "terms": terms,
        },
        "binding_constraints": binding,
    }


def solve_native(
    scenario: dict[str, Any],
    candidate: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Solve a dispatch or sudden-crisis scenario and return Person 3's native envelope."""
    t0 = time.perf_counter()
    opts = options or {}
    allow_unserved = bool(opts.get("allow_unserved", opts.get("allow_load_shedding", True)))
    native_scen = _normalise_to_native_scenario(scenario, opts)

    try:
        eff, cand_id, applied_mods, merged_events = _apply_candidate_and_events(native_scen, candidate, events)
    except ValueError as exc:
        return {
            "status": "error",
            "message": str(exc),
            "scenario_id": native_scen.get("scenario_id", "unknown"),
            "candidate_id": (candidate or {}).get("candidate_id", "baseline"),
            "modifications": [],
            "events": [],
            "options": {"allow_unserved": allow_unserved},
            "time_step_hours": native_scen.get("time_step_hours", 1),
            "timestamps_utc": native_scen.get("timestamps_utc", []),
            "solver": {"name": "SciPy-HiGHS", "version": "1.0", "solve_time_s": 0.0, "solves": 0},
            "objective": None,
            "assets": None,
            "timeseries": None,
            "metrics": None,
            "binding_constraints": [],
        }

    planned_events = [ev for ev in merged_events if ev.get("mode") != "sudden"]
    sudden_events = sorted(
        [ev for ev in merged_events if ev.get("mode") == "sudden"],
        key=lambda e: int(e["from_hour"]),
    )

    solves_count = 1
    current = _solve_lp_window(eff, planned_events, allow_unserved=allow_unserved)
    active = list(planned_events)

    if current["status"] == "optimal" and sudden_events:
        for sev in sudden_events:
            active.append(sev)
            solves_count += 1
            current = _solve_lp_window(
                eff,
                active,
                allow_unserved=allow_unserved,
                fixed_before_hour=int(sev["from_hour"]),
                locked_plan=current,
            )
            if current["status"] != "optimal":
                break

    elapsed = round(time.perf_counter() - t0, 4)
    assets_summary = {
        "batteries": [
            {
                "id": b["id"],
                "node_id": b["node_id"],
                "power_capacity_mw": float(b["power_capacity_mw"]),
                "energy_capacity_mwh": float(b["energy_capacity_mwh"]),
            }
            for b in eff["batteries"]
        ],
        "lines": [
            {"id": ln["id"], "from": ln["from"], "to": ln["to"], "capacity_mw": float(ln["capacity_mw"])}
            for ln in eff["lines"]
        ],
    }

    if current["status"] != "optimal":
        return {
            "status": current["status"],
            "message": current.get("message"),
            "scenario_id": eff.get("scenario_id", "unknown"),
            "candidate_id": cand_id,
            "modifications": applied_mods,
            "events": merged_events,
            "options": {"allow_unserved": allow_unserved},
            "time_step_hours": eff["time_step_hours"],
            "timestamps_utc": eff["timestamps_utc"],
            "solver": {"name": "SciPy-HiGHS", "version": "1.0", "solve_time_s": elapsed, "solves": solves_count},
            "objective": None,
            "assets": assets_summary,
            "timeseries": None,
            "metrics": None,
            "binding_constraints": [],
        }

    return {
        "status": "optimal",
        "message": None,
        "scenario_id": eff.get("scenario_id", "unknown"),
        "candidate_id": cand_id,
        "modifications": applied_mods,
        "events": merged_events,
        "options": {"allow_unserved": allow_unserved},
        "time_step_hours": eff["time_step_hours"],
        "timestamps_utc": eff["timestamps_utc"],
        "solver": {"name": "SciPy-HiGHS", "version": "1.0", "solve_time_s": elapsed, "solves": solves_count},
        "objective": current["objective"],
        "assets": assets_summary,
        "timeseries": current["timeseries"],
        "metrics": current["metrics"],
        "binding_constraints": current["binding_constraints"],
    }


def to_canonical_solution(native_res: dict[str, Any]) -> dict[str, Any]:
    """Convert a native solve() output into Person 4's canonical Solution schema."""
    status = native_res.get("status", "failed")
    mapped_status = "failed" if status == "error" else status
    out: dict[str, Any] = {
        "status": mapped_status,
        "generation_mw_by_generator": {},
        "curtailment_mw_by_generator": {},
        "line_flows_mw_by_line": {},
        "charge_mw_by_battery": {},
        "discharge_mw_by_battery": {},
        "soc_mwh_by_battery": {},
        "load_shedding_mw_by_node": {},
        "reason": native_res.get("message"),
        "native_result": native_res,
    }
    if mapped_status == "optimal" and native_res.get("timeseries"):
        ts = native_res["timeseries"]
        for canonical_key, native_key in CANONICAL_FIELDS.items():
            out[canonical_key] = copy.deepcopy(ts.get(native_key, {}))
    return out


def validate_solution(
    scenario: dict[str, Any],
    solution: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Independently verify a canonical or native dispatch solution against physics and policy rules."""
    opts = options or {}
    battery_policy = opts.get("battery_policy", "optimised")
    allow_shed = bool(opts.get("allow_load_shedding", opts.get("allow_unserved", False)))

    # Extract canonical series whether passed a canonical Solution or a native solution
    is_native = "timeseries" in solution and "generation_mw_by_generator" not in solution
    sol = to_canonical_solution(solution) if is_native else solution

    if sol.get("status") != "optimal":
        return {
            "passed": False,
            "violations": [sol.get("reason") or f"Solution status is {sol.get('status')!r}"],
            "max_residual_mw": 0.0,
            "metrics": None,
        }

    # Build effective scenario if modifications/events were applied in native_result
    native_inner = sol.get("native_result") or (solution if is_native else None)
    eff_scen = _normalise_to_native_scenario(scenario, opts)
    active_events: list[dict[str, Any]] = []
    if native_inner:
        mods = native_inner.get("modifications") or []
        cand_arg = None
        if mods:
            cand_arg = {
                "candidate_id": native_inner.get("candidate_id", "c1"),
                "modifications": [
                    {k: v for k, v in m.items() if k not in ("battery_id", "previous_capacity_mw")}
                    for m in mods
                ],
            }
        try:
            eff_scen, _, _, active_events = _apply_candidate_and_events(
                eff_scen, cand_arg, native_inner.get("events") or []
            )
        except ValueError as exc:
            return {
                "passed": False,
                "violations": [str(exc)],
                "max_residual_mw": 0.0,
                "metrics": None,
            }
        if native_inner.get("options") and "allow_unserved" in native_inner["options"]:
            allow_shed = bool(native_inner["options"]["allow_unserved"])

    T = len(eff_scen["timestamps_utc"])
    dt = float(eff_scen["time_step_hours"])
    errors: list[str] = []
    max_residual = 0.0

    gens = {g["id"]: g for g in eff_scen["generators"]}
    ren_avail = eff_scen.get("renewable_availability_mw_by_generator") or {}
    lines = eff_scen["lines"]
    bats = eff_scen["batteries"]
    demand = eff_scen["demand_mw_by_node"]

    gen_s = sol.get("generation_mw_by_generator") or {}
    curt_s = sol.get("curtailment_mw_by_generator") or {}
    flow_s = sol.get("line_flows_mw_by_line") or {}
    ch_s = sol.get("charge_mw_by_battery") or {}
    dis_s = sol.get("discharge_mw_by_battery") or {}
    soc_s = sol.get("soc_mwh_by_battery") or {}
    shed_s = sol.get("load_shedding_mw_by_node") or {}

    if set(gen_s) != set(gens) or any(len(v) != T for v in gen_s.values()):
        errors.append("generation_mw_by_generator: IDs or horizon mismatch")
    if set(curt_s) != set(ren_avail) or any(len(v) != T for v in curt_s.values()):
        errors.append("curtailment_mw_by_generator: IDs or horizon mismatch")
    if set(flow_s) != {ln["id"] for ln in lines} or any(len(v) != T for v in flow_s.values()):
        errors.append("line_flows_mw_by_line: IDs or horizon mismatch")
    if set(ch_s) != {b["id"] for b in bats} or any(len(v) != T for v in ch_s.values()):
        errors.append("charge_mw_by_battery: IDs or horizon mismatch")
    if set(dis_s) != {b["id"] for b in bats} or any(len(v) != T for v in dis_s.values()):
        errors.append("discharge_mw_by_battery: IDs or horizon mismatch")
    if set(soc_s) != {b["id"] for b in bats} or any(len(v) != T + 1 for v in soc_s.values()):
        errors.append("soc_mwh_by_battery: IDs or horizon mismatch")
    if set(shed_s) != set(demand) or any(len(v) != T for v in shed_s.values()):
        errors.append("load_shedding_mw_by_node: IDs or horizon mismatch")

    if errors:
        return {"passed": False, "violations": errors, "max_residual_mw": 0.0, "metrics": None}

    # Outage masks
    gen_online = {gid: [True] * T for gid in gens}
    line_online = {ln["id"]: [True] * T for ln in lines}
    for ev in active_events:
        fh, th = int(ev["from_hour"]), int(ev["to_hour"])
        if ev["type"] == "generator_outage" and ev["id"] in gen_online:
            for t in range(fh, th):
                gen_online[ev["id"]][t] = False
        elif ev["type"] == "line_outage" and ev["id"] in line_online:
            for t in range(fh, th):
                line_online[ev["id"]][t] = False

    balances = {nid: [-float(v) for v in demand[nid]] for nid in demand}
    cost = 0.0
    curtailed_energy = 0.0
    unserved_energy = 0.0

    for gid, g in gens.items():
        for t, val in enumerate(gen_s[gid]):
            cap = float(g["capacity_mw"]) if gen_online[gid][t] else 0.0
            if val < -TOL_MW or val > cap + TOL_MW:
                errors.append(f"generator {gid} at {t}: capacity")
            balances[g["node_id"]][t] += val
            cost += val * dt * float(g.get("variable_cost_usd_per_mwh", 0.0))
            if gid in ren_avail:
                c_val = curt_s[gid][t]
                av = float(ren_avail[gid][t]) if gen_online[gid][t] else 0.0
                mismatch = abs(val + c_val - av)
                max_residual = max(max_residual, mismatch)
                if c_val < -TOL_MW or mismatch > TOL_MW:
                    errors.append(f"renewable {gid} at {t}: availability/curtailment")
                curtailed_energy += c_val * dt

    for ln in lines:
        lid = ln["id"]
        for t, val in enumerate(flow_s[lid]):
            cap = float(ln["capacity_mw"]) if line_online[lid][t] else 0.0
            if abs(val) > cap + TOL_MW:
                errors.append(f"line {lid} at {t}: capacity")
            balances[ln["from"]][t] -= val
            balances[ln["to"]][t] += val

    for b in bats:
        bid = b["id"]
        vals = soc_s[bid]
        eta_c = float(b["charge_efficiency"])
        eta_d = float(b["discharge_efficiency"])
        soc0 = float(b["initial_soc_mwh"])
        exact_final = b.get("_exact_final_soc_mwh")
        if abs(vals[0] - soc0) > TOL_MW:
            errors.append(f"battery {bid}: initial SOC")
        if exact_final is not None and abs(vals[-1] - exact_final) > TOL_MW:
            errors.append(f"battery {bid}: final SOC")
        elif exact_final is None and vals[-1] < soc0 - TOL_MW:
            errors.append(f"battery {bid}: end-of-horizon SOC below initial SOC")
        if any(v < float(b.get("min_soc_mwh", 0.0)) - TOL_MW or v > float(b["energy_capacity_mwh"]) + TOL_MW for v in vals):
            errors.append(f"battery {bid}: SOC capacity")
        p_cap = float(b["power_capacity_mw"])
        for t, (ch_v, dis_v) in enumerate(zip(ch_s[bid], dis_s[bid])):
            if min(ch_v, dis_v) < -TOL_MW or max(ch_v, dis_v) > p_cap + TOL_MW:
                errors.append(f"battery {bid} at {t}: power capacity")
            if ch_v > TOL_MW and dis_v > TOL_MW:
                errors.append(f"battery {bid} at {t}: simultaneous charge/discharge")
            if battery_policy == "disabled" and max(abs(ch_v), abs(dis_v)) > TOL_MW:
                errors.append(f"battery {bid} at {t}: disabled policy")
            expected = vals[t] + dt * (eta_c * ch_v - dis_v / eta_d)
            if abs(vals[t + 1] - expected) > TOL_MW:
                errors.append(f"battery {bid} at {t}: SOC progression (MWh)")
            balances[b["node_id"]][t] += dis_v - ch_v

    for nid, dem_vals in demand.items():
        for t, val in enumerate(shed_s[nid]):
            if val < -TOL_MW or val > float(dem_vals[t]) + TOL_MW:
                errors.append(f"node {nid} at {t}: load shedding bound")
            if not allow_shed and abs(val) > TOL_MW:
                errors.append(f"node {nid} at {t}: load shedding disabled")
            balances[nid][t] += val
            unserved_energy += val * dt

    for nid, res_vals in balances.items():
        for t, val in enumerate(res_vals):
            max_residual = max(max_residual, abs(val))
            if abs(val) > TOL_MW:
                errors.append(f"node {nid} at {t}: power balance")

    curt_pen = float(scenario.get("curtailment_penalty_usd_per_mwh", eff_scen["objective"].get("curtailment_penalty_usd_per_mwh", 0.0)))
    shed_pen = float(scenario.get("load_shedding_penalty_usd_per_mwh", eff_scen["objective"].get("unserved_energy_penalty_usd_per_mwh", 10000.0)))
    total_cost = cost + curtailed_energy * curt_pen + unserved_energy * shed_pen

    metrics = (
        None
        if errors
        else {
            "curtailed_energy_mwh": round(max(0.0, curtailed_energy), 6),
            "assumed_cost_usd": round(max(0.0, total_cost), 6),
            "unserved_energy_mwh": round(max(0.0, unserved_energy), 6),
        }
    )
    return {
        "passed": not errors,
        "violations": errors,
        "max_residual_mw": round(max_residual, 9),
        "metrics": metrics,
    }


def compare_solutions(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    baseline_validation: dict[str, Any] | None = None,
    candidate_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute deterministic deltas between baseline and candidate solutions."""
    b_nat = baseline.get("native_result") or baseline
    c_nat = candidate.get("native_result") or candidate

    if b_nat.get("status") != "optimal" or c_nat.get("status") != "optimal":
        return {
            "comparable": False,
            "reason": "Both baseline and candidate must have status == 'optimal'",
            "both_valid": False,
            "curtailment_reduction_mwh": 0.0,
            "unserved_reduction_mwh": 0.0,
            "assumed_cost_delta_usd": 0.0,
        }

    b_m = b_nat.get("metrics") or {}
    c_m = c_nat.get("metrics") or {}

    if b_m and c_m and "curtailment_mwh" in b_m:
        b_curt = float(b_m["curtailment_mwh"])
        c_curt = float(c_m["curtailment_mwh"])
        b_uns = float(b_m.get("unserved_mwh", 0.0))
        c_uns = float(c_m.get("unserved_mwh", 0.0))
        b_cost = float(b_m.get("assumed_cost_proxy_usd", 0.0))
        c_cost = float(c_m.get("assumed_cost_proxy_usd", 0.0))
    else:
        b_v = (baseline_validation or {}).get("metrics") or {}
        c_v = (candidate_validation or {}).get("metrics") or {}
        b_curt = float(b_v.get("curtailed_energy_mwh", 0.0))
        c_curt = float(c_v.get("curtailed_energy_mwh", 0.0))
        b_uns = float(b_v.get("unserved_energy_mwh", 0.0))
        c_uns = float(c_v.get("unserved_energy_mwh", 0.0))
        b_cost = float(b_v.get("assumed_cost_usd", 0.0))
        c_cost = float(c_v.get("assumed_cost_usd", 0.0))

    both_valid = True
    if baseline_validation is not None and not baseline_validation.get("passed", False):
        both_valid = False
    if candidate_validation is not None and not candidate_validation.get("passed", False):
        both_valid = False

    return {
        "comparable": both_valid,
        "reason": None if both_valid else "Validation failed on baseline or candidate",
        "both_valid": both_valid,
        "curtailment_reduction_mwh": round(b_curt - c_curt, 6),
        "unserved_reduction_mwh": round(b_uns - c_uns, 6),
        "unserved_energy_delta_mwh": round(c_uns - b_uns, 6),
        "assumed_cost_delta_usd": round(c_cost - b_cost, 6),
        "baseline_metrics": {
            "curtailment_mwh": round(b_curt, 6),
            "unserved_mwh": round(b_uns, 6),
            "assumed_cost_usd": round(b_cost, 6),
        },
        "candidate_metrics": {
            "curtailment_mwh": round(c_curt, 6),
            "unserved_mwh": round(c_uns, 6),
            "assumed_cost_usd": round(c_cost, 6),
        },
    }
