# GridPilot Agent Architecture (`agent/`) — Gemini 4 Argon (`gemini-4-argon`)

**Owner:** Person 2 (Agent Orchestration, Tooling, Crisis Self-Correction & Chilean Regulatory Audit)  
**Branch:** `feature/agent`

---

## 1. Mission & Neuro-Symbolic Separation of Powers

**GridPilot (`gemini-4-argon`)** emulates the operational decision loop of Chile's **Coordinador Eléctrico Nacional (CEN)** across the **Sistema Eléctrico Nacional (SEN)**:

1. **Normal SCED Co-Optimisation:** Minimises renewable curtailment (solar PV in *Norte Grande / Norte Chico* and wind in *Norte Chico / Sur*) and thermal dispatch cost across congested transmission corridors (`L1`, `L2`, `L3`, `L4`).
2. **Sudden N-1 Crisis Simulation & Household Reconnection:** Simulates unexpected power plant or transmission line failures (`mode="sudden"`, locking pre-outage dispatch and battery state of charge without hindsight), autonomously detects mathematical infeasibility under strict zero-shedding, activates **CNE NTSyCS EDAC** emergency load-shedding rules, and synthesises a new BESS + corridor dispatch plan to **reconnect affected Chilean households**.

### Strict Neuro-Symbolic Rule
- **Gemini 4 Argon (`gemini-4-argon`)** performs hypothesis formation, Modification Menu candidate selection, crisis scenario formulation, infeasibility self-correction, and regulatory synthesis.
- **Deterministic LP Solver (`scipy.optimize.linprog(method="highs")`) & Independent Validator** compute every MW, MWh, USD, SOC trajectory, and nodal balance check. The LLM never invents or approximates numerical dispatch outputs.

---

## 2. Public Entrypoints & Cross-Branch Contracts

### 2.1 Primary Backend Entrypoint (`Person 4` Contract)
```python
from agent import run_investigation

# Works both synchronously (`res = run_investigation(...)`) and asynchronously (`res = await run_investigation(...)`)
result = await run_investigation(
    scenario_id="chile-demo-001",
    settings={"battery_policy": "optimised", "allow_load_shedding": False},
)
```
Returns an `AwaitableDict` strictly conforming to `backend.models.AgentResult` (`ConfigDict(extra="forbid")`):
- `baseline`: Canonical `Solution` (`battery_policy="disabled"`, `native_result` included)
- `candidate`: Canonical `Solution` (`battery_policy="optimised"`, `native_result` included)
- `tool_trace`: `list[ToolEvent]` containing `"started"`, `"success"`, `"failed"`, and `"retry"` events across all 6 required tools (`load_scenario`, `inspect_evidence`, `run_optimisation`, `validate_candidate`, `compare_results`, `generate_operator_report`) with UTC ISO-8601 timestamps (`Z`), `execution_mode="live"`, `live_gemini=True`, and recursive secret redaction.
- `operator_report`: `OperatorReport` (`summary`, `sources`, `assumptions`, `limitations`) grounded in solver metrics and Chilean electricity law.
- `model_execution`: `ModelExecution(provider="google", model="gemini-4-argon", response_id=...)`.

### 2.2 Full Crisis & Household Reconnection Entrypoint (`Person 1 & 3` Extended Contract)
```python
from agent import run_crisis_investigation

dossier = run_crisis_investigation(
    scenario_id="chile-sen-5node",
    settings={"battery_policy": "optimised", "allow_load_shedding": False},
)
```
Returns the complete operational dossier:
- `agent_result`: Strict `AgentResult` payload
- `comparison`: Baseline vs. candidate MWh/USD deltas
- `candidate_sweeps`: Ranked Modification Menu interventions (`add_battery`, `uprate_line`, combined)
- `crisis_analysis`: Sudden N-1 contingency (`gas_centro` 600 MW outage at hours 18–22), self-correction trace, and nodal household disconnection/reconnection metrics computed via canonical formula `unserved_mw(node, hour) * households_per_mw` (`1,000 households/MW`, `assumption`, never multiplying MWh by households/MW; `111,900` reconnected out of `562,000` peak disconnected households in the legacy BESS+line sweep, i.e. `562.0 MW * 1,000 households/MW`)
- `regulatory_compliance`: Structured audit table against `LGSE Art. 72°-1`, `DS N° 32/2026 Art. 117 bis`, `CNE NTSyCS`, and `Ley N° 21.505`.

---

## 3. Module Layout

```text
agent/
├── __init__.py          # Public exports (run_investigation, run_crisis_investigation, GridPilotAgent)
├── orchestrator.py      # Neuro-symbolic SCED + N-1 sudden crisis & self-correction loop
├── tools.py             # 6 structured tools + ToolTraceRecorder + secret redaction
├── gemini_client.py     # Gemini 4 Argon REST / deterministic neuro-symbolic planner
├── solver_fallback.py   # HiGHS LP solver + sudden-outage locking + independent physics validator
├── regulatory.py        # Chilean electricity laws (LGSE, DS 32/2026, NTSyCS, Law 21.505) & household engine
├── demo.py              # CLI demonstration (`python3 -m agent.demo`)
├── DESIGN.md            # This architecture & contract reference
├── fixtures/            # Canonical 4-node (`chile-demo-001`) and 5-node SEN (`chile-sen-5node`) scenarios
└── tests/
    └── test_agent.py    # Comprehensive unit & cross-branch contract test suite
```
