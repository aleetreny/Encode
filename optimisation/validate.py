"""Independent validator for dispatch solutions.

This module deliberately does NOT import ``model.py``. It rebuilds the effective
grid from the raw scenario plus what the solution says was applied (candidate,
events, options) and re-checks every physical rule and every reported metric
from the numbers alone. See ``optimisation/DESIGN.md`` section 8.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .scenario import Grid, ScenarioError, build_grid

TOL_MW = 1e-4  # power / energy balance tolerance (MW or MWh)
TOL_REL = 1e-6  # relative tolerance for reported metrics
TOL_ABS_METRIC = 1e-3


class _Report:
    def __init__(self) -> None:
        self.violations: list[dict] = []
        self.checks: list[str] = []
        self.max_residual = 0.0

    def check(self, name: str) -> None:
        if name not in self.checks:
            self.checks.append(name)

    def fail(self, check: str, ident: str | None, hour: int | None, magnitude: float, detail: str) -> None:
        self.check(check)
        self.violations.append(
            {"check": check, "id": ident, "hour": hour, "magnitude": round(float(magnitude), 9), "detail": detail}
        )

    def residual(self, value: float) -> None:
        self.max_residual = max(self.max_residual, float(value))

    def result(self) -> dict:
        return {
            "passed": not self.violations,
            "checks_run": self.checks,
            "violations": self.violations[:200],
            "violation_count": len(self.violations),
            "max_residual_mw": round(self.max_residual, 9),
        }


def _series(rep: _Report, block: Any, ident: str, length: int, where: str) -> np.ndarray | None:
    rep.check("shape")
    if not isinstance(block, dict) or ident not in block:
        rep.fail("shape", ident, None, 0.0, f"{where} is missing series for {ident}")
        return None
    vals = block[ident]
    if not isinstance(vals, list) or len(vals) != length:
        rep.fail("shape", ident, None, 0.0, f"{where}.{ident} must have {length} values")
        return None
    try:
        arr = np.array(vals, dtype=float)
    except (TypeError, ValueError):
        rep.fail("shape", ident, None, 0.0, f"{where}.{ident} contains non-numbers")
        return None
    if not np.isfinite(arr).all():
        rep.fail("shape", ident, None, 0.0, f"{where}.{ident} contains NaN or infinity")
        return None
    return arr


def _over(rep: _Report, check: str, ident: str, excess: np.ndarray, what: str) -> None:
    for t in np.flatnonzero(excess > TOL_MW):
        rep.fail(check, ident, int(t), excess[t], what)


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= TOL_ABS_METRIC + TOL_REL * max(abs(a), abs(b))


def _rebuild(scenario: dict, solution: dict) -> Grid:
    mods = solution.get("modifications") or []
    candidate = None
    if solution.get("candidate_id", "baseline") != "baseline" or mods:
        candidate = {
            "candidate_id": solution.get("candidate_id"),
            "modifications": [
                {k: v for k, v in m.items() if k not in ("battery_id", "previous_capacity_mw")} for m in mods
            ],
        }
    return build_grid(
        scenario, candidate, solution.get("events") or [], solution.get("options") or {},
        include_scenario_events=False,
    )


def validate(scenario: dict, solution: dict) -> dict:
    """Check a ``solve()`` output against the scenario. Returns a pass/fail report."""
    rep = _Report()
    rep.check("status")
    if not isinstance(solution, dict):
        rep.fail("status", None, None, 0.0, "solution must be an object")
        return rep.result()
    if solution.get("status") != "optimal":
        rep.fail("status", None, None, 0.0,
                 f"solution status is {solution.get('status')!r}: {solution.get('message') or 'no feasible dispatch'}")
        return rep.result()

    rep.check("inputs")
    try:
        grid = _rebuild(scenario, solution)
    except ScenarioError as exc:
        rep.fail("inputs", None, None, 0.0, f"cannot rebuild the scenario this solution claims: {exc}")
        return rep.result()

    rep.check("events_consistent")
    try:
        scenario_events = build_grid(scenario).events
    except ScenarioError as exc:
        rep.fail("inputs", None, None, 0.0, str(exc))
        return rep.result()
    for ev in scenario_events:
        if ev not in grid.events:
            rep.fail("events_consistent", ev["id"], ev["from_hour"], 0.0,
                     "an outage defined in the scenario is missing from the solution")
    if solution.get("scenario_id") != grid.scenario_id:
        rep.fail("events_consistent", None, None, 0.0, "solution scenario_id does not match the scenario")

    T, dt = grid.T, grid.dt
    if solution.get("time_step_hours") != dt or solution.get("timestamps_utc") != grid.timestamps:
        rep.fail("shape", None, None, 0.0, "time axis differs from the scenario")
    ts = solution.get("timeseries") or {}

    gens, bats, lines = grid.generators, grid.batteries, grid.lines
    p = {g["id"]: _series(rep, ts.get("generation_mw"), g["id"], T, "generation_mw") for g in gens}
    ch = {b["id"]: _series(rep, ts.get("battery_charge_mw"), b["id"], T, "battery_charge_mw") for b in bats}
    dis = {b["id"]: _series(rep, ts.get("battery_discharge_mw"), b["id"], T, "battery_discharge_mw") for b in bats}
    soc = {b["id"]: _series(rep, ts.get("battery_soc_mwh"), b["id"], T + 1, "battery_soc_mwh") for b in bats}
    f = {ln["id"]: _series(rep, ts.get("line_flow_mw"), ln["id"], T, "line_flow_mw") for ln in lines}
    u = {n: _series(rep, ts.get("unserved_mw"), n, T, "unserved_mw") for n in grid.node_ids}
    curt = {g["id"]: _series(rep, ts.get("curtailment_mw"), g["id"], T, "curtailment_mw") for g in gens if g["renewable"]}
    series = [*p.values(), *ch.values(), *dis.values(), *soc.values(), *f.values(), *u.values(), *curt.values()]
    if any(s is None for s in series):
        return rep.result()

    # generators
    rep.check("generator_bounds")
    for i, g in enumerate(gens):
        _over(rep, "generator_bounds", g["id"], -p[g["id"]], "negative generation")
        _over(rep, "generator_bounds", g["id"], p[g["id"]] - grid.avail[i], "generation above availability (or during outage)")
    rep.check("curtailment_consistency")
    for i, g in enumerate(gens):
        if g["renewable"]:
            diff = np.abs(curt[g["id"]] - (grid.avail[i] - p[g["id"]]))
            _over(rep, "curtailment_consistency", g["id"], diff, "curtailment != available - generation")

    # batteries
    for check in ("battery_bounds", "soc_initial", "soc_dynamics", "soc_final", "simultaneous_charge_discharge"):
        rep.check(check)
    for b in bats:
        bid, P, E = b["id"], b["power_capacity_mw"], b["energy_capacity_mwh"]
        c, d, s = ch[bid], dis[bid], soc[bid]
        for arr, what in ((c, "charge"), (d, "discharge")):
            _over(rep, "battery_bounds", bid, -arr, f"negative {what}")
            _over(rep, "battery_bounds", bid, arr - P, f"{what} above {P:g} MW")
        _over(rep, "battery_bounds", bid, s - E, f"state of charge above {E:g} MWh")
        _over(rep, "battery_bounds", bid, b["min_soc_mwh"] - s, f"state of charge below {b['min_soc_mwh']:g} MWh")
        if abs(s[0] - b["initial_soc_mwh"]) > TOL_MW:
            rep.fail("soc_initial", bid, 0, abs(s[0] - b["initial_soc_mwh"]), "initial state of charge differs from the scenario")
        expected = s[:-1] + b["charge_efficiency"] * c * dt - d * dt / b["discharge_efficiency"]
        resid = np.abs(s[1:] - expected)
        rep.residual(resid.max(initial=0.0))
        _over(rep, "soc_dynamics", bid, resid, "state of charge does not follow charge/discharge")
        if s[-1] < b["initial_soc_mwh"] - TOL_MW:
            rep.fail("soc_final", bid, T, b["initial_soc_mwh"] - s[-1], "battery ends the horizon below its initial charge")
        _over(rep, "simultaneous_charge_discharge", bid, np.minimum(c, d), "charging and discharging in the same hour")

    # lines
    rep.check("line_limits")
    for l, ln in enumerate(lines):
        _over(rep, "line_limits", ln["id"], np.abs(f[ln["id"]]) - grid.line_cap[l], "flow above line limit (or on an outaged line)")

    # unserved
    rep.check("unserved_bounds")
    allow_u = grid.options["allow_unserved"]
    for n_i, n in enumerate(grid.node_ids):
        _over(rep, "unserved_bounds", n, -u[n], "negative unserved demand")
        cap = grid.demand[n_i] if allow_u else np.zeros(T)
        _over(rep, "unserved_bounds", n, u[n] - cap,
              "unserved demand above demand" if allow_u else "unserved demand while not allowed")

    # nodal balance
    rep.check("nodal_balance")
    for n_i, n in enumerate(grid.node_ids):
        net = u[n].copy()
        for g in gens:
            if g["node_id"] == n:
                net += p[g["id"]]
        for b in bats:
            if b["node_id"] == n:
                net += dis[b["id"]] - ch[b["id"]]
        for ln in lines:
            if ln["to"] == n:
                net += f[ln["id"]]
            if ln["from"] == n:
                net -= f[ln["id"]]
        resid = np.abs(net - grid.demand[n_i])
        rep.residual(resid.max(initial=0.0))
        _over(rep, "nodal_balance", n, resid, "supply + imports - exports - demand != 0")

    # ramps
    rep.check("ramp_limits")
    for i, g in enumerate(gens):
        r = g["ramp_rate_mw_per_h"]
        if r is None:
            continue
        step = np.abs(np.diff(p[g["id"]]))
        online = grid.gen_online[i, 1:]
        excess = np.where(online, step - r * dt, 0.0)
        for t in np.flatnonzero(excess > TOL_MW):
            rep.fail("ramp_limits", g["id"], int(t) + 1, excess[t], f"output changes faster than {r:g} MW/h")

    # metrics
    rep.check("metrics_recomputed")
    _check_metrics(rep, grid, solution, p, ch, dis, f, u, curt)
    return rep.result()


def _check_metrics(rep, grid, solution, p, ch, dis, f, u, curt) -> None:
    dt, obj = grid.dt, grid.objective
    gens, bats = grid.generators, grid.batteries
    m = solution.get("metrics") or {}
    o = (solution.get("objective") or {})
    terms = o.get("terms") or {}
    curt_mwh = sum(float(curt[g].sum()) for g in curt) * dt
    uns_mwh = sum(float(u[n].sum()) for n in u) * dt
    ren = sum(float(p[g["id"]].sum()) for g in gens if g["renewable"]) * dt
    disp = sum(float(p[g["id"]].sum()) for g in gens if not g["renewable"]) * dt
    cost = sum(float(p[g["id"]].sum()) * g["variable_cost_usd_per_mwh"] for g in gens if not g["renewable"]) * dt
    ch_tot = sum(float(ch[b["id"]].sum()) for b in bats) * dt
    dis_tot = sum(float(dis[b["id"]].sum()) for b in bats) * dt
    losses = sum(
        float(ch[b["id"]].sum()) * dt * (1 - b["charge_efficiency"])
        + float(dis[b["id"]].sum()) * dt * (1 / b["discharge_efficiency"] - 1)
        for b in bats
    )
    expected = {
        "curtailment_mwh": curt_mwh,
        "unserved_mwh": uns_mwh,
        "renewable_used_mwh": ren,
        "dispatchable_mwh": disp,
        "demand_mwh": float(grid.demand.sum()) * dt,
        "battery_charge_mwh": ch_tot,
        "battery_discharge_mwh": dis_tot,
        "battery_losses_mwh": losses,
        "assumed_cost_proxy_usd": cost,
    }
    for key, val in expected.items():
        got = m.get(key)
        if not isinstance(got, (int, float)) or not math.isfinite(got) or not _close(float(got), val):
            rep.fail("metrics_recomputed", key, None, abs((got or 0) - val) if isinstance(got, (int, float)) else val,
                     f"reported {key}={got!r}, recomputed {val:.6f}")
    for g in curt:
        got = (m.get("curtailment_mwh_by_generator") or {}).get(g)
        val = float(curt[g].sum()) * dt
        if not isinstance(got, (int, float)) or not _close(float(got), val):
            rep.fail("metrics_recomputed", g, None, val, f"curtailment_mwh_by_generator.{g}={got!r}, recomputed {val:.6f}")
    for n in u:
        got = (m.get("unserved_mwh_by_node") or {}).get(n)
        val = float(u[n].sum()) * dt
        if not isinstance(got, (int, float)) or not _close(float(got), val):
            rep.fail("metrics_recomputed", n, None, val, f"unserved_mwh_by_node.{n}={got!r}, recomputed {val:.6f}")
    # energy conservation over the whole system
    supply = ren + disp + dis_tot - ch_tot + uns_mwh
    resid = abs(supply - float(grid.demand.sum()) * dt)
    if resid > TOL_MW * grid.T * max(1, len(grid.node_ids)):
        rep.fail("metrics_recomputed", "energy_conservation", None, resid, "total supply != total demand")
    exp_terms = {
        "dispatchable_cost_usd": cost,
        "unserved_penalty_usd": uns_mwh * obj["unserved_energy_penalty_usd_per_mwh"],
        "curtailment_penalty_usd": curt_mwh * obj["curtailment_penalty_usd_per_mwh"],
        "battery_throughput_cost_usd": (ch_tot + dis_tot) * obj["battery_throughput_cost_usd_per_mwh"],
        "transmission_tiebreak_usd": sum(float(np.abs(f[k]).sum()) for k in f)
        * dt * obj["transmission_tiebreak_usd_per_mwh"],
    }
    for key, val in exp_terms.items():
        got = terms.get(key)
        if not isinstance(got, (int, float)) or not _close(float(got), val):
            rep.fail("metrics_recomputed", key, None, val, f"objective term {key}={got!r}, recomputed {val:.6f}")
    total = o.get("total_usd")
    if not isinstance(total, (int, float)) or not _close(float(total), sum(exp_terms.values())):
        rep.fail("metrics_recomputed", "total_usd", None, 0.0, f"objective total {total!r} != sum of recomputed terms")
