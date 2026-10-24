# GridPilot integration contracts

**Current default: native v2 normal dispatch + crisis recovery.** Read [the complete v2 contract](../docs/contracts-v2.md), use `native-client.ts` and the `native-*.schema.json` / `native-*.example.json` files. `/api/scenario` defaults to `chile-sen-5node-demo` with its intervention menu. `/api/scenarios` lists all scenarios. Native numerical envelopes preserve `optimisation/DESIGN.md` field names.

## Legacy v1 compatibility reference

The sections below describe the retained four-node fixtures selected explicitly by their legacy scenario IDs. Their endpoints coexist with v2 and are not the default project demo.

The implementation in `backend/models.py` is authoritative. JSON Schema/OpenAPI are generated with `python scripts/export_contracts.py`; CI checks drift. Examples are cached offline fixtures, not evidence of a live Gemini invocation. Breaking changes require a version bump and coordinated updates by affected owners.

## HTTP behavior

| Method | Path | Behavior |
|---|---|---|
| GET | `/api/scenarios` | Catalog of v2 and retained v1 scenarios |
| GET | `/api/scenario?scenario_id=chile-demo-001` | A single scenario |
| GET | `/api/evidence/cen-2026-08-01` | Source aggregates, original hour labels and limitations |
| POST | `/api/optimise` | `{scenario_id, options}` → `{status, solution, validation}` |
| POST | `/api/validate` | `{scenario_id, options, solution}` → combined validation |
| POST | `/api/agent/run` | `{scenario_id, execution_mode, settings}` → HTTP 202 and queued run |
| GET | `/api/agent/runs/{run_id}` | Full run state; stop polling on `completed` or `failed` |
| POST | `/api/agent/runs/{run_id}/decision` | `{decision, expected_revision, operator, note}` |
| GET | `/api/agent/runs/{run_id}/report` | Terminal run as downloadable JSON |
| GET | `/api/health` | Local capabilities; missing live adapters do not make replay unhealthy |
| GET | `/api/ready?mode=replay` | Replay configuration readiness |
| GET | `/api/ready?mode=live` | Installed live-adapter readiness; provider connectivity is not probed |

`execution_mode` defaults to `live`; the frontend must explicitly choose `replay` when using cached outputs. Live is never silently replaced with replay. `options` defaults to `battery_policy=optimised`, `allow_load_shedding=false`. The cached replay supports exactly those defaults and rejects other settings. The same synthetic scenario is also available as `synthetic-demo-001`, without historical evidence.

POSTs need `Authorization: Bearer <operator-token>` when configured. This operator token is separate from provider credentials. POST `/api/agent/run` accepts `Idempotency-Key`: same key/input returns the same run (200), different input returns 409. Queue pressure returns 429 with `Retry-After`. Missing adapters return 503, hard execution timeout 504, adapter failure 502. Bad fields return 422 without echoing original inputs. Queued/running failures are exposed in the polled run's `error` and `validation`, not converted into HTTP success metrics.

## Person 1: frontend

Use `contracts/client.ts` with the API base URL. The API already supplies metrics. Do not recompute dispatch metrics from chart values. UI responsibilities:

1. Display scenario mode and explicit synthetic-network/data limitations.
2. Show historical evidence separately from simulated baseline/candidate values.
3. Start with an explicit execution mode, retain the run ID, poll every 500–1000 ms and stop at a terminal status.
4. Disable approval until `status=completed`, `validation.passed=true`, and `approval_status=pending`.
5. Submit the current revision with a decision. On 409, refresh and show the updated state.
6. Download report from the supplied run ID. Render narrative as text, not unescaped HTML.
7. Use `Intl.DateTimeFormat` with `timeZone: 'America/Santiago'` to label simulation times. Do not map observed hour labels to UTC until the source convention is established.
8. Keep Gemini and CEN keys out of the frontend. The limited operator demo token can be entered for the judging session; it must not be hardcoded in a public bundle.

Example start body:

```json
{"scenario_id":"chile-demo-001","execution_mode":"replay","settings":{"battery_policy":"optimised","allow_load_shedding":false}}
```

## Person 3: solver and independent validator

The default bridge targets the native interface from `feature/optimisation`; executable code at `fbf0fdf` has been merged into this branch and API-tested. Synchronous or async functions are supported:

```python
# optimisation/__init__.py — Person 3's native interface
def solve(scenario: dict, candidate=None, events=None, options=None) -> dict: ...
def validate(scenario: dict, solution: dict) -> dict: ...
```

`backend.p3_adapter` maps the current API's fixed-asset subset to that native schema: objective block, explicit one-way efficiencies, `allow_unserved`, native `timeseries` keys and structured validation violations. It retains the full native result in `solution.native_result`, calls the native validator with **two** arguments, checks that normalised arrays match the retained output, and applies the additional backend audit. It does not rewrite Person 3's module. Native `error` maps to API `failed`; infeasibility never becomes zero arrays tagged optimal.

Important scope difference: the current v1 replay compares battery-disabled and battery-enabled dispatch on fixed assets. Person 3's design additionally describes asset additions/uprates, outages and ramping. Those are not accepted silently through this v1 bridge. They need a coordinated effective-scenario contract and corresponding acceptance checks. The bridge rejects native modifications/events. It preserves the API's declared penalties and declared final-SOC policy (the integrated demo uses the initial-SOC floor); a native result that does not meet those declared API assumptions fails acceptance. See `docs/integration-status.md` before final integration.

For a direct custom canonical adapter, configure module:function paths whose signatures are `solve(scenario, options)` and `validate(scenario, solution, options)`, returning `solution.schema.json` and `validation.schema.json`. The default configuration uses the native bridge instead.

All dispatch maps must cover the exact scenario IDs. Generation, curtailment, flow, charge, discharge and shedding arrays have **N** entries. SOC has **N+1** entries: initial state followed by each post-step state. Renewable availability exists only for solar/wind. Non-renewable generation is bounded by rating. Line flow is signed `from → to`. Efficiency is symmetric square root of round-trip efficiency. Final SOC must meet the declared equal/at_least target; the integrated demo uses at_least initial SOC. Baseline disables battery dispatch; candidate enables it without changing physical ratings, demand, availability or SOC targets. Do not permit simultaneous charge/discharge. Monetary terms are assumed proxies.

`backend/audit.py` is an additional integration check, not a replacement for the independent production validator. Model changes (e.g. DC flow, minimum thermal output, reserves) must extend both contract and acceptance checks before they can be claimed as verified.

## Person 2: live agent

```python
# agent/__init__.py, or configure GRIDPILOT_AGENT_CALLABLE
async def run_investigation(scenario_id: str, settings: dict) -> dict: ...
```

Return `agent-result.schema.json`: baseline and candidate solutions, a tool trace, operator report, and `model_execution` with provider `google`, actual model ID and provider response ID. `backend.runtime.load_scenario(scenario_id)` and `inspect_evidence(scenario_id)` use the job's immutable input snapshots during execution. Use the configured backend solver/validator adapters (the default P3 bridge returns canonical outputs), rather than passing raw native solver envelopes into the agent result. Avoid calling the HTTP compute routes recursively because the outer investigation owns the compute slot.

The trace must include timestamped successful `load_scenario`, `inspect_evidence`, `run_optimisation`, `validate_candidate`, `compare_results`, and `generate_operator_report` calls. Include failed/retried calls as such. Summaries must omit secrets and raw prompts. Provider metadata must come from the actual API response, not be invented. The backend separately validates both outputs and recomputes numeric comparison; a model's `passed=true` claim has no authority.

The backend stores the agent's report under `operator_report.agent_commentary`. Its own canonical summary, source references and metrics are deterministic. There is no provider key in this branch, and no real Gemini run has been certified here.

## Runtime and state

One API process per SQLite journal. Each investigation and direct compute operation runs in a separate subprocess with a hard timeout. Queued requests snapshot scenario and evidence before execution. Restarted running jobs fail with `worker_interrupted`; submit a new key for a new run. Replay must match the exact scenario hash and settings. Polling currently shows queued/running state and the final complete tool trace; incremental streaming trace is not implemented.

Successful runs await one decision. Revision checking prevents stale or concurrent decisions from changing an approved simulation. Approval writes a simulation-only journal entry. No plant commands or real infrastructure actions exist.
