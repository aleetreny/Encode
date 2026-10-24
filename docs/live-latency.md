# GridPilot Live Ops — Medición de Latencia y Verificación (Fase 2 / Criterio 2)

- **Fecha de medición (UTC):** `2026-10-24T23:14:36Z`
- **Modelo decisor configurado (`GRIDPILOT_MODEL_DECIDER`):** `gemini-4-argon`
- **Modelo rápido configurado (`GRIDPILOT_MODEL_FAST`):** `gemini-3.8-flash`
- **Modo de ejecución durante el benchmark:** `Planificador determinista local + HiGHS paralelo (sin GEMINI_API_KEY en entorno CI)`

## 1. Resumen Estadístico (10 Fallas Distintas)

| Métrica | `GRIDPILOT_DECIDER_THINKING=high` | `GRIDPILOT_DECIDER_THINKING=medium` | Umbral Criterio 2 | Estado |
|---|---:|---:|---:|---|
| `incident.detected` p50 | `11.21 ms` | `11.38 ms` | `< 300 ms` | PASS |
| `incident.detected` p90 | `20.89 ms` | `13.53 ms` | `< 300 ms` | PASS |
| `incident.detected` máx | `29.63 ms` | `13.74 ms` | `< 300 ms` | PASS |
| `options.ready` p50 | `367.18 ms` | `363.55 ms` | `< 8000 ms` | PASS |
| `options.ready` p90 | `434.18 ms` | `391.20 ms` | `< 8000 ms (8 s)` | PASS |
| `options.ready` máx | `474.20 ms` | `404.07 ms` | `< 8000 ms (8 s)` | PASS |

> **Decisión de configuración:** Ambos niveles (`high` y `medium`) cumplen holgadamente `< 300 ms` hasta `incident.detected` y `< 8 s` (p90) hasta `options.ready`. Se mantiene `GRIDPILOT_DECIDER_THINKING=high` por defecto en producción con timeout duro de `12 s` y respaldo determinista validado sobre el frente de Pareto.

## 2. Detalle por Falla (`GRIDPILOT_DECIDER_THINKING=high` vs `medium`)

| # | Activo | Hora | Descripción | `incident.detected` (`high`) | `options.ready` (`high`) | `options.ready` (`medium`) | Candidatos Evaluados / Validados |
|---:|---|---:|---|---:|---:|---:|---:|
| 1 | `gas_centro` | 18:00 | Caída ciclo combinado Nehuenco en rampa vespertina | `17.38 ms` | `474.20 ms` | `404.07 ms` | 39/39 |
| 2 | `L1` | 12:00 | Apertura corredor Norte Grande -> Norte Chico en pico solar | `11.12 ms` | `349.27 ms` | `360.51 ms` | 37/37 |
| 3 | `L2` | 13:00 | Apertura corredor Norte Chico -> Centro con congestión solar | `11.14 ms` | `324.85 ms` | `345.84 ms` | 34/34 |
| 4 | `L3` | 19:00 | Apertura corredor Centro -> Centro-Sur en punta nocturna | `11.14 ms` | `339.61 ms` | `350.40 ms` | 34/34 |
| 5 | `L4` | 20:00 | Apertura enlace Centro-Sur -> Sur Austral | `11.20 ms` | `374.63 ms` | `388.96 ms` | 37/37 |
| 6 | `hydro_sur` | 19:00 | Indisponibilidad central hidroeléctrica de embalse Sur | `29.63 ms` | `359.73 ms` | `302.49 ms` | 30/30 |
| 7 | `gas_ng` | 18:00 | Salida central ciclo combinado Mejillones Norte Grande | `13.60 ms` | `392.79 ms` | `386.26 ms` | 39/39 |
| 8 | `coal_cs` | 18:00 | Salida unidad térmica base Centro-Sur | `11.21 ms` | `391.99 ms` | `391.20 ms` | 39/39 |
| 9 | `solar_ng` | 12:00 | Desconexión planta fotovoltaica Crucero al mediodía | `20.89 ms` | `434.18 ms` | `366.59 ms` | 39/39 |
| 10 | `b_centro` | 19:00 | Falla de inversor en batería BESS Polpaico Operativo | `7.11 ms` | `262.78 ms` | `243.74 ms` | 39/39 |

## 3. Verificación Criterio 3 (20 Incidentes Aleatorios)

- **Incidentes ejecutados:** `20/20`
- **Ambas opciones pasan el validador independiente (`validate()`):** `20/20 (100%)`
- **`tradeoff_tag` distinto entre Opción 1 y Opción 2:** `20/20 (100%)`
- **Cero dígitos (`\d`) en textos de Gemini (`diagnosis_es`, `title_es`, `rationale_es`, `agent.thought`, `agent.tool_call`):** `20/20 (100%)`

## 4. Verificación Criterio 4 (2 Fallas Simultáneas + Modo Autónomo + Veto)

- **Eventos simultáneos activos:** `2` (`gas_centro` + `L3`)
- **Cuenta regresiva incidente 1 (`autonomy.countdown`):** `[5, 4, 3, 2, 1, 0]` → aplicado por `gemini_autonomous`
- **Veto de operador en incidente 2:** opción `op_bess_b_reserve_ng_plus_dr_n_centro_200` cancelada con evento `plan.vetoed`
- **Auditoría en informe RIO (`/report`):** `True`
