"""Record the canonical LiveEvent JSONL demo stream (`frontend/src/live/fixtures/demo-stream.jsonl`)
directly from the final `LiveSession` engine (`backend/live/engine.py`) and `run_incident_evaluation`
(`backend/live/agent_loop.py`) with real Gemini 4 Argon (`allow_live_gemini=True`), HiGHS LP solver,
and independent physical validator.

Verifies before writing:
1. Only operational levers (`OPERATIONAL_LEVER_TYPES`) are used in crisis options.
2. Pairwise `tradeoff_tag` truthfulness (`is_tag_truthful`) and distinctness across both options.
3. `recommended_id` never points to a 0-household option when the other option reconnects > 0 households,
   and autonomous mode only executes options with positive improvement.
4. Zero digits in all Gemini/agent prose fields (`has_digits`).
5. 100% JSON Schema conformance against `contracts/live.schema.json`.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.live.agent_loop import (
    OPERATIONAL_LEVER_TYPES,
    has_digits,
    is_tag_truthful,
    option_has_positive_improvement,
    sanitize_no_digits,
)
from backend.live.engine import LiveSession

OUT_PATH = ROOT / "frontend" / "src" / "live" / "fixtures" / "demo-stream.jsonl"
SCHEMA_PATH = ROOT / "contracts" / "live.schema.json"


async def record_live_session_stream() -> list[dict[str, Any]]:
    session = LiveSession(
        session_id="ses-live-demo-chile",
        speed_s_per_hour=4.0,
        start_hour=12.0,
        allow_live_gemini=True,
        countdown_step_s=1.0,
    )
    # Mark initial snapshot clock as running=True for offline demo playback
    session.running = True
    session.event_history[0]["clock"]["running"] = True

    # 12:15 -> clock.tick
    session.hour = 12.25
    session._emit({"type": "clock.tick", "running": True})

    # 12:30 -> periodic operator note (midday solar congestion)
    session.hour = 12.50
    session.emit_note(
        "Corredor Norte Chico hacia la Zona Central opera a plena capacidad con recorte solar preventivo en el norte bajo despacho económico."
    )

    # 18:00 -> Incident 1: Jury triggers sudden outage of gas_centro [18, 22)
    session.hour = 18.0
    inc1 = await session.disrupt(
        "gas_centro",
        duration_h=4,
        source="jury",
        jury_name="Prof. María González",
        from_hour_override=18,
        wait_for_options=True,
    )

    # 18:21 -> Operator applies recommended option
    session.hour = 18.35
    await session.decide(
        incident_id=inc1["incident_id"],
        option_id=None,
        decision="apply",
        by="operator",
    )

    # 19:00 -> Incident 2: Jury triggers L3 corridor outage [19, 22) with autonomous mode enabled
    session.hour = 19.0
    session.autonomy = True
    await session.disrupt(
        "L3",
        duration_h=3,
        source="jury",
        jury_name="Dr. Carlos Muñoz",
        from_hour_override=19,
        wait_for_options=True,
    )

    # Wait for autonomous 5->0 countdown and auto-apply to complete
    cd_task = session._countdown_task
    if cd_task is not None:
        await cd_task

    # 22:00 -> Both disruptions reach to_hour=22 and expire; grid returns to normal
    await session.set_clock("seek", hour=22.0)

    # 22:06 -> Final operator note confirming normal restoration
    session.hour = 22.1
    session.emit_note(
        sanitize_no_digits(
            "Activos restituidos y demanda residencial abastecida; el Sistema Eléctrico Nacional retorna a estado normal bajo supervisión continua."
        )
    )

    return list(session.event_history)


def verify_stream(events: list[dict[str, Any]]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)

    options_ready_events = []
    thought_events = []
    countdown_events = []
    for idx, ev in enumerate(events):
        errs = list(validator.iter_errors(ev))
        assert not errs, f"Event #{idx} ({ev.get('type')}) failed schema validation: {errs[0].message}"

        etype = ev.get("type")
        if etype == "agent.thought":
            thought_events.append(ev)
            assert not has_digits(ev["delta"]), f"Digit in agent.thought: {ev['delta']}"
            assert "contingencia detectada en el sistema eléctrico nacional" not in ev["delta"].lower(), (
                f"Generic boilerplate thought detected: {ev['delta']}"
            )
        elif etype == "agent.note":
            assert not has_digits(ev["text_es"]), f"Digit in agent.note: {ev['text_es']}"
        elif etype == "agent.tool_call":
            assert not has_digits(ev["args_summary_es"]), f"Digit in tool_call: {ev['args_summary_es']}"
        elif etype == "autonomy.countdown":
            countdown_events.append(ev)
        elif etype == "options.ready":
            options_ready_events.append(ev)
            me = ev["model_execution"]
            assert me["model"] == "gemini-4-argon", f"Expected gemini-4-argon, got {me}"
            assert me["status"] == "ok", f"Expected status ok, got {me}"
            assert me.get("response_id") and not str(me["response_id"]).startswith("det-"), (
                f"Expected real Gemini response_id, got {me}"
            )
            assert not has_digits(ev["diagnosis_es"]), f"Digit in diagnosis_es: {ev['diagnosis_es']}"
            opts = ev["options"]
            assert len(opts) == 2, f"Expected 2 options, got {len(opts)}"
            opt_a, opt_b = opts[0], opts[1]
            for opt in (opt_a, opt_b):
                assert not has_digits(opt["title_es"]), f"Digit in title_es: {opt['title_es']}"
                assert not has_digits(opt["rationale_es"]), f"Digit in rationale_es: {opt['rationale_es']}"
                assert opt["validation"]["passed"] is True, f"Option {opt['option_id']} failed validation"
                for lv in opt["levers"]:
                    assert lv["type"] in OPERATIONAL_LEVER_TYPES, (
                        f"Non-operational lever {lv['type']} in crisis option {opt['option_id']}"
                    )

            # Verify pairwise tradeoff_tag truthfulness and distinctness
            assert opt_a["tradeoff_tag"] != opt_b["tradeoff_tag"], "Duplicate tradeoff_tag"
            assert is_tag_truthful(opt_a["tradeoff_tag"], opt_a["metrics"], opt_b["metrics"]), (
                f"Option A tag {opt_a['tradeoff_tag']} contradicts metrics: A={opt_a['metrics']} vs B={opt_b['metrics']}"
            )
            assert is_tag_truthful(opt_b["tradeoff_tag"], opt_b["metrics"], opt_a["metrics"]), (
                f"Option B tag {opt_b['tradeoff_tag']} contradicts metrics: B={opt_b['metrics']} vs A={opt_a['metrics']}"
            )

            # Verify recommended_id never points to 0 households when the other > 0
            rec_opt = opt_a if ev["recommended_id"] == opt_a["option_id"] else opt_b
            other_opt = opt_b if rec_opt is opt_a else opt_a
            if other_opt["metrics"]["households_reconnected"] > 0:
                assert option_has_positive_improvement(rec_opt), (
                    f"recommended_id {ev['recommended_id']} has 0 improvement while other option has {other_opt['metrics']}"
                )

    assert len(options_ready_events) == 2, f"Expected 2 options.ready events, got {len(options_ready_events)}"
    assert len(thought_events) >= 2, f"Expected >= 2 agent.thought events, got {len(thought_events)}"
    inc1_thoughts = [e["delta"] for e in thought_events if e["incident_id"] == options_ready_events[0]["incident_id"]]
    inc2_thoughts = [e["delta"] for e in thought_events if e["incident_id"] == options_ready_events[1]["incident_id"]]
    assert inc1_thoughts and inc2_thoughts and set(inc1_thoughts) != set(inc2_thoughts), (
        "Incident 1 and Incident 2 thoughts must be distinct and specific"
    )

    inc1_opt_ids = {o["option_id"] for o in options_ready_events[0]["options"]}
    inc2_opt_ids = {o["option_id"] for o in options_ready_events[1]["options"]}
    assert inc1_opt_ids != inc2_opt_ids, f"Incident 1 and 2 have identical options: {inc1_opt_ids}"
    inc2_lever_types = {
        lv["type"]
        for o in options_ready_events[1]["options"]
        for lv in o["levers"]
    }
    assert inc2_lever_types & {"emergency_rating", "hydro_reserve_release"}, (
        f"Expected emergency_rating or hydro_reserve_release in Incident 2 (L3), got {inc2_lever_types}"
    )

    from datetime import datetime

    incident_events = [e for e in events if e.get("type") == "incident.detected"]
    assert len(incident_events) == 2, f"Expected 2 incident.detected events, got {len(incident_events)}"
    jury_names = [e.get("disruption", {}).get("jury_name") for e in incident_events]
    assert all(jury_names) and len(set(jury_names)) == 2, (
        f"Expected 2 distinct non-empty jury_name values on incident.detected, got {jury_names}"
    )

    assert len(countdown_events) == 6, f"Expected 6 autonomy.countdown events, got {len(countdown_events)}"
    cd_hours = [e["hour"] for e in countdown_events]
    assert len(set(cd_hours)) == 6 and cd_hours == sorted(cd_hours), (
        f"Expected strictly increasing countdown hours, got {cd_hours}"
    )
    cd_ts = [datetime.fromisoformat(e["ts_utc"]) for e in countdown_events]
    cd_deltas = [(cd_ts[i + 1] - cd_ts[i]).total_seconds() for i in range(len(cd_ts) - 1)]
    assert all(0.8 <= d <= 1.5 for d in cd_deltas), (
        f"Expected ~1.0s spacing between autonomy.countdown events, got {cd_deltas}"
    )


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    events = asyncio.run(record_live_session_stream())
    verify_stream(events)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    print(f"Wrote and verified {len(events)} real engine LiveEvents to {OUT_PATH}")


if __name__ == "__main__":
    main()
