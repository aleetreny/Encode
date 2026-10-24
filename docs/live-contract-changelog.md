# Live Contract Changelog (`contracts/live.schema.json` & `frontend/src/live/types.ts`)

All changes after the initial contract freeze are documented here. Only optional additive fields are permitted.

## 2026-10-24 — Initial Freeze (Wave A / Phase 0)
- Frozen `Catalog`, `Solution`, `Disruption`, `Lever`, `Option`, `LiveEvent` (with `seq`, `session_id`, `hour`, `ts_utc` envelope), and REST command schemas in `contracts/live.schema.json` and `frontend/src/live/types.ts`.
