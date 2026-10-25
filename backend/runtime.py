"""Adapters shared by HTTP routes and the agent's Python tools."""

import importlib
import inspect
import json
from contextvars import ContextVar

from backend.config import Settings
from backend.models import Scenario, wire

_active_scenario = ContextVar("gridpilot_scenario", default=None)
_active_evidence = ContextVar("gridpilot_evidence", default=None)


def resolve(target):
    module, name = target.split(":", 1)
    value = getattr(importlib.import_module(module), name)
    if not callable(value):
        raise TypeError("adapter must be callable")
    return value


def available(target):
    try:
        function = resolve(target)
        return all(
            available(dependency) for dependency in getattr(function, "required_callables", ())
        )
    except Exception:
        return False


def scenario_catalog(settings: Settings):
    result = {}
    for path in sorted((settings.data_dir / "demo").glob("*.scenario.json")):
        scenario = Scenario.model_validate_json(path.read_text())
        if scenario.scenario_id in result:
            raise ValueError("duplicate scenario ID")
        result[scenario.scenario_id] = scenario
    if not result:
        raise ValueError("no scenario fixtures installed")
    return result


def native_scenario_catalog(settings: Settings):
    from backend.native_models import NativeScenario

    result = {}
    for path in sorted((settings.data_dir / "demo").glob("*.native-scenario.json")):
        scenario = NativeScenario.model_validate_json(path.read_text())
        if scenario.scenario_id in result:
            raise ValueError("duplicate native scenario ID")
        result[scenario.scenario_id] = scenario
    return result


def load_scenario(scenario_id: str, settings=None):
    active = _active_scenario.get()
    if active and active["scenario_id"] == scenario_id:
        # Return a copy so an adapter cannot mutate the acceptance-check snapshot.
        return json.loads(json.dumps(active))
    config = settings or Settings()
    catalog = {**scenario_catalog(config), **native_scenario_catalog(config)}
    return wire(catalog[scenario_id])


def inspect_evidence(scenario_id: str, settings=None):
    selected = load_scenario(scenario_id, settings)
    evidence_id = selected["provenance"]["evidence_id"]
    if evidence_id is None:
        return {"mode": "synthetic", "evidence": None}
    active = _active_evidence.get()
    config = settings or Settings()
    evidence = (
        json.loads(json.dumps(active))
        if active
        else json.loads(
            (config.data_dir / "processed" / f"{evidence_id}.evidence.json").read_text()
        )
    )
    if selected.get("schema_version") == "2.0.0":
        from optimisation import modification_menu

        return dict(
            evidence=evidence,
            profile_provenance=selected["provenance"],
            modification_menu=modification_menu(selected),
            household_mapping=selected["household_mapping"],
            regulatory_framework=selected["regulatory_framework"],
            demand_peak_mw_by_node={n: max(v) for n, v in selected["demand_mw_by_node"].items()},
            ramp_capabilities={
                g["id"]: g.get("ramp_rate_mw_per_h") for g in selected["generators"]
            },
        )
    return evidence


async def invoke(target, *args, **kwargs):
    result = resolve(target)(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


async def run_optimisation(scenario_id, candidate=None, events=None, options=None):
    config = Settings()
    selected = load_scenario(scenario_id, config)
    if selected.get("schema_version") == "2.0.0":
        from backend.native_service import solve_checked

        return solve_checked(selected, candidate, events, options)
    return await invoke(config.solve_callable, selected, options or candidate or {})


async def validate_candidate(scenario_id, solution, options=None):
    config = Settings()
    selected = load_scenario(scenario_id, config)
    if selected.get("schema_version") == "2.0.0":
        from backend.native_service import check_solution

        return check_solution(selected, solution, options=options)
    return await invoke(config.validate_callable, selected, solution, options or {})


def compare_results(baseline, candidate, baseline_validation=None, candidate_validation=None):
    from optimisation import compare
    from backend.native_service import check_solution, household_impact

    selected = load_scenario(baseline["scenario_id"])
    vb = check_solution(selected, baseline)
    vc = check_solution(selected, candidate)
    if baseline_validation is not None and baseline_validation.get("passed") is not True:
        vb["passed"] = False
    if candidate_validation is not None and candidate_validation.get("passed") is not True:
        vc["passed"] = False
    result = compare(baseline, candidate, vb, vc)
    if result["comparable"] and baseline.get("events"):
        result["household_impact"] = household_impact(
            selected, baseline, candidate, baseline["events"]
        )
    return result
