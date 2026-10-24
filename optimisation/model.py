"""Multi-period dispatch LP (transport model on a radial network) solved with HiGHS.

See ``optimisation/DESIGN.md`` sections 5-7 for the formulation and output format.
"""

from __future__ import annotations

import time
from typing import Any

import highspy
import numpy as np

from .scenario import Grid, ScenarioError, build_grid, candidate_from_solution

BIND_TOL = 1e-6  # MW / MWh: how close to a limit counts as "binding"
ROUND = 6


# ---------------------------------------------------------------- LP builder


class _LP:
    """Tiny column/row accumulator passed to HiGHS in one go."""

    def __init__(self) -> None:
        self.lb: list[float] = []
        self.ub: list[float] = []
        self.cost: list[float] = []
        self.integer: list[int] = []
        self.row_lo: list[float] = []
        self.row_hi: list[float] = []
        self.row_idx: list[list[int]] = []
        self.row_val: list[list[float]] = []

    def var(self, lb: float, ub: float, cost: float = 0.0) -> int:
        self.lb.append(lb)
        self.ub.append(ub)
        self.cost.append(cost)
        return len(self.lb) - 1

    def binary(self) -> int:
        self.integer.append(self.var(0.0, 1.0))
        return self.integer[-1]

    def row(self, idx: list[int], val: list[float], lo: float, hi: float) -> int:
        self.row_idx.append(idx)
        self.row_val.append(val)
        self.row_lo.append(lo)
        self.row_hi.append(hi)
        return len(self.row_lo) - 1

    def solve(self, time_limit: float) -> tuple[str, np.ndarray | None, np.ndarray | None]:
        """Returns (status, column values, row duals). Duals are None for a MILP."""
        h = highspy.Highs()
        h.setOptionValue("output_flag", False)
        h.setOptionValue("threads", 1)
        h.setOptionValue("random_seed", 0)
        h.setOptionValue("time_limit", float(time_limit))
        n = len(self.lb)
        h.addVars(n, np.array(self.lb), np.array(self.ub))
        h.changeColsCost(n, np.arange(n, dtype=np.int32), np.array(self.cost))
        starts, index, value = [], [], []
        for idx, val in zip(self.row_idx, self.row_val):
            starts.append(len(index))
            index.extend(idx)
            value.extend(val)
        h.addRows(
            len(self.row_lo), np.array(self.row_lo), np.array(self.row_hi), len(index),
            np.array(starts, dtype=np.int32), np.array(index, dtype=np.int32), np.array(value),
        )
        if self.integer:
            h.setOptionValue("mip_rel_gap", 1e-9)
            # tight integrality so a "binary" of 1e-6 cannot leave both charge and discharge open
            h.setOptionValue("mip_feasibility_tolerance", 1e-9)
            h.changeColsIntegrality(
                len(self.integer), np.array(self.integer, dtype=np.int32),
                np.full(len(self.integer), highspy.HighsVarType.kInteger),
            )
        h.run()
        status = h.getModelStatus()
        if status == highspy.HighsModelStatus.kOptimal:
            sol = h.getSolution()
            duals = np.array(sol.row_dual) if sol.dual_valid and not self.integer else None
            return "optimal", np.array(sol.col_value), duals
        if status in (highspy.HighsModelStatus.kInfeasible, highspy.HighsModelStatus.kUnboundedOrInfeasible):
            return "infeasible", None, None
        return "error:" + h.modelStatusToString(status), None, None


# ---------------------------------------------------------------- core solve


def _simultaneous(raw: dict, pin_until: int) -> bool:
    both = np.minimum(raw["ch"][:, pin_until:], raw["dis"][:, pin_until:])
    return bool(both.size and both.max() > BIND_TOL)


def _solve_grid(grid: Grid, pinned: dict[str, np.ndarray] | None = None, pin_until: int = 0) -> tuple[str, dict | None, bool]:
    """Solve the LP; if a battery charges and discharges in the same hour, re-solve with binaries.

    Returns (status, raw values, whether the binary fallback was used). Decisions for hours
    < ``pin_until`` are fixed to ``pinned``.
    """
    status, raw = _build_and_solve(grid, pinned, pin_until, exclusive=False)
    if raw is None or not _simultaneous(raw, pin_until):
        return status, raw, False
    # Some objective weights (e.g. a curtailment penalty with no battery throughput cost) make
    # wasting energy through simultaneous charge/discharge losses "optimal". Forbid it exactly.
    status, raw = _build_and_solve(grid, pinned, pin_until, exclusive=True)
    if raw is not None:
        # Re-solve as an LP with the charge/discharge choices fixed, to obtain nodal prices.
        status_lp, raw_lp = _build_and_solve(grid, pinned, pin_until, exclusive=True, fixed_z=raw["z"])
        if raw_lp is not None:
            status, raw = status_lp, raw_lp
    return status, raw, True


def _build_and_solve(
    grid: Grid, pinned: dict[str, np.ndarray] | None, pin_until: int, exclusive: bool,
    fixed_z: np.ndarray | None = None,
) -> tuple[str, dict | None]:
    T, dt = grid.T, grid.dt
    obj = grid.objective
    voll = obj["unserved_energy_penalty_usd_per_mwh"]
    c_curt = obj["curtailment_penalty_usd_per_mwh"]
    c_thr = obj["battery_throughput_cost_usd_per_mwh"]
    allow_u = grid.options["allow_unserved"]
    G, B, L, N = len(grid.generators), len(grid.batteries), len(grid.lines), len(grid.node_ids)
    lp = _LP()

    def bounds(kind: str, i: int, t: int, lo: float, hi: float) -> tuple[float, float]:
        if pinned is not None and t < pin_until:
            v = float(np.clip(pinned[kind][i, t], lo, hi))
            return v, v
        return lo, hi

    P = np.zeros((G, T), dtype=int)
    for g, gen in enumerate(grid.generators):
        cost = dt * (-c_curt if gen["renewable"] else gen["variable_cost_usd_per_mwh"])
        for t in range(T):
            P[g, t] = lp.var(*bounds("p", g, t, 0.0, grid.avail[g, t]), cost)
    CH = np.zeros((B, T), dtype=int)
    DIS = np.zeros((B, T), dtype=int)
    SOC = np.zeros((B, T + 1), dtype=int)
    Z: list[int] = []  # charge/discharge choice variables (exclusive mode only)
    for b, bat in enumerate(grid.batteries):
        pmax = bat["power_capacity_mw"]
        for t in range(T):
            CH[b, t] = lp.var(*bounds("ch", b, t, 0.0, pmax), dt * c_thr)
            DIS[b, t] = lp.var(*bounds("dis", b, t, 0.0, pmax), dt * c_thr)
        s0 = bat["initial_soc_mwh"]
        SOC[b, 0] = lp.var(s0, s0)
        for t in range(1, T):
            SOC[b, t] = lp.var(bat["min_soc_mwh"], bat["energy_capacity_mwh"])
        if bat["final_soc_mwh"] is None:  # end at least as full as at the start
            SOC[b, T] = lp.var(max(bat["min_soc_mwh"], s0), bat["energy_capacity_mwh"])
        else:  # scenario fixes the end-of-horizon state of charge exactly
            SOC[b, T] = lp.var(bat["final_soc_mwh"], bat["final_soc_mwh"])
        if exclusive and pmax > 0:
            for t in range(pin_until if pinned is not None else 0, T):
                if fixed_z is None:
                    z = lp.binary()  # 1 = may charge, 0 = may discharge
                else:
                    v = float(round(fixed_z[len(Z)]))
                    z = lp.var(v, v)
                Z.append(z)
                lp.row([CH[b, t], z], [1.0, -pmax], -np.inf, 0.0)
                lp.row([DIS[b, t], z], [1.0, pmax], -np.inf, pmax)
    # flow f = f_pos - f_neg; a tiny cost on |f| avoids pointless transfers (e.g. shedding
    # load at one node while exporting from it), which keeps results unique and readable
    c_tx = obj["transmission_tiebreak_usd_per_mwh"]
    F = np.zeros((L, T), dtype=int)
    FP = np.zeros((L, T), dtype=int)
    FN = np.zeros((L, T), dtype=int)
    for l in range(L):
        for t in range(T):
            cap = grid.line_cap[l, t]
            F[l, t] = lp.var(*bounds("f", l, t, -cap, cap))
            FP[l, t] = lp.var(0.0, cap, dt * c_tx)
            FN[l, t] = lp.var(0.0, cap, dt * c_tx)
            lp.row([F[l, t], FP[l, t], FN[l, t]], [1.0, -1.0, 1.0], 0.0, 0.0)
    U = np.zeros((N, T), dtype=int)
    for n in range(N):
        for t in range(T):
            hi = grid.demand[n, t] if allow_u else 0.0
            U[n, t] = lp.var(*bounds("u", n, t, 0.0, hi), dt * voll)

    # nodal balance (its dual is the nodal price: cost of 1 MW more demand at that node and hour)
    BAL = np.zeros((N, T), dtype=int)
    for n, node in enumerate(grid.node_ids):
        gens = [g for g, gen in enumerate(grid.generators) if gen["node_id"] == node]
        bats = [b for b, bat in enumerate(grid.batteries) if bat["node_id"] == node]
        inn = [l for l, ln in enumerate(grid.lines) if ln["to"] == node]
        out = [l for l, ln in enumerate(grid.lines) if ln["from"] == node]
        for t in range(T):
            idx = [P[g, t] for g in gens] + [DIS[b, t] for b in bats] + [CH[b, t] for b in bats]
            val = [1.0] * len(gens) + [1.0] * len(bats) + [-1.0] * len(bats)
            idx += [F[l, t] for l in inn] + [F[l, t] for l in out] + [U[n, t]]
            val += [1.0] * len(inn) + [-1.0] * len(out) + [1.0]
            BAL[n, t] = lp.row(idx, val, grid.demand[n, t], grid.demand[n, t])
    # state of charge dynamics
    for b, bat in enumerate(grid.batteries):
        ec, ed = bat["charge_efficiency"], bat["discharge_efficiency"]
        for t in range(T):
            lp.row([SOC[b, t + 1], SOC[b, t], CH[b, t], DIS[b, t]], [1.0, -1.0, -ec * dt, dt / ed], 0.0, 0.0)
    # ramp limits (only into hours where the unit is online; a trip drops output instantly).
    # In the hour a sudden event starts, units may also drop faster than their ramp rate
    # (emergency runback / generator tripping, cf. EDAG): e.g. a plant left exporting into an
    # island after a line trip must be able to back down. Ramping up stays limited.
    # The runback beyond the ramp rate is a penalised slack, so it is only used when nothing
    # else works (it costs more than any fuel saving it could buy).
    c_rb = obj["emergency_runback_penalty_usd_per_mwh"]
    for g, gen in enumerate(grid.generators):
        ramp = gen["ramp_rate_mw_per_h"]
        if ramp is None:
            continue
        for t in range(1, T):
            if not grid.gen_online[g, t]:
                continue
            if t in grid.runback_hours:
                rb = lp.var(0.0, np.inf, dt * c_rb)
                lp.row([P[g, t], P[g, t - 1]], [1.0, -1.0], -np.inf, ramp * dt)
                lp.row([P[g, t], P[g, t - 1], rb], [1.0, -1.0, 1.0], -ramp * dt, np.inf)
            else:
                lp.row([P[g, t], P[g, t - 1]], [1.0, -1.0], -ramp * dt, ramp * dt)

    status, x, duals = lp.solve(grid.options["time_limit_s"])
    if x is None:
        return status, None
    return status, {
        "p": x[P], "ch": x[CH], "dis": x[DIS], "soc": x[SOC], "f": x[F], "u": x[U],
        "z": x[np.array(Z, dtype=int)] if Z else np.zeros(0),
        "price": None if duals is None else duals[BAL] / dt,
    }


# ---------------------------------------------------------------- outputs


def _r(x: float) -> float:
    v = round(float(x), ROUND)
    return 0.0 if v == 0 else v


def _rlist(arr: np.ndarray) -> list[float]:
    return [_r(v) for v in arr]


def _hours(mask: np.ndarray) -> list[int]:
    return [int(t) for t in np.flatnonzero(mask)]


def _binding(grid: Grid, ts: dict) -> list[dict]:
    out: list[dict] = []
    T, dt = grid.T, grid.dt

    def add(kind: str, ident: str, mask: np.ndarray, detail: str) -> None:
        hrs = _hours(mask)
        if hrs:
            out.append({"type": kind, "id": ident, "hours": hrs, "detail": detail})

    for ev in grid.events:
        out.append({"type": "outage", "id": ev["id"], "hours": list(range(ev["from_hour"], ev["to_hour"])),
                    "detail": f"{ev['mode']} {ev['type'].replace('_', ' ')}"})
    for l, ln in enumerate(grid.lines):
        f = np.array(ts["line_flow_mw"][ln["id"]])
        cap = grid.line_cap[l]
        at = (cap > 0) & (np.abs(f) >= cap - BIND_TOL)
        fwd, rev = at & (f > 0), at & (f < 0)
        add("line_limit", ln["id"], fwd, f"flow {ln['from']} -> {ln['to']} at {ln['capacity_mw']:g} MW limit")
        add("line_limit", ln["id"], rev, f"flow {ln['to']} -> {ln['from']} at {ln['capacity_mw']:g} MW limit")
    for b, bat in enumerate(grid.batteries):
        soc = np.array(ts["battery_soc_mwh"][bat["id"]])[1:]
        ch = np.array(ts["battery_charge_mw"][bat["id"]])
        dis = np.array(ts["battery_discharge_mw"][bat["id"]])
        E, P = bat["energy_capacity_mwh"], bat["power_capacity_mw"]
        if E > 0:
            add("battery_full", bat["id"], soc >= E - BIND_TOL, f"state of charge at {E:g} MWh capacity (end of hour)")
            add("battery_empty", bat["id"], soc <= bat["min_soc_mwh"] + BIND_TOL,
                f"state of charge at {bat['min_soc_mwh']:g} MWh minimum (end of hour)")
        if P > 0:
            add("battery_power_limit", bat["id"], (ch >= P - BIND_TOL) | (dis >= P - BIND_TOL),
                f"charging or discharging at {P:g} MW limit")
    for g, gen in enumerate(grid.generators):
        p = np.array(ts["generation_mw"][gen["id"]])
        if gen["renewable"]:
            add("renewable_curtailed", gen["id"], np.array(ts["curtailment_mw"][gen["id"]]) > BIND_TOL,
                "available renewable output not used")
        else:
            add("dispatchable_at_capacity", gen["id"],
                (grid.avail[g] > 0) & (p >= grid.avail[g] - BIND_TOL), f"output at {gen['capacity_mw']:g} MW capacity")
            ramp = gen["ramp_rate_mw_per_h"]
            if ramp is not None and T > 1:
                step = np.diff(p)
                runback = np.array([t in grid.runback_hours for t in range(1, T)])
                mask = np.zeros(T, dtype=bool)
                mask[1:] = (grid.gen_online[g, 1:] & (np.abs(step) >= ramp * dt - BIND_TOL) & (ramp * dt > 0)
                            & ~(runback & (step < -ramp * dt - BIND_TOL)))
                add("ramp_limit", gen["id"], mask, f"output changing at the {ramp:g} MW/h ramp limit")
                fast = np.zeros(T, dtype=bool)
                fast[1:] = grid.gen_online[g, 1:] & runback & (step < -ramp * dt - BIND_TOL)
                add("emergency_runback", gen["id"], fast,
                    f"output cut faster than the {ramp:g} MW/h ramp limit right after a sudden event")
    for n, node in enumerate(grid.node_ids):
        add("unserved_energy", node, np.array(ts["unserved_mw"][node]) > BIND_TOL, "demand not served")
    return out


def _runback_mwh(grid: Grid, ts: dict) -> float:
    """Energy by which units were cut faster than their ramp limit right after sudden events."""
    total = 0.0
    for g, gen in enumerate(grid.generators):
        ramp = gen["ramp_rate_mw_per_h"]
        if ramp is None:
            continue
        p = ts["generation_mw"][gen["id"]]
        for t in grid.runback_hours:
            if 0 < t < grid.T and grid.gen_online[g, t]:
                total += max(0.0, p[t - 1] - p[t] - ramp * grid.dt) * grid.dt
    return total


def _metrics(grid: Grid, ts: dict) -> tuple[dict, dict]:
    dt, obj = grid.dt, grid.objective
    runback = _runback_mwh(grid, ts)
    curt_by = {g["id"]: _r(sum(ts["curtailment_mw"][g["id"]]) * dt) for g in grid.generators if g["renewable"]}
    uns_by = {n: _r(sum(ts["unserved_mw"][n]) * dt) for n in grid.node_ids}
    ren_used = sum(sum(ts["generation_mw"][g["id"]]) for g in grid.generators if g["renewable"]) * dt
    disp = sum(sum(ts["generation_mw"][g["id"]]) for g in grid.generators if not g["renewable"]) * dt
    cost = sum(sum(ts["generation_mw"][g["id"]]) * g["variable_cost_usd_per_mwh"]
               for g in grid.generators if not g["renewable"]) * dt
    ch_tot = sum(sum(ts["battery_charge_mw"][b["id"]]) for b in grid.batteries) * dt
    dis_tot = sum(sum(ts["battery_discharge_mw"][b["id"]]) for b in grid.batteries) * dt
    losses = sum(
        sum(ts["battery_charge_mw"][b["id"]]) * dt * (1 - b["charge_efficiency"])
        + sum(ts["battery_discharge_mw"][b["id"]]) * dt * (1 / b["discharge_efficiency"] - 1)
        for b in grid.batteries
    )
    at_limit = {}
    for l, ln in enumerate(grid.lines):
        f = np.abs(np.array(ts["line_flow_mw"][ln["id"]]))
        at_limit[ln["id"]] = _r(float(((grid.line_cap[l] > 0) & (f >= grid.line_cap[l] - BIND_TOL)).sum()) * dt)
    curt = sum(sum(ts["curtailment_mw"][g["id"]]) for g in grid.generators if g["renewable"]) * dt
    uns = sum(sum(ts["unserved_mw"][n]) for n in grid.node_ids) * dt
    metrics = {
        "curtailment_mwh": _r(curt), "curtailment_mwh_by_generator": curt_by,
        "unserved_mwh": _r(uns), "unserved_mwh_by_node": uns_by,
        "renewable_used_mwh": _r(ren_used), "dispatchable_mwh": _r(disp),
        "demand_mwh": _r(grid.demand.sum() * dt),
        "battery_charge_mwh": _r(ch_tot), "battery_discharge_mwh": _r(dis_tot),
        "battery_losses_mwh": _r(losses),
        "assumed_cost_proxy_usd": _r(cost),
        "emergency_runback_mwh": _r(runback),
        "line_hours_at_limit": at_limit,
    }
    terms = {
        "dispatchable_cost_usd": _r(cost),
        "unserved_penalty_usd": _r(uns * obj["unserved_energy_penalty_usd_per_mwh"]),
        "curtailment_penalty_usd": _r(curt * obj["curtailment_penalty_usd_per_mwh"]),
        "battery_throughput_cost_usd": _r((ch_tot + dis_tot) * obj["battery_throughput_cost_usd_per_mwh"]),
        "transmission_tiebreak_usd": _r(
            sum(sum(abs(v) for v in ts["line_flow_mw"][ln["id"]]) for ln in grid.lines)
            * dt * obj["transmission_tiebreak_usd_per_mwh"]
        ),
        "emergency_runback_penalty_usd": _r(runback * obj["emergency_runback_penalty_usd_per_mwh"]),
    }
    return metrics, {"total_usd": _r(sum(terms.values())), "terms": terms}


def _timeseries(grid: Grid, raw: dict) -> dict:
    gens, bats, lines = grid.generators, grid.batteries, grid.lines
    gen_mw = {g["id"]: _rlist(np.clip(raw["p"][i], 0, grid.avail[i])) for i, g in enumerate(gens)}
    return {
        "generation_mw": gen_mw,
        "available_mw": {g["id"]: _rlist(grid.avail[i]) for i, g in enumerate(gens)},
        "curtailment_mw": {
            g["id"]: _rlist(np.maximum(grid.avail[i] - np.array(gen_mw[g["id"]]), 0.0))
            for i, g in enumerate(gens) if g["renewable"]
        },
        "battery_charge_mw": {b["id"]: _rlist(np.maximum(raw["ch"][i], 0)) for i, b in enumerate(bats)},
        "battery_discharge_mw": {b["id"]: _rlist(np.maximum(raw["dis"][i], 0)) for i, b in enumerate(bats)},
        "battery_soc_mwh": {b["id"]: _rlist(raw["soc"][i]) for i, b in enumerate(bats)},
        "line_flow_mw": {ln["id"]: _rlist(raw["f"][i]) for i, ln in enumerate(lines)},
        "unserved_mw": {n: _rlist(np.maximum(raw["u"][i], 0)) for i, n in enumerate(grid.node_ids)},
    }


def _infeasibility_reason(grid: Grid) -> str:
    """Name hours where some island cannot possibly meet its demand."""
    problems = []
    for t in range(grid.T):
        parent = {n: n for n in grid.node_ids}

        def find(x: str) -> str:
            while parent[x] != x:
                x = parent[x]
            return x

        for l, ln in enumerate(grid.lines):
            if grid.line_cap[l, t] > 0:
                parent[find(ln["from"])] = find(ln["to"])
        islands: dict[str, list[int]] = {}
        for i, n in enumerate(grid.node_ids):
            islands.setdefault(find(n), []).append(i)
        for members in islands.values():
            names = {grid.node_ids[i] for i in members}
            dem = grid.demand[members, t].sum()
            sup = sum(grid.avail[g, t] for g, gen in enumerate(grid.generators) if gen["node_id"] in names)
            sup += sum(b["power_capacity_mw"] for b in grid.batteries if b["node_id"] in names)
            if dem > sup + 1e-6:
                problems.append(f"hour {t}: demand {dem:.1f} MW at {sorted(names)} exceeds maximum possible supply {sup:.1f} MW")
    if problems:
        return "; ".join(problems[:6]) + ("; ..." if len(problems) > 6 else "")
    return ("demand cannot be met with the given line limits, battery energy, ramp limits and "
            "end-of-horizon state-of-charge rule")


def _envelope(scenario: dict, candidate: dict | None, events: Any, options: Any) -> dict:
    cand = candidate if isinstance(candidate, dict) else {}
    return {
        "status": "error", "message": None,
        "scenario_id": scenario.get("scenario_id") if isinstance(scenario, dict) else None,
        "candidate_id": cand.get("candidate_id", "baseline"),
        "modifications": cand.get("modifications", []),
        "events": events if isinstance(events, list) else [],
        "options": options if isinstance(options, dict) else {},
        "time_step_hours": None, "timestamps_utc": None,
        "solver": {"name": "HiGHS", "version": highspy.Highs().version(), "method": None,
                   "solve_time_s": 0.0, "solves": 0},
        "objective": None, "assets": None, "timeseries": None, "metrics": None, "binding_constraints": None,
    }


def solve(scenario: dict, candidate: dict | None = None, events: list | None = None, options: dict | None = None) -> dict:
    """Optimise the scenario (plus optional candidate and outage events). Never raises for bad input."""
    return _solve(scenario, candidate, events, options, with_prices=False)


def nodal_prices(scenario: dict, solution: dict) -> dict:
    """Nodal prices for a ``solve()`` result, recomputed on request.

    Kept out of ``solve()`` on purpose: adding a field to the shared output format breaks consumers
    that compare stored results field by field (e.g. the backend's cached replay). This re-solves
    the same inputs (candidate, events, options echoed in ``solution``) and returns the LP duals of
    the nodal balance: the cost of 1 MWh more demand at each node and hour, in USD/MWh. For hours
    before a sudden event the plan's prices are used. Informational: not independently validated.
    """
    if not isinstance(solution, dict) or solution.get("status") != "optimal":
        return {"status": "error", "message": "prices need an optimal solution", "price_usd_per_mwh": None}
    redo = _solve(scenario, candidate_from_solution(solution), solution.get("events") or [],
                  solution.get("options") or {}, with_prices=True)
    prices = (redo.get("timeseries") or {}).get("price_usd_per_mwh")
    if redo["status"] != "optimal" or prices is None:
        return {"status": "error", "message": redo.get("message") or "prices unavailable", "price_usd_per_mwh": None}
    return {"status": "optimal", "message": None, "price_usd_per_mwh": prices,
            "note": "LP marginal values (USD per MWh of extra demand); informational, not independently validated"}


def _solve(scenario, candidate, events, options, with_prices: bool) -> dict:
    out = _envelope(scenario, candidate, events, options)
    t0 = time.perf_counter()
    try:
        full = build_grid(scenario, candidate, events, options)
    except ScenarioError as exc:
        out["message"] = f"invalid input: {exc}"
        return out
    out.update(
        candidate_id=full.candidate_id, modifications=full.modifications, events=full.events,
        options=full.options, time_step_hours=full.dt, timestamps_utc=full.timestamps,
    )

    planned = [e for e in full.events if e["mode"] == "planned"]
    sudden = [e for e in full.events if e["mode"] == "sudden"]
    applied = list(planned)
    grid = build_grid(scenario, candidate, applied, options, include_scenario_events=False)
    status, raw, mip = _solve_grid(grid)
    solves = 1 + 2 * mip
    # Prices for each hour come from the solve that actually decided that hour: hours before a
    # sudden event keep the plan's prices (they are pinned, so later duals would be meaningless).
    prices = None if raw is None or raw["price"] is None else raw["price"].copy()
    stage = "plan before any sudden outage" if sudden else None
    for ev in sudden:
        if raw is None:
            break
        applied.append(ev)
        grid = build_grid(scenario, candidate, applied, options, include_scenario_events=False)
        status, raw, used = _solve_grid(grid, pinned=raw, pin_until=ev["from_hour"])
        solves += 1 + 2 * used
        mip = mip or used
        if raw is not None and prices is not None and raw["price"] is not None:
            prices[:, ev["from_hour"]:] = raw["price"][:, ev["from_hour"]:]
        else:
            prices = None
        stage = f"re-dispatch after sudden {ev['type'].replace('_', ' ')} of {ev['id']} at hour {ev['from_hour']}"
    out["solver"].update(
        solve_time_s=round(time.perf_counter() - t0, 4), solves=solves,
        method="MILP (battery charge/discharge exclusivity enforced)" if mip else "LP",
    )

    if status != "optimal":
        out["status"] = "infeasible" if status == "infeasible" else "error"
        prefix = f"{stage}: " if stage else ""
        out["message"] = prefix + (_infeasibility_reason(grid) if status == "infeasible" else f"solver returned {status[6:]}")
        return out

    ts = _timeseries(grid, raw)
    if with_prices and prices is not None:
        ts["price_usd_per_mwh"] = {n: _rlist(prices[i]) for i, n in enumerate(grid.node_ids)}
    metrics, objective = _metrics(grid, ts)
    out.update(
        status="optimal",
        objective=objective,
        assets={
            "batteries": [{k: v for k, v in b.items() if k != "added_by_candidate" or v} for b in grid.batteries],
            "lines": [{**ln, "capacity_mw": ln["capacity_mw"]} for ln in grid.lines],
        },
        timeseries=ts,
        metrics=metrics,
        binding_constraints=_binding(grid, ts),
    )
    return out

