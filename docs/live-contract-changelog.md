# Live Contract Changelog (`contracts/live.schema.json` & `frontend/src/live/types.ts`)

All changes after the initial contract freeze are documented here. Only optional additive fields are permitted.

## 2026-10-24 — Initial Freeze (Wave A / Phase 0)
- Frozen `Catalog`, `Solution`, `Disruption`, `Lever`, `Option`, `LiveEvent` (with `seq`, `session_id`, `hour`, `ts_utc` envelope), and REST command schemas in `contracts/live.schema.json` and `frontend/src/live/types.ts`.

## 2026-10-24 — Optional Catalog Metadata Fields (Wave C)
- Added optional additive metadata properties on `Catalog` in `contracts/live.schema.json` (`scenario_id`, `stress_recipes`, `jury_cards`, `assumptions`, node `label`/`substation`/`provenance`, generator `variable_cost_usd_per_mwh`/`ramp_rate_mw_per_h`/`emission_factor_t_per_mwh`, battery `power_capacity_mw`/`energy_capacity_mwh`/`initial_soc_mwh`, line `from_node`/`to_node`). All core required fields remain unchanged.

## 2026-10-25 — Real-day profile and Jimmy monitor (`feature/real-day`)
- Added optional `Catalog.day_profile` (`source`, `date`, `method`, `scale_factor`, `label_es`) so the UI can label the day as synthetic or as a scaled real CEN day.
- Added optional `agent.note` fields `kind`, `severity`, `metrics`, `watch` and `model_execution` for the hourly monitor. Existing notes with only `text_es` stay valid. Details in `docs/real-day-contract.md`.

## 2026-10-25 — Jury Impact Preview Endpoint (Etapa 2)
- Added additive REST response definitions `ImpactPreviewAsset` and `ImpactPreviewResponse` in `contracts/live.schema.json` and `frontend/src/live/types.ts` for `GET /api/live/sessions/{id}/impact_preview`, plus `fetchImpactPreview` in `frontend/src/live/client.ts`.


## 2026-10-25 — Display text is now English (`feature/real-day`)
- No schema change. Fields whose names end in `_es` (`text_es`, `thought_es`, `diagnosis_es`, `title_es`, `rationale_es`, `args_summary_es`, `label_es`, `description_es`, `message_es`…) keep their names for compatibility but now carry **English** text, because the jury and audience are English-speaking. Gemini (decider) and Jimmy (monitor) are prompted to answer in English, still with zero digits in prose.
