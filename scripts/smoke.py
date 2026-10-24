"""Real HTTP smoke test: twice through run -> validation -> decision -> download."""

import argparse
import json
import os
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--mode", choices=("replay", "live", "deterministic"), default="replay")
    parser.add_argument("--scenario", default="chile-sen-5node-demo")
    args = parser.parse_args()
    token = os.getenv("GRIDPILOT_API_TOKEN", "")

    def request(path, body=None, headers=None):
        hdr = {"Content-Type": "application/json", **(headers or {})}
        if token and body is not None:
            hdr["Authorization"] = "Bearer " + token
        req = Request(
            args.base_url.rstrip("/") + path,
            data=None if body is None else json.dumps(body).encode(),
            headers=hdr,
        )
        try:
            with urlopen(req, timeout=10) as response:
                return json.load(response)
        except HTTPError as exc:
            raise SystemExit(f"Smoke failed at {path}: HTTP {exc.code}") from None

    health = request("/api/health")
    if not health["worker_enabled"]:
        raise SystemExit("Worker disabled")
    request("/api/ready?mode=" + args.mode)
    if not health["adapters"]["solver"] or not health["adapters"]["validator"]:
        raise SystemExit(
            "Production numerical adapters are missing; cached replay alone is insufficient for this release smoke"
        )
    selected = request("/api/scenario?scenario_id=" + args.scenario)
    if selected["schema_version"] == "2.0.0":
        candidate = dict(
            candidate_id="north_bess",
            modifications=[
                dict(type="add_battery", node_id="n_norte_grande", power_mw=150, energy_mwh=600)
            ],
        )
        event = dict(
            type="generator_outage", id="gas_centro", from_hour=18, to_hour=22, mode="sudden"
        )
        baseline = request("/api/optimise", dict(scenario_id=args.scenario))
        alternative = request("/api/optimise", dict(scenario_id=args.scenario, candidate=candidate))
        for solution in (baseline, alternative):
            assert (
                solution["accepted"]
                and request("/api/validate", dict(scenario_id=args.scenario, solution=solution))[
                    "passed"
                ]
            )
        comparison = request(
            "/api/compare",
            dict(scenario_id=args.scenario, baseline=baseline, candidate=alternative),
        )
        assert comparison["comparable"]
        strict = request(
            "/api/optimise",
            dict(scenario_id=args.scenario, events=[event], options={"allow_unserved": False}),
        )
        assert strict["status"] == "infeasible" and not strict["accepted"]
        crisis = request(
            "/api/optimise", dict(scenario_id=args.scenario, candidate=candidate, events=[event])
        )
        assert crisis["accepted"] and "no_hindsight" in crisis["validation"]["checks_run"]
        print(
            json.dumps(
                dict(
                    numerical_api="native interventions, strict crisis, recovery and independent no-hindsight validation passed"
                )
            )
        )
    else:
        for policy in ("disabled", "optimised"):
            solve_body = dict(scenario_id=args.scenario, options={"battery_policy": policy})
            computed = request("/api/optimise", solve_body)
            assert computed["status"] == "optimal" and computed["validation"]["passed"]
            checked = request("/api/validate", {**solve_body, "solution": computed["solution"]})
            assert checked["passed"]
        print(
            json.dumps(
                dict(
                    numerical_api="production solver and independent validator passed",
                    policies=["disabled", "optimised"],
                )
            )
        )
    for attempt in range(2):
        body = dict(scenario_id=args.scenario, execution_mode=args.mode)
        key = str(uuid4())
        doc = request("/api/agent/run", body, {"Idempotency-Key": key})
        assert request("/api/agent/run", body, {"Idempotency-Key": key})["run_id"] == doc["run_id"]
        deadline = time.monotonic() + 120
        while doc["status"] in ("queued", "running"):
            if time.monotonic() > deadline:
                raise SystemExit("Investigation polling timed out")
            time.sleep(0.25)
            doc = request("/api/agent/runs/" + doc["run_id"])
        if doc["status"] != "completed" or not doc["validation"]["passed"]:
            raise SystemExit("Investigation failed: " + json.dumps(doc["error"]))
        if args.mode == "replay" and doc["provenance"]["live_gemini"]:
            raise SystemExit("Replay mislabeled as live")
        route = "/api/agent/runs/" + doc["run_id"]
        decision = request(
            route + "/decision",
            dict(
                decision="approved",
                expected_revision=doc["revision"],
                operator="automated smoke test",
                note="Simulation-only automated integration check",
            ),
        )
        report = request(route + "/report")
        assert decision["approval_status"] == report["approval_status"] == "approved"
        print(
            json.dumps(
                dict(
                    attempt=attempt + 1,
                    run_id=doc["run_id"],
                    execution_mode=args.mode,
                    validation_passed=True,
                    comparison={
                        k: doc["comparison"].get(k)
                        for k in ("curtailment_reduction_mwh", "assumed_cost_delta_usd")
                    },
                    crisis_unserved_reduction_mwh=(doc.get("crisis_analysis") or {}).get(
                        "unserved_reduction_mwh"
                    ),
                )
            )
        )


if __name__ == "__main__":
    main()
