"""Integration gates: these tests do not contact or certify Google."""

import pytest

from backend.live import verified_provider_metadata
from tests.test_api import finish


def test_actual_agent_offline_metadata_is_rejected(monkeypatch):
    from agent.gemini_client import GeminiArgonClient

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    narrative, metadata = GeminiArgonClient().synthesise_investigation(
        {"scenario_id": "offline-contract-audit"},
        {},
        {"curtailment_reduction_mwh": 0, "assumed_cost_delta_usd": 0},
    )
    assert narrative["reasoning_mode"] == "neuro_symbolic_deterministic"
    assert metadata["provider"] == "google"
    assert not verified_provider_metadata(metadata)


@pytest.mark.parametrize("scenario_id", ["chile-demo-001", "chile-sen-5node-demo"])
def test_live_without_credentials_is_not_started(client, monkeypatch, scenario_id):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    body = dict(scenario_id=scenario_id, execution_mode="live")
    if scenario_id.endswith("5node-demo"):
        body["settings"] = {"allow_cached_fallback": False}
    response = client.post("/api/agent/run", json=body)
    assert response.status_code == 503
    assert "credentials" in response.json()["error"]["message"]


def test_missing_credentials_fallback_has_explicit_reason(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    response = client.post(
        "/api/agent/run", json=dict(scenario_id="chile-sen-5node-demo", execution_mode="live")
    )
    result = finish(client, response.json()["run_id"])
    assert result["status"] == "completed"
    assert result["execution_mode"] == "replay" and result["requested_execution_mode"] == "live"
    assert result["fallback"]["reason"] == "gemini_credentials_missing"
    assert not result["provenance"]["live_gemini"]


@pytest.mark.parametrize("prefix", ["resp-argon-", "resp-google-"])
def test_known_locally_derived_provider_ids_are_rejected(prefix):
    assert not verified_provider_metadata(
        {"provider": "google", "model": "claimed-model", "response_id": prefix + "hash"}
    )


def test_live_http_smoke_cannot_certify_a_substituted_replay(monkeypatch):
    """Protocol double only: verify the release checker refuses hidden fallback."""
    import io
    import json
    from urllib.parse import urlparse

    from scripts import smoke

    paths = []

    def response(request, timeout):
        path = urlparse(request.full_url).path
        paths.append(path)
        if path == "/api/health":
            body = {"worker_enabled": True, "adapters": {"solver": True, "validator": True}}
        elif path == "/api/ready":
            body = {"ready": True}
        elif path == "/api/scenario":
            body = {"schema_version": "1.0.0"}
        elif path == "/api/optimise":
            body = {"status": "optimal", "validation": {"passed": True}, "solution": {}}
        elif path == "/api/validate":
            body = {"passed": True}
        elif path == "/api/agent/run":
            body = {
                "run_id": "test-double",
                "status": "completed",
                "validation": {"passed": True},
                "execution_mode": "replay",
                "provenance": {"live_gemini": False},
                "fallback": {"mode": "replay"},
            }
        else:
            raise AssertionError("A substituted replay must not be approved or exported")
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr("sys.argv", ["smoke.py", "--mode", "live"])
    monkeypatch.setattr(smoke, "urlopen", response)
    with pytest.raises(SystemExit, match="Requested execution mode was replaced"):
        smoke.main()
    assert not any(path.endswith(("/decision", "/report")) for path in paths)


def test_updated_native_agent_matches_backend_snapshot(monkeypatch):
    """Real numerical/agent execution, explicitly offline; no provider claim."""
    from agent import run_investigation
    from backend.models import wire
    from backend.native_models import InvestigationSettings
    from backend.native_service import check_solution
    from backend.runtime import _active_scenario, _active_evidence, load_scenario, inspect_evidence

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    scenario = load_scenario("chile-sen-5node-demo")
    options = wire(InvestigationSettings())
    scenario_token = _active_scenario.set(scenario)
    evidence_token = _active_evidence.set(inspect_evidence(scenario["scenario_id"])["evidence"])
    try:
        result = run_investigation(scenario["scenario_id"], options)
        assert check_solution(scenario, result["baseline"], None, [], options["options"])["passed"]
        assert check_solution(
            scenario, result["candidate"], result["candidate_definition"], [], options["options"]
        )["passed"]
        assert result["candidate_definition"]["candidate_id"] == "north_bess"
        assert not verified_provider_metadata(result["model_execution"])
        assert len(result["tool_trace"]) <= 100
    finally:
        _active_scenario.reset(scenario_token)
        _active_evidence.reset(evidence_token)
