"""End-to-end demo of the optimisation core (no LLM involved).

Runs the investigation the agent is expected to run: baseline -> validate ->
several candidates -> validate -> compare -> stress-test with a sudden plant trip,
the same outage as planned maintenance, and a sudden line trip that islands a node.

    python -m optimisation.demo            # print results
    python -m optimisation.demo --write    # also refresh optimisation/examples/*.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import compare, load_scenario, modification_menu, solve, validate

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "demo_scenario.json"
EXAMPLES = HERE / "examples"

CANDIDATES = [
    {"candidate_id": "c1_battery_norte_grande", "description": "Battery north of the L2 bottleneck",
     "modifications": [{"type": "add_battery", "node_id": "n_norte_grande", "power_mw": 150, "energy_mwh": 600}]},
    {"candidate_id": "c2_battery_sur", "description": "Same battery, south of the bottleneck",
     "modifications": [{"type": "add_battery", "node_id": "n_sur", "power_mw": 150, "energy_mwh": 600}]},
    {"candidate_id": "c3_uprate_l2", "description": "Raise the L2 limit by 50 %",
     "modifications": [{"type": "uprate_line", "line_id": "L2", "new_capacity_mw": 600}]},
]
SUDDEN_TRIP = {"type": "generator_outage", "id": "gas_centro", "from_hour": 18, "to_hour": 22, "mode": "sudden"}
PLANNED_MAINTENANCE = {**SUDDEN_TRIP, "mode": "planned"}
SUDDEN_LINE_TRIP = {"type": "line_outage", "id": "L1", "from_hour": 6, "to_hour": 10, "mode": "sudden"}


def _row(name: str, sol: dict, val: dict) -> str:
    if sol["status"] != "optimal":
        return f"  {name:26} {sol['status']}: {sol['message']}"
    m = sol["metrics"]
    return (f"  {name:26} curtailment {m['curtailment_mwh']:8.1f} MWh | unserved {m['unserved_mwh']:7.1f} MWh | "
            f"cost proxy {m['assumed_cost_proxy_usd']:>11,.0f} USD | valid {val['passed']}")


def run(write: bool = False) -> dict:
    scen = load_scenario(FIXTURE)
    results: dict[str, dict] = {"menu": modification_menu(scen)}

    print(f"Scenario {scen['scenario_id']} ({scen['mode']}), {len(scen['timestamps_utc'])} h\n")
    print("Normal day")
    base = solve(scen)
    base_v = validate(scen, base)
    print(_row("baseline", base, base_v))
    lines = [f"{b['id']} hours {b['hours'][0]}-{b['hours'][-1]}" for b in base["binding_constraints"] if b["type"] == "line_limit"]
    print(f"  {'':26} binding lines: {', '.join(lines)}")
    results.update(solution_baseline=base, validation_baseline=base_v)

    best = None
    for cand in CANDIDATES:
        sol = solve(scen, cand)
        val = validate(scen, sol)
        cmp = compare(base, sol, base_v, val)
        print(_row(cand["candidate_id"], sol, val) + f" | curtailment reduction {cmp['curtailment_reduction_mwh']:.1f} MWh")
        if cand is CANDIDATES[0]:
            results.update(solution_candidate=sol, validation_candidate=val, comparison=cmp)
        if cmp["comparable"] and (best is None or cmp["curtailment_reduction_mwh"] > best[1]["curtailment_reduction_mwh"]):
            best = (cand, cmp)

    print("\nStress test: gas_centro trips suddenly at hour 18 (back at hour 22, ramp-limited)")
    trip_base = solve(scen, events=[SUDDEN_TRIP])
    trip_base_v = validate(scen, trip_base)
    print(_row("baseline + trip", trip_base, trip_base_v))
    for cand in CANDIDATES:
        sol = solve(scen, cand, [SUDDEN_TRIP])
        val = validate(scen, sol)
        cmp = compare(trip_base, sol, trip_base_v, val)
        print(_row(cand["candidate_id"] + " + trip", sol, val) + f" | unserved reduction {cmp['unserved_reduction_mwh']:.1f} MWh")
        if cand is CANDIDATES[0]:
            results.update(solution_sudden_outage=sol, comparison_sudden_outage=cmp)
    results.update(solution_baseline_sudden_outage=trip_base)

    print("\nPlanned maintenance: the same gas_centro outage, known from the start of the day")
    maint_base = solve(scen, events=[PLANNED_MAINTENANCE])
    maint_base_v = validate(scen, maint_base)
    print(_row("baseline + maintenance", maint_base, maint_base_v)
          + f" | vs sudden: {trip_base['metrics']['unserved_mwh'] - maint_base['metrics']['unserved_mwh']:.1f} MWh less unserved")
    for cand in CANDIDATES:
        sol = solve(scen, cand, [PLANNED_MAINTENANCE])
        val = validate(scen, sol)
        cmp = compare(maint_base, sol, maint_base_v, val)
        print(_row(cand["candidate_id"] + " + maint.", sol, val) + f" | unserved reduction {cmp['unserved_reduction_mwh']:.1f} MWh")
    results.update(solution_planned_maintenance=maint_base)

    print("\nSudden line trip: L1 opens at hour 6 and islands Norte Grande while it is exporting")
    line_trip = solve(scen, events=[SUDDEN_LINE_TRIP])
    print(_row("baseline + L1 trip", line_trip, validate(scen, line_trip))
          + f" | emergency runback {line_trip['metrics']['emergency_runback_mwh']:.1f} MWh")
    results.update(solution_sudden_line_trip=line_trip)

    strict =solve(scen, events=[SUDDEN_TRIP], options={"allow_unserved": False})
    print(f"\nStrict mode (no unserved demand allowed) with the trip: {strict['status']} - {strict['message']}")
    results.update(solution_infeasible=strict, validation_infeasible=validate(scen, strict))

    if best:
        print(f"\nLargest verified curtailment reduction: {best[0]['candidate_id']} "
              f"({best[1]['curtailment_reduction_mwh']:.1f} MWh; investment cost not modelled)")

    if write:
        EXAMPLES.mkdir(exist_ok=True)
        for name, data in results.items():
            if name.startswith("solution_"):
                data = {**data, "solver": {**data["solver"], "solve_time_s": 0.0}}  # stable files
            (EXAMPLES / f"{name}.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"\nWrote {len(results)} example files to {EXAMPLES}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="refresh optimisation/examples/*.json")
    run(write=parser.parse_args().write)


if __name__ == "__main__":
    main()
