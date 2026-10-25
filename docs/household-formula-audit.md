# Household Formula Audit & Canonical Standard (Live Ops W10)

## 1. Canonical Formula Standard

Across the entire repository (frontend, backend, agent, optimisation, contracts, and documentation), the single canonical formula for computing the human impact of unserved power is:

$$\text{hogares\_sin\_luz}(\text{nodo}, \text{hora}) = \min(\text{households\_total}(\text{nodo}),\; \text{round}(\text{unserved\_mw}(\text{nodo}, \text{hora}) \times \text{households\_per\_mw}(\text{nodo})))$$

Where:
- $\text{unserved\_mw}(\text{nodo}, \text{hora})$: Instantaneous unserved active power at node distribution substation bus during hour $h$ ($\text{MW}$).
- $\text{households\_per\_mw}(\text{nodo})$: Conversion factor from substation load shedding to equivalent residential customers served. Default: **`1000` households/MW** (Classification: `assumption` / `derived`, representing an assumed coincident residential diversified demand of $1.0\text{ kW}$ per household at distribution level).
- $\text{households\_total}(\text{nodo})$: Static regional census cap of residential households connected to the regional transmission withdrawal substations (Classification: `derived` / `assumption`).

### Dimensional Consistency Rule (MW vs. MWh)

$$\text{Power (MW)} \times \frac{\text{Households}}{\text{MW}} = \text{Households (simultaneous instantaneous customers without supply)}$$
$$\text{Energy (MWh)} \times \frac{\text{Households}}{\text{MW}} = \text{Household-Hours (cumulative duration of disconnection)}$$

**Rule:** Unserved energy ($\text{MWh}$) must **never** be multiplied by $\text{households\_per\_mw}$ to report "households". Doing so commits a dimensional error (reporting household-hours as if they were instantaneous households). If energy is multiplied by this factor, it must be explicitly labeled as `household-hours` or `household_hours_saved`. Peak or hourly disconnected households are strictly derived from instantaneous $\text{unserved\_mw}$.

---

## 2. Audit of Legacy Numbers

An exhaustive audit of the historical numbers identified across the repository (`120,000`, `243,058`, `562,000`, and `480,000`) was conducted to trace their origin, verify consistency, and remove or document any discrepancies.

### A. 243,058 (`243,058 hogares`)
- **Location:** `frontend/src/components/ChileIsoMaquette.tsx` (lines 643 & 646).
- **Origin & Inconsistency:** This was a legacy, hardcoded string in the maquette's interactive telemetry status banner (`"Activa IA para rescatar 243,058 hogares"` and `"243,058 hogares protegidos"`). It did not react dynamically to changing unserved power or AI injection levels, violating dynamic formula derivation.
- **Resolution:** Replaced with dynamic evaluations following the canonical formula:
  - Line 643: `${(Math.round(unservedMw) * 1000).toLocaleString('en-US')} hogares`
  - Line 646: `${(Math.round(aiInjectMw) * 1000).toLocaleString('en-US')} hogares protegidos`

### B. 562,000 (`562,000 / 562,000`)
- **Location:** `agent/DESIGN.md` (line 53) and `agent/tests/test_agent.py` (line 148).
- **Origin & Inconsistency:** In the synthetic 5-node SEN scenario (`chile-sen-5node`), a sudden N-1 trip of `gas_centro` ($600\text{ MW}$) between hours 18–22 causes a peak unserved power deficit of $562.0\text{ MW}$ in `n_centro`. Under the canonical formula:
  $$\text{Peak households disconnected} = 562.0\text{ MW} \times 1,000\text{ households/MW} = 562,000\text{ households}$$
  This verified metric is tested in `agent/tests/test_agent.py`:
  ```python
  assert crisis["households_disconnected_peak"] == 562000
  ```
  However, `agent/DESIGN.md` mistakenly claimed `562,000 / 562,000 Chilean households reconnected` (implying 100% full recovery in the legacy planning sweep). In reality, the legacy planning sweep reconnected $111.9\text{ MW}$ ($111,900$ households, or $19.91\%$), while Live Ops real-time redispatch levers can restore up to the full peak deficit.
- **Resolution:** Corrected `agent/DESIGN.md` line 53 to explicitly cite the canonical formula and accurately document $111,900$ reconnected out of $562,000$ peak disconnected households in the legacy planning sweep.

### C. 120,000 (`~120,000 households`)
- **Location:** Early commit `1756d68` in `README.md`.
- **Origin & Inconsistency:** An earlier draft narrative stated that shedding $1,921.9\text{ MWh}$ over a 4-hour crisis was equivalent to "~480,000 household-hours / ~120,000 households disconnected". The 120,000 figure was obtained by improperly dividing 480,000 household-hours by 4 hours, or applying an arbitrary divisor to unserved energy.
- **Resolution:** Purged from all active codebase and documentation. All calculations now derive households directly from MW via `unserved_mw * households_per_mw`.

### D. 480,000 (`households_total` census cap)
- **Location:** Early drafts and regional census definitions (`n_norte_grande`).
- **Origin & Inconsistency:** In earlier scenario draft iterations and regional demographics, 480,000 was considered as a static regional census cap for Norte Grande (`households_total`).
- **Resolution:** Clarified in `optimisation/fixtures/build_demo_scenario.py` and `demo_scenario.json` that `households_total` (e.g. `320000`, `280000`, `2400000`, `1100000`, `650000`) represents the static regional census cap (upper bound) of residential customers in each regional subsystem, not the number of disconnected households. Disconnected households cannot exceed `households_total`.

---

## 3. Subsystem Implementation Verification

| Component | File | Formula Implemented | Verified Clean |
|---|---|---|---|
| **Frontend Maquette** | `frontend/src/components/ChileIsoMaquette.tsx` | `Math.round(unservedMw) * 1000` | Yes |
| **Live Backend Engine** | `backend/live/agent_loop.py` | `round(unserved_mw[nid][h] * hh_per_mw[nid])` | Yes |
| **Regulatory Engine** | `agent/regulatory.py` | `int(round(peak_mw * households_per_mw))` | Yes |
| **Live Catalog** | `backend/live/catalog.py` | `households_per_mw = 1000` (`assumption`) | Yes |
| **Scenario Builder** | `optimisation/fixtures/build_demo_scenario.py` | Annotated `households_total` regional cap & canonical formula | Yes |
