# GridPilot
### An AI copilot for renewable curtailment investigation and **verified** electricity-dispatch simulations

### Run the implemented backend

Python 3.13 is the tested runtime. No provider credentials are needed for the explicitly labelled offline replay.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m uvicorn backend.main:create_app --factory --host 127.0.0.1 --port 8000
```

Open [API documentation](http://127.0.0.1:8000/docs). In another terminal, run `python scripts/smoke.py` for two complete HTTP investigations with validation, simulated approval and report export. Use `python -m pytest -q` for the automated checks. This branch contains Person 4's backend/data/integration work; Person 3's production HiGHS solver and validator are integrated on this branch. The Gemini agent and dashboard remain separate team workstreams. Live agent calls fail explicitly until the real agent is installed.

Read [backend operations](backend/README.md), [the implemented v1 contract](contracts/README.md), [research and source findings](docs/task-4-research.md), [72 detailed subtasks](docs/task-4-work-breakdown.md), and [the release runbook](docs/release-runbook.md). Historical source evidence and synthetic simulation inputs are kept separate. A cached replay is never labelled as a live Gemini run.

**Encode London Hackathon · 24–25 October 2026 · Team of 4**

> **Mission:** Turn a real Chilean renewable-curtailment episode into an explainable, reproducible *what-if* study. Gemini investigates the evidence, calls a constrained optimisation model, checks the proposed solution and produces an operator-readable recommendation. A human approves any proposed action **inside a simulation**.
>
> **Scope / safety:** We do **not** operate Chile's grid, control power plants, replace its official dispatch, or claim that a toy network reproduces Chile's actual constraints. Results are valid only under the explicitly documented model assumptions.

## 1. Why this problem is real

Chile's **Coordinador Eléctrico Nacional (CEN)** coordinates the national electricity system. Its real-time dispatch is **not simply a person manually deciding which power plant runs**: scheduling and intraday co-optimisation already exist, alongside SCADA/AGC and human operational processes.

The CEN's **August 2026 automatic economic dispatch implementation plan** explicitly describes:
- Intraday reprogramming introduced in **2024**.
- Existing automatic-generation-control / economic-dispatch modules that **do not yet meet full SCED** (security-constrained economic dispatch) requirements.
- Some zero-variable-cost plant adjustment instructions still issued **by email** from the control centre as the CEN integrates plants into automatic control.
- A phased rollout of new SCED capabilities, with production targeted for **2029**, subject to testing.
- Operational barriers: transmission constraints, high shares of zero-marginal-cost renewables, storage integration, and imperfect real-time data.

In the August plan, **43.4%** of the 355-facility integration universe had passed signal-validation tests, and **38.3%** had passed setpoint reception/execution tests. These are **historical implementation progress figures**, not measurements of how much generation is manually dispatched today.

**Our opportunity is not “invent automatic dispatch.”** It is to help an energy analyst work through fragmented evidence, explore *model-based* interventions, discover constraint violations and explain trade-offs — with a real verification loop and clear human control.

**Primary user:** an electricity-system operations analyst or renewable-integration planner investigating curtailment / congestion. A secondary user is an energy researcher exploring alternative storage and network assumptions.

**One-sentence pitch:** *GridPilot turns real grid events into audited, constraint-checked counterfactuals — using an AI agent to investigate and explain, and mathematical optimisation to calculate.*

### Why Gemini / why an agent?

A static solver can optimise, but it does not independently gather an event's records, detect inconsistent inputs, choose an investigation plan, invoke tools, interpret constraint failures, retry sensible scenarios and assemble a traceable report. Gemini **4 Argon** is the lead orchestrator; **the solver, validator and metrics are deterministic software**.

A strong demo must show **real tool calls**, **at least one independently checked pass/fail signal**, clear sources and a deliverable report. Do not build a generic “chat with a PDF” wrapper.

## 2. The one demo we must ship

**Narrative:** Chile has a documented episode of solar/wind curtailment. The user picks that event; GridPilot inspects the associated data and analyses a *small, explicitly synthetic/representative grid* anchored to the historical demand/generation profile.

1. **Replay:** Load a selected date/time and show historical renewable-generation/curtailment evidence alongside the **illustrative network**, with visible “Observed” vs “Simulated” labels.
2. **Investigate:** Gemini reads the event metadata and available time series, flags the relevant bottleneck in the **model**, and chooses a battery/redispatch what-if experiment.
3. **Compute:** A time-coupled linear/mixed-integer optimisation model solves the original baseline and candidate over a **6–24 hour horizon**, with identical assumptions.
4. **Verify:** A **separate deterministic validator** checks nodal power balance, line limits, asset constraints, battery state of charge and all time steps. If invalid, Gemini must report why or revise its tool inputs. Never silently accept an infeasible solution.
5. **Explain:** Show side-by-side power flows, renewable curtailment, battery state-of-charge, operating-cost **proxy** and the binding constraint(s). Produce an exportable, source-linked decision note.
6. **Approve:** An operator clicks **Approve simulated plan** (or Reject); no real dispatch, plant commands or external infrastructure actions.

**Demo output:** “For this historically inspired scenario, the model-based alternative reduces simulated curtailment by X MWh over Y hours, subject to these constraints.” **Not:** “We saved Chile X dollars / prevented X tonnes of CO2.”

### Absolute MVP requirements

- One selected Chilean historical curtailment event **or** an explicitly labelled synthetic fallback if downloads fail.
- 4–6 synthetic nodes, ~2–4 generators, 1 battery, 3–7 lines, 6–24 time steps.
- Reproducible baseline and candidate dispatch using **the same** constraints and exogenous inputs.
- At least one constrained scenario in which dispatch/battery decisions matter.
- A genuine Gemini tool-use trace and a deterministic validation record.
- An interactive map/schematic, a working **Run investigation** button, comparison metrics, and an approval step.
- A reliable deployed demo, public repo, README, and a 3-minute video.

**Do not expand scope** to an accurate Chile-wide AC power flow, production dispatch, RL, autonomous grid control or a custom forecasting foundation model.

## 3. Four people, four parallel workstreams

**All four start immediately once the data contract in Section 4 is agreed.** Mock the other components; do not wait for teammates to finish.

### Person 1 — Frontend, visual design & interaction
**Owns:** everything in **frontend/**; nothing in the solver, agent or API implementation.

**Build:**
- A polished, dark, control-room-style dashboard with a **Chile-context map** and an **obviously schematic** network overlay. Use MapLibre for geography **only if appropriate**; React Flow/SVG is a reliable fallback for topology.
- Scenario/date selector and a narrative panel stating what is real versus illustrative.
- Animated power-flow lines (do not imply real SCADA streaming), node status, constrained line warnings and battery SOC curve.
- **Baseline / Optimised** toggle, metrics with units and a time scrubber.
- Visible agent activity timeline: tools called, status, citations, validation success/failure.
- Run, Approve **simulation**, Reject, and Export report controls; real working actions, not cosmetic buttons.
- Responsive layout and a hardcoded *fallback fixture* compatible with the contract.

**Stack suggestion:** React + Vite + Tailwind + Recharts + MapLibre/React Flow.

**Deliverable / definition of done:** frontend builds without warnings; rendering works against fixture JSON; swapping the API base URL enables real data without rewriting components; live demo takes <3 minutes.

**While working independently:** consume **contracts/** fixtures, mock GET /api/scenario and POST /api/agent/run, and never wait for Gemini.

### Person 2 — Gemini agent, tool orchestration & evaluation
**Owns:** **agent/**; deterministic reasoning workflow and a traceable recommendation, **not** numerical dispatch calculations.

**Build:**
- Integrate **gemini-4-argon** using the hackathon's official Gemini SDK / Interactions API.
- Agent tools: **load_scenario**, **inspect_evidence**, **run_optimisation**, **validate_candidate**, **compare_results**, **generate_operator_report**.
- A multi-step workflow that investigates evidence, proposes a *bounded* hypothesis (e.g., battery charging window), invokes the solver, checks validation results, optionally revises, and writes a concise recommendation with source references.
- Structured tool log with input/output summaries, timestamps, errors, retries and a clear terminal status.
- Human approval gate. Gemini must **never** execute an action on real industrial systems or present a recommendation as an implemented command.
- Handle missing data, optimiser infeasibility, failed tool calls, malformed responses and timeouts.
- An offline/mock tool adapter so the workflow can be developed and tested before Person 3 finishes.

**Important:** The model cannot invent MWh, USD, prices, safety guarantees or pass/fail labels. All metrics must come from computational tools. A successful model response **without** a verified solver result is a failed investigation.

**Deliverable / definition of done:** callable **agent.run_investigation(scenario_id, settings)** returns a structured final state, provenance-rich tool trace, validated metrics and report; at least one invalid/infeasible test case is handled properly.

**While working independently:** call mocked optimiser + validator tools that match Section 4. The backend owner later wires real implementations.

### Person 3 — Energy optimisation, simulation & numerical validation
**Owns:** **optimisation/**; robust, reproducible mathematical core, **not** the LLM.

**Build:**
- A small representative network with solar/wind, optional thermal generation, demand, line capacities and one battery. Use an **honest network-flow approximation** or properly specified **DC power-flow approximation**, and document which is implemented.
- Optimise over several hours: variable generator output, renewable curtailment, battery charging/discharging, inter-temporal SOC, line flows, and optionally load shedding (with a very large penalty).
- Fixed/common assumptions for baseline and optimised scenarios: same weather, demand, asset ratings, line constraints and initial SOC. Include a suitable final-SOC condition so energy cannot be “created” via end-of-horizon battery depletion.
- Objective: minimise an **explicit assumed** operating-cost / curtailment penalty, not claim it reproduces CEN's actual cost-based dispatch.
- Distinguish generator power [MW], energy [MWh], variable generation cost [USD/MWh], battery energy capacity [MWh], battery power [MW], efficiency [fraction] and time step [h].
- Add a **separate validation routine** rechecking balances, bounds, SOC progression and line flows within numeric tolerances. Avoid simultaneous battery charge and discharge (enforce or detect as appropriate).
- Produce deterministic tests: normal scenario, transmission congestion, insufficient generation, battery depleted, infeasible input and violated constraint.
- Return line flows, per-unit generation, curtailed energy, SOC, objective terms, residuals and reasons for infeasibility.

**Stack suggestion:** Python, SciPy/HiGHS or PuLP/HiGHS, NumPy, pytest.

**Deliverable / definition of done:** **solve(scenario, options)** and **validate(scenario, solution)**; tests pass; solver fails clearly on infeasible input; results are deterministic for a fixed fixture.

**While working independently:** use a synthetic sample scenario. Do not depend on live CEN data or the Gemini API.

### Person 4 — Historical data, FastAPI integration, deployment & submission
**Owns:** **data/**, **backend/**, **contracts/**, deployment and final release coordination.

**Build:**
- Identify and download **one historical renewable-curtailment event** from CEN; record source URL, publication/date, units, local timezone and every transformation.
- Connect available historical CEN generation/demand data where possible, and avoid falsely aligning different temporal resolutions or plant identifiers.
- Use official exports as fallback: the developer API documents endpoints but **requires account registration and credentials**; the demo must work without live credentials.
- Normalise to Section 4 JSON contract. Mark each field as **observed**, **derived** or **synthetic assumption**. Never mix up an observed curtailed-MWh figure with a simulation outcome.
- Expose FastAPI endpoints, wire the agent to optimiser/validator, serve saved demo fixtures when data/network/API calls fail, configure CORS and safe environment variables.
- Implement downloadable **JSON report** or simple formatted report with scenario provenance and validation summary.
- Own deployment, smoke tests, README demo setup updates, video recording, submission text and release branch.
- Be the **integration lead**: freeze contracts, enforce one working end-to-end path, and cut nonessential scope when the deadline threatens it.

**Deliverable / definition of done:** a stable public application; scenario and agent APIs work together; the same demo succeeds twice in a row; repository can be installed and reproduced.

**While working independently:** stub agent + optimiser endpoints against the contract; prepare source-labelled scenario fixture; deploy the skeleton first.

### Boundaries: who owns what?

| Component | Owner | Dependent on |
| --- | --- | --- |
| Frontend/dashboard | **1** | Contract fixtures initially; API later |
| Gemini orchestration / tools / report logic | **2** | Mock tools initially; real solver later |
| Dispatch simulation, solver & independent validator | **3** | Fixed synthetic scenario initially |
| Real-data provenance, FastAPI, API schema, integration, hosting, submission | **4** | Mocks initially; all modules later |

**Never have two people rewriting the same shared files simultaneously.** Contract changes go through Person 4 with agreement from all affected owners.

## 4. Integration contract — agree this BEFORE coding

**Single source of truth:** **contracts/** is owned by Person 4; everyone initially codes against these example schemas. Freeze field names, units, timestamps and meaning before branching.

### Endpoints

| HTTP | Route | Owner | Meaning |
| --- | --- | --- | --- |
| GET | /api/scenario | 4 | List or return the selected source-labelled scenario |
| POST | /api/optimise | 4 (route) / 3 (logic) | Run deterministic candidate optimisation |
| POST | /api/validate | 4 (route) / 3 (logic) | Independently verify a candidate |
| POST | /api/agent/run | 4 (route) / 2 (logic) | Execute full agent investigation |
| GET | /api/agent/runs/{run_id} | 4 + 2 | Poll status and tool trace if asynchronous |
| GET | /api/health | 4 | Readiness of backend and required services |

### Minimal scenario shape (illustrative contract, not a finished dataset)

~~~json
{
  "scenario_id": "chile-demo-001",
  "mode": "historically_anchored_simulation",
  "time_step_hours": 1,
  "timestamps_utc": ["2026-10-01T12:00:00Z", "2026-10-01T13:00:00Z"],
  "provenance": {
    "observed_source_urls": [],
    "observed_fields": [],
    "derived_fields": [],
    "synthetic_fields": ["network_topology", "line_limits", "battery_parameters"],
    "historical_event_date": null,
    "notes": "Sample only; no specific event verified yet."
  },
  "nodes": [{"id": "north", "label": "North (illustrative)"}, {"id": "south", "label": "South (illustrative)"}],
  "lines": [{"id": "L1", "from": "north", "to": "south", "capacity_mw": 100}],
  "generators": [{"id": "solar1", "node_id": "north", "technology": "solar", "capacity_mw": 150, "variable_cost_usd_per_mwh": 0}],
  "batteries": [{"id": "b1", "node_id": "north", "power_capacity_mw": 30, "energy_capacity_mwh": 90, "initial_soc_mwh": 10, "round_trip_efficiency": 0.9}],
  "demand_mw_by_node": {"north": [20, 20], "south": [80, 80]},
  "renewable_availability_mw_by_generator": {"solar1": [120, 110]}
}
~~~

**Note:** the sample is deliberately incomplete (e.g., no guaranteed feasible dispatch or final-SOC treatment). **Person 3 must create the first complete validated fixture**; Person 4 freezes its exact schema. The two sample timestamps are placeholders, not a claim about a historical event.

### Agent output envelope

~~~json
{
  "run_id": "run-001",
  "scenario_id": "chile-demo-001",
  "status": "completed",
  "provenance": {"mode": "historically_anchored_simulation"},
  "tool_trace": [
    {"tool": "load_scenario", "status": "success"},
    {"tool": "run_optimisation", "status": "success"},
    {"tool": "validate_candidate", "status": "success"}
  ],
  "baseline": {"valid": true, "metrics": {}},
  "candidate": {"valid": true, "metrics": {}},
  "comparison": {
    "curtailment_reduction_mwh": null,
    "assumed_cost_delta_usd": null
  },
  "validation": {"passed": true, "violations": [], "max_residual_mw": 0},
  "operator_report": {"summary": "", "sources": [], "assumptions": [], "limitations": []},
  "approval_status": "pending"
}
~~~

**Important:** the above values are **contract examples**, not computed results. Actual implementations **must not** return false success or empty placeholder metrics. Frontend uses mocks until genuine computation is integrated. On failure return **status = failed / infeasible**, error details, and **validation.passed = false**.

### Non-negotiable conventions

- **Times:** ISO 8601 in UTC internally; clearly display **Chile local time** with date/timezone context when appropriate.
- **Power vs energy:** MW vs MWh, multiplied by step duration.
- **Currency:** label any synthetic economic objective **“assumed-cost proxy”**, never actual CEN cost savings.
- **Topology:** schematic/synthetic unless a real CEN network model and constraints are actually used and documented.
- **Metric calculations:** in Python, never fabricated by Gemini or calculated from decorative UI values.
- **Data coverage:** explicitly surface missing fields, source gaps and outdated observations.
- **Security:** Gemini key only on backend; no secrets in Git or frontend; no real dispatch outputs/actions.

## 5. Proposed repository structure

~~~text
Encode/
├── README.md
├── contracts/
│   ├── scenario.example.json
│   └── run-result.example.json
├── frontend/                  # Person 1 — UI
├── agent/                     # Person 2 — Gemini orchestration
├── optimisation/              # Person 3 — mathematical solver & validator
├── backend/                   # Person 4 — API & integration
├── data/
│   ├── raw/                   # source files with provenance
│   ├── processed/
│   └── demo/                  # deterministic demo fixture
└── docs/
    └── demo-script.md
~~~

This is a **target structure**, not a claim that these directories already exist.

**Branches:** feature/frontend, feature/agent, feature/optimisation, feature/data-backend. Person 4 coordinates merging; open small PRs, integrate early and do not overwrite each other's shared code.

## 6. Timeline and integration checkpoints (London local time)

The **Encode submission deadline is Sunday 25 October 2026, 12:00 Europe/London**. The UK clock changes overnight — use local time on the event website.

| Checkpoint | Non-negotiable outcome |
| --- | --- |
| Saturday — first 15–20 min | Choose exactly one demo story, freeze contracts, create shared fixtures and four branches |
| Saturday — first ~3 hours | Frontend mock, agent mocked tool workflow, solver feasible scenario, backend routes all exist |
| Saturday evening | **First real end-to-end**: click → Gemini → optimiser → independent validator → UI |
| Saturday night | Harden that single path; source/provenance labels; deal with missing data and failures |
| Sunday 09:00 | **Feature freeze**: only tests, performance, video and presentation |
| Sunday 10:30 | Video and submission complete; allow buffer before 12:00 |
| Sunday 12:00 | Submission closes — do not rely on last-second uploads |

**Integration cadence:** check every 60–90 minutes, not “everyone merges at the end.” The first integration must happen with fake data if necessary.

### Definition of DONE

- [ ] Public web demo starts and renders scenario data
- [ ] Real historical input linked to CEN **or** explicitly labelled synthetic fallback
- [ ] Clicking Run triggers **live Gemini** and its tool calls
- [ ] Solver outputs a feasible result **or** correctly reports infeasibility
- [ ] Separate deterministic validator confirms/rejects each proposal
- [ ] Comparison of baseline and counterfactual is mathematically defensible
- [ ] Observed facts, assumed inputs and simulated outputs never appear as the same thing
- [ ] Human approval is implemented for simulated actions
- [ ] Trace/report includes source links, assumptions, limitations, units and verification details
- [ ] No API secrets committed
- [ ] App survives a failed API request and can rerun a deterministic cached demo
- [ ] Deployment tested twice, on a fresh browser
- [ ] 3-minute demo video, GitHub repo, README setup instructions and entry submitted

## 7. Demo presentation (3 minutes)

| Time | Visual | The point |
| --- | --- | --- |
| 0:00–0:25 | Historical Chile curtailment evidence; source and timestamp | **Real problem, named user** |
| 0:25–0:50 | Stylised grid and weather/demand profiles | **Clear scenario and limitations** |
| 0:50–1:40 | Press Run; visible Gemini tools, solver and validator | **Agent that does a job, not a chatbot** |
| 1:40–2:25 | Before/after grid, line flow and battery SOC; quantified verified metrics | **Deterministic, reproducible improvement under model assumptions** |
| 2:25–3:00 | Audit report and operator Approve/Reject | **Human control and useful output** |

**Strong differentiator:** intentionally show the agent detecting one invalid assumption or infeasible candidate and rejecting/revising it — *only if this genuinely executes in the demo*. No staged fake “verification.”

## 8. Data sources and research

**Primary / authoritative (Chile):**
1. [CEN, Plan de Trabajo para la Implementación y Operación de la Herramienta Automática de Despacho Económico (August 2026, PDF)](https://www.coordinador.cl/wp-content/uploads/2026/08/Plan_Trabajo_SCED_vf.pdf) — especially Sections 3–5; implementation timeline, partial automation, signal gaps, AGC/SCED constraints.
2. [CEN announcement, 1 September 2026](https://www.coordinador.cl/novedades/coordinador-define-plan-de-trabajo-para-implementar-despacho-de-centrales-de-generacion-de-manera-automatica/) — summary of planned SCED adoption.
3. [CEN — renewable generation reductions](https://www.coordinador.cl/operacion/documentos/reducciones-de-generacion-renovable/) — monthly solar/wind curtailment reports, including 2026.
4. [CEN — real generation and demand](https://www.coordinador.cl/operacion/graficos/operacion-real/) — historical generation, line flows and other views.
5. [CEN — programmed operation](https://www.coordinador.cl/operacion/graficos/operacion-programada/) — scheduled generation/demand.
6. [CEN — operational instructions (RIO, new)](https://www.coordinador.cl/operacion/documentos/registro-de-instrucciones-de-operacion-rio-sscc-energia/) — recorded instructions; downloads from 1 November 2023 onwards contain operational records; earlier entries are test data according to the portal.
7. [CEN — developer API](https://portal.api.coordinador.cl/documentacion?service=sipubv2) — documented endpoints such as generation-real, demand and line flow; **authentication/registration is required**; do not assume live anonymous API access.
8. [Decree 32/2026 / Article 117 bis](https://www.bcn.cl/leychile/Navegar?idNorma=1225248&idVersion=2026-06-17) — Chilean framework for automatic dispatch and safe fallbacks.

**Hackathon:** [Encode London 2026 — official rules, Gemini 4 Argon track and submission](https://www.encodeclub.com/programmes/encode-london-2026). For the Google DeepMind prize, judges emphasise a **3-minute live demo**, verification, named user, usefulness, originality and clear human control; submission requires a repo and a 3-minute demo video.

### Scientific honesty: avoid these three mistakes

1. **“Chile chooses electricity plants by hand” — inaccurate.** Chile already has automated scheduling/controls; SCED is a further step.
2. **“Our synthetic grid captures actual Chilean congestion” — not unless calibrated and validated against actual topology/constraints.** Historical observations can *motivate* a toy counterfactual without validating it as an actual Chilean dispatch recommendation.
3. **“The agent optimises the power grid” — misleading.** The **solver** optimises the mathematical model; the **agent** investigates, orchestrates, checks, explains and asks for approval.

## 9. Contingencies

- **CEN API unavailable / no key?** Download historical CSV/XLSX/PDF manually from published pages, cache inputs, document provenance. If unavailable, use a fully synthetic scenario with an honest label.
- **Solver takes too long?** Shrink to 4 nodes, 6 periods and one battery. Keep independent validation.
- **Gemini fails?** Show meaningful error and allow rerun; cached offline path is clearly labelled **mock/replay**, not a live agent execution.
- **Map takes too long?** Use a beautiful SVG/React Flow schematic rather than pretending to have real geographic network assets.
- **Impact absent?** Show the genuine outcome (possibly no feasible improvement) and explain binding constraints; never manufacture a positive delta.
- **Integration falling behind?** Person 4 cuts optional features; protect the verified end-to-end path and submission.

---

**Project philosophy:** **Real evidence. Explicit assumptions. Optimisation by code. Verification independent of AI. Human control. An exceptional three-minute demo.**
