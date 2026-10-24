# GridPilot optimisation module

**Owner:** Bernardo Guterres (Person 3) · **Branch:** `feature/optimisation`

This folder is the **calculator** of GridPilot. Gemini decides *what to try*; this code works out
*what would happen* and checks that the answer is physically valid. Every number GridPilot shows
(MW, MWh, cost) comes from here — never from the AI.

| You want to… | Read |
|---|---|
| Understand what this module does | Part A (sections 1–9) |
| Use it from the agent, backend or frontend | Section 6 and [`examples/`](examples/) |
| Change or extend the code | **Part B — developer guide** (sections 10–17) |
| Look up an exact formula or field | [`DESIGN.md`](DESIGN.md) |

---

# Part A — what it is

## 1. The problem in one picture

Chile has lots of solar in the north and most of its demand around Santiago. At midday the north
produces more than the transmission lines can carry south, so solar output gets thrown away
("curtailed"). In the evening the sun is gone and expensive gas and diesel plants run instead.

```
 Norte Grande ──L1── Norte Chico ──L2── Centro ──L3── Centro-Sur ──L4── Sur
  solar 700 MW        solar 300 MW    ▲    gas 600, diesel  coal 350      hydro 200, wind 200
  gas 350 MW          wind 200 MW     │    biggest demand
                                      └─ L2 (400 MW) is the bottleneck at midday
```

The module answers questions like:

- *How much solar is wasted today, and which line causes it?*
- *If we add a battery here, or upgrade that line, how much less is wasted?*
- *If a plant or line is out for maintenance, or suddenly crashes, can the rest of the grid cover it?*

The grid above is a **synthetic, illustrative** model shaped like Chile, not Chile's real network.

## 2. What it does, step by step

```
 scenario (grid + 24 h of demand and sun/wind)
      │
      ├─ + candidate?  e.g. "add a 150 MW battery at Norte Grande"   (chosen by the agent)
      ├─ + outages?    e.g. "gas_centro crashes at 18:00"            (stress test)
      ▼
  solve()     finds the cheapest way to run every plant, battery and line, hour by hour
      ▼
  validate()  independently re-checks the answer (separate code, does not trust the solver)
      ▼
  compare()   baseline vs candidate: how much curtailment / unserved demand / cost changed
```

**Solving.** For each of the 24 hours, the solver decides how much each plant produces, how much
each battery charges or discharges, and how much power flows on each line. It picks the cheapest
plan that respects every rule:

- supply equals demand at every location, every hour
- no plant above its capacity; solar and wind no higher than the weather allows
- no line above its limit
- batteries stay between empty and full, lose about 10 % of the energy they store, never charge and
  discharge in the same hour, and must end the day at least as full as they started (so they can't
  "borrow" energy from tomorrow) — or exactly at `final_soc_mwh` if the scenario sets it
- gas, coal and hydro can only change output so fast (ramp limits)

If demand truly cannot be met, it says so: it reports **unserved demand** (where and when) or, in
strict mode, returns `infeasible` with the reason. It never hides a shortfall.

**Validating.** A second, separate piece of code takes the answer and re-checks every rule and every
reported number from scratch. If anything is off — a line over its limit, a battery that gained
energy from nowhere, a metric that doesn't add up — it fails, and says exactly what and when.

**Comparing.** Takes two validated answers that used identical assumptions and reports the
difference. It refuses to compare runs that aren't like-for-like.

## 3. What a "candidate" is

The agent can only propose changes from a fixed menu (`modification_menu()` lists it):

| Change | Allowed range |
|---|---|
| Add a battery at any node | 10–150 MW, storing 1–6 hours of energy |
| Raise a line's limit | up to +50 % |

At most two changes per candidate. Anything else is rejected with a clear error. The agent cannot
change demand, the weather, prices or existing plants.

The **baseline** is the grid as it is today, run optimally. The candidate runs the same optimiser on
the same day with only that change, so any difference is caused by the change itself.

## 4. Outages: planned maintenance and sudden crashes

Any plant (`generator_outage`) or line (`line_outage`) can be taken out for a window of hours.

| Mode | Real-world meaning | How it is solved |
|---|---|---|
| `planned` | Maintenance, known from the start of the day | The whole day is optimised knowing it: batteries can charge up beforehand, slow plants can ramp in advance |
| `sudden` | A crash nobody saw coming | 1) the day is planned as if nothing happens; 2) every hour **before** the crash is frozen to that plan (no hindsight); 3) the hours from the crash onward are re-planned without the asset |

What happens after an asset is lost, cheapest first: previously wasted solar/wind is used, batteries
discharge, other plants ramp up (within their ramp limits), power is imported over lines, and
whatever is still missing is reported as **unserved demand** at the node and hour where it occurs.

**Emergency runback.** When a line crashes, a plant can be left on an island producing more than
the island needs (e.g. L1 opening while Norte Grande's gas plant is exporting south). Real grids
then trip or run back generators automatically (in Chile, EDAG schemes). The model allows plants to
drop faster than their ramp limit **only in the hour a sudden event starts**, at a high penalty
(1 000 USD/MWh, more than any fuel cost) so it is used only when nothing else works. It is reported
as `metrics.emergency_runback_mwh` and as an `emergency_runback` binding constraint.

Every outage case is tested automatically: see section 15.

## 5. Results on the demo day

`python -m optimisation.demo` runs this whole story; every row passes validation:

| Case | Solar/wind wasted | Demand not served |
|---|---|---|
| Today's grid | 1,368 MWh | 0 |
| + battery north of the bottleneck | 737 MWh (−632) | 0 |
| + same battery south of the bottleneck | 1,368 MWh (**no change** — wrong side) | 0 |
| + bottleneck line upgraded 50 % | 375 MWh (−993) | 0 |
| **Sudden crash:** gas_centro trips at 18:00 (back at 22:00) | 1,368 MWh | 1,922 MWh |
| … with the north battery | 737 MWh | 1,530 MWh (−392) |
| … with the south battery | 1,368 MWh | 1,679 MWh (−243) |
| … with the line upgrade | 375 MWh | 1,922 MWh (**no help**) |
| **Planned maintenance:** same gas_centro outage, known in advance | 1,368 MWh | 1,922 MWh |
| … with the north battery | 737 MWh | 1,502 MWh (−420) |
| … with the south battery | 1,368 MWh | 1,502 MWh (−420) |
| … with the line upgrade | 375 MWh | 1,922 MWh (no help) |
| **Sudden line crash:** L1 opens 06:00–10:00, islanding Norte Grande | 1,570 MWh | 0 (19.5 MWh emergency runback) |

What the demo shows:

- The line upgrade is best on a normal day; the north battery is the only option that helps on a
  normal day **and** during a crash.
- Knowing about an outage in advance only helps if there is something to prepare: on today's grid
  planned and sudden give the same result (no storage to pre-charge, other plants already at full
  output), but with a battery, planning ahead reduces unserved demand further — most for the south
  battery (−420 vs −243 MWh), which can pre-charge right next to the deficit.

## 6. How teammates use it

```python
from optimisation import load_scenario, solve, validate, compare, modification_menu

scenario = load_scenario("optimisation/fixtures/demo_scenario.json")

base = solve(scenario)
base_check = validate(scenario, base)

cand = solve(scenario, {"candidate_id": "c1", "modifications": [
    {"type": "add_battery", "node_id": "n_norte_grande", "power_mw": 150, "energy_mwh": 600}]})
cand_check = validate(scenario, cand)

result = compare(base, cand, base_check, cand_check)
print(result["curtailment_reduction_mwh"])        # 631.578947

crash = [{"type": "generator_outage", "id": "gas_centro", "from_hour": 18, "to_hour": 22, "mode": "sudden"}]
maintenance = [{**crash[0], "mode": "planned"}]
stressed = solve(scenario, events=crash)
```

All functions take and return plain JSON-style dicts and never raise on bad input: they return
`status: "error"` with a message instead.

| Teammate | What they need |
|---|---|
| **Person 2 (agent)** | Wrap `solve`, `validate`, `compare` as Gemini tools; put `modification_menu(scenario)` in the prompt (it also lists which plants/lines can be taken out); call `validate(scenario, solution, options)` with the same options given to `solve`; never recommend a candidate whose `validate()["passed"]` is false; quote numbers only from these outputs. |
| **Person 4 (backend)** | `POST /api/optimise` → `solve()`, `POST /api/validate` → `validate()`; scenarios use the format in `DESIGN.md` §4. Pass `final_soc_mwh` through (do not strip it). |
| **Person 1 (frontend)** | Load results from `examples/index.json`: every option (`baseline`, `north_bess`, `south_bess`, `uprate_l2` — the same IDs and modifications as the backend's default candidates, so example files and live runs are interchangeable) in every situation (`normal`, `sudden_outage`, `planned_maintenance`) is a real, validated solution under `examples/cases/<situation>/<option>.solution.json`, with its validation and comparison next to it. Build charts from `timeseries` (hourly values), `metrics` (totals) and `binding_constraints` (what to highlight). **Never edit a solution or type a metric by hand** — if a case is missing, add it to `SITUATIONS`/`CANDIDATES` in `demo.py` and regenerate. |

## 7. Reading the output

| Field | Meaning |
|---|---|
| `status` | `optimal` (good), `infeasible` (demand can't be met in strict mode), `error` (bad input; see `message`) |
| `solver.method` | `LP` normally; `MILP (...)` if it had to forbid simultaneous battery charge/discharge |
| `solver.solves` | How many optimisations ran (a sudden event adds one) |
| `metrics.curtailment_mwh` | Solar/wind energy available but not used |
| `metrics.unserved_mwh` | Demand that could not be supplied (per node in `unserved_mwh_by_node`) |
| `metrics.assumed_cost_proxy_usd` | Fuel cost of gas/coal/hydro/diesel under our assumed prices — **not real CEN costs** |
| `metrics.battery_losses_mwh` | Energy lost charging/discharging (kept separate so it never looks like "less curtailment") |
| `metrics.emergency_runback_mwh` | Energy by which plants were cut faster than their ramp limit right after a crash |
| `timeseries.*` | Hour-by-hour values per plant, battery, line and node |
| `binding_constraints` | Which limits were hit and when, e.g. "line L2 full, hours 9–16" — the *why* behind the result |

Hours are step indices 0–23; `timestamps_utc[i]` gives the UTC start time of hour `i`
(the demo day starts at 00:00 Chile time = 03:00 UTC).

## 8. What it does **not** do

- It is not Chile's real grid: topology, plants and prices are synthetic until Person 4 anchors the
  profiles to CEN data (`provenance` in the scenario says what is observed vs synthetic).
- No AC power flow and no loops in the network (on a loop-free network our model gives the same
  line flows as standard DC power flow).
- Hourly only: nothing about the first seconds after a crash (frequency, inertia, protection relays).
- No reserve requirement or N-1 security constraints, no on/off decisions for plants, no
  investment cost of batteries or lines.
- Hydro is treated like any other dispatchable plant: no daily water (energy) budget.
- It never controls anything real.

## 9. How to run everything

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r optimisation/requirements.txt
pytest optimisation/tests -q            # 115 tests, ~5 s (includes a reduced outage sweep)
python -m optimisation.demo             # the story in section 5
python -m optimisation.demo --write     # also regenerate examples/*.json
python -m optimisation.stress           # full outage sweep: 532 cases, ~2 000 solves, ~20 s
```

Run commands from the repository root (the folder containing `optimisation/`).

---

# Part B — developer guide

For anyone who changes this code after the hackathon.

## 10. Files and responsibilities

| Path | What it is | Rule |
|---|---|---|
| `__init__.py` | Public API: `solve`, `validate`, `compare`, `modification_menu`, `load_scenario`, `ScenarioError` | Anything not exported here is internal |
| `scenario.py` | Reads and checks input; applies candidates and outage events; builds the `Grid` | Data handling only, no optimisation |
| `model.py` | Builds the LP, calls HiGHS, sudden-event re-dispatch, metrics, binding constraints | The only file that imports `highspy` |
| `validate.py` | Independent checker | **Must never import `model.py`** (a test enforces it) |
| `compare.py` | Baseline vs candidate deltas | Refuses unlike or invalid comparisons |
| `demo.py` | The end-to-end demo story; `--write` regenerates `examples/` | |
| `stress.py` | Outage sweep over every asset, mode and time window | Exit code 1 if any check fails |
| `fixtures/build_demo_scenario.py` | Generates `fixtures/demo_scenario.json` | Edit the script, never the JSON by hand |
| `examples/` | Saved outputs teammates code against; `index.json` lists every case; `cases/<situation>/<option>.{solution,validation,comparison}.json` | Regenerate, never edit by hand |
| `tests/test_optimisation.py` | All tests | |
| `DESIGN.md` | Specification: contract, formulation, outputs | Keep in sync with the code |

## 11. How a `solve()` call flows

```
solve(scenario, candidate, events, options)
 ├─ build_grid(...)                         scenario.py: validate everything, apply candidate,
 │                                          merge scenario + call events → Grid (numpy arrays)
 ├─ split events into planned / sudden
 ├─ _solve_grid(grid with planned events)   model.py: the "plan"
 │    ├─ _build_and_solve(exclusive=False)  LP
 │    └─ if a battery charges+discharges in one hour → _build_and_solve(exclusive=True)  MILP
 ├─ for each sudden event, in time order:
 │    └─ _solve_grid(grid + this event, pinned = previous result, pin_until = event hour)
 ├─ _timeseries → _metrics → _binding       outputs rounded to 1e-6, plain JSON
 └─ return the solution envelope (same shape on success, infeasible and error)
```

`validate(scenario, solution)` rebuilds the `Grid` from the scenario plus the candidate, events and
options **echoed in the solution**, then re-checks everything with NumPy.

## 12. The `Grid` object (`scenario.py`)

Everything downstream works on this normalised structure, never on the raw JSON:

| Field | Shape | Meaning |
|---|---|---|
| `T`, `dt` | — | number of steps, hours per step |
| `generators`, `batteries`, `lines` | lists of dicts | normalised assets (candidate additions included) |
| `demand` | (nodes, T) | MW |
| `avail` | (generators, T) | MW available; renewable profile or capacity; **0 during outages** |
| `gen_online` | (generators, T) | False during a generator outage |
| `line_cap` | (lines, T) | MW; **0 during line outages** |
| `runback_hours` | set | hours where a sudden event starts (emergency runback allowed) |
| `events`, `modifications`, `options`, `objective` | | normalised inputs, echoed into the output |

Outages are applied here by zeroing `avail` / `line_cap`, so the model and the validator need no
special outage code beyond ramp handling.

## 13. Invariants — do not break these

1. **Numbers come from here.** Never return placeholder or estimated metrics; on failure return
   `status: "infeasible"` or `"error"` with a `message`.
2. **The validator is independent.** It may import `scenario.py` (input handling) but never
   `model.py`. Every new constraint must be re-checked in `validate.py` from the raw numbers.
3. **Every reported metric and objective term is recomputed by the validator** (`_check_metrics`).
   Add a new metric in both places, or validation will fail.
4. **No hindsight.** In sudden mode, hours before the event must equal the plan exactly.
5. **Outputs are plain JSON** (no NumPy types, no NaN), deterministic, rounded to 1e-6.
6. **Normal mode always finds an answer** (unserved demand and emergency runback are the slacks).
   Only strict mode (`allow_unserved: false`) — or a scenario that fixes an unreachable
   `final_soc_mwh` — may return `infeasible`.
7. **Like-for-like comparisons only**: same scenario, time axis, events and options.
8. **Inputs, outputs and docs change together**: update `DESIGN.md`, regenerate `examples/`, and
   keep the tests green in the same commit.

## 14. How to extend it

**Add a constraint** (e.g. a daily hydro energy budget):
1. Add the input field and its checks in `build_grid` (`scenario.py`); document it in `DESIGN.md` §4.
2. Add the rows in `_build_and_solve` (`model.py`). Respect pinned hours (`bounds(...)` helper).
3. Re-check it in `validate.py` with a new named check, and add a tampering test that breaks it.
4. If it can be "hit", report it in `_binding`.
5. Run tests, demo and stress; regenerate examples.

**Add a new candidate modification type** (e.g. `add_solar`): extend `apply_candidate` and
`DEFAULT_LIMITS` in `scenario.py` (it rewrites a copy of the raw scenario, so model and validator
need no change), list it in `modification_menu`, add tests for valid and out-of-range values.

**Add a new event type** (e.g. a demand spike): extend `EVENT_TYPES` / `normalise_events` and the
loop at the end of `build_grid` that applies events to the arrays; add it to `stress.py`.

**Add a metric**: compute it in `_metrics` (`model.py`) **and** recompute it in
`_check_metrics` (`validate.py`); add a row to section 7 and `DESIGN.md` §7.

**Change the demo grid**: edit `fixtures/build_demo_scenario.py`, run
`python -m optimisation.fixtures.build_demo_scenario`, then `python -m optimisation.demo --write`,
and update the numbers in section 5, `DESIGN.md` §14 and the root `README.md`.

## 15. Testing strategy

| Layer | Where | What it proves |
|---|---|---|
| Unit / behaviour tests | `tests/` | each rule, each error message, each outage mode, compatibility with the backend |
| Tampering tests | `tests/` (`test_validator_catches_*`) | the validator really catches broken solutions |
| Random grids | `tests/` (`test_random_radial_scenarios_*`, 40 seeds) | solve → validate holds on arbitrary radial networks, time steps and outages |
| Example sync | `tests/` (`test_examples_match_current_code`) | `examples/` matches the current code on any platform (metrics, objective, verdicts) and every stored solution still validates |
| Outage sweep | `stress.py` (reduced version in `tests/`) | every generator and line, planned and sudden, 5 time windows, every candidate, normal and strict mode: solves, validates, outage respected, no hindsight, planned ≤ sudden, losing an asset never helps, adding one never hurts |

The outage sweep has already caught two real bugs (an islanded exporting plant made normal mode
infeasible; an unpenalised runback made crashes look cheaper than planning). Run it after any change
to `model.py`, `scenario.py` or `validate.py`.

## 16. Checklist before every push

```bash
pytest optimisation/tests -q
python -m optimisation.stress
python -m optimisation.demo --write   # then check `git diff optimisation/examples` is intended
# authorship rule (see the root CLAUDE.md): both commands must print nothing
git log --format='%an <%ae>%n%cn <%ce>' origin/main..HEAD | grep -vx 'Bernardo Guterres <bernardomloguterres@gmail.com>'
git log --format='%b' origin/main..HEAD | grep -iE 'co-authored-by|claude-session|generated with'
```

## 17. Known gotchas

- **Different machines, different (equally good) hourly schedules.** When several schedules are
  equally cheap, HiGHS can pick a different one on macOS ARM than on Linux (seen for `south_bess`
  in the sudden crash). Totals, cost and validation are identical. That is why
  `test_examples_match_current_code` compares examples *semantically*: metrics, objective, inputs
  and verdicts must match, every stored solution must validate, but hourly arrays and binding hours
  may differ. Regenerate examples on Linux (the CI platform) when outputs change.
- **Degenerate optima.** Many dispatches can be equally cheap. Small tie-break costs (battery
  throughput 0.5, transmission 0.01 USD/MWh) keep results unique and readable; removing them can
  make outputs change between runs or HiGHS versions. `highspy` is pinned in `requirements.txt`.
- **Curtailment penalties invite battery cycling.** If curtailment is penalised, wasting energy
  through battery losses becomes "optimal"; the MILP fallback forbids it. Don't remove the fallback.
- **Ramp limits and outages.** The step *into* a generator outage is exempt (a crash drops output
  instantly); recovery afterwards ramps up from 0; hour 0 is unconstrained.
- **Timestamps** must be timezone-aware ISO 8601, exactly `time_step_hours` apart.
- **Solar/wind without a profile** is rejected on purpose: otherwise it would run at night.
- **New output fields must stay backward compatible.** The backend replays solutions saved by older
  versions. If you add a metric or objective term, add its name to `ADDED_LATER` in `validate.py`
  (missing → read as 0) and add a test like `test_validator_accepts_older_solutions_without_runback_fields`.
  Run the backend's test suite against your change before pushing (see `optimisation/DESIGN.md` §14).
- **Scenario ids**: this module's demo is `chile-sen-5node-demo`; the backend's own small fixtures
  use `chile-demo-001` — they are different scenarios.
