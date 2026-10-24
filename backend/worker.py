"""Isolated invocation process. Only protocol JSON goes to stdout."""

import asyncio
import contextlib
import hashlib
import json
import sys

from backend.audit import audit
from backend.config import Settings
from backend.models import AgentResult, Options, Scenario, Solution, Validation, wire
from backend.runtime import _active_evidence, _active_scenario, invoke


def fingerprint(document):
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def failure(code, message, violations=None):
    return dict(
        status="failed",
        approval_status="unavailable",
        comparison=None,
        validation=dict(passed=False, violations=violations or [message], max_residual_mw=0),
        error=dict(code=code, message=message),
    )


async def execute(payload, settings=None):
    settings = settings or Settings()
    scenario = Scenario.model_validate(payload["scenario"])
    operation = payload["operation"]
    options = Options.model_validate(payload.get("options", {}))
    scenario_json = wire(scenario)
    _active_scenario.set(scenario_json)
    _active_evidence.set(payload.get("evidence_snapshot"))
    if operation == "solve":
        solution = Solution.model_validate(
            await invoke(settings.solve_callable, scenario_json, wire(options))
        )
        checked = audit(scenario, solution, options)
        if solution.status == "optimal" and not checked.passed:
            return dict(status="failed", solution=wire(solution), validation=wire(checked))
        return dict(status=solution.status, solution=wire(solution), validation=wire(checked))
    if operation == "validate":
        solution = Solution.model_validate(payload["solution"])
        external = Validation.model_validate(
            await invoke(settings.validate_callable, scenario_json, wire(solution), wire(options))
        )
        checked = audit(scenario, solution, options)
        if not external.passed:
            checked.passed = False
            checked.violations.extend(
                external.violations or ["external validator rejected solution"]
            )
            checked.metrics = None
        return wire(checked)
    if payload["execution_mode"] == "replay":
        path = settings.data_dir / "demo" / f"{scenario.scenario_id}.replay.json"
        replay = json.loads(path.read_text())
        if replay["scenario_sha256"] != fingerprint(scenario_json) or replay["settings"] != wire(
            options
        ):
            return failure(
                "replay_mismatch", "Cached replay does not match scenario and requested settings"
            )
        result = AgentResult.model_validate(replay["result"])
        provenance = {
            "execution_mode": "replay",
            "live_gemini": False,
            "replay_sha256": fingerprint(replay),
        }
    else:
        result = AgentResult.model_validate(
            await invoke(settings.agent_callable, scenario.scenario_id, wire(options))
        )
        required = {
            "load_scenario",
            "inspect_evidence",
            "run_optimisation",
            "validate_candidate",
            "compare_results",
            "generate_operator_report",
        }
        successful = {event.tool for event in result.tool_trace if event.status == "success"}
        if (
            not result.model_execution
            or not required.issubset(successful)
            or any(
                event.timestamp_utc is None or event.execution_mode == "replay"
                for event in result.tool_trace
            )
        ):
            return failure(
                "unverified_live_trace",
                "Live mode requires provider response metadata and timestamped successful investigation tools",
            )
        provenance = {
            "execution_mode": "live",
            "live_gemini": True,
            "model_execution": wire(result.model_execution),
            "agent_adapter": settings.agent_callable,
            "attestation_note": "Provider execution metadata supplied by the installed agent adapter; no independent provider billing verification.",
        }
    baseline_options = Options(
        battery_policy="disabled", allow_load_shedding=options.allow_load_shedding
    )
    checked = []
    for solution, policy in ((result.baseline, baseline_options), (result.candidate, options)):
        validation = audit(scenario, solution, policy)
        if payload["execution_mode"] == "live":
            external = Validation.model_validate(
                await invoke(
                    settings.validate_callable, scenario_json, wire(solution), wire(policy)
                )
            )
            if not external.passed:
                validation.passed = False
                validation.violations.extend(
                    external.violations or ["external validator rejected solution"]
                )
                validation.metrics = None
        checked.append(validation)
    baseline_validation, candidate_validation = checked
    validations = [wire(v) for v in checked]
    valid = all(v.passed for v in checked)
    comparison = None
    if valid:
        b, c = [v.metrics for v in checked]
        comparison = dict(
            curtailment_reduction_mwh=b.curtailed_energy_mwh - c.curtailed_energy_mwh,
            assumed_cost_delta_usd=c.assumed_cost_usd - b.assumed_cost_usd,
            unserved_energy_delta_mwh=c.unserved_energy_mwh - b.unserved_energy_mwh,
        )
    evidence_id = scenario.provenance.evidence_id
    evidence = payload.get("evidence_snapshot")
    if evidence_id:
        if evidence is None:
            evidence = json.loads(
                (settings.data_dir / "processed" / f"{evidence_id}.evidence.json").read_text()
            )
        if evidence["evidence_id"] != evidence_id:
            return failure("evidence_mismatch", "Historical evidence does not match the scenario")
    return dict(
        status="completed" if valid else "failed",
        provenance={
            **provenance,
            "scenario_sha256": fingerprint(scenario_json),
            "mode": scenario.mode,
            "data": wire(scenario.provenance),
        },
        scenario_snapshot=scenario_json,
        historical_evidence=evidence,
        tool_trace=[wire(event) for event in result.tool_trace]
        + [
            {
                "tool": "backend_acceptance_audit",
                "status": "success" if valid else "failed",
                "scope": "all timesteps, baseline and candidate",
            }
        ],
        baseline=dict(
            solution=wire(result.baseline),
            valid=baseline_validation.passed,
            metrics=validations[0]["metrics"],
        ),
        candidate=dict(
            solution=wire(result.candidate),
            valid=candidate_validation.passed,
            metrics=validations[1]["metrics"],
        ),
        comparison=comparison,
        validation=dict(
            passed=valid,
            violations=[x for v in checked for x in v.violations],
            max_residual_mw=max(v.max_residual_mw for v in checked),
            baseline=validations[0],
            candidate=validations[1],
        ),
        operator_report=dict(
            summary=(
                f"Verified simulated curtailment reduction: {comparison['curtailment_reduction_mwh']:.6f} MWh over {len(scenario.timestamps_utc) * scenario.time_step_hours:g} hours. Candidate minus baseline assumed-cost proxy: {comparison['assumed_cost_delta_usd']:.6f} USD."
                if valid
                else "Verification failed. No candidate is available for approval."
            ),
            sources=scenario.provenance.observed_source_urls,
            assumptions=[
                "Synthetic transport network; all dispatch inputs are assumptions",
                "Baseline battery dispatch disabled; candidate policy explicitly recorded",
                "Identical exogenous inputs, asset ratings and final SOC targets",
            ],
            limitations=[
                "Simulation only; not an operational dispatch instruction",
                "No physical grid security assessment",
                "Historical evidence does not calibrate the network",
            ],
            agent_commentary=wire(result.operator_report),
            agent_commentary_status="generated narrative; numerical authority is the deterministic comparison and validation",
        ),
        approval_status="pending" if valid else "unavailable",
        error=None
        if valid
        else dict(
            code="verification_failed",
            message="Baseline or candidate did not pass independent verification",
        ),
    )


async def main():
    payload = json.loads(sys.stdin.read())
    try:
        with contextlib.redirect_stdout(sys.stderr):
            result = await execute(payload)
        envelope = {"ok": True, "result": result}
    except (ImportError, AttributeError):
        envelope = {
            "ok": False,
            "error": {
                "code": "adapter_unavailable",
                "message": "Required agent or optimisation adapter is not installed.",
            },
        }
    except FileNotFoundError:
        envelope = {
            "ok": False,
            "error": {
                "code": "fixture_unavailable",
                "message": "Required local evidence or replay fixture is missing.",
            },
        }
    except Exception as exc:
        # Exceptions can contain provider tokens/prompts; do not return their text or log it.
        envelope = {
            "ok": False,
            "error": {
                "code": "adapter_failed",
                "message": f"Adapter failed ({type(exc).__name__}); inspect its contract and configuration.",
            },
        }
    print(json.dumps(envelope, allow_nan=False))


if __name__ == "__main__":
    asyncio.run(main())
