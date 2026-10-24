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
    parser.add_argument("--mode", choices=("replay", "live"), default="replay")
    parser.add_argument("--scenario", default="chile-demo-001")
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
                    comparison=doc["comparison"],
                )
            )
        )


if __name__ == "__main__":
    main()
