"""Export schemas and actual OpenAPI. --check fails when generated files drift."""

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import ROOT, Settings
from backend.main import create_app
from backend.models import (
    AgentResult,
    Decision,
    Options,
    RunDocument,
    RunRequest,
    Scenario,
    Solution,
    ValidateRequest,
    Validation,
)
from backend.worker import execute
from backend.native_models import (
    Candidate,
    Outage,
    NativeScenario,
    NativeScenarioResponse,
    NativeSolution,
    NativeRunRequest,
    NativeRunDocument,
    NativeSolveRequest,
    NativeValidateRequest,
    NativeCompareRequest,
    HouseholdMapping,
)


def documents():
    models = {
        "scenario": Scenario,
        "solution": Solution,
        "validation": Validation,
        "agent-result": AgentResult,
        "run-result": RunDocument,
        "run-request": RunRequest,
        "options": Options,
        "decision": Decision,
        "validate-request": ValidateRequest,
    }
    output = {
        f"{name}.schema.json": model.model_json_schema(by_alias=True)
        for name, model in models.items()
    }
    with tempfile.TemporaryDirectory() as directory:
        output["openapi.json"] = create_app(
            Settings(db_path=Path(directory) / "runs.db", worker_enabled=False)
        ).openapi()
    output["scenario.example.json"] = json.loads(
        (ROOT / "data/demo/chile-demo-001.scenario.json").read_text()
    )
    output["agent-result.example.json"] = json.loads(
        (ROOT / "data/demo/chile-demo-001.replay.json").read_text()
    )["result"]
    result = asyncio.run(
        execute(
            dict(
                operation="investigate",
                scenario=output["scenario.example.json"],
                execution_mode="replay",
                options={},
            )
        )
    )
    result["provenance"]["example_metadata"] = (
        "Run identifier and timestamps are illustrative; numerical outputs are checked reference replay results."
    )
    example = dict(
        schema_version="1.0.0",
        run_id="example-replay-run",
        scenario_id="chile-demo-001",
        execution_mode="replay",
        created_at="2026-10-24T00:00:00Z",
        updated_at="2026-10-24T00:00:00Z",
        revision=2,
        **result,
    )
    RunDocument.model_validate(example)
    output["run-result.example.json"] = example
    native_models = {
        "native-scenario": NativeScenario,
        "native-scenario-response": NativeScenarioResponse,
        "native-solution": NativeSolution,
        "native-run-request": NativeRunRequest,
        "native-run-result": NativeRunDocument,
        "native-solve-request": NativeSolveRequest,
        "native-validate-request": NativeValidateRequest,
        "native-compare-request": NativeCompareRequest,
        "candidate": Candidate,
        "outage": Outage,
        "household-mapping": HouseholdMapping,
    }
    output.update(
        {
            f"{name}.schema.json": model.model_json_schema(by_alias=True)
            for name, model in native_models.items()
        }
    )
    native = json.loads((ROOT / "data/demo/chile-sen-5node-demo.native-scenario.json").read_text())
    output["native-scenario.example.json"] = native
    result = asyncio.run(
        execute(
            dict(
                operation="native_investigate",
                scenario=native,
                execution_mode="replay",
                settings={},
                governance_mode="autonomous_sced_with_audit_gate",
                recorded_at_utc="2026-10-24T00:00:00Z",
            )
        )
    )
    native_example = dict(
        schema_version="2.0.0",
        run_id="example-native-replay-run",
        scenario_id=native["scenario_id"],
        created_at="2026-10-24T00:00:00Z",
        updated_at="2026-10-24T00:00:00Z",
        revision=2,
        **result,
    )
    NativeRunDocument.model_validate(native_example)
    output["native-run-result.example.json"] = native_example
    output["native-solution.example.json"] = result["baseline"]
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = []
    for name, value in documents().items():
        path = ROOT / "contracts" / name
        content = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        if args.check:
            if not path.exists() or path.read_text() != content:
                stale.append(name)
        else:
            path.write_text(content)
    if stale:
        raise SystemExit("Stale contracts: " + ", ".join(stale))
    print("Contracts current" if args.check else "Contracts exported")


if __name__ == "__main__":
    main()
