"""GridPilot Live Ops In-Memory Engine (`backend/live/engine.py`).

Manages:
- `LiveSession`: in-memory session state (clock, active disruptions, applied levers,
  current 24h solution, NTSyCS grid_state, SSE subscriber queues, decision log)
- `< 300 ms` disruption detection (`incident.detected` + `solution.updated`)
- Asynchronous candidate + Gemini 4 Argon option generation (`options.ready`)
- Autonomous countdown (`autonomy.countdown` 5->0) with operator `veto` cancellation
- Event expiration (`event.ended` + `solution.updated` returning to `normal`)
- Periodic `agent.note` every 3 simulated hours (digit-free)
- `SessionManager`: multi-session registry with auto-creation for `"demo"` or any session ID
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import copy
import datetime as dt
import math
import time
import uuid
from pathlib import Path
from typing import Any

from backend.live.agent_loop import (
    ASSET_NAMES_ES,
    compute_grid_state,
    compute_incident_impact,
    generate_periodic_note_es,
    lever_to_solver_mod,
    moderate_jury_name,
    option_has_positive_improvement,
    prepare_scenario_and_events,
    run_incident_evaluation,
    sanitize_no_digits,
    to_contract_solution,
)
from backend.live.catalog import build_catalog, scenario_path
from optimisation import load_scenario, solve, validate


class JuryRateLimitError(Exception):
    """Raised when a jury device exceeds the 30s cooldown or max 2 active events."""

    def __init__(self, code: str, message_es: str, status_code: int = 429) -> None:
        super().__init__(message_es)
        self.code = code
        self.message_es = message_es
        self.status_code = status_code


class LiveSession:
    """Single live simulation session for the Chilean SEN 5-node network."""

    def __init__(
        self,
        session_id: str,
        scenario: dict[str, Any] | None = None,
        *,
        speed_s_per_hour: float = 4.0,
        start_hour: float = 7.0,
        allow_live_gemini: bool = True,
        countdown_step_s: float = 1.0,
    ) -> None:
        self.session_id = session_id
        self.scenario = copy.deepcopy(scenario) if scenario is not None else load_scenario(scenario_path())
        self.catalog = build_catalog(self.scenario)
        self.hour: float = float(max(0.0, min(23.99, start_hour)))
        self.running: bool = False
        self.speed_s_per_hour: float = float(max(0.2, speed_s_per_hour))
        self.autonomy: bool = False
        self.allow_live_gemini: bool = allow_live_gemini
        self.countdown_step_s: float = countdown_step_s

        self.seq: int = 0
        self.active_events: list[dict[str, Any]] = []
        self.applied_levers: list[dict[str, Any]] = []
        self.event_history: list[dict[str, Any]] = []
        self.decision_log: list[dict[str, Any]] = []
        self.incident_records: dict[str, dict[str, Any]] = {}
        self.current_incident_id: str | None = None
        self.previous_option_ids: set[str] = set()

        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.jury_cooldowns: dict[str, float] = {}
        self._impact_preview_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
        self._last_note_hour_bucket: int = int(self.hour) // 3
        self._last_note_ts: float = 0.0

        self._clock_task: asyncio.Task[None] | None = None
        self._countdown_task: asyncio.Task[None] | None = None
        self._eval_tasks: set[asyncio.Task[Any]] = set()
        self._disruption_lock: asyncio.Lock | None = None

        # Initial baseline solve
        raw_base = solve(self.scenario)
        val_base = validate(self.scenario, raw_base)
        self.baseline_solution = to_contract_solution(
            self.scenario, raw_base, val_base, "sol_baseline_normal"
        )
        self.solution = copy.deepcopy(self.baseline_solution)
        self.grid_state: str = "normal"

        # Record initial session.snapshot as seq 0
        self.last_snapshot = self._emit(
            {
                "type": "session.snapshot",
                "catalog": self.catalog,
                "solution": self.solution,
                "grid_state": self.grid_state,
                "active_events": list(self.active_events),
                "autonomy": self.autonomy,
                "clock": {
                    "hour": round(self.hour, 2),
                    "running": self.running,
                    "speed_s_per_hour": self.speed_s_per_hour,
                },
            }
        )

    def _now_utc(self) -> str:
        return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _emit(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Attach envelope (`seq`, `session_id`, `hour`, `ts_utc`), record in history, and fan out to SSE queues."""
        event: dict[str, Any] = {
            "seq": self.seq,
            "session_id": self.session_id,
            "hour": round(float(self.hour), 2),
            "ts_utc": self._now_utc(),
            **payload,
        }
        self.seq += 1
        self.event_history.append(event)
        if event["type"] == "session.snapshot":
            self.last_snapshot = event

        dead: list[asyncio.Queue[dict[str, Any]]] = []
        for q in list(self.subscribers):
            try:
                q.put_nowait(event)
            except Exception:
                dead.append(q)
        for q in dead:
            self.subscribers.discard(q)
        return event

    def build_snapshot_event(self, emit_to_history: bool = False) -> dict[str, Any]:
        """Build a fresh `session.snapshot` reflecting current state."""
        payload = {
            "type": "session.snapshot",
            "catalog": self.catalog,
            "solution": self.solution,
            "grid_state": self.grid_state,
            "active_events": list(self.active_events),
            "autonomy": self.autonomy,
            "clock": {
                "hour": round(float(self.hour), 2),
                "running": self.running,
                "speed_s_per_hour": self.speed_s_per_hour,
            },
        }
        if emit_to_history:
            return self._emit(payload)
        return {
            "seq": max(0, self.seq - 1),
            "session_id": self.session_id,
            "hour": round(float(self.hour), 2),
            "ts_utc": self._now_utc(),
            **payload,
        }

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Subscribe an SSE client queue and preload the current `session.snapshot`."""
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=512)
        q.put_nowait(self.build_snapshot_event(emit_to_history=False))
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self.subscribers.discard(q)

    def _resolve_asset_type(self, asset_id: str, explicit_type: str | None = None) -> str:
        if explicit_type in ("generator_outage", "line_outage", "battery_outage"):
            return explicit_type
        gen_ids = {g["id"] for g in self.scenario.get("generators", [])}
        line_ids = {ln["id"] for ln in self.scenario.get("lines", [])}
        bat_ids = {b["id"] for b in self.scenario.get("batteries", [])}
        if asset_id in gen_ids:
            return "generator_outage"
        if asset_id in line_ids:
            return "line_outage"
        if asset_id in bat_ids:
            return "battery_outage"
        raise ValueError(f"Activo desconocido: {asset_id!r}")

    def _solve_current_state(self, solution_id: str, include_applied_levers: bool = True) -> dict[str, Any]:
        """Solve and validate the current network state with all `active_events` and optionally `applied_levers`."""
        scen_for_solve, solver_events = prepare_scenario_and_events(self.scenario, self.active_events)
        cand = None
        if include_applied_levers and self.applied_levers:
            mods = [lever_to_solver_mod(lv) for lv in self.applied_levers[:2]]
            cand = {"candidate_id": f"plan_{uuid.uuid4().hex[:6]}", "modifications": mods}
        raw_sol = solve(
            scen_for_solve,
            candidate=cand,
            events=solver_events,
            options={"allow_unserved": True},
        )
        val_rep = validate(scen_for_solve, raw_sol)
        return to_contract_solution(scen_for_solve, raw_sol, val_rep, solution_id)

    async def set_clock(
        self,
        action: str,
        *,
        hour: float | None = None,
        speed_s_per_hour: float | None = None,
    ) -> dict[str, Any]:
        """Control the session clock (`play`, `pause`, `seek`)."""
        if speed_s_per_hour is not None:
            self.speed_s_per_hour = float(max(0.2, speed_s_per_hour))
        if action == "seek" and hour is not None:
            old_hour = self.hour
            self.hour = float(max(0.0, min(23.99, hour)))
            await self._check_expired_events()
            await self._maybe_emit_periodic_note(force=(int(self.hour) == 12 and int(old_hour) != 12))
        elif action == "play":
            self.running = True
            self._ensure_clock_task()
        elif action == "pause":
            self.running = False
            if self._clock_task and not self._clock_task.done():
                self._clock_task.cancel()
                self._clock_task = None

        return self._emit({"type": "clock.tick", "running": self.running})

    def _ensure_clock_task(self) -> None:
        if self._clock_task is None or self._clock_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._clock_task = loop.create_task(self._clock_loop())
            except RuntimeError:
                pass

    async def _clock_loop(self) -> None:
        """1 Hz clock tick loop advancing simulated hour and expiring finished events."""
        last_ts = time.perf_counter()
        try:
            while self.running:
                await asyncio.sleep(1.0)
                if not self.running:
                    break
                now = time.perf_counter()
                dt_real = max(0.0, min(2.5, now - last_ts))
                last_ts = now
                dh = dt_real / max(0.2, self.speed_s_per_hour)
                self.hour = (self.hour + dh) % 24.0
                self._emit({"type": "clock.tick", "running": self.running})
                await self._check_expired_events()
                await self._maybe_emit_periodic_note()
        except asyncio.CancelledError:
            return

    async def _check_expired_events(self) -> list[str]:
        """Expire any active disruption where `int(floor(hour)) >= to_hour`."""
        expired_ids: list[str] = []
        remaining: list[dict[str, Any]] = []
        cur_h = int(math.floor(self.hour))
        for ev in self.active_events:
            if cur_h >= int(ev["to_hour"]) and cur_h >= int(ev["from_hour"]):
                expired_ids.append(ev["event_id"])
            else:
                remaining.append(ev)

        if expired_ids:
            self.active_events = remaining
            if not self.active_events:
                self.applied_levers = []
            for eid in expired_ids:
                self._emit({"type": "event.ended", "event_id": eid})
            new_sol = self._solve_current_state(
                f"sol_after_end_{uuid.uuid4().hex[:6]}",
                include_applied_levers=bool(self.active_events),
            )
            self.solution = new_sol
            self.grid_state = compute_grid_state(
                self.solution,
                self.active_events,
                has_applied_plan=bool(self.applied_levers),
            )
            self._emit(
                {
                    "type": "solution.updated",
                    "reason": "event_ended",
                    "solution": self.solution,
                    "grid_state": self.grid_state,
                }
            )
        return expired_ids

    async def expire_all_events(self) -> list[str]:
        """Explicitly end all currently active disruptions (used for deterministic demo/testing)."""
        if not self.active_events:
            return []
        expired_ids = [ev["event_id"] for ev in self.active_events]
        self.active_events = []
        self.applied_levers = []
        for eid in expired_ids:
            self._emit({"type": "event.ended", "event_id": eid})
        self.solution = copy.deepcopy(self.baseline_solution)
        self.grid_state = "normal"
        self._emit(
            {
                "type": "solution.updated",
                "reason": "event_ended",
                "solution": self.solution,
                "grid_state": self.grid_state,
            }
        )
        return expired_ids

    async def _maybe_emit_periodic_note(self, force: bool = False) -> dict[str, Any] | None:
        """Emit at most one `agent.note` every 3 simulated hours, with frequency rate limit."""
        bucket = int(self.hour) // 3
        now = time.monotonic()
        if not force:
            if bucket == self._last_note_hour_bucket:
                return None
            if now - self._last_note_ts < 2.0:
                return None
        self._last_note_hour_bucket = bucket
        self._last_note_ts = now
        text_es = generate_periodic_note_es(self.hour, self.grid_state, self.solution)
        return self._emit({"type": "agent.note", "text_es": text_es})

    def emit_note(self, custom_text_es: str | None = None) -> dict[str, Any]:
        """Emit an immediate digit-free `agent.note`."""
        text = (
            sanitize_no_digits(custom_text_es)
            if custom_text_es
            else generate_periodic_note_es(self.hour, self.grid_state, self.solution)
        )
        return self._emit({"type": "agent.note", "text_es": text})

    def check_jury_limits(self, device_key: str) -> None:
        """Enforce Jury rules: max 2 active events in total, and 1 disruption per device every 30s."""
        if len(self.active_events) >= 2:
            raise JuryRateLimitError(
                code="MAX_ACTIVE_EVENTS",
                message_es="Ya hay dos contingencias activas en la red. Espera a que se resuelva una antes de provocar otra falla.",
                status_code=409,
            )
        now = time.monotonic()
        last = self.jury_cooldowns.get(device_key)
        if last is not None and (now - last) < 30.0:
            rem = int(math.ceil(30.0 - (now - last)))
            raise JuryRateLimitError(
                code="JURY_COOLDOWN",
                message_es=f"Límite por dispositivo activo: espera {rem} segundos antes de provocar otra falla.",
                status_code=429,
            )
        self.jury_cooldowns[device_key] = now

    async def disrupt(
        self,
        asset_id: str,
        *,
        duration_h: int = 4,
        source: str = "operator",
        jury_name: str | None = None,
        explicit_type: str | None = None,
        from_hour_override: int | None = None,
        wait_for_options: bool = False,
    ) -> dict[str, Any]:
        """Trigger a sudden asset disruption, emit `incident.detected` + `solution.updated` in <300ms,
        and launch background candidate + Gemini evaluation.
        """
        if self._disruption_lock is None:
            self._disruption_lock = asyncio.Lock()

        async with self._disruption_lock:
            # Cancel any pending autonomy countdown from a previous incident so we re-evaluate the stacked state
            self._cancel_countdown()

            dtype = self._resolve_asset_type(asset_id, explicit_type)
            dur = max(1, min(6, int(duration_h or 4)))
            fh = int(from_hour_override) if from_hour_override is not None else int(math.floor(self.hour))
            fh = max(0, min(22, fh))
            th = max(fh + 2, min(24, fh + dur))

            event_id = f"ev_{asset_id}_{fh}_{uuid.uuid4().hex[:4]}"
            disruption: dict[str, Any] = {
                "event_id": event_id,
                "type": dtype,
                "asset_id": asset_id,
                "from_hour": fh,
                "to_hour": th,
                "source": source if source in ("operator", "jury", "script") else "operator",
            }
            mod_name = moderate_jury_name(jury_name)
            if mod_name:
                disruption["jury_name"] = mod_name

            # Stack disruption if same asset isn't already outaged in the same window
            self.active_events = [
                e for e in self.active_events if e["asset_id"] != asset_id
            ] + [disruption]

            incident_id = f"inc_{asset_id}_{fh}_{uuid.uuid4().hex[:4]}"
            self.current_incident_id = incident_id

            # Fast (< 300ms) no-action solve with all active events
            inc_sol = self._solve_current_state(
                f"sol_{incident_id}_no_action",
                include_applied_levers=False,
            )
            self.solution = inc_sol
            impact = compute_incident_impact(inc_sol)
            self.grid_state = compute_grid_state(
                inc_sol,
                self.active_events,
                has_applied_plan=False,
            )

            inc_event = self._emit(
                {
                    "type": "incident.detected",
                    "incident_id": incident_id,
                    "disruption": disruption,
                    "impact": impact,
                }
            )
            self._emit(
                {
                    "type": "solution.updated",
                    "reason": "incident",
                    "solution": self.solution,
                    "grid_state": self.grid_state,
                }
            )

            self.incident_records[incident_id] = {
                "incident_id": incident_id,
                "disruption": disruption,
                "active_events_snapshot": copy.deepcopy(self.active_events),
                "from_hour": fh,
                "to_hour": th,
                "baseline_solution": inc_sol,
                "impact": impact,
                "detected_at_utc": inc_event["ts_utc"],
                "options": None,
                "recommended_id": None,
                "decided": False,
            }

            if wait_for_options:
                await self._evaluate_and_emit_options(incident_id)
            else:
                task = asyncio.create_task(self._evaluate_and_emit_options(incident_id))
                self._eval_tasks.add(task)
                task.add_done_callback(self._eval_tasks.discard)

            return {
                "incident_id": incident_id,
                "event_id": event_id,
                "disruption": disruption,
                "impact": impact,
            }

    async def _evaluate_and_emit_options(self, incident_id: str) -> dict[str, Any] | None:
        """Run parallel candidate solver + Gemini 4 Argon loop in a worker thread and emit SSE events."""
        rec = self.incident_records.get(incident_id)
        if not rec:
            return None

        loop = asyncio.get_running_loop()

        def _emit_agent_step(payload: dict[str, Any]) -> None:
            self.hour = round(min(23.99, self.hour + 0.02), 2)
            self._emit(payload)

        def emit_thought_cb(delta: str) -> None:
            loop.call_soon_threadsafe(
                _emit_agent_step,
                {
                    "type": "agent.thought",
                    "incident_id": incident_id,
                    "delta": sanitize_no_digits(delta),
                },
            )

        def emit_tool_cb(tool_payload: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(
                _emit_agent_step,
                {
                    "type": "agent.tool_call",
                    "incident_id": incident_id,
                    **tool_payload,
                },
            )

        res = await asyncio.to_thread(
            run_incident_evaluation,
            incident_id=incident_id,
            scenario=self.scenario,
            active_disruptions=rec["active_events_snapshot"],
            base_sol=rec["baseline_solution"],
            from_hour=rec["from_hour"],
            to_hour=rec["to_hour"],
            emit_thought=emit_thought_cb,
            emit_tool_call=emit_tool_cb,
            allow_live_gemini=self.allow_live_gemini,
            exclude_candidate_ids=set(self.previous_option_ids),
        )

        # Allow any queued call_soon_threadsafe callbacks to flush before options.ready
        await asyncio.sleep(0.01)

        rec["options"] = res["options"]
        rec["recommended_id"] = res["recommended_id"]
        rec["diagnosis_es"] = res["diagnosis_es"]
        rec["model_execution"] = res["model_execution"]
        for opt in res["options"]:
            if opt.get("option_id"):
                self.previous_option_ids.add(str(opt["option_id"]))

        self.hour = round(min(23.99, self.hour + 0.02), 2)
        opt_event = self._emit(
            {
                "type": "options.ready",
                "incident_id": incident_id,
                "diagnosis_es": res["diagnosis_es"],
                "options": res["options"],
                "recommended_id": res["recommended_id"],
                "candidates_evaluated": res["candidates_evaluated"],
                "candidates_passed": res["candidates_passed"],
                "model_execution": res["model_execution"],
            }
        )

        # If autonomy is enabled and this is still the current undecided incident, start 5->0 countdown
        if self.autonomy and self.current_incident_id == incident_id and not rec.get("decided"):
            rec_opt = self._find_option(rec, res["recommended_id"])
            if (
                rec_opt
                and rec_opt.get("validation", {}).get("passed")
                and option_has_positive_improvement(rec_opt)
            ):
                self._start_countdown(incident_id, rec_opt["option_id"])
            else:
                self.emit_note(
                    "Modo autónomo en espera: ninguna maniobra operativa disponible reduce el déficit residencial actual, por lo que no se aplica ningún plan automáticamente."
                )

        return opt_event

    def _find_option(self, rec: dict[str, Any], option_id: str | None) -> dict[str, Any] | None:
        options = rec.get("options") or []
        if not options:
            return None
        for opt in options:
            if opt["option_id"] == option_id:
                return opt
        return options[0]

    def _cancel_countdown(self) -> None:
        try:
            cur = asyncio.current_task()
        except RuntimeError:
            cur = None
        if self._countdown_task and not self._countdown_task.done() and self._countdown_task is not cur:
            self._countdown_task.cancel()
        self._countdown_task = None

    def _start_countdown(self, incident_id: str, option_id: str) -> None:
        self._cancel_countdown()
        try:
            loop = asyncio.get_running_loop()
            self._countdown_task = loop.create_task(self._countdown_loop(incident_id, option_id))
        except RuntimeError:
            pass

    async def _countdown_loop(self, incident_id: str, option_id: str) -> None:
        """Emit `autonomy.countdown` 5->0 and auto-apply if not vetoed."""
        try:
            clock_active = self._clock_task is not None and not self._clock_task.done()
            if not clock_active:
                self.hour = round(min(23.99, self.hour + 0.02), 2)
            for secs in (5, 4, 3, 2, 1, 0):
                rec = self.incident_records.get(incident_id)
                if not rec or rec.get("decided") or not self.autonomy:
                    return
                rec_opt = self._find_option(rec, option_id)
                if not option_has_positive_improvement(rec_opt):
                    self.emit_note(
                        "Modo autónomo en espera: ninguna maniobra operativa disponible reduce el déficit residencial actual, por lo que no se aplica ningún plan automáticamente."
                    )
                    return
                self._emit(
                    {
                        "type": "autonomy.countdown",
                        "incident_id": incident_id,
                        "option_id": option_id,
                        "seconds_left": secs,
                    }
                )
                if secs > 0:
                    await asyncio.sleep(self.countdown_step_s)
                    clock_active = self._clock_task is not None and not self._clock_task.done()
                    if not clock_active:
                        dh = 1.0 / max(0.2, self.speed_s_per_hour)
                        self.hour = round(min(23.99, self.hour + dh), 2)
            rec = self.incident_records.get(incident_id)
            if rec and not rec.get("decided") and self.autonomy:
                clock_active = self._clock_task is not None and not self._clock_task.done()
                if not clock_active:
                    self.hour = round(min(23.99, self.hour + 0.02), 2)
                await self.decide(
                    incident_id=incident_id,
                    option_id=option_id,
                    decision="apply",
                    by="gemini_autonomous",
                )
        except asyncio.CancelledError:
            return

    async def set_autonomy(self, enabled: bool) -> bool:
        """Enable or disable autonomous mode."""
        self.autonomy = bool(enabled)
        if not self.autonomy:
            self._cancel_countdown()
        else:
            if self.current_incident_id:
                rec = self.incident_records.get(self.current_incident_id)
                if rec and not rec.get("decided") and rec.get("options"):
                    rec_id = rec.get("recommended_id") or rec["options"][0]["option_id"]
                    opt = self._find_option(rec, rec_id)
                    if (
                        opt
                        and opt.get("validation", {}).get("passed")
                        and option_has_positive_improvement(opt)
                    ):
                        self._start_countdown(self.current_incident_id, opt["option_id"])
                    else:
                        self.emit_note(
                            "Modo autónomo en espera: ninguna maniobra operativa disponible reduce el déficit residencial actual, por lo que no se aplica ningún plan automáticamente."
                        )
        return self.autonomy

    async def decide(
        self,
        incident_id: str | None,
        option_id: str | None,
        decision: str,
        *,
        by: str = "operator",
    ) -> dict[str, Any]:
        """Apply or veto an option for an incident."""
        self._cancel_countdown()
        target_inc_id = incident_id or self.current_incident_id
        if not target_inc_id or target_inc_id not in self.incident_records:
            # If called before incident_id is known, pick the latest incident record
            if self.incident_records:
                target_inc_id = list(self.incident_records.keys())[-1]
            else:
                raise ValueError("No hay ningún incidente activo para decidir.")

        rec = self.incident_records[target_inc_id]
        # If options are still computing in background, wait briefly for them
        if not rec.get("options") and self._eval_tasks:
            await asyncio.wait(self._eval_tasks, timeout=6.0)

        chosen_opt = self._find_option(rec, option_id or rec.get("recommended_id"))
        chosen_opt_id = chosen_opt["option_id"] if chosen_opt else (option_id or "opt_unknown")

        if decision == "veto":
            rec["decided"] = True
            rec["decision"] = "veto"
            rec["decided_by"] = "operator"
            veto_ev = self._emit(
                {
                    "type": "plan.vetoed",
                    "incident_id": target_inc_id,
                    "option_id": chosen_opt_id,
                }
            )
            self.decision_log.append(
                {
                    "ts_utc": veto_ev["ts_utc"],
                    "hour": round(self.hour, 2),
                    "incident_id": target_inc_id,
                    "option_id": chosen_opt_id,
                    "decision": "veto",
                    "by": "operator",
                    "disruption": rec["disruption"],
                    "option": chosen_opt,
                }
            )
            return veto_ev

        if not chosen_opt:
            raise ValueError(f"Opción {option_id!r} no encontrada en el incidente {target_inc_id}.")

        if not chosen_opt.get("validation", {}).get("passed", False):
            err_ev = self._emit(
                {
                    "type": "error",
                    "code": "VALIDATION_FAILED",
                    "message_es": "El plan seleccionado no pasó la validación física independiente y no puede aplicarse.",
                }
            )
            return err_ev

        # Apply levers from current hour without hindsight, verify with independent validator
        rec["decided"] = True
        rec["decision"] = "apply"
        rec["decided_by"] = by
        self.applied_levers = list(chosen_opt.get("levers") or [])

        applied_sol = chosen_opt["solution"]
        self.solution = applied_sol
        base_unserved = sum(
            sum(float(x) for x in vals)
            for vals in rec["baseline_solution"].get("unserved_mw", {}).values()
        )
        self.grid_state = compute_grid_state(
            self.solution,
            self.active_events,
            has_applied_plan=True,
            baseline_unserved_mwh=base_unserved,
        )

        actor = "gemini_autonomous" if by == "gemini_autonomous" else "operator"
        applied_ev = self._emit(
            {
                "type": "plan.applied",
                "incident_id": target_inc_id,
                "option_id": chosen_opt_id,
                "by": actor,
            }
        )
        self._emit(
            {
                "type": "solution.updated",
                "reason": "plan_applied",
                "solution": self.solution,
                "grid_state": self.grid_state,
            }
        )

        self.decision_log.append(
            {
                "ts_utc": applied_ev["ts_utc"],
                "hour": round(self.hour, 2),
                "incident_id": target_inc_id,
                "option_id": chosen_opt_id,
                "decision": "apply",
                "by": actor,
                "disruption": rec["disruption"],
                "option": chosen_opt,
                "validation": chosen_opt["validation"],
                "metrics": chosen_opt["metrics"],
            }
        )
        return applied_ev

    async def reset(self, start_hour: float = 7.0) -> dict[str, Any]:
        """Reset session to clean normal baseline state."""
        self._cancel_countdown()
        for t in list(self._eval_tasks):
            t.cancel()
        self._eval_tasks.clear()

        self.running = False
        if self._clock_task and not self._clock_task.done():
            self._clock_task.cancel()
            self._clock_task = None

        self.hour = float(max(0.0, min(23.99, start_hour)))
        self.active_events = []
        self.applied_levers = []
        self.current_incident_id = None
        self.previous_option_ids.clear()
        self.incident_records.clear()
        self.decision_log.clear()
        self.jury_cooldowns.clear()
        self._impact_preview_cache.clear()
        self.solution = copy.deepcopy(self.baseline_solution)
        self.grid_state = "normal"

        self._emit(
            {
                "type": "solution.updated",
                "reason": "reset",
                "solution": self.solution,
                "grid_state": self.grid_state,
            }
        )
        return self.build_snapshot_event(emit_to_history=True)

    def get_impact_preview(self) -> dict[str, Any]:
        """Compute hypothetical sudden outage impact for each disruptable asset (generators, batteries, lines)
        from `floor(self.hour)` for the default jury duration (4h), including currently active events.
        Cached by `(session_id, hour_int, active_events_signature)`.
        """
        hour_int = max(0, min(23, int(math.floor(self.hour))))
        fh = max(0, min(22, hour_int))
        th = max(fh + 2, min(24, fh + 4))
        active_sig = tuple(
            sorted(
                (
                    str(ev.get("asset_id", "")),
                    str(ev.get("type", "")),
                    int(ev.get("from_hour", 0)),
                    int(ev.get("to_hour", 0)),
                )
                for ev in self.active_events
            )
        )
        cache_key = (self.session_id, hour_int, active_sig)
        cached = self._impact_preview_cache.get(cache_key)
        if cached is not None:
            return copy.deepcopy(cached)

        target_assets: list[tuple[str, str]] = []
        for g in self.catalog.get("generators", []):
            if g.get("disruptable", True):
                target_assets.append(("generator_outage", str(g["id"])))
        for b in self.catalog.get("batteries", []):
            target_assets.append(("battery_outage", str(b["id"])))
        for ln in self.catalog.get("lines", []):
            if ln.get("disruptable", True):
                target_assets.append(("line_outage", str(ln["id"])))

        T = len(self.scenario.get("timestamps_utc", [])) or 24
        nodes = [n["id"] for n in self.scenario.get("nodes", [])]
        hh_per_mw = {
            n["id"]: float(n.get("households_per_mw", 1000.0))
            for n in self.scenario.get("nodes", [])
        }

        def _eval_asset(item: tuple[str, str]) -> dict[str, Any]:
            dtype, asset_id = item
            disruption = {
                "event_id": f"preview_{asset_id}_{fh}",
                "type": dtype,
                "asset_id": asset_id,
                "from_hour": fh,
                "to_hour": th,
                "source": "jury",
            }
            events_for_preview = [
                e for e in self.active_events if e.get("asset_id") != asset_id
            ] + [disruption]
            scen_for_solve, solver_events = prepare_scenario_and_events(
                self.scenario, events_for_preview
            )
            raw_sol = solve(
                scen_for_solve,
                candidate=None,
                events=solver_events,
                options={"allow_unserved": True},
            )
            ts = raw_sol.get("timeseries") or {}
            raw_unserved = ts.get("unserved_mw") or {}
            unserved_mw = {
                nid: [round(float(x), 4) for x in raw_unserved.get(nid, [0.0] * T)]
                for nid in nodes
            }
            households_off = {
                nid: [round(unserved_mw[nid][h] * hh_per_mw[nid]) for h in range(T)]
                for nid in nodes
            }
            unserved_by_h = [
                sum(float(unserved_mw[n][h]) for n in nodes) for h in range(T)
            ]
            hh_by_h = [
                sum(float(households_off[n][h]) for n in nodes) for h in range(T)
            ]
            unserved_peak = round(max(unserved_by_h, default=0.0), 2)
            hh_peak = int(round(max(hh_by_h, default=0.0)))
            return {
                "asset_id": asset_id,
                "households_off_peak": hh_peak,
                "unserved_mw_peak": unserved_peak,
                "absorbed": hh_peak == 0,
            }

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            assets_list = list(pool.map(_eval_asset, target_assets))

        result = {
            "hour": hour_int,
            "assets": assets_list,
        }
        self._impact_preview_cache[cache_key] = copy.deepcopy(result)
        return result


class SessionManager:
    """In-memory registry of LiveSession instances."""

    def __init__(self) -> None:
        self._sessions: dict[str, LiveSession] = {}

    def create_session(
        self,
        session_id: str | None = None,
        *,
        speed_s_per_hour: float = 4.0,
        start_hour: float = 7.0,
        allow_live_gemini: bool = True,
    ) -> LiveSession:
        sid = (session_id or f"s_{uuid.uuid4().hex[:8]}").strip()
        session = LiveSession(
            session_id=sid,
            speed_s_per_hour=speed_s_per_hour,
            start_hour=start_hour,
            allow_live_gemini=allow_live_gemini,
        )
        self._sessions[sid] = session
        return session

    def get_or_create(self, session_id: str) -> LiveSession:
        sid = (session_id or "demo").strip()
        if sid not in self._sessions:
            self._sessions[sid] = LiveSession(session_id=sid)
        return self._sessions[sid]

    def get(self, session_id: str) -> LiveSession | None:
        return self._sessions.get(session_id)


SESSION_MANAGER = SessionManager()
