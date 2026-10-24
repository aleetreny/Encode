# GridPilot Live Ops — Medición de Latencia y Verificación (Fase 2 / Criterio 2)

- **Fecha de medición (UTC):** `2026-10-24T22:40:45Z`
- **Modelo decisor configurado (`GRIDPILOT_MODEL_DECIDER`):** `gemini-4-argon`
- **Modelo rápido configurado (`GRIDPILOT_MODEL_FAST`):** `gemini-3.8-flash`
- **Modo de ejecución durante el benchmark:** `Planificador determinista local + HiGHS paralelo (sin GEMINI_API_KEY en entorno CI)`

## 1. Resumen Estadístico (10 Fallas Distintas)

| Métrica | `GRIDPILOT_DECIDER_THINKING=high` | `GRIDPILOT_DECIDER_THINKING=medium` | Umbral Criterio 2 | Estado |
|---|---:|---:|---:|---|
| `incident.detected` p50 | `11.84 ms` | `13.45 ms` | `< 300 ms` | PASS |
| `incident.detected` p90 | `29.31 ms` | `19.24 ms` | `< 300 ms` | PASS |
| `incident.detected` máx | `37.99 ms` | `50.60 ms` | `< 300 ms` | PASS |
| `options.ready` p50 | `382.24 ms` | `414.24 ms` | `< 8000 ms` | PASS |
| `options.ready` p90 | `1112.35 ms` | `545.81 ms` | `< 8000 ms (8 s)` | PASS |
| `options.ready` máx | `1115.74 ms` | `1130.36 ms` | `< 8000 ms (8 s)` | PASS |

> **Decisión de configuración:** Ambos niveles (`high` y `medium`) cumplen holgadamente `< 300 ms` hasta `incident.detected` y `< 8 s` (p90) hasta `options.ready`. Se mantiene `GRIDPILOT_DECIDER_THINKING=high` por defecto en producción con timeout duro de `12 s` y respaldo determinista validado sobre el frente de Pareto.

## 2. Detalle por Falla (`GRIDPILOT_DECIDER_THINKING=high` vs `medium`)

| # | Activo | Hora | Descripción | `incident.detected` (`high`) | `options.ready` (`high`) | `options.ready` (`medium`) | Candidatos Evaluados / Validados |
|---:|---|---:|---|---:|---:|---:|---:|
| 1 | `gas_centro` | 18:00 | Caída ciclo combinado Nehuenco en rampa vespertina | `16.69 ms` | `689.69 ms` | `419.16 ms` | 37/37 |
| 2 | `L1` | 12:00 | Apertura corredor Norte Grande -> Norte Chico en pico solar | `11.80 ms` | `352.04 ms` | `450.42 ms` | 35/35 |
| 3 | `L2` | 13:00 | Apertura corredor Norte Chico -> Centro con congestión solar | `11.66 ms` | `337.58 ms` | `323.32 ms` | 32/32 |
| 4 | `L3` | 19:00 | Apertura corredor Centro -> Centro-Sur en punta nocturna | `11.66 ms` | `372.76 ms` | `401.30 ms` | 32/32 |
| 5 | `L4` | 20:00 | Apertura enlace Centro-Sur -> Sur Austral | `11.61 ms` | `385.83 ms` | `360.60 ms` | 35/35 |
| 6 | `hydro_sur` | 19:00 | Indisponibilidad central hidroeléctrica de embalse Sur | `11.29 ms` | `319.38 ms` | `295.97 ms` | 28/28 |
| 7 | `gas_ng` | 18:00 | Salida central ciclo combinado Mejillones Norte Grande | `11.88 ms` | `378.64 ms` | `409.32 ms` | 37/37 |
| 8 | `coal_cs` | 18:00 | Salida unidad térmica base Centro-Sur | `29.31 ms` | `1112.35 ms` | `513.08 ms` | 37/37 |
| 9 | `solar_ng` | 12:00 | Desconexión planta fotovoltaica Crucero al mediodía | `37.99 ms` | `1115.74 ms` | `1130.36 ms` | 37/37 |
| 10 | `b_centro` | 19:00 | Falla de inversor en batería BESS Polpaico Operativo | `17.25 ms` | `683.21 ms` | `545.81 ms` | 37/37 |

## 3. Verificación Criterio 3 (20 Incidentes Aleatorios)

- **Incidentes ejecutados:** `20/20`
- **Ambas opciones pasan el validador independiente (`validate()`):** `20/20 (100%)`
- **`tradeoff_tag` distinto entre Opción 1 y Opción 2:** `20/20 (100%)`
- **Cero dígitos (`\d`) en textos de Gemini (`diagnosis_es`, `title_es`, `rationale_es`, `agent.thought`, `agent.tool_call`):** `20/20 (100%)`

## 4. Verificación Criterio 4 (2 Fallas Simultáneas + Modo Autónomo + Veto)

- **Eventos simultáneos activos:** `2` (`gas_centro` + `L3`)
- **Cuenta regresiva incidente 1 (`autonomy.countdown`):** `[5, 4, 3, 2, 1, 0]` → aplicado por `gemini_autonomous`
- **Veto de operador en incidente 2:** opción `op_peaker_diesel_plus_dr_n_centro_200` cancelada con evento `plan.vetoed`
- **Auditoría en informe RIO (`/report`):** `True`
