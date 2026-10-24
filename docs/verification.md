# Verification record — integration audit, 24 October 2026

Branch `feature/data-backend` incorporates frontend `d481a6a`, agent `bc1d3d4` and numerical `c9306bb`. See [owner-specific integration handoff](demo-integration-handoff.md) and [machine-readable HTTP evidence](demo-verification.json).

- **206 tests passed** across backend/data, the numerical module and the actual agent's five offline unit tests. Test doubles and offline tests are not Google execution evidence.
- P3's outage stress sweep passed **532 cases / 1,982 solves**, including planned/sudden outages, validation and no-hindsight checks.
- Ruff lint/format, strict TypeScript compilation of both backend contract clients, schema drift, CEN source regeneration and `pip check` passed. Numerical owner source is integrated unchanged.
- The actual agent imports in a runtime-only environment after adding its required HTTP/SciPy imports to the runtime manifest.
- A fresh Uvicorn server in that runtime-only environment completed **two deterministic and two replay HTTP investigations**, including actual solver/validator calls, comparisons, persisted simulation approvals and report downloads. The four full downloaded reports are saved locally under `var/demo-verification/`; run IDs and report hashes are recorded in `demo-verification.json`.
- Native replay was regenerated because the updated numerical validator requires emergency-runback fields absent from the old cache. Default normal curtailment reduction remains 631.578947 MWh; whole-horizon crisis unserved reduction remains 391.875 MWh. Current event-window household-hours are 364,800, averaging 91,200 equivalents across four hours under the explicit synthetic factor. Individual hourly dispatch changed with the numerical update; old UI constants must not be reused.
- Strict live start actually returned HTTP **503** with missing-credential information. An explicitly allowed fallback actually completed with `execution_mode=replay`, `requested_execution_mode=live`, `live_gemini=false` and reason `gemini_credentials_missing`. The release smoke refuses this as a live success.
- Direct invocation of the actual agent against the native snapshot returned the legacy shape and no bounded native candidate. Its no-key client produced locally hashed Google metadata; backend live acceptance now rejects those known local IDs.
- The current frontend decision endpoint actually returned HTTP **404**. Source inspection confirms the drawer changes local approval state and generates its own fixture report, rather than persisting/downloading a backend run.
- `npm ci` succeeded. Standard **`npm run build` failed**: `src/api/client.ts(6,30): TS2339 Property 'env' does not exist on type 'ImportMeta'`. Diagnostic TypeScript compilation with externally supplied `--types vite/client`, followed by Vite build, passed without changing frontend source. That is not a passing standard build.
- Browser verification was denied by the browser authorization gate for localhost. No alternate browser, browser automation or UI-network workaround was attempted; UI click-through is unverified.

The test runner emits one Starlette/httpx deprecation warning. Actual Uvicorn HTTP tests pass independently.

Docker is unavailable locally. [PR checks](https://github.com/aleetreny/Encode/pull/1/checks) separately expose backend/container verification and the standard frontend build gate. A green backend check does not mean the complete demo works; the frontend gate remains blocked until the owner supplies the Vite type fix.

No successful real Google request, model-selected solver call, integrated browser approval/download, public deployment, video or submission is certified. Ready now is the real backend/numerical simulation demo with explicit deterministic/replay labels. Complete live demo acceptance remains blocked by the agent native/tool-calling changes, frontend wiring/build, Gemini credentials/model and final browser verification.
