# Verification record — latest integration, 24 October 2026

Branch `feature/data-backend` incorporates frontend `260744a`, agent `d0acb32` and numerical `e60d223`. See [owner handoff](demo-integration-handoff.md) and [actual HTTP evidence](demo-verification.json). `main` is unchanged.

- **209 tests passed**, including the updated numerical/agent suites and a backend test invoking the actual native agent against the request snapshot. Test doubles/offline agent execution are not Google execution evidence.
- Numerical stress sweep passed **532 cases / 1,982 solves**.
- Ruff lint/format, strict TypeScript contract compilation and schema drift passed. Runtime dependencies were already verified in the runtime-only environment used for these HTTP runs.
- Standard **`npm ci && npm run build` now passes**, without editing frontend source. The former Vite type failure is resolved by P1's update.
- Actual native agent invocation now supplies valid native baseline/candidate, selected `north_bess` and a complete 53-event trace; both numerical solutions independently pass against the backend snapshot. Its offline Google metadata remains rejected. The earlier v1 result mismatch is resolved.
- A fresh runtime-only Uvicorn server passed **six approved HTTP investigations**: two deterministic and two replay through the Python checker, plus one deterministic and one replay through the actual compiled `contracts/native-client.ts`. All verified numerical acceptance, persisted simulation decisions and actual downloaded reports. Reports are under `var/integration-latest/`; run IDs, modes and file hashes are committed in `demo-verification.json`.
- Both Python and shared TypeScript live checks failed correctly with HTTP **503** because no Gemini credential is configured. Explicitly allowed fallback completed as replay with `gemini_credentials_missing` and `live_gemini=false`; it cannot pass a live release gate.
- The latest numerical example matrix exposed two stale generated south-battery sudden-outage files: hourly discharge/flows and binding-hour allocation differed, while aggregate metrics matched. Ran the owner's prescribed `python -m optimisation.demo --write`; only those two generated files changed. No numerical source, constraints or tests were edited to make checks pass.
- Frontend source inspection confirms `App.tsx` calculates sandbox output in JavaScript, loops SOC using a timer, and does not call the API. The shared client is functional over HTTP; this does not establish that the React UI uses it. Current UI has no verified-run approval/download controls.
- The earlier browser authorization denial for localhost was not retried or bypassed. Browser click-through remains unverified.

The current native cache's normal curtailment reduction is 631.578947 MWh; crisis whole-horizon unserved reduction is 391.875 MWh. Event-window equivalents remain explicitly scoped and synthetic. Do not copy constants from local UI calculations into a verified run.

The test runner emits one Starlette/httpx deprecation warning; actual Uvicorn HTTP checks pass separately. Docker is unavailable locally. [PR checks](https://github.com/aleetreny/Encode/pull/1/checks) independently run backend/container/shared-client verification and the standard frontend build. Local checks above do not substitute for the current commit's CI results.

Ready: backend/numerical workflow, native agent protocol compatibility, shared network client and frontend build. Not yet certified: a real Google/model-selected tool loop, UI scenario/run/decision/report integration, final browser path, public deployment, recording or submission. Remaining provider/UI changes are specified in the handoff; no new product features were added.
