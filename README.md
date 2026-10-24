# GridPilot
### An Autonomous AI Grid Coordinator for Chilean Renewable/Thermal Dispatch, Regulatory Compliance & Crisis Recovery Simulations

**Encode London Hackathon · 24–25 October 2026 · Team of 4**

> **Mission:** Emulate Chile's **Coordinador Eléctrico Nacional (CEN)** inside a verified digital-twin simulation. Powered by **Gemini 4 Argon** as the autonomous orchestrator and a deterministic **HiGHS LP solver + independent physics/regulatory validator**, GridPilot manages both **renewable** (solar, wind) and **non-renewable / dispatchable** (hydro, gas, coal, diesel, BESS) generation across Chile's north–south transmission backbone. It models selected requirements inspired by Chilean electricity regulation (**LGSE**, **Supreme Decree N° 32/2026 Art. 117 bis**, **NTSyCS**, and **Law N° 21.505**; see Section 2 for exactly what is and is not implemented), reduces renewable curtailment under normal operation, and **responds autonomously to sudden crisis scenarios** (such as a power plant or transmission line trip) by computing an emergency redispatch (batteries, ramp-limited thermal/hydro units, imports) to **reduce and restore unserved demand**.
>
> **Scope / safety:** We do **not** operate Chile's live physical grid, send real SCADA commands to power plants, replace official CEN/distributor control systems, or claim that a reduced 5-node backbone reproduces every bus of Chile's >1,000-node grid. All autonomous dispatches and crisis reconnections occur **strictly inside an audited simulation** under explicitly documented model assumptions.
>
> **Implementation status (24 Oct):** `optimisation/` (solver, validator, comparison, outages) is built, tested and verified against the backend bridge; `backend/`, `data/`, `contracts/` are on `feature/data-backend`; `agent/` and `frontend/` are in progress. The 5-node demo scenario is **synthetic**; CEN evidence is kept as separate, labelled context.

---

## 1. Why this problem is real (and why October 2026 is the inflection point)

Chile's **Coordinador Eléctrico Nacional (CEN)** operates the **Sistema Eléctrico Nacional (SEN)**, stretching over 3,100 km from Arica to Chiloé. Managing this grid involves two tightly coupled challenges:
1. **Structural North–South Congestion & Renewable Curtailment:** Massive solar and wind generation in the northern desert (*Norte Grande* and *Norte Chico*) must flow south toward the main residential and industrial load centres (*Centro / Santiago* and *Sur*). When transmission corridors saturate, zero-marginal-cost renewable energy is curtailed while thermal plants must run elsewhere.
2. **Sudden Contingencies & Household Disconnections (Crisis Recovery):** When a major thermal/hydro plant or a 500 kV corridor suddenly trips (**N-1 / N-2 contingency**), power flows redistribute instantaneously. Under Chile's **Norma Técnica de Seguridad y Calidad de Servicio (NTSyCS)**, if ramp rates and line thermal limits cannot absorb the deficit, **EDAC** (*Esquema de Desconexión Automática de Carga* — automatic load shedding) disconnects substation distribution feeders, leaving tens or hundreds of thousands of households without electricity until an emergency redispatch restores balance.

### The 2026 Regulatory Catalyst: Supreme Decree N° 32/2026 & SCED
Real-time dispatch in Chile already uses intraday scheduling and SCADA/AGC, but the CEN's **August 2026 Automatic Economic Dispatch (SCED) Implementation Plan** (mandated by **Supreme Decree N° 32/2026, Article 117 bis**) highlights critical operational gaps:
- Intraday reprogramming was introduced in **2024**, yet existing AGC/ED modules **do not yet meet full SCED** (*Security-Constrained Economic Dispatch*) requirements.
- Some zero-variable-cost plant adjustment instructions are still issued **by email** from the control centre while plants are progressively integrated into automated telemetry.
- As of August 2026, **43.4%** of the 355-facility integration universe had passed signal-validation tests, and **38.3%** had passed setpoint reception/execution tests, with full SCED production targeted for **2029**.
- Operational barriers include transmission bottlenecks, high shares of zero-marginal-cost renewables, battery storage (**SAE**) coordination, generator ramp limits, and rapid post-contingency redispatch.

**Our opportunity:** Build the **autonomous neuro-symbolic prototype of the SCED + Crisis Redispatch engine** envisioned by Chile's 2026 regulation — combining **Gemini 4 Argon** for real-time situational reasoning, hypothesis generation, and regulatory reporting with **deterministic mathematical optimisation and independent physics validation** to guarantee zero hallucinated megawatts.

**Primary user:** A CEN control-room operations engineer, system planner, or emergency coordinator evaluating automated dispatch and post-contingency household recovery plans.

**One-sentence pitch:** *GridPilot is an autonomous AI grid coordinator for Chile's SEN that optimises renewable and thermal dispatch under rules inspired by Chilean regulation and automatically re-routes power after sudden plant or line outages to reconnect affected households — verified at every step by deterministic physics.*

---

## 2. Chilean Regulatory Framework Mapped to Code

GridPilot does not treat regulation as decorative text: each row below names the **hard mathematical constraint or objective term** that represents it in the solver and validator, and what is deliberately **not** modelled. This is a simplified representation for a simulation, not a certified compliance check.

| Chilean Law / Standard | Legal Mandate in Chile | Deterministic Implementation in GridPilot |
| --- | --- | --- |
| **LGSE (DFL N° 4/2006, Art. 72°-1)**<br/>*Ley General de Servicios Eléctricos* | CEN must preserve overall system security while guaranteeing **minimum total operating cost** via **audited marginal-cost merit order** (generators do not submit free-market price bids; they declare audited fuel/variable costs). | Linear objective dispatches $0/MWh renewables (`solar`, `wind`) first, then lower-cost `hydro` / `coal` / `gas` ($25–$95/MWh in the demo), and the `diesel` peaker ($220/MWh in the demo) only when needed, all as an **assumed-cost proxy** (not audited CEN costs), with a dominant Value of Lost Load (`VoLL = $10,000/MWh`) penalising any unserved demand. |
| **Supreme Decree N° 32/2026 (Art. 117 bis)**<br/>*Automatic Economic Dispatch (SCED)* | Mandates automated security-constrained economic dispatch co-optimising generation, transmission limits, and dynamic unit capabilities within a 36-month rollout. | Closed-loop autonomous agent workflow (`agent/` + `optimisation/`) that computes nodal generation setpoints (`generation_mw`) and line flows (`line_flow_mw`) while enforcing line limits and unit-specific **maximum ramp rates (`ramp_rate_mw_per_h`)**. *Not modelled:* preventive N-1 security constraints and reserve requirements. |
| **NTSyCS (CNE)**<br/>*Norma Técnica de Seguridad y Calidad de Servicio* | Defines system states (*Normal, Alerta, Emergencia, Recuperación*), **N-1 contingency security**, line thermal ratings, generator ramp limits, and **EDAC** (automatic load shedding during deficits) followed by corrective redispatch to restore service. | **No-hindsight sudden outage solver (`mode: "sudden"`)**: locks pre-trip dispatch and battery SOC prior to the fault hour, applies the generator/line trip, enforces ramp limits on surviving thermal/hydro units, quantifies affected demand (`unserved_mw`, per node and hour), and computes the optimal recovery redispatch. *Not modelled:* NTSyCS system states, EDAC relay settings and sub-hourly frequency response. |
| **Law N° 21.505 (2022/2023)**<br/>*Storage (SAE) & Electromobility Law* | Integrates Battery Energy Storage Systems (**BESS / SAE**) into centralized CEN dispatch to absorb solar curtailment and provide fast-response contingency reserve. | Time-coupled battery dynamics (`battery_charge_mw`, `battery_discharge_mw`, `battery_soc_mwh`) with one-way efficiencies, minimum/maximum SOC bounds, and end-of-horizon conservation (`soc[T] >= soc[0]`) so batteries absorb northern solar peaks and bridge evening thermal outages. |
| **NTD / SEC Household Equivalence**<br/>*Distribution Substation Interface* | CEN coordinates transmission down to primary distribution substations (*barras de retiro*), from which distribution feeders serve residential households. | Nodal demand (`demand_mw_by_node`) and unserved energy (`unserved_mwh_by_node`) can be mapped to **equivalent affected households** using a per-node `households_per_mw` factor. **Status: planned (Person 4), not yet implemented in code**; the factor must be sourced and labelled as an assumption, and must exclude industrial/mining load, which is a large share of Chilean demand. |

---

## 3. The One Demo We Must Ship (Normal Dispatch + Crisis Recovery)

**Narrative:** GridPilot operates a 5-node Chilean backbone (`Norte Grande → Norte Chico → Centro → Centro-Sur → Sur`) anchored to Chilean generation technologies and demand profiles. The demo executes a **two-stage autonomous investigation**:

1. **Replay & Baseline Dispatch (Normal Operation):**
   - Load the Chilean scenario with visible **Observed** vs **Derived** vs **Synthetic** provenance labels.
   - Gemini inspects the grid and runs the baseline economic dispatch (`run_optimisation`). During midday solar peak (hours 9–16), corridor `L2 (Norte Chico → Centro)` saturates at its thermal limit, causing **1,368.2 MWh of northern solar curtailment**.
2. **Investigate & Optimise Curtailment (What-If Intervention):**
   - Gemini queries `modification_menu`, identifies the binding bottleneck (`L2` line limit), and tests bounded grid interventions (e.g., co-locating a utility-scale battery in `Norte Grande` vs `Sur`, or uprating `L2`).
   - Every candidate is checked by the **independent deterministic validator (`validate_candidate`)**. The `Sur` battery passes validation (it is physically valid) but `compare_results` shows it yields **0 MWh** curtailment reduction (wrong side of the bottleneck!), whereas placing a **150 MW / 600 MWh BESS in `Norte Grande`** cuts curtailment by **631.6 MWh** and uprating `L2` cuts it by **993.0 MWh**.
3. **Crisis Stress-Test (Sudden Plant Outage & Household Reconnection):**
   - Suddenly at **18:00 (evening peak)**, a major central thermal plant (`gas_centro`, 600 MW) suffers an unexpected forced outage (`generator_outage`, `mode: "sudden"`, hours 18–22).
   - **Without hindsight** (hours 0–17 remain locked to the pre-outage plan), the remaining coal, hydro and northern gas units are already at full output, the `diesel_centro` peaker maxes out, and `gas_centro`'s return at 22:00 is **ramp-limited (`ramp_limit`)**. Under the baseline grid, **1,921.9 MWh** of load is shed in `Centro` only, over hours 18–22 (peak 553 MW at 21:00) — the simulation's stand-in for EDAC load shedding.
   - Gemini evaluates recovery across the candidate configurations: the northern 150 MW / 600 MWh BESS **reduces unserved energy by 391.9 MWh** (and shortens the shedding window by one hour), the `Sur` battery by 243.1 MWh, and the `L2` uprate by 0 MWh — every number from `optimisation.compare`, every solution validated.
4. **Verify & Self-Correct:**
   - If Gemini proposes an invalid parameter or if strict zero-shedding mode (`allow_unserved: false`) is tested during the crisis, the solver/validator returns `infeasible` / `error` naming the exact hours and MW shortfall. Gemini reads the diagnostic and revises its operational plan rather than inventing numbers.
5. **Explain & Governance Gate:**
   - The UI shows side-by-side generation stacks (solar, wind, hydro, gas, coal, diesel, BESS), line flows, binding constraints, curtailment reduction, and **households protected/reconnected**, producing an exportable **RIO-style audit report** (format inspired by CEN's RIO log; not an official RIO submission) with an operator **Autonomous / Approve / Reject** control gate.

---

## 4. Four People, Four Parallel Workstreams

**All four workstreams run in parallel against the frozen contract in Section 5 and `optimisation/DESIGN.md`.** Never edit another person's directory without agreement.

### Person 1 — Frontend, Visual Design & Control-Room Interaction
**Owns:** everything in **`frontend/`** (`feature/frontend`); nothing in the solver, agent, or backend implementation.

**Build:**
- A dark, CEN control-room dashboard with a **Chile backbone map / schematic overlay** (`Norte Grande → Norte Chico → Centro → Centro-Sur → Sur`) showing real-time nodal generation mix (Solar, Wind, Hydro, Gas, Coal, Diesel, BESS), line loading percentages, and congestion/outage alerts.
- **Two operational views / modes:**
  1. **Normal SCED & Curtailment View:** Midday solar bottleneck on `L2`, battery SOC charging/discharging curves, and Baseline vs Candidate comparison.
  2. **Crisis Simulation & Household Reconnection View:** Interactive **"Trigger Sudden Outage (`gas_centro` / Line Trip)"** toggle or crisis replay showing the 18:00–22:00 plant trip, affected households in `Centro` (EDAC load shedding), emergency thermal/hydro ramping, and households reconnected by the autonomous recovery plan.
- Visible **Gemini 4 Argon Agent Timeline**: live tool calls, arguments, validator pass/fail badges, self-correction steps, and regulatory citations (*LGSE*, *DS 32/2026*, *NTSyCS*).
- **Governance & Audit Controls:** Run Autonomous Investigation, Approve Simulated Plan, Reject, and Export Regulatory Report (RIO format).
- Hardcoded fallback fixtures (from `optimisation/examples/*.json`) so the UI works offline instantly.

### Person 2 — Gemini 4 Argon Agent, Tool Orchestration & Regulatory Reasoning
**Owns:** everything in **`agent/`** (`feature/agent`); deterministic reasoning workflow, crisis stress-testing, and traceable regulatory report — **never** manual math calculation.

**Build:**
- Integrate **Gemini 4 Argon (`gemini-4-argon`)** with structured tool calling and deterministic fallback/mock adapters.
- **Agent tools:**
  - `load_scenario(scenario_id)` — loads scenario metadata, topology, and provenance.
  - `inspect_evidence(scenario_id)` — summarises demand peaks, renewable availability, thermal fleet ramp capabilities, and allowed interventions (`optimisation.modification_menu`).
  - `run_optimisation(scenario_id, candidate, events, options)` — calls `optimisation.solve` for baseline, candidate interventions, and **sudden crisis events (`generator_outage` / `line_outage` with `mode: "sudden"`)**.
  - `validate_candidate(scenario_id, solution)` — calls `optimisation.validate` to independently audit nodal balance, line limits, ramp limits, and battery SOC.
  - `compare_results(baseline, candidate, baseline_validation, candidate_validation)` — calls `optimisation.compare` to compute verified curtailment, cost-proxy, and unserved-energy (household reconnection) deltas.
  - `generate_operator_report(...)` — synthesises a source-linked **CEN / RIO-style decision note** citing Chilean regulation (*LGSE Art. 72°-1*, *DS 32/2026 Art. 117 bis*, *NTSyCS*, *Law 21.505*) and explicit model limitations.
- **Multi-step autonomous investigation loop:**
  1. Solve & validate baseline under normal conditions; identify binding constraints (`L2` congestion).
  2. Propose and test candidate modifications; demonstrate **self-correction** when a candidate is suboptimal, invalid, or rejected by strict crisis constraints (`allow_unserved: false` → `infeasible`).
  3. **Crisis Stress-Test:** Automatically subject baseline and winning candidates to a sudden generator trip (`gas_centro` outage hours 18–22), quantify household impact (`unserved_mwh` & equivalent households reconnected), and recommend the most resilient compliant plan.

### Person 3 — Energy Optimisation, Crisis Redispatch & Independent Validation
**Owns:** everything in **`optimisation/`** (`feature/optimisation`, Bernardo Guterres); the deterministic mathematical core (HiGHS via `highspy`, `NumPy`, `pytest`). **Status: M0–M4 implemented and verified with 123 passing tests and a 532-case outage sweep (planned maintenance and sudden crashes on every plant and line); integrated and verified end-to-end against Person 4's backend (full backend test suite and HTTP smoke test in replay and deterministic modes) (see `optimisation/README.md` for a plain-language guide and `optimisation/DESIGN.md` for the specification).**

**Built & Maintained:**
- **5-node Chilean radial backbone (`DC-equivalent transport model`)** with renewable (`solar`, `wind`) and dispatchable (`hydro`, `gas`, `coal`, `diesel`) generators, transmission lines (`L1`–`L4`), and batteries (`BESS`).
- **Multi-hour LP dispatch (`optimisation/model.py`):** Minimises an assumed dispatchable-cost proxy + Value of Lost Load (`VoLL = $10,000/MWh`) + small battery-throughput and transmission tie-breaks, subject to nodal balance, battery SOC dynamics (`soc[T] >= soc[0]`, or an exact `final_soc_mwh` when the scenario sets one), line thermal capacities, and generator **ramp rates (`ramp_rate_mw_per_h`)**. If any objective weights would make a battery charge and discharge in the same hour, it automatically re-solves with that forbidden exactly (MILP fallback).
- **Planned & Sudden Crisis Outages (`mode: "planned" | "sudden"`):** True **no-hindsight sudden-outage re-dispatch** (locks hours `< from_hour` to pre-trip plan, trips the generator or line, and re-solves hours `>= from_hour` subject to physical ramp limits and islanded balances), with a penalised **emergency runback** (cf. EDAG) when a line trip leaves an exporting plant islanded. Planned maintenance is optimised for the whole day in advance.
- **Independent Validator (`optimisation/validate.py`):** Never imports `model.py` (shares only input parsing); independently checks nodal balances, line limits, ramp rates, battery recursion, simultaneous charge/discharge, and recomputes all metrics within `1e-4 MW` tolerance.
- **Comparator & Menu (`optimisation/compare.py`, `modification_menu`):** Deterministic deltas for curtailment, cost proxy, unserved energy (`unserved_reduction_mwh`), and binding constraints.

### Person 4 — Chilean CEN Data Provenance, FastAPI Backend & Deployment
**Owns:** **`data/`**, **`backend/`**, **`contracts/`** (`feature/data-backend`), deployment, and final integration.

**Build:**
- Anchor scenario profiles and provenance to **official CEN sources** (*Infotécnica*, *Operación Real*, *Reducciones de Generación Renovable*, *RIO*, *Supreme Decree 32/2026*), clearly tagging every field as **`observed`**, **`derived`**, or **`synthetic`**.
- Provide the household equivalence mapping (`households_per_mw` / affected residential feeders per node) so `unserved_mwh_by_node` translates transparently into **affected and reconnected households**.
- Expose FastAPI endpoints (`/api/scenario`, `/api/optimise`, `/api/validate`, `/api/agent/run`, `/api/agent/runs/{run_id}`, `/api/health`) wiring Person 2's agent to Person 3's solver/validator.
- Serve deterministic cached fixtures from `optimisation/examples/` and `data/demo/` if live API calls fail or time out.
- Own deployment, CORS, environment security, end-to-end smoke testing, and the 3-minute submission video.

### Boundaries: Who Owns What?

| Component | Owner | Branch | Dependent On |
| --- | --- | --- | --- |
| Frontend control-room & crisis UI | **Person 1** | `feature/frontend` | `optimisation/examples/*.json` initially; FastAPI later |
| Gemini 4 Argon agent, tools & regulatory report | **Person 2** | `feature/agent` | `optimisation` package / mock adapter |
| LP dispatch, sudden-outage solver & validator | **Person 3** | `feature/optimisation` | Standalone (`highspy`, `numpy`, `pytest`) — **Ready** |
| CEN data provenance, FastAPI, contracts & hosting | **Person 4** | `feature/data-backend` | Connects P1, P2, and P3 |

---

## 5. Integration Contract (Aligned with `optimisation/DESIGN.md`)

**Single source of truth:** See `optimisation/DESIGN.md` and `optimisation/examples/*.json` for exact schemas.

### HTTP Endpoints (`backend/`)

| HTTP | Route | Owner | Meaning |
| --- | --- | --- | --- |
| `GET` | `/api/scenario` | P4 | Return the selected scenario (plus `modification_menu` bounds and provenance) |
| `POST` | `/api/optimise` | P4 (route) / P3 (logic) | Run `solve(scenario, candidate, events, options)` (normal or crisis outage) |
| `POST` | `/api/validate` | P4 (route) / P3 (logic) | Run `validate(scenario, solution)` independently |
| `POST` | `/api/agent/run` | P4 (route) / P2 (logic) | Execute full Gemini 4 Argon investigation (normal dispatch + crisis stress-test) |
| `GET` | `/api/agent/runs/{run_id}` | P4 + P2 | Poll status, tool trace, and final report |
| `GET` | `/api/health` | P4 | Readiness of backend, solver, and Gemini configuration |

### Agent Output Envelope (`agent.run_investigation`)

```json
{
  "run_id": "run-001",
  "scenario_id": "chile-sen-5node-demo",
  "status": "completed",
  "governance_mode": "autonomous_sced_with_audit_gate",
  "provenance": {
    "mode": "synthetic",
    "regulatory_framework": ["LGSE DFL 4/2006 Art. 72-1", "DS 32/2026 Art. 117 bis (SCED)", "NTSyCS (CNE)", "Ley 21.505 (SAE)"]
  },
  "tool_trace": [
    {"step": 1, "tool": "load_scenario", "status": "success"},
    {"step": 2, "tool": "inspect_evidence", "status": "success"},
    {"step": 3, "tool": "run_optimisation", "label": "baseline_normal", "status": "success"},
    {"step": 4, "tool": "validate_candidate", "label": "baseline_normal", "status": "success"},
    {"step": 5, "tool": "run_optimisation", "label": "candidate_north_bess", "status": "success"},
    {"step": 6, "tool": "validate_candidate", "label": "candidate_north_bess", "status": "success"},
    {"step": 7, "tool": "run_optimisation", "label": "crisis_sudden_outage_strict", "status": "infeasible_caught"},
    {"step": 8, "tool": "run_optimisation", "label": "crisis_sudden_outage_recovery", "status": "success"},
    {"step": 9, "tool": "validate_candidate", "label": "crisis_sudden_outage_recovery", "status": "success"},
    {"step": 10, "tool": "compare_results", "status": "success"},
    {"step": 11, "tool": "generate_operator_report", "status": "success"}
  ],
  "baseline": {},
  "candidate": {},
  "comparison": {
    "curtailment_reduction_mwh": 631.6,
    "assumed_cost_delta_usd": -74229.8
  },
  "crisis_analysis": {
    "event": {"type": "generator_outage", "id": "gas_centro", "from_hour": 18, "to_hour": 22, "mode": "sudden"},
    "baseline_unserved_mwh": 1921.9,
    "candidate_unserved_mwh": 1530.0,
    "unserved_reduction_mwh": 391.9,
    "estimated_households_reconnected": null
  },
  "validation": {"passed": true, "violations": [], "max_residual_mw": 0.0},
  "operator_report": {
    "summary": "",
    "regulatory_compliance": [],
    "crisis_recovery_plan": "",
    "sources": [],
    "assumptions": [],
    "limitations": []
  },
  "approval_status": "pending"
}
```

---

## 6. Real Chilean Data Sources & Regulatory References

1. **[CEN — Plan de Trabajo para la Implementación y Operación de la Herramienta Automática de Despacho Económico (SCED, August 2026 PDF)](https://www.coordinador.cl/wp-content/uploads/2026/08/Plan_Trabajo_SCED_vf.pdf)** — Sections 3–5 detail the 36-month transition to automated dispatch, current email instructions for zero-cost plants, and telemetry test rates (43.4% / 38.3%).
2. **[Supreme Decree N° 32/2026 / Article 117 bis (Biblioteca del Congreso Nacional)](https://www.bcn.cl/leychile/Navegar?idNorma=1225248&idVersion=2026-06-17)** — Legal mandate for automated economic dispatch (SCED) and safe operational fallbacks.
3. **[LGSE — DFL N° 4/2006 (Ley General de Servicios Eléctricos)](https://www.bcn.cl/leychile/Navegar?idNorma=258171)** — Art. 72°-1 establishing CEN coordination principles: security of service and minimum-cost audited marginal-cost dispatch.
4. **[CNE — Norma Técnica de Seguridad y Calidad de Servicio (NTSyCS)](https://www.cne.cl/normativas/electrica/normas-tecnicas/)** — Defines N-1 criterion, emergency states, ramp constraints, and EDAC automatic load-shedding schemes.
5. **[CEN — Infotécnica (`infotecnica.coordinador.cl`)](https://infotecnica.coordinador.cl/)** — Official technical registry of Chilean power plants (capacities, technologies), substations, and 500 kV / 220 kV transmission lines.
6. **[CEN — Reducciones de Generación Renovable](https://www.coordinador.cl/operacion/documentos/reducciones-de-generacion-renovable/)** — Historical solar and wind curtailment datasets.
7. **[CEN — Operación Real & SIPUB Developer API](https://portal.api.coordinador.cl/documentacion?service=sipubv2)** — Historical generation by technology, demand, and marginal costs.
8. **[CEN — Registro de Instrucciones de Operación (RIO)](https://www.coordinador.cl/operacion/documentos/registro-de-instrucciones-de-operacion-rio-sscc-energia/)** — Official log of real-time operational instructions, plant trips, and redispatches.

---

## 7. Critical Engineering Analysis: Limitations, Risks & Strengths

### A. Key Technical & Regulatory Limitations (and how we address them honestly)
1. **Transmission Backbone (CEN) vs. Street-Level Distribution (Distributors):**
   - *Limitation:* In Chile, the CEN coordinates generation and high-voltage transmission down to primary distribution substations (*barras de retiro*, e.g. *Polpaico* / *Alto Jahuel*). Low-voltage street feeders to individual homes are operated by distribution utilities (Enel, CGE, Chilquinta) with non-public topologies.
   - *Our solution:* We model the grid down to nodal distribution substations and express load shedding (`unserved_mw`) and reconnection in **substation feeder blocks and, once implemented, equivalent households (via a sourced, labelled `households_per_mw` assumption per node)** — matching how **EDAC** disconnects and restores residential demand in real CEN operations.
2. **Hourly/Multi-Step LP Transport Model vs. Sub-Second AC Electromechanical Transients:**
   - *Limitation:* In the first 0.1–5 seconds after a plant trip, grid survival depends on physical rotational inertia, primary frequency control (CPF), and automatic protection relays (50 Hz stability), not cloud LLM inference.
   - *Our solution:* We explicitly scope GridPilot to **SCED and Post-Contingency Corrective Redispatch (minutes to 24 hours)** — the exact window where human coordinators currently calculate redispatches and issue recovery instructions.
3. **5-Node Reduced Equivalent vs. Full >1,000-Bus SEN Model:**
   - *Limitation:* Solving a full AC-OPF over 1,000+ Chilean buses is incompatible with a fast, interactive 3-minute live demo.
   - *Our solution:* A 5-node radial north–south corridor (`Norte Grande → Norte Chico → Centro → Centro-Sur → Sur`) where line flows are mathematically **exact DC-equivalent flows** and every constraint is independently verifiable in milliseconds.

### B. Main Hackathon Risks & Mitigations
1. **Risk — LLM Hallucinating Megawatts or Violating Physics:**
   - *Mitigation:* Strict **Brain vs. Calculator separation**. Gemini 4 Argon never invents MW, MWh, USD, or validation status; every number is produced by `optimisation.solve` and audited by `optimisation.validate`.
2. **Risk — Framing "Autonomous / No Humans" as Unsafe for Critical Infrastructure:**
   - *Mitigation:* Implement **Verified Autonomy with a Regulatory Guardrail**. Normal SCED adjustments execute autonomously *only* after passing deterministic NTSyCS validation (`passed == true`), while crisis recovery plans produce a transparent RIO audit trail with an operator **Approve / Override** gate.
3. **Risk — External API Downtime (CEN API or Network Glitch During Demo):**
   - *Mitigation:* All scenarios (synthetic, with CEN evidence kept as separate labelled context) and pre-validated fallback runs are cached locally in the repo so the demo is 100% reproducible offline and online.

### C. Our Core Strengths
1. **Timely Regulatory Alignment:** Directly targets Chile's **August/September 2026 SCED Implementation Plan** and **Supreme Decree N° 32/2026 (Art. 117 bis)**.
2. **Tangible Human & Social Impact:** Connects abstract megawatt optimisation to **preventing blackouts and reconnecting tens of thousands of Chilean households** after a sudden power-plant crisis, while maximising clean energy.
3. **Genuine Self-Correcting Neuro-Symbolic Loop:** Demonstrates Gemini 4 Argon detecting an infeasible/suboptimal dispatch (e.g., wrong side of a transmission bottleneck or ramp-rate shortage during a sudden trip), interpreting the validator/solver diagnostics, and revising its strategy in real time.

---

## 8. Repository Structure & Timeline

```text
Encode/
├── README.md                  # Shared project narrative, regulatory map & team contract
├── CLAUDE.md                  # Repo conventions & ownership rules
├── contracts/                 # Shared JSON schemas (Person 4)
├── frontend/                  # Person 1 — Control-room & Crisis UI
├── agent/                     # Person 2 — Gemini 4 Argon orchestration & regulatory tools
├── optimisation/              # Person 3 — LP dispatch, sudden-outage solver & validator
│   ├── README.md              # Plain-language guide (start here)
│   ├── DESIGN.md              # Frozen mathematical & API specification
│   ├── model.py               # HiGHS LP solver (normal + no-hindsight sudden outages)
│   ├── validate.py            # Independent physics & regulatory validator
│   ├── compare.py             # Baseline vs candidate & crisis delta calculator
│   ├── summary.py             # Compact result summary for Gemini (+ nodal prices via model.py)
│   ├── stress.py              # Outage sweep: planned maintenance & sudden crashes on every asset
│   ├── fixtures/              # 5-node Chilean corridor scenario
│   ├── examples/              # Pre-computed validated JSON outputs for P1, P2, P4
│   └── tests/                 # 123 deterministic pytest tests
├── backend/                   # Person 4 — FastAPI routes & service integration
└── data/                      # Person 4 — CEN historical datasets & provenance
```

### Demo Presentation Storyboard (3 Minutes)

| Time | Visual | The Point |
| --- | --- | --- |
| **0:00–0:30** | Chile SEN context, August 2026 CEN SCED plan, and 5-node backbone | **Real regulatory mandate & clear scope** |
| **0:30–1:15** | Midday solar congestion on `L2`; Gemini tests candidates; comparison exposes the wrong-side battery (0 MWh) | **Autonomous reasoning + deterministic verification** |
| **1:15–2:15** | **CRISIS:** Sudden 600 MW `gas_centro` trip at 18:00; load shed in Centro; Gemini compares BESS / line-uprate recovery options | **High-stakes crisis simulation & household reconnection** |
| **2:15–3:00** | Quantified metrics (−631.6 MWh curtailment, −391.9 MWh unserved), RIO audit report & operator gate | **Regulatory compliance, human control & verified impact** |

---

**Project philosophy:** **Real Chilean regulation. Explicit assumptions. Optimisation by code. Verification independent of AI. Autonomous speed with human auditability. An exceptional three-minute demo.**
