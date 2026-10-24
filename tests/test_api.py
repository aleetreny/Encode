import time

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app


BODY = dict(scenario_id="chile-demo-001", execution_mode="replay")


def finish(client, run_id):
    for _ in range(150):
        doc = client.get(f"/api/agent/runs/{run_id}").json()
        if doc["status"] not in ("queued", "running"):
            return doc
        time.sleep(0.03)
    raise AssertionError("run did not terminate")


def test_replay_twice_export_approve(client):
    results = []
    for _ in range(2):
        response = client.post("/api/agent/run", json=BODY)
        assert response.status_code == 202
        doc = finish(client, response.json()["run_id"])
        assert doc["status"] == "completed" and doc["validation"]["passed"]
        assert doc["provenance"]["live_gemini"] is False
        assert doc["historical_evidence"]["evidence_id"] == "cen-2026-08-01"
        result = client.post(
            f"/api/agent/runs/{doc['run_id']}/decision",
            json=dict(
                decision="approved", expected_revision=doc["revision"], operator="test operator"
            ),
        )
        assert result.status_code == 200 and result.json()["decision"]["scope"] == "simulation_only"
        report = client.get(f"/api/agent/runs/{doc['run_id']}/report")
        assert report.status_code == 200 and "attachment" in report.headers["Content-Disposition"]
        assert report.json()["approval_status"] == "approved"
        results.append(doc["comparison"])
    assert results[0] == results[1]


def test_idempotency(client):
    headers = {"Idempotency-Key": "same-click"}
    first = client.post("/api/agent/run", json=BODY, headers=headers)
    again = client.post("/api/agent/run", json=BODY, headers=headers)
    assert again.status_code == 200
    assert first.json()["run_id"] == again.json()["run_id"]
    changed = {**BODY, "settings": {"battery_policy": "disabled"}}
    assert client.post("/api/agent/run", json=changed, headers=headers).status_code == 409


def test_unknown_and_invalid(client):
    assert client.get("/api/scenario?scenario_id=missing").status_code == 404
    assert client.post("/api/agent/run", json={**BODY, "scenario_id": "missing"}).status_code == 404
    assert client.get("/api/agent/runs/missing").status_code == 404
    assert client.get("/api/evidence/missing").status_code == 404
    assert client.post("/api/agent/run", json={**BODY, "api_key": "SECRET"}).status_code == 422
    assert "SECRET" not in client.post("/api/agent/run", json={**BODY, "api_key": "SECRET"}).text
    assert client.post("/api/agent/run", content="{").status_code == 422
    assert client.post("/api/agent/run", content="x" * 262145).status_code == 413


def test_missing_live_fails_honestly(client):
    assert client.get("/api/health").json()["live_ready"] is False
    assert client.get("/api/ready?mode=live").status_code == 503
    assert (
        client.post("/api/agent/run", json={"scenario_id": BODY["scenario_id"]}).status_code == 503
    )


def test_real_solver_and_independent_validator_through_api(client):
    state = client.get("/api/health").json()
    assert state["adapters"]["solver"] and state["adapters"]["validator"]
    for policy in ("disabled", "optimised"):
        body = dict(scenario_id=BODY["scenario_id"], options={"battery_policy": policy})
        response = client.post("/api/optimise", json=body)
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "optimal" and result["validation"]["passed"]
        assert result["solution"]["native_result"]["solver"]["name"] == "HiGHS"
        checked = client.post("/api/validate", json={**body, "solution": result["solution"]})
        assert checked.status_code == 200 and checked.json()["passed"]
        assert checked.json()["metrics"]["assumed_cost_usd"] == pytest.approx(
            result["solution"]["native_result"]["objective"]["total_usd"], abs=1e-3
        )


def test_missing_solver_is_reported(settings):
    settings.solve_callable = "not_installed_gridpilot:solve"
    with TestClient(create_app(settings)) as client:
        assert (
            client.post("/api/optimise", json={"scenario_id": BODY["scenario_id"]}).status_code
            == 503
        )


def test_replay_options_mismatch(client):
    r = client.post("/api/agent/run", json={**BODY, "settings": {"battery_policy": "disabled"}})
    doc = finish(client, r.json()["run_id"])
    assert doc["status"] == "failed" and doc["comparison"] is None
    assert doc["error"]["code"] == "replay_mismatch"
    assert (
        client.post(
            f"/api/agent/runs/{doc['run_id']}/decision",
            json=dict(decision="approved", expected_revision=doc["revision"], operator="test"),
        ).status_code
        == 409
    )


def test_auth_cors(settings):
    settings.api_token = "test-token-with-enough-characters"
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/agent/run", json=BODY).status_code == 401
        assert (
            client.post(
                "/api/agent/run",
                json=BODY,
                headers={"Authorization": "Bearer " + settings.api_token},
            ).status_code
            == 202
        )
        assert client.get("/api/health").status_code == 200
        r = client.options(
            "/api/agent/run",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,idempotency-key",
            },
        )
        assert (
            r.status_code == 200
            and r.headers["access-control-allow-origin"] == "http://localhost:5173"
        )
        assert (
            client.options(
                "/api/agent/run",
                headers={
                    "Origin": "https://untrusted.invalid",
                    "Access-Control-Request-Method": "POST",
                },
            ).status_code
            == 400
        )


def test_stale_and_duplicate_approval(client):
    r = client.post("/api/agent/run", json=BODY)
    doc = finish(client, r.json()["run_id"])
    route = f"/api/agent/runs/{doc['run_id']}/decision"
    body = dict(decision="rejected", expected_revision=0, operator="test")
    assert client.post(route, json=body).status_code == 409
    body["expected_revision"] = doc["revision"]
    assert client.post(route, json=body).status_code == 200
    assert client.post(route, json=body).status_code == 409


def test_queue_limit_and_early_approval(settings):
    settings.worker_enabled = False
    settings.queue_limit = 1
    with TestClient(create_app(settings)) as client:
        r = client.post("/api/agent/run", json=BODY)
        assert client.post("/api/agent/run", json=BODY).status_code == 429
        rid = r.json()["run_id"]
        assert client.get(f"/api/agent/runs/{rid}/report").status_code == 409
        assert (
            client.post(
                f"/api/agent/runs/{rid}/decision",
                json=dict(decision="approved", operator="test", expected_revision=0),
            ).status_code
            == 409
        )


@pytest.mark.parametrize(
    "adapter,status,code",
    [
        ("slow", 504, "execution_timeout"),
        ("broken", 502, "adapter_failed"),
        ("async_solve", 200, None),
        ("infeasible", 200, None),
        ("invalid_solution", 200, None),
    ],
)
def test_adapter_execution(settings, adapter, status, code):
    settings.solve_callable = "tests.adapters:" + adapter
    settings.timeout_seconds = 0.15 if adapter == "slow" else 5
    with TestClient(create_app(settings)) as client:
        r = client.post("/api/optimise", json={"scenario_id": BODY["scenario_id"]})
        assert r.status_code == status
        assert "SECRET_PROVIDER_KEY" not in r.text
        if code:
            assert r.json()["error"]["code"] == code
        if adapter in ("infeasible", "invalid_solution"):
            assert not r.json()["validation"]["passed"]


def test_live_adapter_boundary_and_external_rejection(settings):
    settings.agent_callable = "tests.adapters:investigate"
    settings.solve_callable = "tests.adapters:solve"
    settings.validate_callable = "tests.adapters:reject"
    with TestClient(create_app(settings)) as client:
        r = client.post("/api/agent/run", json={"scenario_id": BODY["scenario_id"]})
        doc = finish(client, r.json()["run_id"])
        assert doc["status"] == "failed"
        assert doc["comparison"] is None and not doc["candidate"]["valid"]


def test_synthetic_fallback(client):
    r = client.post("/api/agent/run", json={**BODY, "scenario_id": "synthetic-demo-001"})
    doc = finish(client, r.json()["run_id"])
    assert doc["status"] == "completed"
    assert doc["historical_evidence"] is None and doc["provenance"]["mode"] == "synthetic"


def test_cached_trace_cannot_be_presented_as_live(settings):
    settings.agent_callable = "tests.adapters:unattested"
    settings.solve_callable = "tests.adapters:solve"
    settings.validate_callable = "tests.adapters:validate"
    with TestClient(create_app(settings)) as client:
        r = client.post("/api/agent/run", json={"scenario_id": BODY["scenario_id"]})
        doc = finish(client, r.json()["run_id"])
        assert doc["status"] == "failed" and doc["error"]["code"] == "unverified_live_trace"


def test_validation_adapter_and_boundary(settings, replay):
    settings.validate_callable = "tests.adapters:validate"
    with TestClient(create_app(settings)) as client:
        body = dict(scenario_id=BODY["scenario_id"], solution=replay["result"]["candidate"])
        assert client.post("/api/validate", json=body).json()["passed"]
        body["solution"]["soc_mwh_by_battery"]["b1"][-1] = 0
        assert not client.post("/api/validate", json=body).json()["passed"]


def test_report_summary_uses_verified_numbers(client):
    doc = finish(client, client.post("/api/agent/run", json=BODY).json()["run_id"])
    assert "77.777778 MWh" in doc["operator_report"]["summary"]
    assert "agent_commentary" in doc["operator_report"]


def test_missing_historical_data_leaves_synthetic_available(settings, tmp_path):
    import shutil

    settings.data_dir = tmp_path / "data"
    from backend.config import ROOT

    shutil.copytree(ROOT / "data/demo", settings.data_dir / "demo")
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/agent/run", json=BODY).status_code == 503
        r = client.post("/api/agent/run", json={**BODY, "scenario_id": "synthetic-demo-001"})
        assert finish(client, r.json()["run_id"])["status"] == "completed"
