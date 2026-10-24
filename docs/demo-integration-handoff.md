# Demo integration handoff — latest branch integration, 24 October 2026

Target: open the backend scenario → request a Gemini analysis → Gemini calls numerical tools → backend independently verifies → UI renders that same run → operator approves in simulation → download that run's backend report. Complete this before adding product features.

## Current sources and verified status

All changes are on `feature/data-backend` / PR #1. `main` is unchanged.

| Workstream | Latest remote commit merged | Verified state |
|---|---|---|
| P1 frontend | `260744a` | Standard `npm ci && npm run build` now passes: Vite types are fixed. Current `App.tsx` is a local schematic sandbox using JavaScript arithmetic and timer-based battery SOC. It does not call the backend and has no verified-run approval/report path. |
| P2 agent | `d0acb32` (includes native support `b3abdf5`) | Native v2 baseline/candidate and selected definition now match the backend snapshot and independently pass validation. Actual native trace has 53 events. Provider behavior remains unchanged: Python chooses candidates/tools, Google is called only for final synthesis if a key exists, and offline output claims locally generated Google IDs. |
| P3 numerical | `e60d223` | Older saved-result compatibility plus full validated example matrix integrated. Solver and validator source are unchanged by P4. Two generated south-battery crisis examples differed in hourly dispatch; regenerated with the owner's prescribed `python -m optimisation.demo --write`, without changing tests/constraints. |
| P4 backend/client | Current branch | Real HTTP workflow and the shared TypeScript client pass scenario → run → independent acceptance → persisted simulation approval → report download, in deterministic and replay modes. Strict live correctly fails with no configured credential. |

Earlier reports that the frontend build fails or the agent only supports v1 are superseded. Neither correction establishes a complete live demo.

## Person 1 — wire the current interface

Files to change: `frontend/src/App.tsx`, `frontend/src/api/client.ts`, and, as needed, `frontend/src/components/ChileIsoMaquette.tsx`. The older drawer/map components were removed; do not implement fixes against their old paths.

1. Import the shared `contracts/native-client.ts` and its `contracts/client.ts` dependency. The base URL is a server origin such as `http://127.0.0.1:8000`, or `""` with the Vite `/api` proxy. Do not pass a base ending in `/api`, which doubles the prefix. Set the proxy target to `http://127.0.0.1:8000` to match the documented backend IPv4 bind.
2. Load `GET /api/scenario`, retain its actual ID, topology, timestamps and modification menu. Default ID is `chile-sen-5node-demo`. Do not substitute the sandbox's local demand, solar or cable values into the fixed native scenario: those sliders have no agreed backend request representation. Keep that sandbox explicitly labelled as a local educational illustration, or disable its local calculations while a verified run is displayed.
3. Add/connect the analysis action using `POST /api/agent/run`, then poll `GET /api/agent/runs/{run_id}`. For live demo acceptance, use `execution_mode="live"` and `settings.allow_cached_fallback=false`. Clear old results on a new run and display HTTP/terminal errors. Do not translate a timer or `agentEnabled` into a claim that Gemini executed.
4. Render the same completed run's native `baseline`, `candidate`, `comparison`, `validation`, trace and report. Crisis data is in `crisis_analysis`. Use `timeseries`, `metrics` and `binding_constraints`; native candidate IDs are returned dynamically (defaults include `north_bess`, `south_bess`, `uprate_l2`). Do not combine sandbox arithmetic or looping SOC with verified solver arrays. A schematic aggregation needs a visible, correct mapping to model assets; retain nodal results if no mapping is implemented.
5. Show actual `execution_mode`, `provenance.live_gemini`, `provenance.model_execution.model`, fallback/error, synthetic profile provenance and numerical units. Display hourly timestamps in `America/Santiago`; interpolated animation does not constitute a new solved interval. Household equivalents come from the backend mapping/window, not a decorative house count.
6. Enable approval only on a completed, validated, pending run. Call `api.decision(run, 'approved', operatorName)` with the latest revision; update from the returned run. Handle 409 by reloading. Do not use the leftover `postOperatorDecision` implementation: it targets nonexistent `/api/investigations/...` and returns true on network failure. Local state changes are not persisted approvals.
7. Download the current run using `api.reportUrl(run.run_id)`. Do not generate a replacement report in the browser. Verify the report contains that run ID, validation and the persisted simulation-only decision. Show `legal_compliance_status=not_certified` rather than claiming official certification.

Minimal sequence (inside async UI handlers with loading/error state):

```ts
const api = nativeGridPilotClient(""); // same-origin Vite /api proxy
const scenario = await api.scenario();
let run = await api.start("live", {allow_cached_fallback: false},
  "operator_approval", scenario.scenario_id as string);
while (run.status === "queued" || run.status === "running") {
  await new Promise(resolve => setTimeout(resolve, 500));
  run = await api.run(run.run_id);
}
if (run.status !== "completed" || !run.validation.passed ||
    run.execution_mode !== "live" || !run.provenance?.live_gemini) {
  throw new Error("Live investigation failed; display the returned error");
}
// Render this run. A separate operator click performs:
run = await api.decision(run, "approved", operatorName);
// A separate report click downloads api.reportUrl(run.run_id).
```

This exact shared client's network/persistence/download methods have been exercised against the real API with Node, not just type-checked. That verifies the client/backend boundary, not the current React screen.

## Person 2 — remaining provider/tool loop work

Native output compatibility is now verified. Keep that implementation and close these remaining items:

1. In `agent/gemini_client.py`, use actual model-selected function calls. Submit tool declarations, execute returned `functionCall` arguments through the bounded numerical tools, send matching `functionResponse` results, and continue the model loop. Current native orchestration enumerates candidates in Python and invokes Gemini only to summarise the final results. See [Google function calling](https://ai.google.dev/gemini-api/docs/generate-content/function-calling) and [generateContent fields](https://ai.google.dev/api/generate-content).
2. Remove the successful Google impersonation on missing credentials or provider failure. `synthesise_investigation` still creates `resp-argon-<hash>` without a provider request, and `_call_google_rest_api` may create `resp-google-<hash>` if `responseId` is absent. The backend rejects both. Raise a truthful error instead; backend fallback, if explicitly allowed, labels the whole result replay.
3. Return the actual provider response ID and model/version. The client currently sends the default `gemini-4-argon` request as `gemini-2.5-flash` but reports the configured Argon name. Use a supported model accessible to the account and report the model actually invoked. Keep secrets in backend environment variables only.
4. Preserve native baseline assets and requested candidates/events/options; do not reintroduce the v1 disabled-battery comparison. The actual v2 results now pass `backend.native_service.check_solution`; a focused backend integration test exercises the real agent against the request snapshot.
5. Do not swallow numerical/validator errors into a less restrictive standalone fallback in the integrated live path. Let the backend surface failure. The backend independently revalidates all accepted results regardless of the agent's own check.
6. Use backend household metrics and explicit model limitations in the narrative. Local household summaries are not unique reconnected customers, and passed mathematical checks do not establish full legal/N-1 certification. Keep actual model-selected tool events timestamped and distinguish them from deterministic backend verification.

`run_investigation(scenario_id, settings)` remains the agreed entrypoint. See `docs/contracts-v2.md` for the full native return shape. The backend independently validates normal results, computes/verifies crisis results, persists the decision and exports the authoritative report.

## Person 3 — no solver change requested

The latest numerical branch and example index are integrated. The complete test suite and the 532-case stress sweep are rerun. The new matrix exposed only two stale generated `c2_battery_sur` crisis files: different valid hourly discharge/flow allocation, same aggregate metrics. They were regenerated using your script; solver, validator and tests were not edited. A different platform producing a different degenerate optimum would need an owner decision on exact snapshot equality versus semantic validation, not manually altered metrics or relaxed physics.

## Person 4 — completed and remaining boundary

Completed: merge current sources on our branch; preserve teammate implementation; verify native agent snapshot compatibility; regenerate generated examples with owner tooling; validate standard frontend build; verify real Python HTTP calls and the shared TypeScript client's run/decision/report flow; enforce truthful live/fallback labels; update automated checks and handoff.

No alternative UI, slider API, provider implementation or new product features were introduced. P1/P2 still own the UI wiring and genuine Gemini tool loop. No public deployment or messages to teammates were made. Source and instructions are visible in PR #1.

## Reproduce the verified backend/client path

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m optimisation.stress
python scripts/export_contracts.py --check
python -m uvicorn backend.main:create_app --factory --host 127.0.0.1 --port 8000
```

In another terminal, run Python HTTP checks:

```bash
python scripts/smoke.py --mode deterministic --report-dir var/integration-latest/python
python scripts/smoke.py --mode replay --report-dir var/integration-latest/python
```

Compile and exercise the actual frontend contract client (Node 22+, no frontend source changes):

```bash
npx --yes --package typescript@5.9.3 tsc --strict --lib DOM,ES2022 --target ES2022 \
  --moduleResolution node --module commonjs --outDir /tmp/gridpilot-contract-client \
  contracts/client.ts contracts/native-client.ts
node scripts/smoke-client.cjs /tmp/gridpilot-contract-client http://127.0.0.1:8000 deterministic
node scripts/smoke-client.cjs /tmp/gridpilot-contract-client http://127.0.0.1:8000 replay
```

Both checkers require the returned mode to match the request and verify persisted approval and downloaded report. Backend CI repeats these shared-client checks against Uvicorn and the container. They do not simulate or certify React clicks.

For live testing, configure `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) and an agreed `GRIDPILOT_GEMINI_MODEL` in the backend process environment, restart it, and run both checkers with `live`. No key was found locally and both live attempts correctly returned HTTP 503. Do not put provider keys in `VITE_*`, git or chat. A key alone does not fix P2's tool loop or model metadata.

After the remaining P1/P2 changes, use `cd frontend && npm ci && npm run build && npm run dev`, then exercise the exact browser path twice. Network must show scenario GET, run POST (202), polling GET, decision POST (200), report GET (200), all for the same run. Reload to verify approval persisted. Repeat with the API stopped: the UI must report failure. Only then record the complete live demo.

The earlier browser authorization for localhost was denied; it has not been retried or bypassed. Current UI remains unverified by browser interaction. Hosting/video are unnecessary to establish the local path and were not started.
