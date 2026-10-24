# GridPilot optimisation module

**Owner:** Bernardo Guterres (Person 3) · **Branch:** `feature/optimisation`

This folder is the **calculator** of GridPilot. Gemini decides *what to try*; this code works out
*what would happen* and checks that the answer is physically valid. Every number GridPilot shows
(MW, MWh, cost) comes from here — never from the AI.

- **New here?** Read this file.
- **Need exact formulas and field definitions?** See [`DESIGN.md`](DESIGN.md).

---

## 1. The problem in one picture

Chile has lots of solar in the north and most of its demand around Santiago. At midday the north
produces more than the transmission lines can carry south, so solar output gets thrown away
("curtailed"). In the evening the sun is gone and expensive gas and diesel plants run instead.

```
 Norte Grande ──L1── Norte Chico ──L2── Centro ──L3── Centro-Sur ──L4── Sur
  solar 700 MW        solar 300 MW    ▲    gas, diesel      coal          hydro, wind
  gas 350 MW          wind 200 MW     │    biggest demand
                                      └─ L2 (400 MW) is the bottleneck at midday
```

The module answers questions like:

- *How much solar is wasted today, and which line causes it?*
- *If we add a battery here, or upgrade that line, how much less is wasted?*
- *If a gas plant suddenly breaks at 18:00, can the rest of the grid cover it?*

The grid above is a **synthetic, illustrative** model shaped like Chile, not Chile's real network.

## 2. What it does, step by step

```
 scenario (grid + 24 h of demand and sun/wind)
      │
      ├─ + candidate?  e.g. "add a 150 MW battery at Norte Grande"   (chosen by the agent)
      ├─ + outages?    e.g. "gas_centro trips at 18:00"              (stress test)
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

## 4. Outages

| Kind | Meaning | How it is handled |
|---|---|---|
| `planned` | Known in advance (maintenance) | The whole day is planned around it |
| `sudden` | Nobody knew (a trip) | Hours before the trip stay exactly as originally planned; only the hours after are re-planned. No hindsight. |

Plants or lines can be taken out. After a trip, the grid covers the gap with spare renewables,
batteries, other plants (within ramp limits) and imports; whatever is still missing is reported as
unserved demand.

## 5. Results on the demo day

`python -m optimisation.demo` runs this whole story; every row passes validation:

| Case | Solar/wind wasted | Demand not served |
|---|---|---|
| Today's grid | 1,368 MWh | 0 |
| + battery north of the bottleneck | 737 MWh (−632) | 0 |
| + same battery south of the bottleneck | 1,368 MWh (**no change** — wrong side) | 0 |
| + bottleneck line upgraded 50 % | 375 MWh (−993) | 0 |
| Gas plant trips at 18:00 | 1,368 MWh | 1,922 MWh |
| … with the north battery | 737 MWh | 1,530 MWh (−392) |
| … with the south battery | 1,368 MWh | 1,679 MWh (−243) |
| … with the line upgrade | 375 MWh | 1,922 MWh (**no help**) |

The takeaway for the demo: the line upgrade is best on a normal day, the north battery is the only
option that helps on both a normal day and during the outage. That is a real trade-off the agent
can explain, and every number behind it is computed and checked.

## 6. How to run it

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r optimisation/requirements.txt
pytest optimisation/tests -q            # 110 tests, ~1 s
python -m optimisation.demo             # the story above
python -m optimisation.demo --write     # also regenerate examples/*.json
```

## 7. How teammates use it

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

trip = [{"type": "generator_outage", "id": "gas_centro", "from_hour": 18, "to_hour": 22, "mode": "sudden"}]
stressed = solve(scenario, events=trip)
```

All functions take and return plain JSON-style dicts and never raise on bad input: they return
`status: "error"` with a message instead.

| Teammate | What they need |
|---|---|
| **Person 2 (agent)** | Wrap `solve`, `validate`, `compare` as Gemini tools; put `modification_menu(scenario)` in the prompt; call `validate(scenario, solution, options)` with the same options given to `solve`; never recommend a candidate whose `validate()["passed"]` is false; quote numbers only from these outputs. |
| **Person 4 (backend)** | `POST /api/optimise` → `solve()`, `POST /api/validate` → `validate()`; scenarios use the format in `DESIGN.md` §4. |
| **Person 1 (frontend)** | Build charts from `examples/solution_*.json`: `timeseries` (hourly values), `metrics` (totals), `binding_constraints` (what to highlight in red). |

Example outputs for all of these live in [`examples/`](examples/).

## 8. Reading the output

| Field | Meaning |
|---|---|
| `status` | `optimal` (good), `infeasible` (demand can't be met in strict mode), `error` (bad input; see `message`) |
| `solver.method` | `LP` normally; `MILP (...)` if it had to forbid simultaneous battery charge/discharge |
| `metrics.curtailment_mwh` | Solar/wind energy available but not used |
| `metrics.unserved_mwh` | Demand that could not be supplied |
| `metrics.assumed_cost_proxy_usd` | Fuel cost of gas/coal/hydro/diesel under our assumed prices — **not real CEN costs** |
| `metrics.battery_losses_mwh` | Energy lost charging/discharging (kept separate so it never looks like "less curtailment") |
| `timeseries.*` | Hour-by-hour values per plant, battery, line and node |
| `binding_constraints` | Which limits were hit and when, e.g. "line L2 full, hours 9–16" — the *why* behind the result |

Hours are step indices 0–23; `timestamps_utc[i]` gives the UTC start time of hour `i`
(the demo day starts at 00:00 Chile time = 03:00 UTC).

## 9. What it does **not** do

- It is not Chile's real grid: topology, plants and prices are synthetic until Person 4 anchors the
  profiles to CEN data (`provenance` in the scenario says what is observed vs synthetic).
- No AC power flow and no loops in the network (on a loop-free network our model gives the same
  line flows as standard DC power flow).
- Hourly only: nothing about the first seconds after a trip (frequency, inertia).
- No reserve requirement, no on/off decisions for plants, no investment cost of batteries or lines.
- Hydro is treated like any other dispatchable plant: no daily water (energy) budget.
- It never controls anything real.

## 10. Files

| Path | What it is |
|---|---|
| `scenario.py` | Reads and checks the input; applies candidates and outages |
| `model.py` | Builds and solves the optimisation (HiGHS) |
| `validate.py` | Independent checker (deliberately does not import `model.py`) |
| `compare.py` | Baseline vs candidate differences |
| `demo.py` | The end-to-end demo story |
| `fixtures/` | Synthetic demo scenario and the script that generates it |
| `examples/` | Saved outputs for teammates to code against |
| `tests/` | 110 automated tests |
| `DESIGN.md` | Full technical specification |
