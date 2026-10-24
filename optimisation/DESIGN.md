# GridPilot — Optimisation & Validation Design (Person 3)

Owner: Bernardo Guterres · Branch: `feature/optimisation` · Status: **agreed design, implemented in this package**

This document is the single reference for what the optimisation module does, what it accepts, what it
returns and how it is checked. Persons 2 (agent) and 4 (backend/contracts) should read sections 2, 4, 5 and 9.

---

## 1. Purpose and scope

The module is the **deterministic numerical core** of GridPilot. It:

1. Takes a source-labelled scenario (small synthetic grid anchored to Chilean profiles).
2. Optionally applies a **candidate**: a bounded asset modification chosen by the agent.
3. Optionally applies **events**: generator or line outages, planned or sudden.
4. Solves a multi-hour linear dispatch problem (HiGHS).
5. Independently **validates** any solution against the physics and the rules.
6. **Compares** two validated solutions and reports deltas and binding constraints.

It does **not**: call any LLM, access the network, read live CEN data, model AC power flow, model
sub-hourly dynamics (frequency, inertia, AGC), model unit commitment, or claim to reproduce CEN dispatch.

All numbers shown anywhere in GridPilot (MWh, MW, USD proxy) must come from this module.

---

## 2. Decision 1 — what "baseline" and "candidate" mean

**Asset what-if (option B).**

| | Grid | Dispatch |
|---|---|---|
| **Baseline** | Scenario as given (existing assets) | Optimal over the full horizon |
| **Candidate** | Scenario + 1–2 modifications from a fixed menu | Same optimiser, same inputs, same events |

Both sides use identical demand, renewable availability, costs, penalties, initial state of charge and
events. The **only** difference is the modification, so any delta is attributable to it.

Consequences:
- A candidate that only adds capacity can never have higher optimal objective than the baseline. For
  curtailment specifically, the objective does not reward it directly, so curtailment can rise slightly
  if that lowers cost; the comparison reports whatever really happens (never forced to look good).
- Investment cost of the modification is **not modelled**. Reports must say so.

### 2.1 Modification menu (what the agent may ask for)

A candidate:
```json
{"candidate_id": "c1",
 "modifications": [{"type": "add_battery", "node_id": "n_norte_grande", "power_mw": 100, "energy_mwh": 400}]}
```

| `type` | Fields | Bounds (default, overridable by `scenario.modification_limits`) |
|---|---|---|
| `add_battery` | `node_id`, `power_mw`, `energy_mwh` | `power_mw` 10–150; duration `energy_mwh/power_mw` 1–6 h; starts at 50 % SOC; charge/discharge efficiency 0.95 each; min SOC 0 |
| `uprate_line` | `line_id`, `new_capacity_mw` | strictly greater than current, ≤ 1.5 × current |

- At most **2** modifications per candidate; a line may be uprated at most once per candidate.
- Anything else (unknown type/node/line, out-of-range numbers, extra fields) → `status: "error"` with a
  precise message. The agent may correct and retry.
- Added batteries get ids `"{candidate_id}_bat{k}"` (k = 1, 2).
- The agent may **not** change demand, renewable availability, costs, penalties or existing assets.

---

## 3. Decision 2 — the network model

**Transport model on a loop-free (radial / forest) topology.**

On a network without loops, the line flows are fully determined by the nodal injections, so a transport
model gives **exactly** the same flows as a lossless DC power flow. We can therefore say
"DC-equivalent on a radial network" honestly without needing reactances.

- Scenario loading **rejects** any topology containing a loop (union–find check).
- Line flow sign: positive = from `from` to `to`.
- Losses on lines are ignored (lossless).
- `reactance_pu` on lines is reserved for a future meshed DC model and ignored today.
- A line outage splits the grid into islands; each island must balance by itself. The transport
  model handles this naturally (flow fixed to 0).

Demo topology: a 5-node north–south chain (Norte Grande → Norte Chico → Centro → Centro-Sur → Sur),
4 lines, labelled *illustrative*.

---

## 4. Scenario contract (input)

```jsonc
{
  "scenario_id": "chile-sen-5node-demo",
  "mode": "historically_anchored_simulation",      // or "synthetic"
  "time_step_hours": 1,
  "timestamps_utc": ["2026-10-01T03:00:00Z", "..."],   // length T, start of each step
  "display_timezone": "America/Santiago",
  "provenance": {
    "observed_source_urls": [], "observed_fields": [],
    "derived_fields": [], "synthetic_fields": ["network_topology", "..."],
    "historical_event_date": null, "notes": "..."
  },
  "nodes": [{"id": "n_centro", "label": "Centro (illustrative)", "lat": -33.4, "lon": -70.6}],
  "lines": [{"id": "L2", "from": "n_norte_chico", "to": "n_centro", "capacity_mw": 350}],
  "generators": [
    {"id": "solar_ng", "node_id": "n_norte_grande", "technology": "solar",
     "capacity_mw": 700, "variable_cost_usd_per_mwh": 0},
    {"id": "gas_centro", "node_id": "n_centro", "technology": "gas",
     "capacity_mw": 600, "variable_cost_usd_per_mwh": 90, "ramp_rate_mw_per_h": 250}
  ],
  "batteries": [
    {"id": "b_centro", "node_id": "n_centro", "power_capacity_mw": 30, "energy_capacity_mwh": 60,
     "min_soc_mwh": 0, "initial_soc_mwh": 30,          // optional "final_soc_mwh": exact end value
     "charge_efficiency": 0.95, "discharge_efficiency": 0.95}
  ],
  "demand_mw_by_node": {"n_centro": [ "... T values ..." ]},
  "renewable_availability_mw_by_generator": {"solar_ng": [ "... T values ..." ]},
  "objective": {
    "unserved_energy_penalty_usd_per_mwh": 10000,
    "curtailment_penalty_usd_per_mwh": 0,
    "battery_throughput_cost_usd_per_mwh": 0.5,
    "transmission_tiebreak_usd_per_mwh": 0.01
  },
  "modification_limits": { "...optional overrides of section 2.1..." },
  "events": [ "...optional, see section 6..." ]
}
```

Rules enforced at load time (violations → `status: "error"`):
- `T ≥ 1`; every time-series has exactly `T` finite values; `time_step_hours > 0`.
- `timestamps_utc` are timezone-aware ISO 8601 strings exactly `time_step_hours` apart.
- A generator whose `technology` is `solar` or `wind` must have an availability profile (otherwise it
  would silently run at full capacity day and night).
- All ids unique per type; every `node_id`/`from`/`to` exists; no self-loops; no topology loops.
- Generators **with** an entry in `renewable_availability_mw_by_generator` are *renewable*
  (curtailable; availability must be within `[0, capacity_mw]`). Generators without one are
  *dispatchable* (output in `[0, capacity_mw]`, optional `ramp_rate_mw_per_h`).
- Demands ≥ 0; capacities ≥ 0; efficiencies in `(0, 1]`; `min_soc ≤ initial_soc ≤ energy_capacity`.
- Missing `objective` block → defaults above. Missing node demand → treated as 0.

`round_trip_efficiency` (old README draft) is accepted only if both one-way efficiencies are absent, and
is split as `sqrt(rte)` each. Prefer the explicit fields.

---

## 5. Mathematical model

Indices: hours `t = 0..T-1`, step `Δt` h; nodes `n`; lines `l`; renewables `r`; dispatchables `d`;
batteries `b`.

**Variables** (all continuous, so the problem is an LP):

| Symbol | Meaning | Bounds |
|---|---|---|
| `p[g,t]` | generator output, MW | `0 ≤ p ≤ avail[g,t]` (renewable profile, or capacity; 0 during outage) |
| `ch[b,t]`, `dis[b,t]` | battery charge / discharge, MW | `[0, P_b]` |
| `soc[b,t]`, `t = 0..T` | state of charge, MWh | `[minSOC_b, E_b]`; `soc[b,0] = SOC0_b` |
| `f[l,t]` | line flow, MW | `[-cap_l, cap_l]` (0 during outage) |
| `u[n,t]` | unserved demand, MW | `[0, D[n,t]]` if `allow_unserved`, else 0 |

**Constraints**
- Nodal balance: `Σ_{g@n} p + Σ_{b@n}(dis − ch) + Σ_{l: to=n} f − Σ_{l: from=n} f + u[n,t] = D[n,t]`
- SOC dynamics: `soc[b,t+1] = soc[b,t] + η_c·ch[b,t]·Δt − dis[b,t]·Δt/η_d`
- End-of-horizon: `soc[b,T] ≥ SOC0_b` (no "free" energy from emptying the battery), or
  `soc[b,T] = final_soc_mwh` exactly when the scenario sets `final_soc_mwh` (the backend contract does)
- Ramp (dispatchables with a ramp rate): for each `t ≥ 1` where the unit is **online at t**:
  `|p[d,t] − p[d,t−1]| ≤ ramp_d·Δt`. The step *into* an outage is exempt (a trip drops output
  instantly); recovery after an outage ramps up from 0. Hour 0 is unconstrained.
- Emergency runback: in an hour `t ∈ runback_hours` (the start hour of a sudden event), the
  ramp-*down* limit becomes `p[d,t−1] − p[d,t] ≤ ramp_d·Δt + rb[d,t]` with a penalised slack
  `rb ≥ 0`; ramping up stays limited. See section 6.

**Objective** (minimise, USD — an *assumed-cost proxy*, not CEN cost):
```
Σ_t Δt · [ Σ_d c_d p[d,t]                                  thermal/dispatchable cost
         + VoLL · Σ_n u[n,t]                               unserved-energy penalty (10 000)
         + c_curt · Σ_r (avail[r,t] − p[r,t])              curtailment penalty (default 0)
         + c_thr · Σ_b (ch[b,t] + dis[b,t])                battery throughput cost (0.5)
         + c_tx · Σ_l |f[l,t]|                             transmission tie-break (0.01)
         + c_rb · Σ_d rb[d,t] ]                            emergency runback penalty (1 000)
```
`|f|` is modelled as `f = f⁺ − f⁻` with `f⁺, f⁻ ≥ 0` (still an LP).

**Why these numbers.**
- `c_curt = 0`: renewables already beat thermal on cost. With no reward for "not curtailing", the
  solver has no incentive to waste surplus through simultaneous charge/discharge losses.
- `c_thr = 0.5`: makes pointless cycling strictly worse and breaks ties, so the LP is safe without
  binary variables. The validator still flags any simultaneous charge/discharge.
- `VoLL = 10 000`: dominates every other term without numerical trouble.
- `c_tx = 0.01`: without it, unserved energy (equal penalty everywhere) can be "placed" at any node,
  e.g. shedding load in the north while exporting northern power south. A tiny cost on moving power
  makes the solver shed load where the deficit actually is and makes flows unique.
- `c_rb = 1 000`: above every fuel cost, so runback is never used to save fuel — only when nothing
  else can absorb surplus generation after a sudden event (otherwise a crash could look *cheaper*
  than planning for it; the outage sweep caught exactly that with a free runback).
- Thermal minimum output 0 and no on/off decisions keep the problem an LP (milliseconds to solve).

**Charge/discharge exclusivity.** The LP is solved first. If any battery charges and discharges in
the same hour (possible when objective weights reward it, e.g. a curtailment penalty with zero
throughput cost — exactly the backend's v1 settings), the problem is re-solved with one binary per
battery-hour (`ch ≤ P·z`, `dis ≤ P·(1−z)`), which forbids it exactly. `solver.method` reports
`"LP"` or `"MILP (battery charge/discharge exclusivity enforced)"`; for the demo it is plain LP.

**Solver:** HiGHS via `highspy` (pinned), single thread, deterministic. Problem size for the demo:
~5 nodes × 24 h → ~700 variables. Results are rounded to 1e-6.

---

## 6. Outages (events)

```json
"events": [
  {"type": "generator_outage", "id": "gas_centro", "from_hour": 18, "to_hour": 22, "mode": "sudden"},
  {"type": "line_outage",      "id": "L3",         "from_hour": 10, "to_hour": 12, "mode": "planned"}
]
```
- Hours are step indices; `from_hour` inclusive, `to_hour` exclusive; `0 ≤ from < to ≤ T`.
- Events may be in the scenario and/or passed to `solve(..., events=...)`; they are merged.
- **`planned`** — known from the start of the day: availability/capacity is 0 for those hours and the
  whole horizon is optimised with that knowledge (the battery may pre-charge).
- **`sudden`** — nobody knew in advance. Procedure (no hindsight):
  1. Solve the horizon **without** that event (the "plan"; planned events still apply).
  2. Fix every decision for hours `< from_hour` to the plan's values (incl. SOC at `from_hour`).
  3. Apply the outage and re-solve hours `≥ from_hour`.
  Multiple sudden events are processed in order of `from_hour`, each starting from the previous result.
- Redistribution happens automatically in cost order: previously curtailed renewables → battery →
  other dispatchables (within ramp limits) → imports over lines → finally unserved energy, which is
  **always reported** per node and hour, never hidden.

- **Emergency runback.** A sudden *line* outage can leave a plant on an island producing more than
  the island needs (e.g. L1 opening while `gas_ng` exports south). With only ramp limits that would
  be infeasible even in normal mode. Real grids trip or run back generators automatically (EDAG in
  Chile), so in the hour a sudden event starts, plants may drop faster than their ramp rate at the
  penalty `c_rb`. Reported as `metrics.emergency_runback_mwh`, objective term
  `emergency_runback_penalty_usd`, and binding constraint `emergency_runback`. Planned outages never
  need it (the plant is ramped down in advance).
- **Guarantee:** in normal mode (`allow_unserved: true`) every outage combination solves. Checked
  by `python -m optimisation.stress` (section 11).

Not modelled (state this in reports): sub-hourly dynamics after a trip, reserve holding, N-1 security.
A reserve requirement is a stretch goal (section 12).

---

## 7. `solve()` output

```jsonc
{
  "status": "optimal",                  // "optimal" | "infeasible" | "error"
  "message": null,                      // human-readable error / infeasibility reason
  "scenario_id": "chile-sen-5node-demo",
  "candidate_id": "baseline",           // or the candidate's id
  "modifications": [],
  "events": [],                         // events actually applied (merged, normalised)
  "options": {"allow_unserved": true},
  "time_step_hours": 1,
  "timestamps_utc": ["..."],
  "solver": {"name": "HiGHS", "version": "1.15.1", "method": "LP", "solve_time_s": 0.02, "solves": 1},
  "objective": {"total_usd": 0.0,
                "terms": {"dispatchable_cost_usd": 0.0, "unserved_penalty_usd": 0.0,
                          "curtailment_penalty_usd": 0.0, "battery_throughput_cost_usd": 0.0,
                          "transmission_tiebreak_usd": 0.0, "emergency_runback_penalty_usd": 0.0}},
  "assets": {"batteries": ["...effective batteries incl. added"], "lines": ["...effective capacities"]},
  "timeseries": {
    "generation_mw":         {"gen_id": ["T values"]},
    "available_mw":          {"gen_id": ["T values"]},
    "curtailment_mw":        {"renewable_id": ["T values"]},
    "battery_charge_mw":     {"bat_id": ["T values"]},
    "battery_discharge_mw":  {"bat_id": ["T values"]},
    "battery_soc_mwh":       {"bat_id": ["T+1 values"]},
    "line_flow_mw":          {"line_id": ["T values"]},
    "unserved_mw":           {"node_id": ["T values"]}
  },
  "metrics": {
    "curtailment_mwh": 0.0, "curtailment_mwh_by_generator": {},
    "unserved_mwh": 0.0,    "unserved_mwh_by_node": {},
    "renewable_used_mwh": 0.0, "dispatchable_mwh": 0.0,
    "demand_mwh": 0.0, "battery_charge_mwh": 0.0, "battery_discharge_mwh": 0.0,
    "battery_losses_mwh": 0.0,
    "assumed_cost_proxy_usd": 0.0,            // dispatchable cost only
    "emergency_runback_mwh": 0.0,             // see section 6
    "line_hours_at_limit": {"L2": 0}
  },
  "binding_constraints": [
    {"type": "line_limit", "id": "L2", "hours": [10, 11, 12], "detail": "flow at +350 MW limit"}
  ]
}
```
- `binding_constraints.type` ∈ `line_limit`, `battery_full`, `battery_empty`, `battery_power_limit`,
  `dispatchable_at_capacity`, `ramp_limit`, `emergency_runback`, `renewable_curtailed`,
  `unserved_energy`, `outage`.
- Errors/infeasibility return the same envelope with `timeseries`/`metrics` = `null` and a message.
  Infeasible messages name the hours/islands where demand exceeds the maximum possible supply.
- Everything is plain JSON (no NumPy types, no NaN).

---

## 8. `validate(scenario, solution, options=None)` — independent checker

The validator **does not import the solver**. It rebuilds the effective scenario (same input
normalisation in `scenario.py`, which is data handling, not physics) and re-checks every rule from
the raw numbers with NumPy:

| Check | Rule |
|---|---|
| `status` | solution must be `optimal` to pass |
| `shape` | every series has the right length and finite values; all assets present |
| `generator_bounds` | `0 ≤ p ≤ avail` (0 during outages) |
| `curtailment_consistency` | `curtailment = avail − p` for renewables |
| `battery_bounds` | `0 ≤ ch, dis ≤ P`, `minSOC ≤ soc ≤ E` |
| `soc_initial` / `soc_dynamics` / `soc_final` | initial value, recursion, `soc_T ≥ soc_0` (or `= final_soc_mwh`) |
| `simultaneous_charge_discharge` | `min(ch, dis) ≤ tol` |
| `line_limits` | `|f| ≤ cap` (0 during outage) |
| `nodal_balance` | per node and hour, residual ≤ tol |
| `unserved_bounds` | `0 ≤ u ≤ D`, and 0 if unserved not allowed |
| `ramp_limits` | same exemption rule as the model |
| `metrics_recomputed` | every reported metric and objective term matches recomputation |

Returns `{"passed", "checks_run", "violations": [{"check","id","hour","magnitude","detail"}],
"violation_count", "max_residual_mw"}` (at most 200 violations listed). If the caller passes the
`options` it gave `solve`, a solution solved with different options (e.g. unserved demand allowed when
strict mode was requested) fails `options_consistent`.

**Backward compatibility.** Output fields added after the first release (`emergency_runback_mwh`,
`emergency_runback_penalty_usd`) may be missing from solutions saved by older versions (e.g. the
backend's cached replay). A missing field is read as 0, so such a solution passes only if the
recomputed value really is 0; a solution that ran a plant back cannot hide it by omitting the field.
Any future output field must follow the same rule (add it to `ADDED_LATER` in `validate.py`). It also checks that every outage
defined in the scenario is present in the solution (`events_consistent`) and that the time axis matches. Tolerances: 1e-4 MW for flows/balances, 1e-3 MWh/USD-relative for metrics.

"No hindsight" for sudden outages (pre-event hours identical to the plan) is proven by tests.

---

## 9. `compare(baseline, candidate)`

Input: two `solve()` outputs (optionally with their validation results). Output:
```jsonc
{"comparable": true, "reason": null,
 "baseline_id": "baseline", "candidate_id": "c1", "modifications": [...],
 "both_valid": true,
 "metrics": {"curtailment_mwh": {"baseline": 0, "candidate": 0, "delta": 0}, "...": {}},
 "curtailment_reduction_mwh": 0, "unserved_reduction_mwh": 0, "assumed_cost_delta_usd": 0,
 "objective_delta_usd": 0, "line_hours_at_limit": {"L2": {"baseline": 8, "candidate": 8, "delta": 0}},
 "binding_constraints": {"baseline": [...], "candidate": [...]},
 "notes": ["Investment cost of modifications is not modelled.", "..."]}
```
Not comparable (with reason) if either is not optimal, scenarios/events/time axes differ, or a
validation result is provided and failed. Positive "reduction" means the candidate is better.

---

## 10. How it plugs into the system

```
Frontend (P1) ──POST /api/agent/run──► Backend (P4) ──run_investigation()──► Agent (P2, Gemini)
                                                                           │ tool calls
                                         optimisation (P3): solve / validate / compare / list_options
```

| Agent tool (P2) | Calls | Notes |
|---|---|---|
| `load_scenario` | P4 data loader | |
| `inspect_evidence` | P4 provenance summary | |
| `run_optimisation(candidate?, events?)` | `optimisation.solve` | |
| `validate_candidate(solution)` | `optimisation.validate` | must pass before any recommendation |
| `compare_results(a, b)` | `optimisation.compare` | the only source of deltas |
| *(helper)* | `optimisation.modification_menu(scenario)` | lists allowed nodes, lines and bounds for the prompt |

Backend routes: `POST /api/optimise {scenario_id|scenario, candidate?, events?, options?}` → `solve()`;
`POST /api/validate {scenario_id|scenario, solution}` → `validate()`.

Typical investigation: baseline → validate → read `binding_constraints` → try 2–4 candidates →
validate each → stress-test the best with a sudden outage → compare → report → human approval.

---

## 11. Tests (pytest, `optimisation/tests/`)

1. Demo scenario solves `optimal` and validates.
2. Congestion: a line is binding and there is curtailment in the baseline.
3. Candidate battery north of the bottleneck reduces curtailment; south battery helps less.
4. Adding assets never increases the optimal objective.
5. Battery depleted: initial SOC 0 → still feasible, SOC never negative.
6. Insufficient generation: strict mode → `infeasible` with reason; default mode → unserved reported.
7. Bad input: negative capacity, wrong lengths, unknown node, loop topology → `error`.
8. Bad candidate: out-of-range power/duration, unknown node, too many modifications → `error`.
9. Tampered solution: modify one flow / SOC / generation → validator fails with the right check.
10. Determinism: same input twice → identical output.
11. Energy conservation identity holds every hour.
12. Planned generator outage → output 0 in those hours.
13. Sudden outage → hours before the trip identical to the plan; unserved/cost reported after.
14. Line outage → islands balance separately; flow 0.
15. Ramp limits respected and reported as binding after a trip.
16. No simultaneous charge/discharge in solutions.
17. JSON round-trip of every output.
18. Randomised property test: random feasible radial scenarios → solve then validate passes.
19. Emergency runback after a sudden line trip that islands an exporting plant; none when planned.
20. Example files match the current code; options consistency; bad timestamps; solar without profile.
21. **Outage sweep** (`python -m optimisation.stress`; reduced version in the test suite): every
    generator and line × planned/sudden × 5 time windows × baseline and every candidate × normal and
    strict mode, plus combined maintenance-and-crash days (532 cases, ~2 000 solves). Checks: normal
    mode always `optimal` and validated; outaged asset at 0; no hindsight; planned ≤ sudden; losing an
    asset never lowers the objective; adding one never raises it (planned); strict mode is `optimal`
    with 0 unserved or `infeasible` with a reason, never `error`.

---

## 12. Milestones

| # | Deliverable | Unblocks |
|---|---|---|
| M0 | This design + example scenario + example output | P1, P2, P4 code against real field names |
| M1 | `solve`, `validate` on the demo scenario | P2 swaps mocks; P4 wires routes |
| M2 | Candidates, `compare`, binding constraints | First end-to-end run |
| M3 | Outages (planned + sudden), ramps | Stress-test demo moment |
| M4 | Full test suite, CLI demo, example outputs | Hardening |
| Stretch | Reserve requirement; meshed DC flow with reactances; CEN-shaped profiles from P4 | |

## 13. Honesty rules for this module

- Never return `optimal` for something that is not; never return placeholder numbers.
- Units: MW for power, MWh for energy (= MW × `time_step_hours`), USD labelled *assumed-cost proxy*.
- Topology and asset data are synthetic unless P4 documents otherwise in `provenance`.
- A delta of zero (or a worse result) is reported as is.

---

## 14. Implementation status and demo results

Implemented in this package (all milestones M0–M4; stretch goals not started). For a plain-language
explanation and the developer guide (architecture, invariants, how to extend, testing), see
[`README.md`](README.md).

```bash
pip install -r optimisation/requirements.txt
pytest optimisation/tests -q          # 114 tests
python -m optimisation.demo --write   # prints the table below and refreshes optimisation/examples/
python -m optimisation.stress         # full outage sweep, all checks must pass
```

Demo scenario (`fixtures/demo_scenario.json`, fully **synthetic**, built by
`fixtures/build_demo_scenario.py`): 5-node chain, 4 lines (L2 Norte Chico → Centro = 400 MW is the
bottleneck), 1 000 MW of northern solar, 200 MW northern wind, 200 MW southern wind, gas in the north
and centre, coal, hydro, diesel, and a small existing 30 MW / 60 MWh battery in the centre.

Results from `python -m optimisation.demo` (every row validated):

| Case | Curtailment MWh | Unserved MWh | Note |
|---|---|---|---|
| Baseline | 1 368.2 | 0 | L2 at its limit hours 9–16 |
| + 150 MW / 600 MWh battery, Norte Grande | 736.6 | 0 | −631.6 MWh curtailment |
| + same battery, Sur | 1 368.2 | 0 | 0 MWh reduction: wrong side of the bottleneck |
| + L2 uprated to 600 MW | 375.2 | 0 | −993 MWh curtailment |
| Baseline + sudden gas_centro trip 18–22 h | 1 368.2 | 1 921.9 | shed only at Centro |
| North battery + trip | 736.6 | 1 530.0 | −391.9 MWh unserved |
| South battery + trip | 1 368.2 | 1 678.9 | −243.1 MWh unserved |
| L2 uprate + trip | 375.2 | 1 921.9 | no help during the outage |
| Baseline + **planned** gas_centro maintenance 18–22 h | 1 368.2 | 1 921.9 | same as sudden: nothing to prepare |
| North battery + maintenance | 736.6 | 1 501.5 | −420.4 (vs −391.9 when sudden) |
| South battery + maintenance | 1 368.2 | 1 501.5 | −420.4 (vs −243.1 when sudden): pre-charges next to the deficit |
| L2 uprate + maintenance | 375.2 | 1 921.9 | no help |
| Baseline + sudden L1 trip 06–10 h | 1 570.4 | 0 | Norte Grande islanded; 19.5 MWh emergency runback of `gas_ng` |
| Strict mode + trip | — | — | `infeasible`, with the hours and shortfall named |

Example outputs for Persons 1, 2 and 4: `optimisation/examples/*.json`
(`solution_*.json`, `validation_*.json`, `comparison*.json`, `menu.json`).

### Integration with the backend (`feature/data-backend`, Person 4)

Verified on 24 Oct by running the backend's FastAPI app against this package: with the backend's
bridge passing `final_soc_mwh` through (one-line change in `backend/p3_adapter.py`), `/api/optimise`
and `/api/validate` return `optimal` and pass **both** this validator and the backend's own audit for
every bundled scenario and option set. The backend's v1 scenarios are a different, smaller fixed-asset
network (scenario id `chile-demo-001`); this package's 5-node demo is `chile-sen-5node-demo`.
Candidates and outages are not yet exposed through the backend contract.

**Update (24 Oct, evening).** The backend (`feature/data-backend`, commit `a089c47`) now exposes the
5-node native workflow (candidates, crisis events, no-hindsight checks). It vendors an older copy of
this package. Verified by overlaying the current `optimisation/` on that branch: the backend's full
test suite passes (after the backward-compatibility fix above), and `scripts/smoke.py` passes twice
in `replay` and twice in `deterministic` mode over HTTP, reproducing −631.6 MWh curtailment,
−74 229.8 USD and −391.9 MWh crisis unserved energy. To test future changes the same way:
`git worktree add ../integ origin/feature/data-backend`, copy `optimisation/` over it, install
`requirements-dev.txt` and `optimisation/requirements.txt`, run `pytest` and `scripts/smoke.py`.
