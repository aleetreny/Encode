"""Rebuild cached, independently validated outputs using the production numerical module.

No LLM is invoked. Cached outputs are always labelled replay.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import highspy

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
                    final_soc_policy="at_least",
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
            curtailment_penalty_usd_per_mwh=0,
            battery_throughput_cost_usd_per_mwh=0.5,
            load_shedding_penalty_usd_per_mwh=10000,
        )
    )


def reference_dispatch(s: Scenario, options: Options):
    from backend.p3_adapter import solve, validate

    async def compute():
        result = await solve(wire(s), wire(options))
        validation = await validate(wire(s), result, wire(options))
        if not validation["passed"]:
            raise RuntimeError(validation["violations"])
        return Solution.model_validate(result)

    return asyncio.run(compute())


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
                    "note": "Independently validated production HiGHS outputs loaded from a saved fixture. No agent was executed.",
                }
            ],
            operator_report={
                "summary": "Offline reference scenario: inspect the independently verified simulated baseline and battery alternative. All dispatch inputs are synthetic.",
                "sources": s.provenance.observed_source_urls,
                "assumptions": [
                    "Transport model with no electrical losses or voltage constraints",
                    "Symmetric charge/discharge efficiency = sqrt(round-trip efficiency)",
                    "Final SOC is at least initial SOC; no end-of-horizon battery depletion",
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
                    highs_version=highspy.Highs().version(),
                    solver="Person 3 production HiGHS LP",
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
