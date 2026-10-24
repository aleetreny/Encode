"""Bridge to Person 3's published DESIGN.md at commit 932faea.

Only the common fixed-asset transport subset is accepted here. Asset modifications,
outages and ramps need their own versioned effective-scenario contract before the
backend can independently certify them. Do not discard native provenance.
"""

from math import isfinite, sqrt

from backend.audit import audit
from backend.models import Options, Scenario, Solution, Validation, wire
from backend.runtime import invoke

FIELDS = {
    "generation_mw_by_generator": "generation_mw",
    "curtailment_mw_by_generator": "curtailment_mw",
    "line_flows_mw_by_line": "line_flow_mw",
    "charge_mw_by_battery": "battery_charge_mw",
    "discharge_mw_by_battery": "battery_discharge_mw",
    "soc_mwh_by_battery": "battery_soc_mwh",
    "load_shedding_mw_by_node": "unserved_mw",
}


def native_scenario(scenario, options):
    s = Scenario.model_validate(scenario)
    policy = Options.model_validate(options)
    native = wire(s)
    native.pop("schema_version")
    native.pop("network_model")
    native.pop("curtailment_penalty_usd_per_mwh")
    native.pop("battery_throughput_cost_usd_per_mwh")
    native.pop("load_shedding_penalty_usd_per_mwh")
    native["display_timezone"] = "America/Santiago"
    native["objective"] = {
        "unserved_energy_penalty_usd_per_mwh": s.load_shedding_penalty_usd_per_mwh,
        "curtailment_penalty_usd_per_mwh": s.curtailment_penalty_usd_per_mwh,
        "battery_throughput_cost_usd_per_mwh": s.battery_throughput_cost_usd_per_mwh,
        "transmission_tiebreak_usd_per_mwh": 0,
    }
    batteries = []
    for battery in s.batteries:
        if battery.final_soc_mwh != battery.initial_soc_mwh:
            raise ValueError("P3 bridge currently requires final SOC equal to initial SOC")
        item = wire(battery)
        item.pop("final_soc_mwh")
        item.pop("final_soc_policy")
        item.pop("round_trip_efficiency")
        item.update(
            min_soc_mwh=0,
            charge_efficiency=sqrt(battery.round_trip_efficiency),
            discharge_efficiency=sqrt(battery.round_trip_efficiency),
        )
        if policy.battery_policy == "disabled":
            # Policy constraint only; the canonical scenario's physical rating is unchanged.
            item["power_capacity_mw"] = 0
        batteries.append(item)
    native["batteries"] = batteries
    return native


def canonical_solution(native):
    if native.get("modifications") or native.get("events"):
        raise ValueError("Native modifications/events require an extended acceptance contract")
    status = native["status"]
    if status not in ("optimal", "infeasible", "error"):
        raise ValueError("Unknown native solver status")
    data = dict(
        status="failed" if status == "error" else status,
        reason=native.get("message"),
        native_result=native,
    )
    if status == "optimal":
        timeseries = native["timeseries"]
        for canonical, source in FIELDS.items():
            data[canonical] = timeseries[source]
    return Solution.model_validate(data)


async def solve(scenario, options):
    native = await invoke(
        "optimisation:solve",
        native_scenario(scenario, options),
        options={"allow_unserved": options.get("allow_load_shedding", False)},
    )
    return wire(canonical_solution(native))


async def validate(scenario, solution, options):
    s, policy = Scenario.model_validate(scenario), Options.model_validate(options)
    candidate = Solution.model_validate(solution)
    if candidate.native_result is None:
        return wire(
            Validation(
                passed=False,
                violations=["Native solver envelope is required for P3 validation"],
                max_residual_mw=0,
            )
        )
    reconstructed = canonical_solution(candidate.native_result)
    for field in FIELDS:
        if getattr(candidate, field) != getattr(reconstructed, field):
            return wire(
                Validation(
                    passed=False,
                    violations=["Canonical arrays differ from retained native solver output"],
                    max_residual_mw=0,
                )
            )
    native = await invoke(
        "optimisation:validate", native_scenario(scenario, options), candidate.native_result
    )
    checked = audit(s, candidate, policy)
    residual = float(native.get("max_residual_mw", 0))
    if not isfinite(residual) or residual < 0:
        raise ValueError("Native validator returned an invalid residual")
    if native.get("passed") is not True or native.get("violations"):
        checked.passed = False
        checked.metrics = None
        checked.violations.extend(str(v) for v in native.get("violations", []))
        if not checked.violations:
            checked.violations.append("Person 3 independent validator rejected the solution")
    checked.max_residual_mw = max(checked.max_residual_mw, residual)
    return wire(checked)


solve.required_callables = ("optimisation:solve",)
validate.required_callables = ("optimisation:validate",)
