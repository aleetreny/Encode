"""Jimmy, the grid monitor (`agent.note` with `kind: "monitor"`).

Every simulated hour the live engine asks this module for one short digit-free Spanish note:

- the numbers (`metrics`) are computed here from the current solution, never by a model;
- `classify` turns them into `severity` (`info` | `watch` | `alert`) and a `watch` list;
- the fast Gemini model (`GRIDPILOT_MODEL_FAST`) only words the note, with a hard timeout;
- on no key / timeout / error the deterministic sentence is used and `model_execution` says so.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any, Iterable, NamedTuple

from backend.live import agent_loop
from backend.live.agent_loop import ASSET_NAMES_ES, sanitize_no_digits

MONITOR_TIMEOUT_S = 3.0
# One sentence per simulated hour must land inside the 3 s budget: gemini-3.8-flash measured 5-10 s,
# gemini-3.5-flash-lite about 1 s (25 Oct). The decider stays on GRIDPILOT_MODEL_DECIDER.
DEFAULT_MONITOR_MODEL = "gemini-3.5-flash-lite"


def get_monitor_model() -> str:
    return (os.getenv("GRIDPILOT_MODEL_MONITOR") or "").strip() or DEFAULT_MONITOR_MODEL
DETERMINISTIC_MODEL = "deterministic-monitor"

SEVERITY_RANK = {"info": 0, "watch": 1, "alert": 2}

# Contract thresholds (docs/real-day-contract.md section 2). Applied to the 1-decimal metrics shown in the UI.
# The LP caps flow at the limit, so a saturated corridor reads exactly 100 %: that is congestion to watch,
# not an alert. Only unserved load (or a non-optimal solve) is an alert.
LINE_SATURATED_PCT = 100.0
LINE_WATCH_PCT = 90.0
RESERVE_WATCH_PCT = 10.0
STORAGE_WATCH_PCT = 20.0
# Wording only (not a contract threshold): a net-load ramp counts as notable above this share of demand per hour.
NOTABLE_RAMP_PCT_OF_DEMAND = 3.0

WEATHER_DRIVEN = ("solar", "wind")
_MIN_MODEL_TEXT_CHARS = 20
_MAX_MODEL_TEXT_CHARS = 320
_EMPTY_MODEL_TEXT = "\x00"  # sanitize_no_digits fallback sentinel: lets us tell "model said nothing usable" apart

MONITOR_SYSTEM_PROMPT_ES = """Eres Jimmy, el agente que vigila en tiempo real la red eléctrica simulada del Sistema Eléctrico Nacional de Chile.
Cada hora simulada escribes UNA sola oración en español, de quince a treinta palabras, dirigida al operador de la sala de control.
Usa únicamente los datos entregados: qué corredor troncal está más exigido, si la carga neta sube o baja, si hay recorte renovable, cómo están las reservas y el almacenamiento, y las fallas activas si las hay. Si hay algo que vigilar, di qué es y por qué importa.
REGLA ABSOLUTA: no escribas ningún dígito ni número en cifras, ni siquiera en nombres como L1 o L2; usa palabras («alto», «la mitad», «dos corredores») y los nombres de corredor que recibes. Las cifras las muestra la interfaz.
No inventes datos, no calcules cifras y no propongas acciones sobre el mundo real: todo es una simulación.
Responde solo con la oración, enteramente en español (nada en inglés), sin comillas, listas ni encabezados, y no repitas la redacción de la nota anterior."""

_EVENT_LABELS_ES = {
    "generator_outage": "salida de una central",
    "line_outage": "corte de un corredor",
    "battery_outage": "falla de una batería",
}
_WATCH_LABELS_ES = {
    "unserved": "demanda sin abastecer",
    "reserve_margin": "margen de reserva",
    "storage_soc": "carga del almacenamiento",
    "solver_status": "estado de la solución del despacho",
}


class MonitorAssessment(NamedTuple):
    metrics: dict[str, Any]
    severity: str
    watch: list[str]


def _series(table: dict[str, Any] | None, key: str, hour: int, default: float = 0.0) -> float:
    values = (table or {}).get(key)
    if not values or hour >= len(values):
        return default
    return float(values[hour])


def _horizon(solution: dict[str, Any]) -> int:
    for key in ("demand_mw", "generation_mw", "available_mw"):
        table = solution.get(key) or {}
        for values in table.values():
            return len(values)
    return len(solution.get("cost_proxy_usd") or []) or 24


def _hour_index(solution: dict[str, Any], hour: float) -> int:
    return max(0, min(_horizon(solution) - 1, int(hour)))


def _renewable_ids(scenario: dict[str, Any]) -> set[str]:
    profiled = set((scenario.get("renewable_availability_mw_by_generator") or {}).keys())
    weather = {
        g["id"]
        for g in scenario.get("generators", [])
        if str(g.get("technology", "")).lower() in WEATHER_DRIVEN
    }
    return profiled | weather


def _operating_batteries(scenario: dict[str, Any], solution: dict[str, Any]) -> list[dict[str, Any]]:
    """Batteries that count as storage: not on standby, or activated by a plan (they move in the solution)."""
    flows = solution.get("battery_flow_mw") or {}
    soc = solution.get("battery_soc_mwh") or {}
    out: list[dict[str, Any]] = []
    for bat in scenario.get("batteries", []):
        bid = bat["id"]
        if bid not in soc:
            continue
        if bat.get("standby") and not any(abs(float(x)) > 1e-6 for x in flows.get(bid, [])):
            continue
        out.append(bat)
    return out


def line_loadings_pct(solution: dict[str, Any], hour: float) -> dict[str, float]:
    """|flow| / capacity in percent per line at this hour (lines with zero capacity, i.e. in outage, are skipped)."""
    h = _hour_index(solution, hour)
    loadings: dict[str, float] = {}
    for lid, flows in (solution.get("line_flow_mw") or {}).items():
        cap = _series(solution.get("line_capacity_mw"), lid, h)
        if cap > 0 and h < len(flows):
            loadings[lid] = round(abs(float(flows[h])) / cap * 100.0, 1)
    return loadings


def compute_monitor_metrics(
    scenario: dict[str, Any],
    solution: dict[str, Any],
    hour: float,
    *,
    outaged_battery_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Grid indicators at `int(hour)`, straight from the solution arrays. 1-decimal plain floats.

    `outaged_battery_ids` removes batteries on outage from the discharge capacity used for the reserve margin.
    """
    T = _horizon(solution)
    h = _hour_index(solution, hour)
    renewables = _renewable_ids(scenario)
    down = set(outaged_battery_ids)

    def system_demand(i: int) -> float:
        return sum(float(v[i]) for v in (solution.get("demand_mw") or {}).values() if i < len(v))

    def renewable_generation(i: int) -> float:
        gen = solution.get("generation_mw") or {}
        return sum(_series(gen, gid, i) for gid in renewables)

    demand = system_demand(h)
    available = sum(_series(solution.get("available_mw"), gid, h) for gid in (solution.get("available_mw") or {}))
    batteries = _operating_batteries(scenario, solution)
    discharge_cap = sum(float(b.get("power_capacity_mw", 0.0)) for b in batteries if b["id"] not in down)
    reserve = (available + discharge_cap - demand) / demand * 100.0 if demand > 0 else 0.0

    curtailment = sum(
        max(0.0, _series(solution.get("available_mw"), gid, h) - _series(solution.get("generation_mw"), gid, h))
        for gid in renewables
    )
    unserved = sum(float(v[h]) for v in (solution.get("unserved_mw") or {}).values() if h < len(v))
    households = sum(float(v[h]) for v in (solution.get("households_off") or {}).values() if h < len(v))

    if h + 1 < T:
        ramp = (system_demand(h + 1) - renewable_generation(h + 1)) - (demand - renewable_generation(h))
    else:
        ramp = 0.0  # last hour of the horizon: there is no next hour to compare with

    metrics: dict[str, Any] = {
        "demand_mw": round(demand, 1),
        "reserve_margin_pct": round(reserve, 1),
        "curtailment_mw": round(curtailment, 1),
        "unserved_mw": round(unserved, 1),
        "households_off": round(households, 1),
        "net_load_ramp_mw_per_h": round(ramp, 1),
    }

    loadings = line_loadings_pct(solution, hour)
    if loadings:
        max_id = max(loadings, key=lambda lid: loadings[lid])
        metrics["max_line_loading_pct"] = loadings[max_id]
        metrics["max_line_id"] = max_id
    else:
        metrics["max_line_loading_pct"] = 0.0

    energy_cap = sum(float(b.get("energy_capacity_mwh", 0.0)) for b in batteries)
    if energy_cap > 0:
        stored = sum(_series(solution.get("battery_soc_mwh"), b["id"], h) for b in batteries)
        metrics["storage_soc_pct"] = round(stored / energy_cap * 100.0, 1)
    return metrics


def classify(
    metrics: dict[str, Any],
    line_loading_pct: dict[str, float] | None = None,
) -> tuple[str, list[str]]:
    """(severity, watch ids) from the contract thresholds.

    alert: unserved energy > 0. watch: a line >= 90 % (saturated included), reserve margin < 10 %
    or storage < 20 %. Watch ids are `unserved`, line ids (all lines >= 90 % when `line_loading_pct` is given,
    otherwise only the most loaded one), `reserve_margin` and `storage_soc`.
    """
    unserved = float(metrics.get("unserved_mw", 0.0)) > 0 or float(metrics.get("households_off", 0.0)) > 0
    max_loading = float(metrics.get("max_line_loading_pct", 0.0))
    reserve = metrics.get("reserve_margin_pct")
    storage = metrics.get("storage_soc_pct")

    if line_loading_pct is not None:
        hot_lines = {lid: pct for lid, pct in line_loading_pct.items() if pct >= LINE_WATCH_PCT}
    elif metrics.get("max_line_id") and max_loading >= LINE_WATCH_PCT:
        hot_lines = {str(metrics["max_line_id"]): max_loading}
    else:
        hot_lines = {}

    watch: list[str] = []
    if unserved:
        watch.append("unserved")
    watch.extend(sorted(hot_lines, key=lambda lid: (-hot_lines[lid], lid)))
    if reserve is not None and float(reserve) < RESERVE_WATCH_PCT:
        watch.append("reserve_margin")
    if storage is not None and float(storage) < STORAGE_WATCH_PCT:
        watch.append("storage_soc")

    if unserved:
        return "alert", watch
    if watch:
        return "watch", watch
    return "info", watch


def assess(
    scenario: dict[str, Any],
    solution: dict[str, Any],
    hour: float,
    *,
    outaged_battery_ids: Iterable[str] = (),
) -> MonitorAssessment:
    """Metrics + severity + watch ids. A solution that is not `optimal` is an alert, never a quiet `info`."""
    metrics = compute_monitor_metrics(scenario, solution, hour, outaged_battery_ids=outaged_battery_ids)
    severity, watch = classify(metrics, line_loadings_pct(solution, hour))
    if solution.get("status", "optimal") != "optimal":
        severity = "alert"
        watch = ["solver_status", *watch]
    return MonitorAssessment(metrics, severity, watch)


def _curtailment_scale_es(curtailment: float, demand: float) -> str:
    if demand <= 0:
        return "una parte"
    share = curtailment / demand
    if share < 0.05:
        return "una parte pequeña"
    if share < 0.15:
        return "una parte considerable"
    return "una parte muy grande"


def _corridor_es(line_id: Any) -> str:
    name = ASSET_NAMES_ES.get(str(line_id)) if line_id else None
    return name or "corredor troncal más cargado"


def deterministic_text_es(
    metrics: dict[str, Any],
    severity: str,
    watch: list[str],
    grid_state: str = "normal",
) -> str:
    """One digit-free Spanish sentence built from the metrics (corridor, ramp, reserve, storage, curtailment)."""
    corridor = _corridor_es(metrics.get("max_line_id"))
    loading = float(metrics.get("max_line_loading_pct", 0.0))
    demand = float(metrics.get("demand_mw", 0.0))
    ramp = float(metrics.get("net_load_ramp_mw_per_h", 0.0))
    curtailment = float(metrics.get("curtailment_mw", 0.0))
    ramp_notable = demand > 0 and abs(ramp) >= demand * NOTABLE_RAMP_PCT_OF_DEMAND / 100.0

    clauses: list[str] = []
    if "solver_status" in watch:
        clauses.append("la solución del despacho no es óptima y sus resultados no son confiables hasta resolverla de nuevo")
    if float(metrics.get("unserved_mw", 0.0)) > 0 or float(metrics.get("households_off", 0.0)) > 0:
        clauses.append("hay hogares sin suministro y la prioridad es reconectarlos con las maniobras disponibles")
    if loading >= LINE_SATURATED_PCT:
        scale = _curtailment_scale_es(curtailment, demand)
        tail = f", por eso se recorta en origen {scale} del excedente renovable" if curtailment > 0 else ""
        clauses.append(f"el {corridor} opera en su límite de transferencia{tail}")
    elif loading >= LINE_WATCH_PCT:
        clauses.append(f"el {corridor} se acerca a su límite de transferencia")
    if "reserve_margin" in watch:
        clauses.append("el margen de reserva es estrecho, con oferta disponible apenas por encima de la demanda")
    if "storage_soc" in watch:
        clauses.append("el almacenamiento operativo queda casi descargado y limita el respaldo inmediato")
    if ramp_notable and ramp > 0:
        clauses.append("la carga neta sube con fuerza y la generación firme debe acompañar la rampa")
    if curtailment > 0 and loading < LINE_SATURATED_PCT:
        scale = _curtailment_scale_es(curtailment, demand)
        clauses.append(f"se recorta {scale} de la generación renovable por falta de capacidad para evacuarla")
    if ramp_notable and ramp < 0:
        clauses.append("la carga neta cae y libera holgura en los corredores")
    if not clauses:
        clauses.append(
            f"el sistema está en equilibrio, con el {corridor} como tramo más exigido y holgura en reservas"
            if metrics.get("max_line_id")
            else "el sistema está en equilibrio, con holgura en reservas"
        )
    elif len(clauses) == 1 and metrics.get("max_line_id") and loading < LINE_WATCH_PCT:
        clauses.append(f"el {corridor} sigue siendo el tramo más cargado, aún con holgura")

    lead = clauses[0]
    text = lead[0].upper() + lead[1:]
    if len(clauses) > 1:
        text += "; además, " + clauses[1]
    if grid_state == "recuperacion":
        text += ", bajo un plan de mitigación en curso"
    return sanitize_no_digits(text + ".")


def _daypart_es(hour_index: int) -> str:
    if hour_index < 6:
        return "madrugada"
    if hour_index < 12:
        return "mañana"
    if hour_index < 15:
        return "mediodía"
    if hour_index < 18:
        return "tarde"
    if hour_index < 23:
        return "punta vespertina"
    return "noche"


def build_monitor_prompt(
    assessment: MonitorAssessment,
    *,
    hour: float,
    grid_state: str,
    active_events: list[dict[str, Any]],
    previous_text: str | None,
) -> str:
    """User message for the fast model: code-computed facts only, with named assets instead of ids."""
    metrics = assessment.metrics
    named_metrics = {k: v for k, v in metrics.items() if k != "max_line_id"}
    lines = [
        f"Franja horaria simulada: {_daypart_es(int(hour) % 24)} (hora local de Chile).",
        f"Estado de la red: {grid_state}. Severidad calculada por código: {assessment.severity}.",
        f"Corredor más cargado: {_corridor_es(metrics.get('max_line_id'))}.",
        "Métricas del solver (no las escribas en cifras): "
        + ", ".join(f"{k}={v}" for k, v in named_metrics.items()),
    ]
    watched = [
        ASSET_NAMES_ES.get(w) or _WATCH_LABELS_ES.get(w, w) for w in assessment.watch
    ]
    lines.append("A vigilar: " + ("; ".join(watched) if watched else "nada fuera de lo normal") + ".")
    if active_events:
        faults = "; ".join(
            f"{_EVENT_LABELS_ES.get(str(ev.get('type')), 'falla')}: "
            f"{ASSET_NAMES_ES.get(str(ev.get('asset_id')), 'un activo de la red')}"
            for ev in active_events
        )
        lines.append("Fallas activas: " + faults + ".")
    else:
        lines.append("Fallas activas: ninguna.")
    if previous_text:
        lines.append("Nota anterior (no repitas su redacción): " + previous_text)
    lines.append("Escribe ahora la nota de esta hora.")
    return "\n".join(lines)


def _extract_text(resp: dict[str, Any]) -> tuple[str, str | None]:
    candidates = resp.get("candidates") or []
    parts = ((candidates[0].get("content") or {}).get("parts") or []) if candidates else []
    text = " ".join(
        str(p["text"]) for p in parts if isinstance(p, dict) and p.get("text") and not p.get("thought")
    )
    rid = resp.get("responseId") or resp.get("id")
    return text, (str(rid) if rid else None)


def _tidy_model_text(raw: str) -> str:
    text = re.sub(r"\s+", " ", raw).strip().strip("\"'«»`*#- ")
    if len(text) > _MAX_MODEL_TEXT_CHARS:
        cut = text[:_MAX_MODEL_TEXT_CHARS]
        end = max(cut.rfind(". "), cut.rfind("; "))
        text = cut[: end + 1] if end > _MIN_MODEL_TEXT_CHARS else cut.rsplit(" ", 1)[0].rstrip(",;:") + "."
    return text


def _note_payload(
    assessment: MonitorAssessment,
    text_es: str,
    model_execution: dict[str, Any],
) -> dict[str, Any]:
    return {
        "type": "agent.note",
        "text_es": text_es,
        "kind": "monitor",
        "severity": assessment.severity,
        "metrics": dict(assessment.metrics),
        "watch": list(assessment.watch),
        "model_execution": model_execution,
    }


def deterministic_note(
    assessment: MonitorAssessment,
    *,
    grid_state: str,
    status: str,
    latency_ms: int = 0,
) -> dict[str, Any]:
    """Monitor note worded by code, labelled with why the model was not used (`status`)."""
    return _note_payload(
        assessment,
        deterministic_text_es(assessment.metrics, assessment.severity, assessment.watch, grid_state),
        {
            "model": DETERMINISTIC_MODEL,
            "role": "monitor",
            "status": status,
            "latency_ms": latency_ms,
            "cached": False,
        },
    )


async def generate_monitor_note(
    assessment: MonitorAssessment,
    *,
    hour: float,
    grid_state: str,
    active_events: list[dict[str, Any]] | None = None,
    previous_text: str | None = None,
    api_key: str | None = None,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    """Full `agent.note` payload. Never raises: any model problem falls back to the deterministic sentence.

    The blocking HTTP call runs in a worker thread and is abandoned after `timeout_s` (default 3 s).
    """
    key = agent_loop.get_api_key() if api_key is None else api_key
    if not key:
        return deterministic_note(assessment, grid_state=grid_state, status="no_key")

    timeout = MONITOR_TIMEOUT_S if timeout_s is None else timeout_s
    model = get_monitor_model()
    started = time.perf_counter()

    def elapsed_ms() -> int:
        return int(round((time.perf_counter() - started) * 1000))

    try:
        prompt = build_monitor_prompt(
            assessment,
            hour=hour,
            grid_state=grid_state,
            active_events=active_events or [],
            previous_text=previous_text,
        )
        resp = await asyncio.wait_for(
            asyncio.to_thread(
                agent_loop._call_gemini_generate_content,
                model=model,
                api_key=key,
                contents=[{"role": "user", "parts": [{"text": prompt}]}],
                system_instruction=MONITOR_SYSTEM_PROMPT_ES,
                timeout_s=timeout,
            ),
            timeout=timeout,
        )
    except (asyncio.TimeoutError, TimeoutError):
        return deterministic_note(assessment, grid_state=grid_state, status="timeout", latency_ms=elapsed_ms())
    except asyncio.CancelledError:
        raise
    except Exception:
        return deterministic_note(assessment, grid_state=grid_state, status="error", latency_ms=elapsed_ms())

    try:
        raw_text, response_id = _extract_text(resp)
        text = sanitize_no_digits(_tidy_model_text(raw_text), fallback=_EMPTY_MODEL_TEXT)
    except Exception:
        return deterministic_note(assessment, grid_state=grid_state, status="error", latency_ms=elapsed_ms())
    if text == _EMPTY_MODEL_TEXT or len(text) < _MIN_MODEL_TEXT_CHARS:
        return deterministic_note(assessment, grid_state=grid_state, status="error", latency_ms=elapsed_ms())

    execution: dict[str, Any] = {
        "model": model,
        "role": "monitor",
        "status": "ok",
        "latency_ms": elapsed_ms(),
        "cached": False,
    }
    if response_id:
        execution["response_id"] = response_id
    return _note_payload(assessment, text, execution)
