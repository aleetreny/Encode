"""Jimmy monitor: metrics, severity, wording, model fallbacks and the engine's hourly/escalation cadence.

Nothing here touches the network: the Gemini HTTP helper is replaced in every test.
"""

import asyncio
import copy
import threading
import time

import httpx
import pytest

from backend.live import agent_loop, monitor
from backend.live.agent_loop import has_digits
from backend.live.engine import LiveSession


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    attempts: list[dict] = []

    def blocked(**kwargs):
        attempts.append(kwargs)
        raise AssertionError("test tried to call Gemini")

    monkeypatch.setattr(agent_loop, "_call_gemini_generate_content", blocked)
    yield attempts
    assert not attempts, "a test reached the Gemini helper without installing its own fake"


@pytest.fixture
def no_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)


@pytest.fixture
def fake_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-not-a-provider-key")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)


def gemini_reply(text: str, response_id: str | None = "resp-monitor-1") -> dict:
    reply: dict = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    if response_id:
        reply["responseId"] = response_id
    return reply


# --------------------------------------------------------------------------- hand-built 3-hour grid


def small_scenario() -> dict:
    return {
        "generators": [
            {"id": "solar_a", "technology": "solar", "capacity_mw": 100},
            {"id": "wind_b", "technology": "wind", "capacity_mw": 50},
            {"id": "gas_a", "technology": "gas", "capacity_mw": 200},
        ],
        "renewable_availability_mw_by_generator": {"solar_a": [0, 100, 100], "wind_b": [10, 40, 20]},
        "batteries": [
            {"id": "b1", "power_capacity_mw": 20, "energy_capacity_mwh": 40},
            {"id": "b_res", "power_capacity_mw": 50, "energy_capacity_mwh": 100, "standby": True},
        ],
        "lines": [{"id": "L1", "capacity_mw": 100}, {"id": "L2", "capacity_mw": 200}],
    }


def small_solution() -> dict:
    return {
        "status": "optimal",
        "demand_mw": {"n1": [100.0, 120.0, 130.0], "n2": [50.0, 60.0, 70.0]},
        "available_mw": {
            "solar_a": [0.0, 100.0, 100.0],
            "wind_b": [10.0, 40.0, 20.0],
            "gas_a": [200.0, 200.0, 200.0],
        },
        "generation_mw": {
            "solar_a": [0.0, 60.0, 80.0],
            "wind_b": [10.0, 40.0, 20.0],
            "gas_a": [140.0, 80.0, 100.0],
        },
        "line_flow_mw": {"L1": [50.0, -92.34, 10.0], "L2": [-150.0, -120.0, 0.0]},
        "line_capacity_mw": {"L1": [100.0] * 3, "L2": [200.0] * 3},
        "battery_flow_mw": {"b1": [0.0, 0.0, 0.0], "b_res": [0.0, 0.0, 0.0]},
        "battery_soc_mwh": {"b1": [20.0, 10.0, 5.0], "b_res": [100.0, 100.0, 100.0]},
        "unserved_mw": {"n1": [0.0, 0.0, 0.0], "n2": [0.0, 0.0, 3.0]},
        "households_off": {"n1": [0.0, 0.0, 0.0], "n2": [0.0, 0.0, 3000.0]},
    }


# --------------------------------------------------------------------------- metrics


def test_metrics_formulas_on_hand_built_solution():
    m = monitor.compute_monitor_metrics(small_scenario(), small_solution(), 1.7)
    # demand: 120 + 60
    assert m["demand_mw"] == 180.0
    # (available 100 + 40 + 200 + battery discharge 20 - demand 180) / 180; standby b_res excluded
    assert m["reserve_margin_pct"] == 100.0
    # |92.34| / 100, L2 is only 60 %
    assert m["max_line_loading_pct"] == 92.3
    assert m["max_line_id"] == "L1"
    # renewable available (100 + 40) - generated (60 + 40); gas is not renewable
    assert m["curtailment_mw"] == 40.0
    assert m["unserved_mw"] == 0.0
    assert m["households_off"] == 0.0
    # net load = demand - renewable generation: hour 1 = 180 - 100 = 80, hour 2 = 200 - 100 = 100
    assert m["net_load_ramp_mw_per_h"] == 20.0
    # only b1 counts: 10 / 40
    assert m["storage_soc_pct"] == 25.0
    assert all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in m.values() if v != m["max_line_id"])


def test_metrics_use_the_hour_index_and_report_unserved_households():
    m = monitor.compute_monitor_metrics(small_scenario(), small_solution(), 2.0)
    assert m["unserved_mw"] == 3.0
    assert m["households_off"] == 3000.0
    assert m["demand_mw"] == 200.0
    # last hour of the horizon has no next hour to compare with
    assert m["net_load_ramp_mw_per_h"] == 0.0
    # hour index is clamped into the horizon
    assert monitor.compute_monitor_metrics(small_scenario(), small_solution(), 23.5)["demand_mw"] == 200.0


def test_metrics_round_to_one_decimal():
    sol = small_solution()
    sol["demand_mw"]["n1"][1] = 120.04
    sol["battery_soc_mwh"]["b1"][1] = 12.349
    m = monitor.compute_monitor_metrics(small_scenario(), sol, 1)
    assert m["demand_mw"] == 180.0
    assert m["storage_soc_pct"] == 30.9


def test_standby_battery_counts_once_a_plan_activates_it():
    sol = small_solution()
    sol["battery_flow_mw"]["b_res"] = [0.0, 25.0, 0.0]
    sol["battery_soc_mwh"]["b_res"] = [100.0, 75.0, 75.0]
    m = monitor.compute_monitor_metrics(small_scenario(), sol, 1)
    # (10 + 75) / (40 + 100)
    assert m["storage_soc_pct"] == 60.7
    # discharge capacity 20 + 50
    assert m["reserve_margin_pct"] == round((340 + 70 - 180) / 180 * 100, 1)


def test_battery_outage_removes_discharge_capacity():
    base = monitor.compute_monitor_metrics(small_scenario(), small_solution(), 1)
    out = monitor.compute_monitor_metrics(small_scenario(), small_solution(), 1, outaged_battery_ids=["b1"])
    assert out["reserve_margin_pct"] == round((340 - 180) / 180 * 100, 1)
    assert out["reserve_margin_pct"] < base["reserve_margin_pct"]


def test_line_in_outage_is_not_a_loading_reading():
    sol = small_solution()
    sol["line_capacity_mw"]["L1"] = [100.0, 0.0, 100.0]
    sol["line_flow_mw"]["L1"] = [50.0, 0.0, 10.0]
    m = monitor.compute_monitor_metrics(small_scenario(), sol, 1)
    assert m["max_line_id"] == "L2"
    assert m["max_line_loading_pct"] == 60.0


# --------------------------------------------------------------------------- severity


CALM = {
    "unserved_mw": 0.0,
    "households_off": 0.0,
    "max_line_loading_pct": 50.0,
    "max_line_id": "L1",
    "reserve_margin_pct": 40.0,
    "storage_soc_pct": 60.0,
}


@pytest.mark.parametrize(
    "change, severity, watch",
    [
        ({}, "info", []),
        ({"max_line_loading_pct": 89.9}, "info", []),
        ({"reserve_margin_pct": 10.0}, "info", []),
        ({"storage_soc_pct": 20.0}, "info", []),
        ({"max_line_loading_pct": 90.0}, "watch", ["L1"]),
        ({"max_line_loading_pct": 99.9}, "watch", ["L1"]),
        ({"reserve_margin_pct": 9.9}, "watch", ["reserve_margin"]),
        ({"storage_soc_pct": 19.9}, "watch", ["storage_soc"]),
        ({"max_line_loading_pct": 100.0}, "watch", ["L1"]),
        ({"unserved_mw": 0.1}, "alert", ["unserved"]),
        ({"households_off": 1.0}, "alert", ["unserved"]),
        (
            {"unserved_mw": 5.0, "max_line_loading_pct": 95.0, "reserve_margin_pct": 2.0, "storage_soc_pct": 1.0},
            "alert",
            ["unserved", "L1", "reserve_margin", "storage_soc"],
        ),
    ],
)
def test_classify_threshold_edges(change, severity, watch):
    assert monitor.classify({**CALM, **change}) == (severity, watch)


def test_classify_lists_every_hot_line_when_loadings_are_given():
    severity, watch = monitor.classify(
        {**CALM, "max_line_loading_pct": 96.0, "max_line_id": "L2"},
        {"L1": 91.0, "L2": 96.0, "L3": 40.0},
    )
    assert (severity, watch) == ("watch", ["L2", "L1"])


def test_assess_is_alert_when_the_solution_is_not_optimal():
    sol = small_solution()
    sol["status"] = "infeasible"
    a = monitor.assess(small_scenario(), sol, 0)
    assert a.severity == "alert"
    assert a.watch[0] == "solver_status"
    assert "no es óptima" in monitor.deterministic_text_es(a.metrics, a.severity, a.watch)


# --------------------------------------------------------------------------- deterministic wording


def test_deterministic_text_is_specific_and_digit_free():
    full = {**CALM, "max_line_loading_pct": 100.0, "max_line_id": "L2", "demand_mw": 1000.0}
    hot = monitor.deterministic_text_es({**full, "curtailment_mw": 120.0}, "alert", ["L2"], "alerta")
    assert "corredor troncal del Norte Chico a la Zona Central" in hot
    assert "límite" in hot and "recorta" in hot and "una parte considerable" in hot
    assert "una parte pequeña" in monitor.deterministic_text_es({**full, "curtailment_mw": 10.0}, "alert", ["L2"])
    assert "una parte muy grande" in monitor.deterministic_text_es({**full, "curtailment_mw": 300.0}, "alert", ["L2"])

    ramp = monitor.deterministic_text_es({**CALM, "demand_mw": 1000.0, "net_load_ramp_mw_per_h": 200.0}, "info", [])
    assert "rampa" in ramp

    storage = monitor.deterministic_text_es({**CALM, "storage_soc_pct": 5.0}, "watch", ["storage_soc"])
    assert "almacenamiento" in storage

    reserve = monitor.deterministic_text_es({**CALM, "reserve_margin_pct": 3.0}, "watch", ["reserve_margin"])
    assert "reserva" in reserve

    unserved = monitor.deterministic_text_es({**CALM, "unserved_mw": 12.0, "households_off": 12000.0}, "alert", ["unserved"], "emergencia")
    assert "sin suministro" in unserved

    recovery = monitor.deterministic_text_es(CALM, "info", [], "recuperacion")
    assert "plan de mitigación" in recovery

    texts = {hot, ramp, storage, reserve, unserved, recovery}
    assert len(texts) == 6
    assert not any(has_digits(t) for t in texts)


def test_deterministic_text_does_not_depend_on_the_clock():
    a = monitor.deterministic_text_es(CALM, "info", [], "normal")
    assert a == monitor.deterministic_text_es(CALM, "info", [], "normal")
    assert "L1" not in a and not has_digits(a)


# --------------------------------------------------------------------------- model wrapper


def run(coro):
    return asyncio.run(coro)


def assessment_for_small_grid(hour: float = 1.0) -> monitor.MonitorAssessment:
    return monitor.assess(small_scenario(), small_solution(), hour)


def test_no_key_gives_labelled_deterministic_note(no_key):
    a = assessment_for_small_grid()
    note = run(monitor.generate_monitor_note(a, hour=1.0, grid_state="alerta"))
    assert note["type"] == "agent.note"
    assert note["kind"] == "monitor"
    assert note["severity"] == a.severity == "watch"
    assert note["watch"] == a.watch == ["L1"]
    assert note["metrics"] == a.metrics
    assert note["model_execution"] == {
        "model": "deterministic-monitor",
        "role": "monitor",
        "status": "no_key",
        "latency_ms": 0,
        "cached": False,
    }
    assert note["text_es"] and not has_digits(note["text_es"])


def test_ok_path_uses_the_fast_model_and_strips_digits(fake_key, monkeypatch):
    monkeypatch.setenv("GRIDPILOT_MODEL_MONITOR", "fake-fast-model")
    seen: dict = {}

    def fake(**kwargs):
        seen.update(kwargs)
        return gemini_reply("El corredor L1 está al 92% de su capacidad.\nVigilar el recorte solar de la tarde.")

    monkeypatch.setattr(agent_loop, "_call_gemini_generate_content", fake)
    note = run(
        monitor.generate_monitor_note(
            assessment_for_small_grid(),
            hour=1.0,
            grid_state="alerta",
            active_events=[{"asset_id": "L2", "type": "line_outage"}],
            previous_text="Nota previa de prueba.",
        )
    )
    ex = note["model_execution"]
    assert (ex["model"], ex["role"], ex["status"], ex["cached"], ex["response_id"]) == (
        "fake-fast-model",
        "monitor",
        "ok",
        False,
        "resp-monitor-1",
    )
    assert isinstance(ex["latency_ms"], int)
    assert not has_digits(note["text_es"])
    assert "Vigilar el recorte solar" in note["text_es"]
    assert (note["kind"], note["severity"], note["watch"]) == ("monitor", "watch", ["L1"])

    assert seen["model"] == "fake-fast-model"
    assert seen["timeout_s"] == monitor.MONITOR_TIMEOUT_S == 3.0
    assert seen["system_instruction"] == monitor.MONITOR_SYSTEM_PROMPT_ES
    prompt = seen["contents"][0]["parts"][0]["text"]
    assert "corredor troncal del Norte Grande al Norte Chico" in prompt  # most loaded line, named
    assert "corte de un corredor: corredor troncal del Norte Chico a la Zona Central" in prompt  # active fault, named
    assert "Nota previa de prueba." in prompt
    assert "max_line_loading_pct=92.3" in prompt


@pytest.mark.parametrize(
    "reply",
    [
        gemini_reply(""),
        gemini_reply("1234 5678 90"),
        gemini_reply("Corto."),
        {"candidates": []},
        {"candidates": [{"content": {"parts": [{"text": "pensando " * 5, "thought": True}]}}]},
    ],
)
def test_unusable_model_reply_falls_back_with_error_status(fake_key, monkeypatch, reply):
    monkeypatch.setattr(agent_loop, "_call_gemini_generate_content", lambda **kw: reply)
    note = run(monitor.generate_monitor_note(assessment_for_small_grid(), hour=1.0, grid_state="normal"))
    assert note["model_execution"]["status"] == "error"
    assert note["model_execution"]["model"] == "deterministic-monitor"
    assert note["text_es"] == monitor.deterministic_text_es(note["metrics"], note["severity"], note["watch"], "normal")


def test_http_error_falls_back_with_error_status(fake_key, monkeypatch):
    def broken(**kwargs):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(agent_loop, "_call_gemini_generate_content", broken)
    note = run(monitor.generate_monitor_note(assessment_for_small_grid(), hour=1.0, grid_state="normal"))
    assert note["model_execution"]["status"] == "error"
    assert note["model_execution"]["model"] == "deterministic-monitor"
    assert not has_digits(note["text_es"])


def test_slow_model_times_out_with_labelled_deterministic_note(fake_key, monkeypatch):
    release = threading.Event()

    def slow(**kwargs):
        release.wait(5.0)
        return gemini_reply("Respuesta tardía que nunca debe mostrarse en pantalla.")

    monkeypatch.setattr(agent_loop, "_call_gemini_generate_content", slow)

    async def scenario():
        t0 = time.perf_counter()
        try:
            note = await monitor.generate_monitor_note(
                assessment_for_small_grid(), hour=1.0, grid_state="normal", timeout_s=0.3
            )
            return note, time.perf_counter() - t0
        finally:
            release.set()  # let the abandoned worker thread end before the loop shuts down

    note, waited = run(scenario())
    assert waited < 2.0  # the caller was released at the timeout, not when the thread finished
    ex = note["model_execution"]
    assert (ex["model"], ex["role"], ex["status"], ex["cached"]) == ("deterministic-monitor", "monitor", "timeout", False)
    assert ex["latency_ms"] >= 250
    assert "tardía" not in note["text_es"]


# --------------------------------------------------------------------------- engine cadence


def monitor_notes(session: LiveSession) -> list[dict]:
    return [e for e in session.event_history if e["type"] == "agent.note" and e.get("kind") == "monitor"]


def test_one_monitor_note_per_simulated_hour(no_key):
    session = LiveSession("monitor-hourly", start_hour=6.0)
    session.hour = 6.9
    session._maybe_emit_monitor_note()
    assert monitor_notes(session) == []  # same hour as the start: nothing is due

    hour = 6.9
    while hour + 0.25 < 12.0:  # quarter-hour steps, like clock ticks at 4 simulated hours per minute
        hour = round(hour + 0.25, 2)
        session.hour = hour
        session._maybe_emit_monitor_note()

    notes = monitor_notes(session)
    assert [int(n["hour"]) for n in notes] == [7, 8, 9, 10, 11]
    for n in notes:
        assert n["model_execution"]["status"] == "no_key"
        assert set(n["metrics"]) >= {"demand_mw", "reserve_margin_pct", "max_line_loading_pct", "curtailment_mw"}
        assert not has_digits(n["text_es"])


def test_seek_to_another_hour_emits_one_note(no_key):
    session = LiveSession("monitor-seek", start_hour=7.0)
    run(session.set_clock("seek", hour=12.0))
    run(session.set_clock("seek", hour=12.5))
    notes = monitor_notes(session)
    assert [int(n["hour"]) for n in notes] == [12]
    assert notes[0]["severity"] in {"info", "watch", "alert"}


def test_severity_rise_emits_an_immediate_note_in_the_same_hour(no_key):
    async def scenario():
        session = LiveSession("monitor-escalation", start_hour=18.0, allow_live_gemini=False)
        assert monitor_notes(session) == []
        await session.disrupt("gas_centro", duration_h=4, from_hour_override=18, wait_for_options=True)
        return session

    session = run(scenario())
    notes = monitor_notes(session)
    assert len(notes) == 1
    note = notes[0]
    assert note["severity"] == "alert"
    assert note["metrics"]["unserved_mw"] > 0 and note["metrics"]["households_off"] > 0
    assert "unserved" in note["watch"]
    assert int(note["hour"]) == 18
    types = [e["type"] for e in session.event_history]
    assert types.index("solution.updated") < types.index("agent.note") < types.index("options.ready")

    # same hour, same severity: nothing more is due
    session._maybe_emit_monitor_note()
    assert len(monitor_notes(session)) == 1


def test_severity_that_stays_or_falls_does_not_repeat(no_key):
    session = LiveSession("monitor-quiet", start_hour=7.0, allow_live_gemini=False)
    session._monitor_rank = 2  # pretend the last reading was an alert
    session._maybe_emit_monitor_note()  # baseline at this hour is calmer: falls silently
    assert monitor_notes(session) == []
    assert session._monitor_rank < 2


def test_emit_note_keeps_working_for_custom_texts(no_key):
    session = LiveSession("monitor-custom", start_hour=7.0)
    ev = session.emit_note("Corredor Norte Chico a 100 por ciento con recorte solar.")
    assert ev["type"] == "agent.note"
    assert ev["kind"] == "periodic"
    assert not has_digits(ev["text_es"])
    assert "model_execution" not in ev


def test_clock_keeps_ticking_while_a_slow_model_is_pending(fake_key, monkeypatch):
    release = threading.Event()
    calls: list[dict] = []

    def slow(**kwargs):
        calls.append(kwargs)
        release.wait(5.0)
        return gemini_reply("Respuesta tardía que nunca debe mostrarse en pantalla.")

    monkeypatch.setattr(agent_loop, "_call_gemini_generate_content", slow)

    async def scenario():
        session = LiveSession("monitor-slow", start_hour=7.0, speed_s_per_hour=0.5, allow_live_gemini=True)
        t0 = time.monotonic()
        await session.set_clock("play")
        start_hour = session.hour
        await asyncio.sleep(2.4)  # two ticks; the first one made the monitor call, which is still blocked
        ticks_while_pending = [e for e in session.event_history if e["type"] == "clock.tick" and e["seq"] > 0]
        hour_while_pending = session.hour
        notes_while_pending = monitor_notes(session)
        calls_while_pending = len(calls)

        deadline = time.monotonic() + 5.0
        while not monitor_notes(session) and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        elapsed = time.monotonic() - t0
        ticks_at_note = [e for e in session.event_history if e["type"] == "clock.tick"]
        await session.set_clock("pause")
        release.set()
        if session._monitor_task:
            session._monitor_task.cancel()
        return (
            start_hour,
            hour_while_pending,
            len(ticks_while_pending),
            notes_while_pending,
            calls_while_pending,
            monitor_notes(session),
            elapsed,
            len(ticks_at_note),
        )

    start_hour, hour_pending, n_ticks, notes_pending, n_calls, notes, elapsed, ticks_at_note = run(scenario())
    assert hour_pending > start_hour + 1  # simulated time advanced while the model call was blocked
    assert n_ticks >= 2
    assert notes_pending == []  # the clock did not wait for the model
    assert n_calls == 1  # at most one call in flight, although two simulated hours went by
    assert ticks_at_note >= 3
    assert 2.5 < elapsed < 5.0  # 3 s timeout after the first tick
    ex = notes[0]["model_execution"]
    assert (ex["status"], ex["model"], ex["role"]) == ("timeout", "deterministic-monitor", "monitor")
    assert not has_digits(notes[0]["text_es"])


def test_a_late_answer_is_replaced_by_a_fresh_reading_and_the_grid_is_read_again(fake_key, monkeypatch):
    release = threading.Event()
    calls: list[str] = []

    def gated(**kwargs):
        calls.append(kwargs["contents"][0]["parts"][0]["text"])
        release.wait(5.0)
        return gemini_reply(f"Nota de prueba número uno para la llamada {len(calls)} del monitor.")

    monkeypatch.setattr(agent_loop, "_call_gemini_generate_content", gated)

    async def scenario():
        session = LiveSession("monitor-coalesce", start_hour=7.0, allow_live_gemini=True)
        session.hour = 8.0
        session._maybe_emit_monitor_note()  # starts the call for hour 8
        await asyncio.sleep(0.05)
        session.hour = 9.0
        session._maybe_emit_monitor_note()  # falls due during the call: flag only
        session.hour = 10.0
        session._maybe_emit_monitor_note()
        assert session._monitor_pending is True
        assert len(calls) == 1
        release.set()
        await asyncio.wait_for(session._monitor_task, 3.0)
        return session

    session = run(scenario())
    notes = monitor_notes(session)
    assert len(calls) == 2  # the hour-8 call, then one fresh call: never one per missed hour
    # The hour-8 answer arrived at hour 10: worded by code from the grid at hour 10, labelled stale.
    assert [n["model_execution"]["status"] for n in notes] == ["stale", "ok"]
    assert notes[0]["model_execution"]["model"] == "deterministic-monitor"
    assert all(n["hour"] == 10.0 for n in notes)
    assert not any(has_digits(n["text_es"]) for n in notes)


def test_an_escalation_queued_during_a_call_is_emitted_from_a_fresh_reading(fake_key, monkeypatch):
    release = threading.Event()

    def gated(**kwargs):
        release.wait(5.0)
        return gemini_reply("Nota de prueba sobre el estado actual de la red simulada del sistema.")

    monkeypatch.setattr(agent_loop, "_call_gemini_generate_content", gated)

    async def scenario():
        session = LiveSession("monitor-escalation-busy", start_hour=7.0, allow_live_gemini=True)
        session.hour = 8.0
        session._maybe_emit_monitor_note()  # call in flight
        await asyncio.sleep(0.05)
        calm = session._assess_monitor()
        alert = calm._replace(severity="alert", watch=["unserved"])
        monkeypatch.setattr(session, "_assess_monitor", lambda: alert)
        session._maybe_emit_monitor_note()  # severity rises during the call
        assert session._monitor_pending is True
        release.set()
        await asyncio.wait_for(session._monitor_task, 3.0)
        return session

    notes = monitor_notes(run(scenario()))
    assert [n["severity"] for n in notes][-1] == "alert"  # the queued escalation is not lost


def test_live_gemini_disabled_sessions_never_call_the_model(fake_key):
    session = LiveSession("monitor-offline", start_hour=7.0, allow_live_gemini=False)
    session.hour = 8.0
    session._maybe_emit_monitor_note()
    notes = monitor_notes(session)
    assert len(notes) == 1
    assert notes[0]["model_execution"]["status"] == "no_key"  # the autouse fixture proves no HTTP call happened


def test_assessment_does_not_mutate_the_solution(no_key):
    session = LiveSession("monitor-pure", start_hour=12.0)
    before = copy.deepcopy(session.solution)
    session._assess_monitor()
    session._maybe_emit_monitor_note()
    assert session.solution == before


def test_a_monitor_failure_never_breaks_the_clock(no_key, monkeypatch, caplog):
    session = LiveSession("monitor-broken", start_hour=7.0, allow_live_gemini=False)

    def broken():
        raise RuntimeError("bad solution shape")

    monkeypatch.setattr(session, "_assess_monitor", broken)
    session.hour = 8.0
    session._maybe_emit_monitor_note()  # logged, not raised, and no invented note
    assert monitor_notes(session) == []
    assert "could not assess" in caplog.text
