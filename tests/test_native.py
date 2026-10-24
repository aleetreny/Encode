import copy
import json

import pytest

from backend.config import ROOT
from backend.native_models import NativeScenario
from backend.native_service import (
    check_solution,
    default_candidates,
    default_events,
    household_impact,
)
from tests.test_api import finish

SCENARIO_ID = "chile-sen-5node-demo"


@pytest.fixture
def native_scenario():
    return json.loads((ROOT / f"data/demo/{SCENARIO_ID}.native-scenario.json").read_text())


@pytest.fixture
def native_bundle():
    return json.loads((ROOT / f"data/demo/{SCENARIO_ID}.native-replay.json").read_text())["bundle"]


def test_default_scenario_is_native_five_node_with_menu(client):
    result = client.get("/api/scenario").json()
    assert result["scenario_id"] == SCENARIO_ID and len(result["nodes"]) == 5
    assert "gas" in {g["technology"] for g in result["generators"]}
    assert "add_battery" in result["modification_menu"]
    assert result["household_mapping"]["classification"] == "synthetic_assumption"
    assert client.get("/api/scenarios").json()["default_scenario_id"] == SCENARIO_ID


@pytest.mark.parametrize("candidate", default_candidates())
def test_native_interventions_through_http(client, candidate):
    result = client.post(
        "/api/optimise", json=dict(scenario_id=SCENARIO_ID, candidate=candidate)
    ).json()
    assert result["status"] == "optimal" and result["validation"]["passed"]
    assert result["candidate_id"] == candidate["candidate_id"]
    checked = client.post(
        "/api/validate", json=dict(scenario_id=SCENARIO_ID, solution=result, candidate=candidate)
    ).json()
    assert checked["passed"] and "no_hindsight" in checked["checks_run"]


def test_crisis_strict_infeasible_and_recovery_passes(client):
    body = dict(scenario_id=SCENARIO_ID, events=default_events())
    strict = client.post(
        "/api/optimise", json={**body, "options": {"allow_unserved": False}}
    ).json()
    assert strict["status"] == "infeasible" and strict["metrics"] is None
    assert not strict["validation"]["passed"]
    recovered = client.post(
        "/api/optimise", json={**body, "options": {"allow_unserved": True}}
    ).json()
    assert recovered["status"] == "optimal" and recovered["validation"]["passed"]
    assert recovered["metrics"]["unserved_mwh"] > 0
    assert "no_hindsight" in recovered["validation"]["checks_run"]


@pytest.mark.parametrize("mode", ["replay", "deterministic"])
def test_native_two_stage_run_export_and_gate(client, mode):
    r = client.post(
        "/api/agent/run",
        json=dict(
            scenario_id=SCENARIO_ID,
            execution_mode=mode,
            governance_mode="autonomous_sced_with_audit_gate",
        ),
    )
    assert r.status_code == 202
    doc = finish(client, r.json()["run_id"])
    assert doc["status"] == "completed", doc.get("error")
    assert doc["schema_version"] == "2.0.0" and doc["validation"]["passed"]
    assert doc["governance"]["normal_dispatch"] == "applied_in_simulation"
    assert doc["governance"]["crisis_recovery"] == "awaiting_operator_approval"
    assert doc["provenance"]["live_gemini"] is False
    assert len(doc["candidate_evaluations"]) == 3
    assert doc["comparison"]["curtailment_reduction_mwh"] == pytest.approx(631.578947)
    assert doc["crisis_analysis"]["unserved_reduction_mwh"] == pytest.approx(391.875)
    assert doc["crisis_analysis"]["strict_attempt"]["status"] == "infeasible"
    assert all(
        r["legal_compliance_status"] == "not_certified"
        for r in doc["operator_report"]["regulatory_compliance"]
    )
    route = f"/api/agent/runs/{doc['run_id']}"
    decision = client.post(
        route + "/decision",
        json=dict(decision="approved", expected_revision=doc["revision"], operator="native test"),
    )
    assert decision.status_code == 200
    exported = client.get(route + "/report").json()
    assert exported["governance"]["crisis_recovery"] == "approved_in_simulation"
    assert (
        exported["approval_status"] == "approved"
        and exported["crisis_analysis"]["household_impact"]
    )


def test_native_live_missing_agent_falls_back_explicitly(client):
    r = client.post("/api/agent/run", json=dict(scenario_id=SCENARIO_ID, execution_mode="live"))
    assert r.status_code == 202
    doc = finish(client, r.json()["run_id"])
    assert doc["status"] == "completed", doc.get("error")
    assert doc["requested_execution_mode"] == "live" and doc["execution_mode"] == "replay"
    assert doc["fallback"]["mode"] == "replay" and not doc["provenance"]["live_gemini"]
    assert (
        client.post(
            "/api/agent/run",
            json=dict(
                scenario_id=SCENARIO_ID,
                execution_mode="live",
                settings={"allow_cached_fallback": False},
            ),
        ).status_code
        == 503
    )


def test_native_cached_settings_are_not_silently_changed(client):
    r = client.post(
        "/api/agent/run",
        json=dict(
            scenario_id=SCENARIO_ID,
            execution_mode="replay",
            settings={"candidates": [default_candidates()[0]]},
        ),
    )
    doc = finish(client, r.json()["run_id"])
    assert doc["status"] == "failed" and doc["error"]["code"] == "replay_mismatch"


def test_native_comparison_revalidates_and_returns_household_units(client, native_bundle):
    crisis = native_bundle["crisis_analysis"]
    body = dict(scenario_id=SCENARIO_ID, baseline=crisis["baseline"], candidate=crisis["candidate"])
    result = client.post("/api/compare", json=body)
    assert result.status_code == 200 and result.json()["comparable"]
    assert result.json()["household_impact"]["unique_households_reconnected"] is None
    body["candidate"]["timeseries"]["battery_soc_mwh"]["b_centro"][0] = 9999
    assert not client.post("/api/compare", json=body).json()["comparable"]


def test_native_timeout_fallback_is_relabelled(settings, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-not-a-provider-key")
    from backend.main import create_app
    from fastapi.testclient import TestClient

    settings.agent_callable = "tests.adapters:slow"
    settings.timeout_seconds = 1.5
    with TestClient(create_app(settings)) as client:
        r = client.post("/api/agent/run", json=dict(scenario_id=SCENARIO_ID, execution_mode="live"))
        doc = finish(client, r.json()["run_id"])
        assert doc["status"] == "completed", doc.get("error")
        assert (
            doc["fallback"]["reason"] == "execution_timeout" and doc["execution_mode"] == "replay"
        )


def test_native_wrong_candidates_rejected(client):
    bad = copy.deepcopy(default_candidates()[0])
    bad["modifications"][0]["power_mw"] = 999
    result = client.post("/api/optimise", json=dict(scenario_id=SCENARIO_ID, candidate=bad)).json()
    assert result["status"] == "error" and not result["validation"]["passed"]
    assert (
        client.post(
            "/api/agent/run",
            json=dict(
                scenario_id=SCENARIO_ID,
                execution_mode="deterministic",
                settings={"candidates": [bad]},
            ),
        ).status_code
        == 422
    )


def test_household_units_and_window_are_distinct(native_scenario, native_bundle):
    crisis = native_bundle["crisis_analysis"]
    impact = household_impact(
        native_scenario, crisis["baseline"], crisis["candidate"], default_events()
    )
    assert impact["event_duration_hours"] == 4
    assert impact["horizon_avoided_household_hours"] == pytest.approx(391875)
    assert impact["avoided_household_hours"] == pytest.approx(364800)
    assert impact["average_households_reconnected_equivalent"] == pytest.approx(91200)
    assert impact["unique_households_reconnected"] is None
    before = impact["average_households_reconnected_equivalent"]
    native_scenario["household_mapping"]["households_per_mw"] = 250
    changed = household_impact(
        native_scenario, crisis["baseline"], crisis["candidate"], default_events()
    )
    assert changed["average_households_reconnected_equivalent"] == before / 4


def test_backend_detects_extra_assets(native_scenario, native_bundle):
    solution = native_bundle["baseline"]
    solution["timeseries"]["generation_mw"]["invented_generator"] = [0] * 24
    checked = check_solution(native_scenario, solution)
    assert not checked["passed"]
    assert any(v["check"] == "exact_asset_ids" for v in checked["violations"])


def test_backend_detects_hindsight_even_when_native_physics_pass(native_scenario):
    from optimisation import solve, validate

    planned = [{**default_events()[0], "mode": "planned"}]
    solution = solve(native_scenario, events=planned)
    solution["events"][0]["mode"] = "sudden"
    # The native checker checks physical feasibility, not the absence of advance knowledge.
    assert validate(native_scenario, solution)["passed"]
    checked = check_solution(native_scenario, solution, events=default_events())
    assert not checked["passed"] and any(
        v["check"] == "no_hindsight" for v in checked["violations"]
    )


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s["household_mapping"]["residential_share_by_node"].__setitem__("n_sur", 2),
        lambda s: s["timestamps_utc"].__setitem__(0, "2026-10-01T03:00:00"),
        lambda s: s["demand_mw_by_node"]["n_sur"].pop(),
    ],
)
def test_native_scenario_rejects_invalid_inputs(native_scenario, change):
    from pydantic import ValidationError

    change(native_scenario)
    with pytest.raises(ValidationError):
        NativeScenario.model_validate(native_scenario)
