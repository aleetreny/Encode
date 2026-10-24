import concurrent.futures
import hashlib
import json

import pytest

from backend.config import ROOT
from backend.models import Decision
from backend.store import Conflict, Store
from scripts.prepare_data import extract


def test_source_checksum_and_totals():
    manifest = json.loads((ROOT / "data/raw/cen-2026-08.manifest.json").read_text())
    path = ROOT / "data/raw/cen-2026-08.xlsx"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest["sha256"]
    records, controls, reconciliation, anomalies = extract(path)
    assert len(records) == 4123 and len(controls) == 62
    assert all(abs(c["residual_mwh"]) < 1e-4 for c in reconciliation.values())
    assert all(c["missing_observations"] == 0 for c in controls if c["date"] == "2026-08-01")
    assert any(a["date"] == "2026-08-10" for a in anomalies)
    missing = [v for r in records for v in r["curtailed_energy_mwh_by_hour_label"] if v is None]
    assert missing  # Missing values remain null, never numerical zero.


def test_restart_recovery(settings):
    store = Store(settings.db_path)
    request = dict(scenario_id="chile-demo-001", execution_mode="replay", settings={})
    doc, _ = store.enqueue(request, "hash", None, 8)
    store.claim()
    Store(settings.db_path).recover()
    assert store.get(doc["run_id"])["error"]["code"] == "worker_interrupted"
    doc, _ = store.enqueue(request, "hash", None, 8)
    Store(settings.db_path).recover()
    assert store.get(doc["run_id"])["status"] == "queued"


def test_concurrent_idempotency(settings):
    store = Store(settings.db_path)
    request = dict(scenario_id="chile-demo-001", execution_mode="replay", settings={})
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        result = list(
            pool.map(lambda _: store.enqueue(request, "same-hash", "same-key", 8), range(6))
        )
    assert len({r[0]["run_id"] for r in result}) == 1
    assert sum(r[1] for r in result) == 1


def test_concurrent_decisions_only_one_wins(settings, scenario_json):
    import asyncio
    from backend.worker import execute

    store = Store(settings.db_path)
    request = dict(scenario_id="chile-demo-001", execution_mode="replay", settings={})
    doc, _ = store.enqueue(request, "hash", None, 8)
    store.claim()
    result = asyncio.run(
        execute(
            dict(
                operation="investigate", scenario=scenario_json, options={}, execution_mode="replay"
            ),
            settings,
        )
    )
    store.finish(doc["run_id"], result)
    revision = store.get(doc["run_id"])["revision"]

    def decide(value):
        try:
            store.decide(
                doc["run_id"], Decision(decision=value, expected_revision=revision, operator="test")
            )
            return True
        except Conflict:
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(decide, ["approved", "rejected"]))
    assert sum(result) == 1


def test_production_requires_token(monkeypatch):
    from backend.config import Settings

    monkeypatch.setenv("GRIDPILOT_ENV", "production")
    with pytest.raises(ValueError):
        Settings(api_token="")


def test_live_tool_uses_immutable_snapshot(scenario_json):
    from backend.runtime import _active_scenario, load_scenario

    token = _active_scenario.set(scenario_json)
    try:
        loaded = load_scenario(scenario_json["scenario_id"])
        loaded["demand_mw_by_node"]["north"][0] = 999
        assert load_scenario(scenario_json["scenario_id"])["demand_mw_by_node"]["north"][0] == 20
    finally:
        _active_scenario.reset(token)


def test_store_cannot_mark_empty_outputs_completed(settings):
    from pydantic import ValidationError

    store = Store(settings.db_path)
    doc, _ = store.enqueue(
        dict(scenario_id="chile-demo-001", execution_mode="replay"), "hash", None, 8
    )
    store.claim()
    with pytest.raises(ValidationError):
        store.finish(
            doc["run_id"],
            dict(
                status="completed",
                approval_status="pending",
                validation=dict(passed=True, violations=[], max_residual_mw=0),
            ),
        )
