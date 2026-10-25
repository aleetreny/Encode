"""Tests for Offline Incident Library (`tests/test_incident_library.py`).

Verifies:
1. `frontend/public/incidents/index.json` catalog structure, assets, hours, and combos.
2. Sample and all incident .jsonl files:
   - Valid JSON on every line.
   - Required headers on every event: `type`, `seq`, `session_id`, `hour`, `ts_utc`.
   - Contains `incident.detected`, `solution.updated`, and `options.ready`.
   - In `options.ready`:
     - `model_execution["cached"] is True`
     - `model_execution["cached_at_utc"]` is non-empty ISO string
     - `validation["passed"] is True` on both options
     - `options[0]["tradeoff_tag"] != options[1]["tradeoff_tag"]`
     - Zero digits (`has_digits() is False`) in all Spanish prose fields:
       `diagnosis_es`, `title_es`, `rationale_es`, `agent.thought.delta`, `agent.note.text_es`.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from backend.live.agent_loop import has_digits

ROOT = Path(__file__).resolve().parents[1]
INCIDENTS_DIR = ROOT / "frontend" / "public" / "incidents"
INDEX_PATH = INCIDENTS_DIR / "index.json"

REQUIRED_HOURS = {9, 12, 13, 18, 19, 20}

# 14 core disruptable assets
CORE_GENERATORS = {
    "solar_ng",
    "solar_nc",
    "wind_nc",
    "gas_ng",
    "gas_centro",
    "coal_cs",
    "hydro_sur",
    "wind_sur",
    "diesel_centro",
}
CORE_LINES = {"L1", "L2", "L3", "L4"}
CORE_BATTERIES = {"b_centro"}
CORE_ASSETS = CORE_GENERATORS | CORE_LINES | CORE_BATTERIES

REQUIRED_COMBOS = {"combo_gas_centro_L3_18", "combo_L1_gas_ng_12"}


def test_index_json_exists_and_valid():
    assert INDEX_PATH.is_file(), f"Missing incident library index at {INDEX_PATH}"
    with open(INDEX_PATH, encoding="utf-8") as f:
        data = json.load(f)

    assert "generated_at_utc" in data
    assert bool(data["generated_at_utc"])
    assert "hours" in data
    assert set(data["hours"]) == REQUIRED_HOURS
    assert data.get("duration_h") == 4
    assert "incidents" in data
    assert isinstance(data["incidents"], dict)
    assert "combos" in data
    assert isinstance(data["combos"], dict)


def test_index_contains_all_core_assets_and_combos():
    with open(INDEX_PATH, encoding="utf-8") as f:
        data = json.load(f)

    incidents = data["incidents"]
    combos = data["combos"]

    # Verify all 14 core assets × 6 hours = 84 incidents
    for asset in CORE_ASSETS:
        for hour in REQUIRED_HOURS:
            key = f"{asset}_{hour}"
            assert key in incidents, f"Missing incident {key} in index.json"
            entry = incidents[key]
            assert entry["asset_id"] == asset
            assert entry["hour"] == hour
            assert "file" in entry
            assert "unserved_mw_peak" in entry
            assert "households_off_peak" in entry
            assert "recommended_id" in entry
            assert bool(entry.get("cached_at_utc"))

    # Verify required multi-failure combos
    for combo_key in REQUIRED_COMBOS:
        assert combo_key in combos, f"Missing combo {combo_key} in index.json combos"
        c_entry = combos[combo_key]
        assert "assets" in c_entry
        assert len(c_entry["assets"]) >= 2
        assert "file" in c_entry
        assert "recommended_id" in c_entry
        assert bool(c_entry.get("cached_at_utc"))


def test_sample_incident_files():
    sample_keys = [
        "gas_centro_18",
        "L1_12",
        "L2_13",
        "hydro_sur_20",
        "solar_ng_9",
        "b_centro_18",
        "combo_gas_centro_L3_18",
        "combo_L1_gas_ng_12",
    ]

    for key in sample_keys:
        jsonl_path = INCIDENTS_DIR / f"{key}.jsonl"
        assert jsonl_path.is_file(), f"Missing incident file: {jsonl_path}"

        lines = []
        with open(jsonl_path, encoding="utf-8") as f:
            for line_idx, raw_line in enumerate(f):
                if not raw_line.strip():
                    continue
                try:
                    ev = json.loads(raw_line)
                except json.JSONDecodeError as err:
                    pytest.fail(f"Invalid JSON in {key}.jsonl line {line_idx}: {err}")
                lines.append(ev)

        assert len(lines) >= 5, f"Too few events in {key}.jsonl: {len(lines)}"

        # Verify envelope on every line
        event_types = set()
        for idx, ev in enumerate(lines):
            assert "type" in ev, f"Missing 'type' in {key}.jsonl line {idx}"
            assert "seq" in ev and isinstance(ev["seq"], int), f"Missing integer 'seq' in {key}.jsonl line {idx}"
            assert "session_id" in ev, f"Missing 'session_id' in {key}.jsonl line {idx}"
            assert "hour" in ev, f"Missing 'hour' in {key}.jsonl line {idx}"
            assert "ts_utc" in ev and bool(ev["ts_utc"]), f"Missing 'ts_utc' in {key}.jsonl line {idx}"
            event_types.add(ev["type"])

        # Must contain incident.detected, solution.updated, and options.ready
        assert "incident.detected" in event_types, f"Missing incident.detected in {key}.jsonl"
        assert "solution.updated" in event_types, f"Missing solution.updated in {key}.jsonl"
        assert "options.ready" in event_types, f"Missing options.ready in {key}.jsonl"

        # Check options.ready contract and digit-free guardrail
        options_ready = next(e for e in lines if e["type"] == "options.ready")
        me = options_ready.get("model_execution", {})
        assert me.get("cached") is True, f"model_execution.cached must be True in {key}.jsonl"
        assert bool(me.get("cached_at_utc")), f"model_execution.cached_at_utc missing in {key}.jsonl"
        assert bool(me.get("model")), f"model_execution.model missing in {key}.jsonl"
        assert bool(me.get("response_id")), f"model_execution.response_id missing in {key}.jsonl"

        opts = options_ready.get("options", [])
        assert len(opts) >= 2, f"Expected at least 2 options in {key}.jsonl, got {len(opts)}"
        opt_a, opt_b = opts[0], opts[1]

        assert opt_a.get("validation", {}).get("passed") is True, f"Option A validation failed in {key}.jsonl"
        assert opt_b.get("validation", {}).get("passed") is True, f"Option B validation failed in {key}.jsonl"
        assert opt_a.get("tradeoff_tag") != opt_b.get("tradeoff_tag"), f"Options have identical tradeoff tags in {key}.jsonl"

        # Check zero digits across all prose fields
        diag = options_ready.get("diagnosis_es", "")
        assert not has_digits(diag), f"Digit found in diagnosis_es ({key}): {diag}"

        for opt in opts:
            t = opt.get("title_es", "")
            r = opt.get("rationale_es", "")
            assert not has_digits(t), f"Digit found in option title ({key}): {t}"
            assert not has_digits(r), f"Digit found in option rationale ({key}): {r}"

        for ev in lines:
            if ev["type"] == "agent.thought":
                delta = ev.get("delta", "")
                assert not has_digits(delta), f"Digit found in agent thought delta ({key}): {delta}"
            elif ev["type"] == "agent.note":
                note_text = ev.get("text_es", "")
                assert not has_digits(note_text), f"Digit found in agent note text ({key}): {note_text}"


def test_all_jsonl_files_in_library_pass_digit_free_and_cache_checks():
    jsonl_files = list(INCIDENTS_DIR.glob("*.jsonl"))
    assert len(jsonl_files) >= 86, f"Expected >= 86 incident files, found {len(jsonl_files)}"

    for fpath in jsonl_files:
        with open(fpath, encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]

        opt_event = next((e for e in lines if e.get("type") == "options.ready"), None)
        assert opt_event is not None, f"File {fpath.name} missing options.ready"
        assert opt_event.get("model_execution", {}).get("cached") is True
        assert not has_digits(opt_event.get("diagnosis_es", ""))
        for opt in opt_event.get("options", []):
            assert not has_digits(opt.get("title_es", ""))
            assert not has_digits(opt.get("rationale_es", ""))
