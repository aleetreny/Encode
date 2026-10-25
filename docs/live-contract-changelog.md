# Live Contract Changelog (`contracts/live.schema.json` & `frontend/src/live/types.ts`)

All changes after the initial contract freeze are documented here. Only optional additive fields are permitted.

## 2026-10-24 — Initial Freeze (Wave A / Phase 0)
- Frozen `Catalog`, `Solution`, `Disruption`, `Lever`, `Option`, `LiveEvent` (with `seq`, `session_id`, `hour`, `ts_utc` envelope), and REST command schemas in `contracts/live.schema.json` and `frontend/src/live/types.ts`.

## 2026-10-24 — Optional Catalog Metadata Fields (Wave C)
- Added optional additive metadata properties on `Catalog` in `contracts/live.schema.json` (`scenario_id`, `stress_recipes`, `jury_cards`, `assumptions`, node `label`/`substation`/`provenance`, generator `variable_cost_usd_per_mwh`/`ramp_rate_mw_per_h`/`emission_factor_t_per_mwh`, battery `power_capacity_mw`/`energy_capacity_mwh`/`initial_soc_mwh`, line `from_node`/`to_node`). All core required fields remain unchanged.

## 2026-10-25 — Jury Impact Preview Endpoint (Etapa 2)
- Added additive REST response definitions `ImpactPreviewAsset` and `ImpactPreviewResponse` in `contracts/live.schema.json` and `frontend/src/live/types.ts` for `GET /api/live/sessions/{id}/impact_preview`, plus `fetchImpactPreview` in `frontend/src/live/client.ts`.

