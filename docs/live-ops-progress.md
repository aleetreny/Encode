# GridPilot Live Ops — Progress Log

## Ola A · Fase 0: Rama, Merge, Contrato y `demo-stream.jsonl` inicial (`7c656c0`)
- **Modelo**: Gemini 4 Argon · High (Orquestador)
- **Qué entró**:
  - Creación de `feature/live-ops` desde `origin/feature/data-backend` con merge limpio de `origin/feature/agent` (`76ada5c`) y `origin/feature/frontend` (`71dad5c`).
  - Actualización de `CLAUDE.md` con el nuevo reparto de responsabilidades y autoría de commits (`alonsoquezadar`).
  - Contrato en vivo congelado en `contracts/live.schema.json` y `frontend/src/live/types.ts` + `docs/live-contract-changelog.md`.
  - Grabación inicial de `frontend/src/live/fixtures/demo-stream.jsonl` (29 eventos reales calculados y validados con HiGHS desde `scripts/record_demo_stream.py`: snapshot inicial, nota periódica, falla de `gas_centro` a las 18 h, pensamiento y llamadas a herramientas de Gemini sin dígitos, 2 opciones con trade-off distinto, aplicación por operador, segunda falla en `L3` por jurado en modo autónomo con cuenta regresiva 5→0 y retorno a estado `normal`).
- **Cómo probarlo**:
  - `pytest -q && pytest optimisation/tests -q`
  - `PYTHONPATH=. python3 scripts/record_demo_stream.py`
  - `cd frontend && npm run build`

## Ola B · Subagentes Paralelos W1–W6
- **W1 — Palancas operacionales LP y métricas de CO₂** (`live-ops/w1`, commit `404e4a8`):
  - **Modelo**: `pro` (Gemini 4 Argon / Pro)
  - **Qué entró**: Implementación de las 5 palancas operacionales (`emergency_rating`, `demand_response`, `activate_reserve_bess`, `hydro_reserve_release`, `start_peaker`) y métricas de emisiones (`co2_t` y `co2_t_by_hour`) en `optimisation/scenario.py`, `optimisation/model.py` y `optimisation/stress.py`, con tests en `optimisation/tests/test_optimisation.py`.
- **W2 — Validador independiente de palancas operacionales y CO₂** (`live-ops/w2`, commit `1caf700`, merge `6b05a5c`):
  - **Modelo**: `pro` (Gemini 4 Argon / Pro, subagente independiente sin leer `optimisation/model.py`)
  - **Qué entró**: Validación matemática independiente en `optimisation/validate.py` para las 5 palancas operacionales (`demand_response_bounds`, ventanas activas de baterías `active_from_hour`..`active_to_hour`, balance nodal con respuesta de demanda, costos horarios variables para `hydro_reserve_release`, recálculo de `co2_t` y `co2_t_by_hour`) y tamper tests en `optimisation/tests/test_optimisation.py`.
- **W3 — Datos de escenario (coordenadas, hogares, emisiones, BESS de reserva) + Catálogo** (`live-ops/w3`, commit `a61beed`):
  - **Modelo**: `inherit`
  - **Qué entró**: Coordenadas reales de subestaciones SEN (Crucero, Cardones, Polpaico, Charrúa, Puerto Montt), `households_per_mw: 1000` (`assumption`), `emission_factors_t_per_mwh`, baterías de reserva `b_reserve_ng` (150 MW / 600 MWh) y `b_reserve_centro` (80 MW / 240 MWh) con `standby: true` en `optimisation/fixtures/build_demo_scenario.py` y `optimisation/fixtures/demo_scenario.json`, además de `backend/live/catalog.py` (`build_catalog()`).
- **W4 — Capa de datos en vivo del frontend (`client.ts`, `store.ts`, `offline.ts`)** (`live-ops/w4`, commit `706512f`, merge `dd960a9`):
  - **Modelo**: `inherit`
  - **Qué entró**: Cliente SSE/REST con reconexión exponencial (`frontend/src/live/client.ts`), store React y reductor de eventos (`frontend/src/live/store.ts`), reproductor determinista de `demo-stream.jsonl` (`frontend/src/live/offline.ts`) y eliminación del `postOperatorDecision('approved')` automático al elegir un preset en `frontend/src/components/ChileIsoMaquette.tsx`.
- **W5 — Página móvil `/jurado`, Consola `/dev` y ruteo en `App.tsx`** (`live-ops/w5`, commit `44f70eb`):
  - **Modelo**: `inherit`
  - **Qué entró**: Página móvil `/jurado` (`frontend/src/live/JuryPage.tsx`) con persistencia de nombre, `device_fingerprint`, 5 tarjetas de acción, banner de enfriamiento de 30 s y estado en vivo; consola `/dev` (`frontend/src/live/DevConsole.tsx`) con selector de modo, reloj, autonomía, inyector de fallas, inspector de pensamiento/herramientas y tabla Pareto; ruteo por `pathname` en `frontend/src/App.tsx`.
- **W6 — `make demo`, `scripts/demo.sh`, `Dockerfile`, `render.yaml` y `/api/health`** (`live-ops/w6`, commit `51bd1f2`, merge `2ca565a`):
  - **Modelo**: `inherit`
  - **Qué entró**: `Makefile`, `scripts/demo.sh` (`--check-only`), `Dockerfile` multi-etapa (Node 20 + Python 3.11), `render.yaml` y enriquecimiento de `/api/health` en `backend/main.py` con `mode`, `solver_ok`, `gemini_model_agent`, `gemini_model_fast` y sonda opcional `probe_gemini=true`.
- **Cómo probar la Ola B completa**:
  - `/opt/anaconda3/bin/python3 -m pytest -q` (215 passed)
  - `cd frontend && npm run build`
  - `./scripts/demo.sh --check-only`

## Ola C · Motor en Vivo, Bucle de Gemini 4 Argon, Transporte SSE/Comandos (W7) e Informe RIO (W8)
- **Fase 2 — Motor en vivo y bucle de Gemini 4 Argon** (`f4619d8`):
  - **Modelo**: Gemini 4 Argon · High (Orquestador)
  - **Qué entró**:
    - `backend/live/agent_loop.py`: Guardarraíl estricto sin dígitos (`sanitize_no_digits`, `has_digits`), generación de hasta 40 candidatos de palancas operacionales individuales y pares, evaluación y validación paralela con HiGHS (`ThreadPoolExecutor`), cálculo de frente de Pareto 4D, selección garantizada de 2 opciones con `tradeoff_tag` distinto, bucle de function-calling de Gemini 4 Argon (`inspect_node`, `simulate_plan` ≤ 3 llamadas extra, `propose_options`) con timeout de 12 s, y moderación de nombres del jurado (`moderate_jury_name`).
    - `backend/live/engine.py`: `LiveSession` y `SessionManager` en memoria con detección de falla en `< 300 ms` (`incident.detected` + `solution.updated`), reloj simulado a 1 Hz con expiración automática de eventos (`event.ended`), cuenta regresiva autónoma 5→0 (`autonomy.countdown`) cancelable mediante `veto`, y notas periódicas cada 3 h simuladas (`agent.note`).
    - Eliminación de `solver_fallback` de `agent/tools.py` en la ruta nativa.
- **W7 — Transporte SSE, endpoints REST, límites del jurado y QR SVG** (`live-ops/w7`, commit `f8dc383` + `19ef130`):
  - **Modelo**: `pro` (Gemini 4 Argon / Pro)
  - **Qué entró**: `backend/live/router.py` (`/api/live/catalog`, `/api/live/sessions`, `/stream`, `/clock`, `/disrupt`, `/jury/disrupt` con enfriamiento de 30 s por dispositivo y máx. 2 eventos activos, `/decide`, `/autonomy`, `/reset`, `/qr.svg`, `/report`), generador QR SVG ISO/IEC 18004 escaneable en Python puro (`backend/live/qr.py`), montaje en `backend/main.py` y tests en `tests/test_live_api.py`.
- **W8 — Generador de Informe Regulatorio RIO (`md` y `html`)** (`live-ops/w8`, commit `32c0052`):
  - **Modelo**: `flash` (Gemini 3.8 Flash)
  - **Qué entró**: `backend/live/report.py` (`render_session_report(session, fmt='md'|'html')`) con línea de tiempo de incidentes, tabla de decisiones con autoría (`operator` vs `gemini_autonomous` y `veto`), métricas verificadas, resultados del validador independiente, procedencia/supuestos (`households_per_mw = 1000`) y citas legales de `agent/regulatory.py`, más tests en `tests/test_live_report.py`.
- **Cómo probar la Ola C completa**:
  - `pytest tests/test_live_api.py tests/test_live_report.py -q`
  - `pytest -q` (224 passed)

## Ola D · Biblioteca de Incidentes Sin Red (W9), Unificación de Fórmula de Hogares (W10) y Verificación de Aceptación
- **W9 — Biblioteca de incidentes pre-calculados (`frontend/public/incidents/`) y modo sin red (`offline.ts`)** (`live-ops/w9`, commit `a907efc`):
  - **Modelo**: `flash` (Gemini 3.8 Flash)
  - **Qué entró**: `scripts/build_incident_library.py` que genera 111 secuencias `.jsonl` en `frontend/public/incidents/` (activos × horas `{9, 12, 13, 18, 19, 20}` × duración 4 h, más combinaciones dobles `combo_gas_centro_L3_18` y `combo_L1_gas_ng_12`) e `index.json`, marcando `model_execution.cached = True` con `cached_at_utc` y `response_id`, integración de carga y reproducción por activo/hora en `frontend/src/live/offline.ts`, y suite `tests/test_incident_library.py`.
- **W10 — Auditoría y unificación de la fórmula única de hogares** (`live-ops/w10`, commit `90cc439`):
  - **Modelo**: `flash` (Gemini 3.8 Flash)
  - **Qué entró**: Eliminación del número fijo `243,058` en `frontend/src/components/ChileIsoMaquette.tsx` reemplazándolo por `Math.round(unservedMw) * 1000`, aclaración de la fórmula `unserved_mw * households_per_mw` (`1000`, `assumption`) en `agent/DESIGN.md`, auditoría histórica completa (`120,000`, `243,058`, `562,000`, `480,000`) en `docs/household-formula-audit.md`, y suite `tests/test_household_consistency.py`.
- **Verificación de Aceptación y `demo-stream.jsonl` final**:
  - **Modelo**: Gemini 4 Argon · High (Orquestador)
  - **Qué entró**: Actualización de `scripts/record_demo_stream.py` y `frontend/src/live/fixtures/demo-stream.jsonl` con palancas operacionales de Fase 1 (`activate_reserve_bess`, `emergency_rating`, `hydro_reserve_release`, `demand_response`, `start_peaker`), script `scripts/verify_live_acceptance.py` y reporte de latencia/aceptación en `docs/live-latency.md` (`incident.detected` p90 `29.31 ms < 300 ms`, `options.ready` p90 `1112.35 ms < 8 s`, `20/20` incidentes aleatorios validados sin dígitos y con `tradeoff_tag` distinto, y `2` fallas simultáneas + autonomía + veto verificados).
- **Cómo probar la Ola D y los 9 criterios de aceptación**:
  - `python3 scripts/verify_live_acceptance.py`
  - `pytest -q && pytest optimisation/tests -q && python3 -m optimisation.stress`
  - `cd frontend && npm run build && ./scripts/demo.sh --check-only`
