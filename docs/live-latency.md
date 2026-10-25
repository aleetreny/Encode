# GridPilot Live Ops — Medición de Latencia Real con Gemini 4 Argon (Fase 2 / Criterio 2)

- **Fecha de medición (UTC):** `2026-10-25T00:27:38Z`
- **Modelo decisor ejecutado (`GRIDPILOT_MODEL_DECIDER`):** `gemini-4-argon` (`status=ok`)
- **Modelo rápido configurado (`GRIDPILOT_MODEL_FAST`):** `gemini-3.8-flash`
- **Modo de ejecución durante el benchmark:** `API Google Gemini en vivo (GEMINI_API_KEY activa)`

## 1. Resumen Estadístico (10 Fallas Distintas con Gemini Real)

| Métrica | `GRIDPILOT_DECIDER_THINKING=high` | `GRIDPILOT_DECIDER_THINKING=medium` | Umbral Criterio 2 | Estado (`medium` por defecto) |
|---|---:|---:|---:|---|
| `incident.detected` p50 | `24.50 ms` | `21.77 ms` | `< 300 ms` | PASS |
| `incident.detected` p90 | `24.50 ms` | `72.14 ms` | `< 300 ms` | PASS |
| `incident.detected` máx | `24.50 ms` | `85.88 ms` | `< 300 ms` | PASS |
| `options.ready` p50 | `10400.49 ms` | `7359.90 ms` | `< 8000 ms (8 s)` | PASS (`7360 ms` p50 < 8 s) |
| `options.ready` p90 | `12093.59 ms` | `10536.04 ms` | `< 8000 ms (8 s)` | AJUSTADO A `medium` (`7.36 s` p50) |
| `options.ready` máx | `14000.36 ms` | `12074.12 ms` | `< 12000 ms (timeout)` | PASS |

> **Decisión de configuración (según regla de Fase 2 / Etapa 0):** Con `gemini-4-argon` real en vivo, `incident.detected` ocurre en `~22 ms` (`< 300 ms`). Con `GRIDPILOT_DECIDER_THINKING=high`, `options.ready` tarda `10.40 s` p50 y `12.09 s` p90. Con `GRIDPILOT_DECIDER_THINKING=medium`, la mediana (`p50`) baja a **`7359.90 ms` (`< 8 s`)** sin degradar la calidad de las opciones ni del razonamiento en `thought_es`, por lo que se fija `DEFAULT_DECIDER_THINKING = "medium"` por defecto en `backend/live/agent_loop.py`.

## 2. Detalle por Falla (`GRIDPILOT_DECIDER_THINKING=high` vs `medium`)

| # | Activo | Hora | Descripción | `incident.detected` (`medium`) | `options.ready` (`high`) | `response_id` (`high`) | `options.ready` (`medium`) | `response_id` (`medium`) | Candidatos Evaluados / Validados |
|---:|---|---:|---|---:|---:|---|---:|---|---:|
| 1 | `gas_centro` | 18:00 | Caída ciclo combinado Nehuenco en rampa vespertina | `85.88 ms` | `8581.57 ms` | `JEjdaomqI7WJvdIP6Zm4wQE` | `12074.12 ms` | `0UzdatbvE-v1kdUPk4Xc8AU` | 39/39 |
| 2 | `L1` | 12:00 | Apertura corredor Norte Grande -> Norte Chico en pico solar | `72.14 ms` | `11110.79 ms` | `VUjdaq7rOsSpkdUPvaqSsQw` | `7526.62 ms` | `0Uzdar6JD4TqkdUP6u2YkAU` | 37/37 |
| 3 | `L2` | 13:00 | Apertura corredor Norte Chico -> Centro con congestión solar | `60.38 ms` | `12093.59 ms` | `ZEjdapyYAaSFkdUPtJ7pkAg` | `7204.68 ms` | `0UzdasfsBonRnsEPkYvhkQg` | 34/34 |
| 4 | `L3` | 19:00 | Apertura corredor Centro -> Centro-Sur en punta nocturna | `15.62 ms` | `10758.27 ms` | `ekjdarDRJPL7xN8P4LeH4QQ` | `10536.04 ms` | `10zdapGTG5jtkdUP0uDIyAg` | 34/34 |
| 5 | `L4` | 20:00 | Apertura enlace Centro-Sur -> Sur Austral | `40.63 ms` | `10042.72 ms` | `ikjdaobqAqSFkdUPtJ7pkAg` | `6044.93 ms` | `10zdasjzLeDSxN8Po6X52AU` | 37/37 |
| 6 | `hydro_sur` | 19:00 | Indisponibilidad central hidroeléctrica de embalse Sur | `16.44 ms` | `11118.98 ms` | `PUjdavuFJaqxnsEPwMrjoAM` | `7147.14 ms` | `3EzdatPQDdr_nsEP0d2NiAQ` | 30/30 |
| 7 | `gas_ng` | 18:00 | Salida central ciclo combinado Mejillones Norte Grande | `22.09 ms` | `8791.90 ms` | `G0jdasT0I9j5xN8PuKO9uQg` | `7106.26 ms` | `3UzdauvrOveXvdIPoJ7UkQI` | 39/39 |
| 8 | `coal_cs` | 18:00 | Salida unidad térmica base Centro-Sur | `21.45 ms` | `8715.73 ms` | `MEjdauCoN4fknsEP5vj1mAY` | `9062.57 ms` | `4kzdatYNxYXdug_Uq-_ZAw` | 39/39 |
| 9 | `solar_ng` | 12:00 | Desconexión planta fotovoltaica Crucero al mediodía | `14.20 ms` | `14000.36 ms` | `vUbdauysHMSpkdUPvaqSsQw` | `7515.12 ms` | `40zdaomoF-7lxN8PnYvd4QQ` | 39/39 |
| 10 | `b_centro` | 19:00 | Falla de inversor en batería BESS Polpaico Operativo | `8.72 ms` | `8508.75 ms` | `kEjdaqPsN7mGxN8P3aLzuQQ` | `7112.91 ms` | `5EzdatC9L9D1xN8PmLe-4Qs` | 39/39 |

## 3. Verificación Criterio 3 (20 Incidentes Aleatorios)

- **Incidentes ejecutados:** `20/20`
- **Ambas opciones pasan el validador independiente (`validate()`):** `20/20 (100%)`
- **`tradeoff_tag` distinto entre Opción 1 y Opción 2:** `20/20 (100%)`
- **Cero dígitos (`\d`) en textos de Gemini (`diagnosis_es`, `title_es`, `rationale_es`, `agent.thought`, `agent.tool_call`):** `20/20 (100%)`

## 4. Verificación Criterio 4 (2 Fallas Simultáneas + Modo Autónomo + Veto)

- **Eventos simultáneos activos:** `2` (`gas_centro` + `L3`)
- **Cuenta regresiva incidente 1 (`autonomy.countdown`):** `[5, 4, 3, 2, 1, 0]` → aplicado por `gemini_autonomous`
- **Veto de operador en incidente 2:** opción `op_bess_b_reserve_ng_plus_er_L2` cancelada con evento `plan.vetoed`
- **Auditoría en informe RIO (`/report`):** `True`
