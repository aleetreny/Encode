import json
import os
import pytest
import jsonschema
from fastapi.testclient import TestClient
from backend.main import create_app

app = create_app()
client = TestClient(app)

SCHEMA_PATH = "contracts/live.schema.json"
with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
    schema_json = json.load(f)

def validate_data(data, schema_def):
    jsonschema.validate(instance=data, schema={"$defs": schema_json.get("$defs", {}), "$ref": f"#/$defs/{schema_def}"})

def test_get_catalog():
    response = client.get("/api/live/catalog")
    assert response.status_code == 200
    validate_data(response.json(), "Catalog")

def test_session_creation_and_stream():
    resp = client.post("/api/live/sessions", json={"session_id": "test_session_1"})
    assert resp.status_code == 202
    data = resp.json()
    assert "session_id" in data
    
    session_id = data["session_id"]
    
    stream_resp = client.get(f"/api/live/sessions/{session_id}/stream?max_events=1")
    assert stream_resp.status_code == 200
    text = stream_resp.text
    assert text.startswith("data: ")
    
    event_str = text.split("\n\n")[0][6:]
    event_data = json.loads(event_str)
    
    assert event_data["type"] == "session.snapshot"
    validate_data(event_data, "LiveEvent")

def test_disrupt_decide_autonomy_clock_reset():
    session_id = "test_session_actions"
    client.post("/api/live/sessions", json={"session_id": session_id})
    
    resp = client.post(f"/api/live/sessions/{session_id}/disrupt", json={
        "asset_id": "gas_centro",
        "duration_h": 4,
        "wait_for_options": True
    })
    assert resp.status_code == 202
    res_data = resp.json()
    assert res_data["accepted"] is True
    
    resp = client.post(f"/api/live/sessions/{session_id}/clock", json={
        "action": "play"
    })
    assert resp.status_code == 202
    
    resp = client.post(f"/api/live/sessions/{session_id}/autonomy", json={
        "enabled": True
    })
    assert resp.status_code == 202
    
    resp = client.post(f"/api/live/sessions/{session_id}/reset")
    assert resp.status_code == 202

def test_jury_disrupt():
    session_id = "test_session_jury"
    client.post("/api/live/sessions", json={"session_id": session_id})
    client.post(f"/api/live/sessions/{session_id}/reset")
    
    resp1 = client.post(f"/api/live/sessions/{session_id}/jury/disrupt", json={
        "asset_id": "gas_centro",
        "device_id": "dev1"
    })
    assert resp1.status_code == 202
    
    resp2 = client.post(f"/api/live/sessions/{session_id}/jury/disrupt", json={
        "asset_id": "gas_centro",
        "device_id": "dev1"
    })
    assert resp2.status_code == 429
    
    resp3 = client.post(f"/api/live/sessions/{session_id}/jury/disrupt", json={
        "asset_id": "L1",
        "device_id": "dev2"
    })
    assert resp3.status_code == 202
    
    resp4 = client.post(f"/api/live/sessions/{session_id}/jury/disrupt", json={
        "asset_id": "L2",
        "device_id": "dev3"
    })
    assert resp4.status_code == 409

def test_qr_code():
    session_id = "test_session_qr"
    resp = client.get(f"/api/live/sessions/{session_id}/qr.svg")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/svg+xml"
    assert "jurado?s=test_session_qr" in resp.text
    assert "<svg" in resp.text


def test_operational_levers_only_in_crisis():
    from backend.live.agent_loop import (
        LIVE_DECIDER_TOOLS,
        OPERATIONAL_LEVER_TYPES,
        generate_operational_candidates,
        lever_to_solver_mod,
    )
    from backend.live.catalog import FIXTURE_PATH

    # Verify tool declaration enum only contains operational lever types
    sim_tool = next(d for d in LIVE_DECIDER_TOOLS if d["name"] == "simulate_plan")
    enum_types = sim_tool["parameters"]["properties"]["levers"]["items"]["properties"]["type"]["enum"]
    assert tuple(enum_types) == OPERATIONAL_LEVER_TYPES
    assert "add_battery" not in enum_types
    assert "uprate_line" not in enum_types

    # Verify crisis candidate generator only produces operational levers
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        scenario = json.load(f)
    cands = generate_operational_candidates(scenario, active_disruptions=[], from_hour=18, to_hour=22)
    assert len(cands) > 0
    for c in cands:
        for lv in c["levers"]:
            assert lv["type"] in OPERATIONAL_LEVER_TYPES

    # Verify lever_to_solver_mod rejects planning levers when allow_planning_levers=False
    with pytest.raises(ValueError, match="no permitida en modo crisis"):
        lever_to_solver_mod(
            {"type": "add_battery", "target_id": "n_centro", "params": {"power_mw": 100}},
            allow_planning_levers=False,
        )
    with pytest.raises(ValueError, match="no permitida en modo crisis"):
        lever_to_solver_mod(
            {"type": "uprate_line", "target_id": "L2", "params": {"factor": 1.15}},
            allow_planning_levers=False,
        )


def test_pairwise_tradeoff_tag_truthfulness():
    from backend.live.agent_loop import enforce_option_pair_guardrails, is_tag_truthful

    opt_a = {
        "option_id": "opt_a",
        "title_es": "Opción A",
        "tradeoff_tag": "min_costo",  # Contradicted: cost is higher than opt_b!
        "rationale_es": "Racional A",
        "levers": [{"type": "demand_response", "target_id": "n_centro", "params": {"max_mw": 200.0}}],
        "metrics": {
            "households_reconnected": 342900,
            "households_newly_off": 0,
            "unserved_mwh_avoided": 999.0,
            "cost_delta_usd": 146500.0,
            "co2_delta_t": -50.0,
            "curtailment_delta_mwh": 0.0,
            "max_line_loading_pct": 100.0,
            "hours_to_zero_unserved": 0,
        },
    }
    opt_b = {
        "option_id": "opt_b",
        "title_es": "Opción B",
        "tradeoff_tag": "max_hogares",  # Contradicted: households_reconnected is lower than opt_a!
        "rationale_es": "Racional B",
        "levers": [{"type": "activate_reserve_bess", "target_id": "b_reserve_centro", "params": {"power_mw": 150.0}}],
        "metrics": {
            "households_reconnected": 212400,
            "households_newly_off": 0,
            "unserved_mwh_avoided": 600.0,
            "cost_delta_usd": 12000.0,
            "co2_delta_t": 10.0,
            "curtailment_delta_mwh": 0.0,
            "max_line_loading_pct": 85.0,
            "hours_to_zero_unserved": 2,
        },
    }

    assert not is_tag_truthful("min_costo", opt_a["metrics"], opt_b["metrics"])
    assert not is_tag_truthful("max_hogares", opt_b["metrics"], opt_a["metrics"])

    fixed_opts, rec_id, diag = enforce_option_pair_guardrails(
        [opt_a, opt_b],
        recommended_id="opt_a",
        diagnosis_es="Diagnóstico de prueba sin dígitos.",
    )
    fa, fb = fixed_opts[0], fixed_opts[1]
    assert fa["tradeoff_tag"] != fb["tradeoff_tag"]
    assert is_tag_truthful(fa["tradeoff_tag"], fa["metrics"], fb["metrics"])
    assert is_tag_truthful(fb["tradeoff_tag"], fb["metrics"], fa["metrics"])


def test_zero_improvement_guardrails_and_autonomy():
    import asyncio
    from backend.live.agent_loop import enforce_option_pair_guardrails, has_digits
    from backend.live.engine import LiveSession

    # Case 3a: One option has 0 reconnected households, the other has > 0 -> never recommend the 0 option
    opt_zero = {
        "option_id": "opt_zero",
        "title_es": "Maniobra Nula",
        "tradeoff_tag": "min_costo",
        "rationale_es": "Sin efecto residencial",
        "levers": [{"type": "emergency_rating", "target_id": "L4", "params": {"factor": 1.15}}],
        "metrics": {
            "households_reconnected": 0,
            "households_newly_off": 0,
            "unserved_mwh_avoided": 0.0,
            "cost_delta_usd": 0.0,
            "co2_delta_t": 0.0,
            "curtailment_delta_mwh": 0.0,
            "max_line_loading_pct": 50.0,
            "hours_to_zero_unserved": None,
        },
    }
    opt_pos = {
        "option_id": "opt_pos",
        "title_es": "Maniobra Efectiva",
        "tradeoff_tag": "max_hogares",
        "rationale_es": "Reconecta hogares",
        "levers": [{"type": "activate_reserve_bess", "target_id": "b_reserve_centro", "params": {"power_mw": 150.0}}],
        "metrics": {
            "households_reconnected": 150000,
            "households_newly_off": 0,
            "unserved_mwh_avoided": 450.0,
            "cost_delta_usd": 10000.0,
            "co2_delta_t": 0.0,
            "curtailment_delta_mwh": 0.0,
            "max_line_loading_pct": 80.0,
            "hours_to_zero_unserved": 1,
        },
    }

    fixed_opts, rec_id, _ = enforce_option_pair_guardrails(
        [opt_zero, opt_pos],
        recommended_id="opt_zero",
        diagnosis_es="Diagnóstico inicial.",
    )
    assert rec_id == "opt_pos"

    # Case 3c: Both options have 0 reconnected households -> diagnosis_es must explicitly note it without digits
    opt_zero_b = {
        **opt_zero,
        "option_id": "opt_zero_b",
        "tradeoff_tag": "min_co2",
    }
    _, _, diag_zero = enforce_option_pair_guardrails(
        [opt_zero, opt_zero_b],
        recommended_id="opt_zero",
        diagnosis_es="Falla en corredor aislado.",
    )
    assert "ninguna maniobra" in diag_zero.lower()
    assert not has_digits(diag_zero)

    # Case 3b: Autonomous mode must not start countdown or apply a 0-improvement plan
    async def _run_autonomy_zero_check():
        ses = LiveSession(session_id="test_auto_zero", start_hour=12.0, allow_live_gemini=False)
        ses.autonomy = True
        q = ses.subscribe()
        # Simulate an incident where options have 0 improvement (e.g. L1 at hour 12 has 0 unserved MW)
        await ses.disrupt("L1", duration_h=4, from_hour_override=12, wait_for_options=True)
        events = []
        while not q.empty():
            events.append(q.get_nowait())
        countdown_events = [e for e in events if e["type"] == "autonomy.countdown"]
        applied_events = [e for e in events if e["type"] == "plan.applied"]
        note_events = [e for e in events if e["type"] == "agent.note"]
        assert len(countdown_events) == 0
        assert len(applied_events) == 0
        assert len(note_events) >= 1
        assert not has_digits(note_events[-1]["text_es"])

    asyncio.run(_run_autonomy_zero_check())

