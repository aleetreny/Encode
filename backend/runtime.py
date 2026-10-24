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


def load_scenario(scenario_id: str, settings=None):
    active = _active_scenario.get()
    if active and active["scenario_id"] == scenario_id:
        # Return a copy so an adapter cannot mutate the acceptance-check snapshot.
        return json.loads(json.dumps(active))
    return wire(scenario_catalog(settings or Settings())[scenario_id])


def inspect_evidence(scenario_id: str, settings=None):
    selected = load_scenario(scenario_id, settings)
    evidence_id = selected["provenance"]["evidence_id"]
    if evidence_id is None:
        return {"mode": "synthetic", "evidence": None}
    active = _active_evidence.get()
    if active:
        return json.loads(json.dumps(active))
    config = settings or Settings()
    return json.loads((config.data_dir / "processed" / f"{evidence_id}.evidence.json").read_text())


async def invoke(target, *args, **kwargs):
    result = resolve(target)(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


async def run_optimisation(scenario_id, options=None):
    config = Settings()
    return await invoke(config.solve_callable, load_scenario(scenario_id, config), options or {})


async def validate_candidate(scenario_id, solution, options=None):
    config = Settings()
    return await invoke(
        config.validate_callable, load_scenario(scenario_id, config), solution, options or {}
    )
