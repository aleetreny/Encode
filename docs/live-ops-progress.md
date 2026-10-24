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
