"""Build reproducible offline fixtures, not the team's production optimiser.

This tiny reference MILP exists solely to create cached dispatch fixtures while Person 3
works independently. It is never exposed as a live solver or a Gemini agent.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import scipy
from scipy.optimize import Bounds, LinearConstraint, milp

from backend.audit import audit
from backend.models import AgentResult, Options, Scenario, Solution, wire
from backend.worker import fingerprint
from scripts.prepare_data import LANDING_URL, ROOT, SOURCE_URL, save


def make_scenario(historical=True):
    return Scenario.model_validate(
        dict(
            scenario_id="chile-demo-001" if historical else "synthetic-demo-001",
            mode="historically_anchored_simulation" if historical else "synthetic",
            time_step_hours=1,
            timestamps_utc=[f"2026-08-01T{h:02d}:00:00Z" for h in range(14, 20)],
            provenance=dict(
                observed_source_urls=[SOURCE_URL, LANDING_URL] if historical else [],
                observed_fields=["historical_event_date"] if historical else [],
                derived_fields=[],
                synthetic_fields=[
                    "network_topology",
                    "line_limits",
                    "battery_parameters",
                    "demand_mw_by_node",
                    "renewable_availability_mw_by_generator",
                    "generator_ratings",
                    "cost_parameters",
                    "timestamps_utc",
                ],
                historical_event_date="2026-08-01" if historical else None,
                evidence_id="cen-2026-08-01" if historical else None,
                notes="Historical evidence is separate context only. All dispatch inputs, including generation availability and demand, are synthetic. The network is not calibrated to Chile.",
                gaps=[
                    "Observed demand and generation have not been aligned",
                    "No actual transmission model",
                    "Observed hour boundaries unverified; simulation clock is assumed",
                ],
            ),
            nodes=[
                dict(id=i, label=label)
                for i, label in (
                    ("north", "North — illustrative"),
                    ("central", "Central — illustrative"),
                    ("south", "South — illustrative"),
                    ("coast", "Coast — illustrative"),
                )
            ],
            lines=[
                dict(id="L1", **{"from": "north", "to": "central"}, capacity_mw=60),
                dict(id="L2", **{"from": "central", "to": "south"}, capacity_mw=80),
                dict(id="L3", **{"from": "south", "to": "coast"}, capacity_mw=30),
            ],
            generators=[
                dict(
                    id="solar1",
                    node_id="north",
                    technology="solar",
                    capacity_mw=160,
                    variable_cost_usd_per_mwh=0,
                ),
                dict(
                    id="wind1",
                    node_id="coast",
                    technology="wind",
                    capacity_mw=30,
                    variable_cost_usd_per_mwh=0,
                ),
                dict(
                    id="thermal1",
                    node_id="south",
                    technology="thermal",
                    capacity_mw=150,
                    variable_cost_usd_per_mwh=65,
                ),
            ],
            batteries=[
                dict(
                    id="b1",
                    node_id="north",
                    power_capacity_mw=30,
                    energy_capacity_mwh=90,
                    initial_soc_mwh=10,
                    final_soc_mwh=10,
                    round_trip_efficiency=0.9,
                )
            ],
            demand_mw_by_node={
                "north": [20] * 6,
                "central": [30] * 6,
                "south": [50] * 6,
                "coast": [10] * 6,
            },
            renewable_availability_mw_by_generator={
                "solar1": [140, 160, 150, 70, 20, 0],
                "wind1": [15, 18, 20, 15, 12, 10],
            },
            curtailment_penalty_usd_per_mwh=1,
            load_shedding_penalty_usd_per_mwh=10000,
        )
    )


def reference_dispatch(s: Scenario, options: Options):
    n, dt = len(s.timestamps_utc), s.time_step_hours
    names, cost, lower, upper, integral = [], [], [], [], []

    def var(name, lo, hi, c=0, integer=0):
        index = len(names)
        names.append(name)
        lower.append(lo)
        upper.append(hi)
        cost.append(c)
        integral.append(integer)
        return index

    g = {
        (x.id, t): var(
            ("generation", x.id, t),
            0,
            s.renewable_availability_mw_by_generator.get(x.id, [x.capacity_mw] * n)[t],
            x.variable_cost_usd_per_mwh * dt,
        )
        for x in s.generators
        for t in range(n)
    }
    c = {
        (gid, t): var(("curtailment", gid, t), 0, v[t], s.curtailment_penalty_usd_per_mwh * dt)
        for gid, v in s.renewable_availability_mw_by_generator.items()
        for t in range(n)
    }
    f = {
        (x.id, t): var(("flow", x.id, t), -x.capacity_mw, x.capacity_mw)
        for x in s.lines
        for t in range(n)
    }
    enabled = options.battery_policy == "optimised"
    ch = {
        (b.id, t): var(("charge", b.id, t), 0, b.power_capacity_mw if enabled else 0)
        for b in s.batteries
        for t in range(n)
    }
    dis = {
        (b.id, t): var(("discharge", b.id, t), 0, b.power_capacity_mw if enabled else 0)
        for b in s.batteries
        for t in range(n)
    }
    soc = {
        (b.id, t): var(("soc", b.id, t), 0, b.energy_capacity_mwh)
        for b in s.batteries
        for t in range(n + 1)
    }
    z = {
        (b.id, t): var(("charge_mode", b.id, t), 0, 1, integer=1)
        for b in s.batteries
        for t in range(n)
    }
    rows, lows, highs = [], [], []

    def constraint(coefficients, lo, hi=None):
        row = np.zeros(len(names))
        for index, value in coefficients.items():
            row[index] = value
        rows.append(row)
        lows.append(lo)
        highs.append(lo if hi is None else hi)

    for node in s.nodes:
        for t in range(n):
            coeff = {g[x.id, t]: 1 for x in s.generators if x.node_id == node.id}
            coeff.update(
                {
                    f[x.id, t]: -1 if x.from_node == node.id else 1
                    for x in s.lines
                    if node.id in (x.from_node, x.to)
                }
            )
            coeff.update({ch[b.id, t]: -1 for b in s.batteries if b.node_id == node.id})
            coeff.update({dis[b.id, t]: 1 for b in s.batteries if b.node_id == node.id})
            constraint(coeff, s.demand_mw_by_node[node.id][t])
    for gid, values in s.renewable_availability_mw_by_generator.items():
        for t, v in enumerate(values):
            constraint({g[gid, t]: 1, c[gid, t]: 1}, v)
    for b in s.batteries:
        eta = np.sqrt(b.round_trip_efficiency)
        constraint({soc[b.id, 0]: 1}, b.initial_soc_mwh)
        constraint({soc[b.id, n]: 1}, b.final_soc_mwh)
        for t in range(n):
            constraint(
                {
                    soc[b.id, t + 1]: 1,
                    soc[b.id, t]: -1,
                    ch[b.id, t]: -dt * eta,
                    dis[b.id, t]: dt / eta,
                },
                0,
            )
            constraint({ch[b.id, t]: 1, z[b.id, t]: -b.power_capacity_mw}, -np.inf, 0)
            constraint(
                {dis[b.id, t]: 1, z[b.id, t]: b.power_capacity_mw}, -np.inf, b.power_capacity_mw
            )
    result = milp(
        np.array(cost),
        integrality=np.array(integral),
        bounds=Bounds(lower, upper),
        constraints=LinearConstraint(np.array(rows), lows, highs),
        options={"time_limit": 10, "mip_rel_gap": 0},
    )
    if not result.success:
        raise RuntimeError("Reference fixture optimisation failed")

    def output(indices, ids, count=n):
        return {i: [float(result.x[indices[i, t]]) for t in range(count)] for i in ids}

    solution = Solution(
        status="optimal",
        generation_mw_by_generator=output(g, [x.id for x in s.generators]),
        curtailment_mw_by_generator=output(c, s.renewable_availability_mw_by_generator),
        line_flows_mw_by_line=output(f, [x.id for x in s.lines]),
        charge_mw_by_battery=output(ch, [b.id for b in s.batteries]),
        discharge_mw_by_battery=output(dis, [b.id for b in s.batteries]),
        soc_mwh_by_battery=output(soc, [b.id for b in s.batteries], n + 1),
        load_shedding_mw_by_node={node.id: [0.0] * n for node in s.nodes},
    )
    checked = audit(s, solution, options)
    if not checked.passed:
        raise RuntimeError(checked.violations)
    return solution


def main():
    for historical in (True, False):
        s = make_scenario(historical)
        baseline = reference_dispatch(s, Options(battery_policy="disabled"))
        candidate = reference_dispatch(s, Options())
        result = AgentResult(
            baseline=baseline,
            candidate=candidate,
            tool_trace=[
                {
                    "tool": "load_cached_dispatch",
                    "status": "success",
                    "execution_mode": "replay",
                    "live_gemini": False,
                    "note": "Reference MILP outputs loaded from a saved fixture. No agent was executed.",
                }
            ],
            operator_report={
                "summary": "Offline reference scenario: inspect the independently verified simulated baseline and battery alternative. All dispatch inputs are synthetic.",
                "sources": s.provenance.observed_source_urls,
                "assumptions": [
                    "Transport model with no electrical losses or voltage constraints",
                    "Symmetric charge/discharge efficiency = sqrt(round-trip efficiency)",
                    "Final SOC equals initial SOC",
                    "Baseline disables battery dispatch; candidate enables existing battery; common exogenous inputs and asset ratings",
                ],
                "limitations": [
                    "Cached replay is not a live Gemini investigation",
                    "Not a reconstruction of Chilean dispatch",
                    "No claim about real savings, emissions, security or optimal real-world operation",
                ],
            },
        )
        save(ROOT / "data/demo" / f"{s.scenario_id}.scenario.json", wire(s))
        save(
            ROOT / "data/demo" / f"{s.scenario_id}.replay.json",
            dict(
                scenario_sha256=fingerprint(wire(s)),
                settings=wire(Options()),
                generator=dict(
                    script="scripts/build_demo.py",
                    scipy_version=scipy.__version__,
                    solver="SciPy milp / HiGHS",
                    scope="offline reference fixture only",
                ),
                result=wire(result),
            ),
        )
        print(
            s.scenario_id,
            wire(audit(s, baseline, Options(battery_policy="disabled"))).get("metrics"),
            wire(audit(s, candidate, Options())).get("metrics"),
        )


if __name__ == "__main__":
    main()
