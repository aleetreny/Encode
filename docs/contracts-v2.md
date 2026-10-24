# Native v2 contract — normal dispatch and crisis recovery

This implements the shared README at upstream commit `1756d68` and preserves the numerical schema in `optimisation/DESIGN.md`. The default fixture is `chile-sen-5node-demo`: five nodes, solar/wind and hydro/gas/coal/diesel, existing BESS, 24 hourly intervals, and explicit ramp/line constraints. All dispatch inputs remain synthetic. The CEN export is separate historical context, not a calibrated demand/generation profile.

## Endpoints

| Route | Request / result |
|---|---|
| `GET /api/scenario` | Default native scenario plus `modification_menu`; select another with `scenario_id` query |
| `GET /api/scenarios` | Catalog including current v2 and retained v1 fixtures |
| `POST /api/optimise` | `{scenario_id, candidate?, events?, options?}` → original native solution, `validation`, `accepted` |
| `POST /api/validate` | `{scenario_id, solution, candidate?, events?, options?}` → independent native checks plus backend acceptance |
| `POST /api/compare` | `{scenario_id, baseline, candidate}` → revalidated native comparison; crisis household impact when events exist |
| `POST /api/agent/run` | `{scenario_id, execution_mode, governance_mode, settings}` → 202 and run ID |
| `GET /api/agent/runs/{id}` | Full state, native normal results, crisis results, comparisons, trace and report |
| `POST /api/agent/runs/{id}/decision` | `{decision, operator, expected_revision, note?}` → one atomic simulation decision |
| `GET /api/agent/runs/{id}/report` | Download complete RIO-style simulation JSON, including native arrays and provenance |

Native solver status is `optimal`, `infeasible` or `error`. **Only `accepted=true` and `validation.passed=true` permit use as a verified plan.** An infeasible solve has null metrics, not invented zeros. Cost fields retain native meanings: `assumed_cost_delta_usd` is dispatch-only; `objective_delta_usd` also includes penalties, throughput and transmission tie-break. Investment costs are excluded.

## Interventions and crisis events

```json
{
  "scenario_id": "chile-sen-5node-demo",
  "candidate": {
    "candidate_id": "north_bess",
    "modifications": [{"type":"add_battery","node_id":"n_norte_grande","power_mw":150,"energy_mwh":600}]
  },
  "events": [{"type":"generator_outage","id":"gas_centro","from_hour":18,"to_hour":22,"mode":"sudden"}],
  "options": {"allow_unserved":true,"time_limit_s":20}
}
```

Candidate bounds come from the actual `modification_menu`: up to two modifications, allowed batteries or line uprates only. Outage intervals are step indices `[from_hour, to_hour)`, not arbitrary wall-clock strings. Both `generator_outage` and `line_outage`, planned and sudden, are accepted. Display timestamps in `America/Santiago`.

The validator checks the native effective scenario, modifications, event list, options, IDs, dimensions and metrics. The backend additionally verifies that all series have exactly the expected asset IDs and reproduces the plan before each sudden outage. Generator output, flows, curtailment, available power, charge/discharge, unserved load and the pre-event SOC must match the no-advance-knowledge plan. A physically feasible hindsight solution fails this additional check.

## Two-stage investigation settings

```json
{
  "scenario_id":"chile-sen-5node-demo",
  "execution_mode":"deterministic",
  "governance_mode":"autonomous_sced_with_audit_gate",
  "settings":{"allow_cached_fallback":true}
}
```

The default workflow computes/validates normal baseline, north BESS, south BESS and L2 uprate. It then actually attempts strict zero-shedding crisis dispatch, records the real infeasibility diagnostic when applicable, and compares baseline and all valid interventions during the sudden `gas_centro` trip at hours 18–22. The deterministic runner selects the largest verified crisis unserved-energy reduction, then normal curtailment reduction and objective as tie-breaks. Every result comes from the numerical module, not the README's illustrative numbers.

`settings.candidates` can supply up to four bounded alternatives. `settings.crisis_events` can supply up to two events. `settings.options` uses the native option names. Full investigations need `allow_unserved=true` for recovery; strict zero-shedding is an explicit separate stage. Use `/api/optimise` directly for other strict experiments.

Execution modes are distinct:

- `deterministic`: execute the whole software workflow now, with no Gemini claim.
- `replay`: load the exact matching cached bundle, verify scenario/settings hashes, rerun independent validation and comparisons, and report no live model execution.
- `live`: invoke the installed Person 2 agent and require actual Google model/response metadata and the complete timestamped tool trace. Numerical outputs are independently checked and crisis assessment is verified by the backend.

On provider error, missing agent or timeout, native live mode may use a **matching** cache when `allow_cached_fallback=true`. The completed record then says `execution_mode=replay`, `requested_execution_mode=live`, `provenance.live_gemini=false`, and includes the failure reason in `fallback`. Different candidates/events/options cannot silently reuse the default cache. Set the fallback option false to require live success.

## Household equivalence

The scenario stores `household_mapping.households_per_mw` and one residential share per node. The committed factor is 1,000 households/MW and all shares are 1, explicitly an uncalibrated residential-equivalent assumption, not a legal SEC conversion or actual customer population.

For each node/time: household-equivalents affected = unserved MW × residential share × households/MW. Household-hours are that value integrated over time. Event-window averages divide event household-hours by the union of outage durations; overlapping events are not counted twice. Whole-horizon household-hours remain separate. Unique households cannot be inferred from these aggregates and are returned as null.

After integrating numerical commit `c9306bb` and regenerating the cache, for the current northern BESS example, the native full-horizon reduction is 391.875 MWh. At the assumed factor it corresponds to 391,875 whole-horizon household-hours. Within hours 18–22 the net avoided quantity is 364,800 household-hours, or 91,200 average household-equivalents across those four hours. Using full-horizon energy divided by only four hours would mix scopes. The report supplies the actual per-step/node values so the UI need not invent a household count.

## Governance and regulatory report

`operator_approval` waits for a decision on the normal and crisis plans. `autonomous_sced_with_audit_gate` records verified normal dispatch as applied **inside the simulation**, while crisis recovery remains pending. A decision changes exactly the applicable simulation states and is protected by the current revision. No physical commands exist.

The canonical report is deterministic and RIO-style, not an official CEN record. References cover LGSE, DS 32/2026, NTSyCS and Ley 21.505. It states which mathematical checks passed and which requirements are not assessed: full legal compliance, AC voltages/reactive power, frequency/transients, full N-1 security, actual protection relays and distribution switching. `legal_compliance_status=not_certified` must remain visible. A passed toy-network validator cannot certify the whole regulatory framework or guarantee zero curtailment.

## Person 1 and Person 2 handoff

Person 1: use `contracts/native-client.ts`, `native-scenario.example.json`, `native-solution.example.json` and `native-run-result.example.json`. Render mode/fallback labels, validation, governance and household units directly from the API. Use `timeseries`/`metrics`/`binding_constraints` exactly as in the native numerical examples. Do not recompute numerical impact from decorative UI values.

Person 2: retain `run_investigation(scenario_id, settings)`. Call snapshot-aware `backend.runtime.load_scenario`, `inspect_evidence`, `run_optimisation(scenario_id, candidate, events, options)`, `validate_candidate(scenario_id, solution)` and `compare_results`. Avoid recursively calling HTTP compute routes from the worker. Return native normal `baseline` and `candidate`, optional `candidate_definition`, actual `model_execution={provider:'google', model, response_id}`, a timestamped successful six-tool trace, and your generated operator narrative. The backend verifies those arrays, records its actual crisis computations, produces canonical metrics and retains agent text as generated commentary. Provider IDs must come from the real API response.

V1 four-node fixtures and `contracts/client.ts` remain for compatibility when explicitly selected. They are not the current default demo. Use `native-*.schema.json` as the v2 schemas; the unprefixed v1 schemas remain versioned historical interfaces.

The live HTTP smoke explicitly disables cache fallback and rejects a different returned execution mode. Missing Gemini credentials prevent strict live execution from starting. Known locally derived provider response IDs from the current agent are rejected. Adapter metadata alone remains an attestation; verify actual Google requests and model-selected function calls before certifying the final live demo.
