"""Test-only doubles. Never configured by deployment."""

import json
import time

from backend.audit import audit
from backend.config import ROOT
from backend.models import Options, Scenario, Solution, wire


def solve(scenario, options):
    data = json.loads((ROOT / "data/demo/chile-demo-001.replay.json").read_text())
    return data["result"]["baseline" if options["battery_policy"] == "disabled" else "candidate"]


def validate(scenario, solution, options):
    return wire(
        audit(
            Scenario.model_validate(scenario),
            Solution.model_validate(solution),
            Options.model_validate(options),
        )
    )


def investigate(scenario_id, settings):
    result = json.loads((ROOT / "data/demo/chile-demo-001.replay.json").read_text())["result"]
    result["model_execution"] = dict(
        provider="google", model="test-double", response_id="not-a-real-provider-response"
    )
    result["tool_trace"] = [
        dict(
            tool=name, status="success", timestamp_utc="2026-10-24T12:00:00Z", execution_mode="live"
        )
        for name in (
            "load_scenario",
            "inspect_evidence",
            "run_optimisation",
            "validate_candidate",
            "compare_results",
            "generate_operator_report",
        )
    ]
    return result


def reject(scenario, solution, options):
    return dict(
        passed=False,
        violations=["test rejection by independent validator"],
        max_residual_mw=0,
        metrics=None,
    )


def slow(*args):
    time.sleep(10)


def broken(*args):
    raise RuntimeError("SECRET_PROVIDER_KEY_DO_NOT_EXPOSE")


def infeasible(scenario, options):
    return {"status": "infeasible", "reason": "test insufficient supply"}


async def async_solve(scenario, options):
    return solve(scenario, options)


def unattested(scenario_id, settings):
    return json.loads((ROOT / "data/demo/chile-demo-001.replay.json").read_text())["result"]


def invalid_solution(scenario, options):
    solution = solve(scenario, options)
    solution["line_flows_mw_by_line"]["L1"][0] = 999
    return solution
