"""Integration acceptance checks for the transport contract, independent of adapters.

This is a final boundary check, not the production optimiser or Person 3's validator.
It also verifies cached demonstration outputs before they can be approved.
"""

from math import sqrt

from backend.models import Metrics, Options, Scenario, Solution, Validation

TOL = 1e-6


def audit(scenario: Scenario, solution: Solution, options: Options) -> Validation:
    errors = []
    residual = 0.0
    n = len(scenario.timestamps_utc)
    dt = scenario.time_step_hours

    def fail(message):
        errors.append(message)

    if solution.status != "optimal":
        return Validation(
            passed=False, violations=[solution.reason or solution.status], max_residual_mw=0
        )

    def series(name, expected, length=n):
        values = getattr(solution, name)
        if set(values) != set(expected) or any(len(v) != length for v in values.values()):
            fail(f"{name}: IDs or horizon mismatch")
        return values

    generators = {g.id: g for g in scenario.generators}
    renewable = scenario.renewable_availability_mw_by_generator
    generation = series("generation_mw_by_generator", generators)
    curtailed = series("curtailment_mw_by_generator", renewable)
    flows = series("line_flows_mw_by_line", [x.id for x in scenario.lines])
    charge = series("charge_mw_by_battery", [b.id for b in scenario.batteries])
    discharge = series("discharge_mw_by_battery", charge)
    soc = series("soc_mwh_by_battery", charge, n + 1)
    shed = series("load_shedding_mw_by_node", scenario.demand_mw_by_node)
    if errors:
        return Validation(passed=False, violations=errors, max_residual_mw=0)
    balances = {
        node.id: [-v for v in scenario.demand_mw_by_node[node.id]] for node in scenario.nodes
    }
    cost = 0.0
    curtailed_energy = 0.0
    unserved = 0.0
    for gid, g in generators.items():
        for t, value in enumerate(generation[gid]):
            if value < -TOL or value > g.capacity_mw + TOL:
                fail(f"generator {gid} at {t}: capacity")
            balances[g.node_id][t] += value
            cost += value * dt * g.variable_cost_usd_per_mwh
            if gid in renewable:
                c = curtailed[gid][t]
                mismatch = abs(value + c - renewable[gid][t])
                residual = max(residual, mismatch)
                if c < -TOL or mismatch > TOL:
                    fail(f"renewable {gid} at {t}: availability/curtailment")
                curtailed_energy += c * dt
    for line in scenario.lines:
        for t, value in enumerate(flows[line.id]):
            if abs(value) > line.capacity_mw + TOL:
                fail(f"line {line.id} at {t}: capacity")
            balances[line.from_node][t] -= value
            balances[line.to][t] += value
    for b in scenario.batteries:
        values = soc[b.id]
        eta = sqrt(b.round_trip_efficiency)
        if abs(values[0] - b.initial_soc_mwh) > TOL or abs(values[-1] - b.final_soc_mwh) > TOL:
            fail(f"battery {b.id}: initial/final SOC")
        if any(v < -TOL or v > b.energy_capacity_mwh + TOL for v in values):
            fail(f"battery {b.id}: SOC capacity")
        for t, (c, d) in enumerate(zip(charge[b.id], discharge[b.id])):
            if min(c, d) < -TOL or max(c, d) > b.power_capacity_mw + TOL:
                fail(f"battery {b.id} at {t}: power capacity")
            if c > TOL and d > TOL:
                fail(f"battery {b.id} at {t}: simultaneous charge/discharge")
            if options.battery_policy == "disabled" and max(abs(c), abs(d)) > TOL:
                fail(f"battery {b.id} at {t}: disabled policy")
            expected = values[t] + dt * (eta * c - d / eta)
            if abs(values[t + 1] - expected) > TOL:
                fail(f"battery {b.id} at {t}: SOC progression (MWh)")
            balances[b.node_id][t] += d - c
    for node, demand in scenario.demand_mw_by_node.items():
        for t, value in enumerate(shed[node]):
            if value < -TOL or value > demand[t] + TOL:
                fail(f"node {node} at {t}: load shedding bound")
            if not options.allow_load_shedding and abs(value) > TOL:
                fail(f"node {node} at {t}: load shedding disabled")
            balances[node][t] += value
            unserved += value * dt
    for node, values in balances.items():
        for t, value in enumerate(values):
            residual = max(residual, abs(value))
            if abs(value) > TOL:
                fail(f"node {node} at {t}: power balance")
    cost += curtailed_energy * scenario.curtailment_penalty_usd_per_mwh
    cost += unserved * scenario.load_shedding_penalty_usd_per_mwh
    metrics = (
        None
        if errors
        else Metrics(
            curtailed_energy_mwh=max(0, curtailed_energy),
            assumed_cost_usd=max(0, cost),
            unserved_energy_mwh=max(0, unserved),
        )
    )
    return Validation(
        passed=not errors, violations=errors, max_residual_mw=residual, metrics=metrics
    )
