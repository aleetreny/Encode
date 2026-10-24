# Demo integration handoff — 24 October 2026

The target is one path: open a backend scenario → request a Gemini analysis → Gemini invokes numerical tools → backend verifies results → UI shows that same run → operator approves in simulation → download that run's backend report. No additional product features are required before this passes.

## Sources integrated on `feature/data-backend`

| Owner | Remote commit inspected and merged | Actual state |
|---|---|---|
| P1 frontend | `d481a6a` | React UI and map exist. Standard build fails on `ImportMeta.env`. Scenario, dispatch, trace, decision and report are local fixture/state paths. |
| P2 agent | `bc1d3d4` | Importable with runtime dependencies; five unit tests pass offline. Returns legacy canonical results, not native v2. Google credentials are absent here. Offline synthesis currently claims Google/model metadata using a local hash. |
| P3 numerical | `c9306bb` | Latest solver and independent validator integrated unchanged. 113 numerical tests and 532-case outage stress sweep pass. Adds emergency-runback output fields and improved dispatch; old cached native results no longer pass its validator. |
| P4 backend | This branch / PR #1 | API, native tools, independent acceptance, run persistence, simulation decision and report work via actual HTTP. Native replay regenerated against P3's current module. Runtime manifest now includes the imports required by P2. |

These are merges into the integration branch, not into `main`. No public deployment or messages to teammates were made.

## Person 1 — required changes in frontend

1. Make the existing build work: add `frontend/src/vite-env.d.ts` containing `/// <reference types="vite/client" />`. `npm ci && npm run build` currently fails at `src/api/client.ts:6`. Passing `--types vite/client` externally lets TypeScript and Vite build; that diagnostic is not a fix committed to your area.
2. Use `contracts/native-client.ts` (and `contracts/client.ts`, which defines `ApiError`). The client takes the **server origin**, e.g. `http://127.0.0.1:8000`, or `""` with a same-origin `/api` proxy. Do not pass a base ending in `/api`, or requests become `/api/api/...`. Keep the Gemini key only in the backend. The Vite proxy should target `http://127.0.0.1:8000` to match the documented IPv4 backend bind.
3. In `App.tsx`, load `GET /api/scenario` and retain its returned `scenario_id` (`chile-sen-5node-demo` by default), timestamps, topology and modification menu. Current `scenarioData.ts` imports are offline fixture previews; they must not be the source of a live result. Label any retained preview visibly as offline fixtures.
4. Replace `AgentCopilotDrawer.tsx::runLiveInvestigationReplay` and its timer/static trace with `POST /api/agent/run` and polling `GET /api/agent/runs/{run_id}`. Request `execution_mode="live"`, `settings.allow_cached_fallback=false` for the live demo. Display HTTP errors and terminal failed/infeasible states; clear stale prior results when starting a new run. Do not label the animation as a model execution.
5. Drive map, comparison, validation and recommendation from the **same completed run**. `run.baseline` and `run.candidate` are native solutions (`timeseries`, `metrics`, `binding_constraints`); crisis equivalents are under `run.crisis_analysis`. Native candidate IDs include `north_bess`, `south_bess`, `uprate_l2`; do not assume the fixture IDs `c1_battery_norte_grande` etc. Accept other returned candidate IDs. Render check names/counts from the response, not the fixed “16/16” string.
6. Show `execution_mode`, `provenance.live_gemini`, actual `provenance.model_execution.model`, fallback/error and synthetic-input provenance. An unmodified current frontend says “Gemini 4 Argon” even though its data is local; replace this with actual mode/model evidence. Keep hourly timestamps as hourly results; 15-minute interpolation must be labelled as display interpolation.
7. Enable approval only when status is completed, validation passed and approval status pending. Call `client.decision(run, 'approved', operator)` using the latest `revision`; update from the returned run. On 409 fetch again and show the conflict. `setApprovalStatus('approved')` alone does not persist a decision. `src/api/client.ts::postOperatorDecision` currently names a nonexistent `/api/investigations/...` route and returns success on network failure: remove that success fallback. Do not add a backend compatibility route for an unverified local action.
8. Replace `App.tsx::handleExportRioReport`'s locally assembled JSON with the backend report download for the current run. It contains actual decision, run ID, scenario snapshot and validation. Do not label a frontend fixture export as “CEN audited”. Display simulation-only scope and `legal_compliance_status=not_certified`.

Minimal client sequence (inside an async handler; keep React state and error handling around it):

```ts
const api = nativeGridPilotClient(""); // Vite /api proxy, no Gemini key
const scenario = await api.scenario();
let run = await api.start("live", {allow_cached_fallback: false},
  "operator_approval", scenario.scenario_id as string);
while (run.status === "queued" || run.status === "running") {
  await new Promise(resolve => setTimeout(resolve, 500));
  run = await api.run(run.run_id);
}
if (run.status !== "completed" || !run.validation.passed ||
    run.execution_mode !== "live" || !run.provenance?.live_gemini) {
  throw new Error("Live investigation did not pass; show the returned error");
}
// Render this run first; approval happens only on a separate user click:
run = await api.decision(run, "approved", operatorName);
// A separate download click uses api.reportUrl(run.run_id).
```

A build gate in `.github/workflows/frontend-integration.yml` now runs the standard build. It is expected to fail until item 1 is committed; a passing backend job does not certify the UI.

## Person 2 — required changes in agent

1. Keep `run_investigation(scenario_id, settings)` but implement the native v2 path from `docs/contracts-v2.md`. Load the snapshot through `backend.runtime.load_scenario` and `inspect_evidence`. The current agent can load that snapshot, but its returned candidate fails `NativeSolution`: native scenario/candidate IDs, timeseries and other fields are absent at the top level.
2. Use actual Gemini function calling: submit tool declarations and the scenario/evidence context, execute the returned `functionCall` via the bounded backend tools, send the matching `functionResponse`, then continue the model loop. The current `plan_candidates_and_crisis` is Python selection logic and the only Google call is a final one-sentence synthesis; this is not evidence that Gemini called the solver. See [Google function calling](https://ai.google.dev/gemini-api/docs/generate-content/function-calling) and [generateContent response fields](https://ai.google.dev/api/generate-content).
3. Call native tools, without recursively calling HTTP from the worker:
   - `load_scenario(scenario_id)` → immutable request snapshot copy.
   - `inspect_evidence(scenario_id)` → historical evidence, native modification menu and assumptions.
   - `await run_optimisation(scenario_id, candidate, events, options)` → native solution with validation.
   - `await validate_candidate(scenario_id, solution)` → independent native acceptance.
   - `compare_results(baseline, candidate)` → native comparison after revalidation.
   - Record your actual `generate_operator_report` synthesis/tool execution.
   Read modification bounds from the real menu, not the standalone fallback's alternate `allowed_types` layout.
4. Native baseline preserves the scenario's existing assets. Do not disable the existing battery as a legacy “baseline policy”. Candidate means a bounded asset intervention; native options are `allow_unserved` and `time_limit_s`, not `battery_policy` or `allow_load_shedding`. Honour `settings.candidates`, `settings.crisis_events`, `settings.options`. The backend already computes and verifies the crisis stage; return normal native arrays and selected `candidate_definition` so that stage can execute consistently.
5. Return native `baseline`, `candidate`, selected `candidate_definition`, actual timestamped six-tool trace, `operator_report`, and `model_execution`. The backend independently validates results and will reject mismatched assets, inputs or hindsight. A local solver fallback is deterministic software execution, not Google execution.
6. Missing key, HTTP error, quota error or timeout must raise a truthful failure, not synthesize a successful provider result. `GeminiArgonClient.synthesise_investigation` currently produces `resp-argon-<hash>` offline; `_call_google_rest_api` can also synthesize `resp-google-<hash>`. Both are now rejected by backend live acceptance. Return the response ID and actual model/version from the real successful response. The current default `gemini-4-argon` is silently sent as `gemini-2.5-flash` while still reported as Argon: remove that mismatch. Set an explicit supported model available to your account and report the model actually used.
7. Do not claim full regulatory certification, a real reconnection or invented household totals in the narrative. Backend numeric comparisons and the explicit household mapping are authoritative. Test the native contract in addition to the current five offline unit tests.

The backend's rejection of known fake metadata is a guard, not independent verification of every future adapter attestation. Final acceptance requires a real successful provider exchange, model-selected tool calls and the resulting verified native arrays.

## Person 3 — current handoff

Your branch is integrated unchanged, including the new validator and emergency runback fields. No numerical changes are requested for this path. The full numerical suite and stress sweep pass. Backend replay/examples were regenerated because old results lack `emergency_runback_mwh` and the objective runback term. Deterministic dispatch within a degenerate optimum can change individual hourly values; UI household figures must come from the returned run, not the older fixtures.

## Person 4 — completed integration work

- Integrated all three current remote workstreams on the existing feature branch; preserved owner source files.
- Resolved runtime import dependencies (`httpx`, SciPy) for the actual imported agent, including in the container.
- Regenerated native cache and contract examples using the current numerical module; retained actual independent verification.
- Blocked strict live requests without credentials. Allowed cache fallback explicitly reports `gemini_credentials_missing`, `execution_mode=replay`, requested mode live, and `live_gemini=false`.
- Rejected current locally generated Google response IDs on both API protocols.
- Fixed the HTTP release smoke so live mode disables fallback, checks the **returned** mode/provenance and refuses substituted execution. It can save the actual approved backend reports with `--report-dir`.
- Included agent unit tests in the integrated suite, added runtime import/pip checks and deterministic HTTP checks to backend CI, and added the real frontend build gate.

## Reproduce and close the demo gate

From the repository root:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m optimisation.stress
python scripts/export_contracts.py --check
python -m uvicorn backend.main:create_app --factory --host 127.0.0.1 --port 8000
```

In another terminal:

```bash
python scripts/smoke.py --mode deterministic --report-dir var/demo-verification
python scripts/smoke.py --mode replay --report-dir var/demo-verification
# Only after P2's fixes and backend environment credentials are configured:
python scripts/smoke.py --mode live --report-dir var/demo-verification
```

Configure `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) and an agreed `GRIDPILOT_GEMINI_MODEL` in the backend process environment; restart the backend after configuration. No credentials were found in this workspace/environment. Do not commit them or place them in `VITE_*` variables. Missing credentials are not evidence of a Google outage. No successful Google call has been observed here.

Then run `cd frontend && npm ci && npm run build && npm run dev`, open the app, and exercise the exact live path twice. Browser Network must show scenario GET, run POST (202), polling GET, decision POST (200) and report GET (200), all tied to the same run ID. Confirm the result is live, validated and has the actual provider/model response metadata; confirm approval is persisted after page reload and the downloaded report includes that decision. Repeat with a stopped backend: the UI must show failure, not success. Only then record the integrated demo.

Browser UI verification in this session was blocked by the browser authorization gate for localhost. It was not bypassed. The HTTP numerical/persistence path is tested separately; no claim is made that a browser click completed it.

Ready now: real numerical/backend demonstration with explicit deterministic or replay labels. Not ready: the complete Gemini-driven UI demonstration. Remaining blockers are P1's wiring/build, P2's native tool-calling/provenance changes, a valid Gemini credential/model, and final browser verification. Hosting/video are unnecessary to prove the local integration path and were not started.
