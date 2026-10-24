"""Native v2 worker protocol; preserves native arrays and verifies crisis results."""

import copy
import json

from optimisation import compare

from backend.models import wire, utc_now
from backend.native_models import Candidate, InvestigationSettings, NativeOptions, NativeScenario
from backend.native_service import (
    candidate_from_solution,
    check_solution,
    computational_settings,
    household_impact,
    investigate,
    operator_report,
    solve_checked,
)
from backend.runtime import _active_evidence, _active_scenario, invoke


def _failure(code, message):
    return dict(
        status="failed",
        approval_status="unavailable",
        error=dict(code=code, message=message),
        comparison=None,
        validation=dict(passed=False, violations=[message], max_residual_mw=0),
    )


def verified_bundle(scenario, bundle):
    result = copy.deepcopy(bundle)
    candidate = result["candidate_definition"]
    plan = result["computational_settings"]
    options = plan["options"]
    events = plan["crisis_events"]
    crisis = result["crisis_analysis"]
    pairs = [
        (result["baseline"], None, []),
        (result["candidate"], candidate, []),
        (crisis["baseline"], None, events),
        (crisis["candidate"], candidate, events),
    ]
    checks = [check_solution(scenario, s, c, e, options) for s, c, e in pairs]
    if not all(c["passed"] for c in checks):
        raise ValueError("cached or agent-supplied normal/crisis solution failed verification")
    for (solution, _, _), checked in zip(pairs, checks):
        solution["validation"] = checked
        solution["accepted"] = checked["passed"]
    result["comparison"] = compare(result["baseline"], result["candidate"], checks[0], checks[1])
    crisis["comparison"] = compare(crisis["baseline"], crisis["candidate"], checks[2], checks[3])
    crisis.update(
        baseline_unserved_mwh=crisis["baseline"]["metrics"]["unserved_mwh"],
        candidate_unserved_mwh=crisis["candidate"]["metrics"]["unserved_mwh"],
        unserved_reduction_mwh=crisis["comparison"]["unserved_reduction_mwh"],
        household_impact=household_impact(
            scenario, crisis["baseline"], crisis["candidate"], events
        ),
    )
    crisis["estimated_households_reconnected"] = crisis["household_impact"][
        "average_households_reconnected_equivalent"
    ]
    for evaluation in result.get("candidate_evaluations", []):
        checked = check_solution(
            scenario, evaluation["solution"], evaluation["candidate_definition"], [], options
        )
        evaluation["solution"]["validation"] = checked
        evaluation["solution"]["accepted"] = checked["passed"]
        evaluation["comparison"] = compare(
            result["baseline"], evaluation["solution"], checks[0], checked
        )
    for evaluation in crisis.get("candidate_evaluations", []):
        checked = check_solution(
            scenario,
            evaluation["solution"],
            evaluation["normal"]["candidate_definition"],
            events,
            options,
        )
        evaluation["solution"]["validation"] = checked
        evaluation["solution"]["accepted"] = checked["passed"]
        evaluation["comparison"] = compare(
            crisis["baseline"], evaluation["solution"], checks[2], checked
        )
    result["validation"] = dict(
        passed=True,
        violations=[],
        max_residual_mw=max(c["max_residual_mw"] for c in checks),
        normal_baseline=checks[0],
        normal_candidate=checks[1],
        crisis_baseline=checks[2],
        crisis_candidate=checks[3],
    )
    return result


async def execute(payload, settings):
    from backend.worker import fingerprint

    scenario = wire(NativeScenario.model_validate(payload["scenario"]))
    _active_scenario.set(scenario)
    _active_evidence.set(payload.get("evidence_snapshot"))
    operation = payload["operation"]
    if operation == "native_solve":
        return solve_checked(
            scenario,
            payload.get("candidate"),
            payload.get("events", []),
            payload.get("options", wire(NativeOptions())),
        )
    if operation == "native_validate":
        return check_solution(
            scenario,
            payload["solution"],
            payload.get("candidate"),
            payload.get("events"),
            payload.get("options"),
        )
    if operation == "native_compare":
        from backend.runtime import compare_results

        return compare_results(payload["baseline"], payload["candidate"])
    request_settings = wire(InvestigationSettings.model_validate(payload.get("settings", {})))
    plan = computational_settings(scenario, request_settings)
    mode = payload["execution_mode"]
    provider = None
    narrative = None
    agent_trace = []
    if mode == "replay":
        cache = json.loads(
            (
                settings.data_dir / "demo" / f"{scenario['scenario_id']}.native-replay.json"
            ).read_text()
        )
        if (
            cache["scenario_sha256"] != fingerprint(scenario)
            or cache["computational_settings"] != plan
            or cache["bundle"]["computational_settings"] != plan
        ):
            return _failure(
                "replay_mismatch",
                "Native replay does not match the requested scenario, candidates, events and options",
            )
        bundle = verified_bundle(scenario, cache["bundle"])
    elif mode == "deterministic":
        bundle = investigate(scenario, request_settings)
    else:
        agent_result = await invoke(
            settings.agent_callable, scenario["scenario_id"], request_settings
        )
        provider = agent_result.get("model_execution")
        trace = agent_result.get("tool_trace", [])
        required = {
            "load_scenario",
            "inspect_evidence",
            "run_optimisation",
            "validate_candidate",
            "compare_results",
            "generate_operator_report",
        }
        if (
            not provider
            or provider.get("provider") != "google"
            or not provider.get("response_id")
            or not provider.get("model")
        ):
            return _failure(
                "unverified_live_trace",
                "Actual Google provider/model/response metadata is required",
            )
        if (
            len(trace) > 100
            or not required.issubset({e.get("tool") for e in trace if e.get("status") == "success"})
            or any(not e.get("timestamp_utc") or e.get("execution_mode") == "replay" for e in trace)
        ):
            return _failure(
                "unverified_live_trace", "A complete timestamped live tool trace is required"
            )
        selected = agent_result.get("candidate_definition") or candidate_from_solution(
            agent_result["candidate"]
        )
        if selected is None:
            return _failure("missing_candidate", "Agent must select a bounded asset intervention")
        selected = wire(Candidate.model_validate(selected))
        for solution, candidate in (
            (agent_result["baseline"], None),
            (agent_result["candidate"], selected),
        ):
            if not check_solution(scenario, solution, candidate, [], plan["options"])["passed"]:
                return _failure(
                    "verification_failed",
                    "Agent-supplied normal dispatch failed independent native validation",
                )
        bundle = investigate(scenario, request_settings, selected_candidate=selected)
        narrative = agent_result.get("operator_report")
        allowed = (
            "step",
            "tool",
            "label",
            "status",
            "timestamp_utc",
            "input_summary",
            "output_summary",
        )
        agent_trace = [{k: v for k, v in e.items() if k in allowed} for e in trace]
    governance_mode = payload.get("governance_mode", "operator_approval")
    report = operator_report(scenario, bundle)
    if narrative is not None:
        report.update(
            agent_commentary=narrative,
            agent_commentary_status="Generated narrative; authoritative numbers are the verified native results",
        )
    evidence = payload.get("evidence_snapshot")
    if evidence is None and scenario["provenance"].get("evidence_id"):
        try:
            evidence = json.loads(
                (
                    settings.data_dir
                    / "processed"
                    / f"{scenario['provenance']['evidence_id']}.evidence.json"
                ).read_text()
            )
        except FileNotFoundError:
            if scenario["mode"] != "synthetic":
                raise
    trace = agent_trace + [
        dict(e, execution_mode=mode, live_gemini=False) for e in bundle["tool_trace"]
    ]
    trace.append(
        dict(
            tool="generate_operator_report",
            status="success",
            driver="deterministic_backend",
            execution_mode=mode,
            timestamp_utc=payload.get("recorded_at_utc") or utc_now(),
        )
    )
    return dict(
        status="completed",
        execution_mode=mode,
        governance_mode=governance_mode,
        provenance=dict(
            mode=scenario["mode"],
            execution_mode=mode,
            live_gemini=mode == "live",
            model_execution=provider,
            scenario_sha256=fingerprint(scenario),
            data=scenario["provenance"],
            requested_settings=request_settings,
            comparison_basis="bounded_asset_modifications_with_common_exogenous_inputs_and_events",
        ),
        scenario_snapshot=scenario,
        historical_evidence=evidence,
        tool_trace=trace,
        baseline=bundle["baseline"],
        candidate=bundle["candidate"],
        comparison=bundle["comparison"],
        candidate_evaluations=bundle["candidate_evaluations"],
        crisis_analysis=bundle["crisis_analysis"],
        validation=bundle["validation"],
        operator_report=report,
        approval_status="pending",
        error=None,
        governance=dict(
            normal_dispatch="applied_in_simulation"
            if governance_mode == "autonomous_sced_with_audit_gate"
            else "awaiting_operator_approval",
            crisis_recovery="awaiting_operator_approval",
            scope="simulation_only",
            real_world_actions=False,
        ),
    )
