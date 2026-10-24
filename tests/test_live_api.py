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
