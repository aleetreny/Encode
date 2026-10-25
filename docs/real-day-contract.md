# Real-day contract (`feature/real-day`)

Goal: the live demo runs on the shape of a real CEN day (14 Aug 2026), the Gemini monitor
comments on the grid every simulated hour and warns before something breaks, and jury attacks are
still resolved live by the existing decider. The synthetic day stays as a selectable fallback.

Deadline: Encode London submission, Sun 25 Oct 12:00 Europe/London. Anything not green by 11:30
does not replace the current demo.

## 1. Real-day scenario

- File: `optimisation/fixtures/real_day_scenario.json`, built by `scripts/build_real_day_scenario.py`
  (no network; reads only `data/processed/cen-sip/day-2026-08-14.json`, the SIP catalogue in
  `data/raw/cen-sip/centrales/` and `data/raw/cen-sip/demanda-real-estimada/2026-08-14/`).
- `scenario_id`: `chile-sen-5node-real-2026-08-14`. Same node, line, generator and battery ids and
  capacities as `demo_scenario.json`, so the jury cards, levers, incident library and maquette keep
  working. Only `timestamps_utc` (2026-08-14 local hours, as UTC), `demand_mw_by_node`,
  `renewable_availability_mw_by_generator`, `provenance` and a new top-level `day_profile` change.
- Method `scaled-observed-shape`:
  - System demand per hour = `gen_bruta_mwh − cons_propio_mwh` from SIP `demanda-neta`.
    Do not use `demanda_neta_mwh`: it already subtracts variable renewables
    (9153.7 − 3424.2 − 1414.0 = 4315.5 at hour 1).
  - Zone split per hour from `demanda-real-estimada` by bus when the bus→zone table
    `data/processed/cen-sip/bus-zone-2026-08-14.csv` exists and covers ≥ 99 % of the energy;
    otherwise the zone shares of the synthetic scenario (labelled `assumption`).
  - Solar and wind availability per generator = real capacity factor of that technology in that
    zone (`Σ mw / Σ pmax_mw` of the real plants mapped to the zone by catalogue `region`) × the
    scenario `capacity_mw`.
  - Demand is multiplied by one `scale_factor` so the real day fits the 5-node network.
    It is written to `day_profile.scale_factor`.
  - **Accepted deviations (orchestrator, 10:00):** the spec-literal build failed gates 2 and 3 at
    every scale. (a) System demand is the sum of |`medida_kwh`| over all buses of
    `demanda-real-estimada` (measured withdrawals): `gen_bruta − cons_propio` includes about 3 GW of
    storage charging at midday and put the Santiago peak at 11:00. Hour 00 is incomplete in the
    source and is rebuilt from hour 01. (b) Solar/wind keep the real hourly shape of each zone's
    capacity factor, but the amplitude is normalised so the daily peak equals `capacity_mw`; real
    winter peaks are about 0.6. Zone shares stay the synthetic ones (`assumption`) because the bus
    table covers 78.2 % of the energy. `scale_factor = 0.18`; gates 1 and 4 leave a window of
    about 0.17–0.19. The spec-literal build is kept behind
    `--demand-source gen-bruta --renewable-amplitude capacity-factor`.
- Region → zone: Arica y Parinacota, Tarapacá, Antofagasta → `n_norte_grande`; Atacama, Coquimbo →
  `n_norte_chico`; Valparaíso, Metropolitana, O'Higgins → `n_centro`; Maule, Ñuble, Biobío →
  `n_centro_sur`; La Araucanía, Los Ríos, Los Lagos, Aysén → `n_sur`. Magallanes is not in the SEN.
- `day_profile` (scenario and live `Catalog`, optional, additive):
  `{source: "CEN SIP", date: "2026-08-14", method: "scaled-observed-shape", scale_factor, label_es: "Día real CEN · 14-ago-2026 · perfil escalado"}`.
  The synthetic scenario reports `method: "synthetic"`.
- Provenance: demand and renewable shapes are `derived` from observed data; topology, line limits,
  capacities, costs, batteries and `households_per_mw` stay `synthetic`/`assumption`.
- Selection: env `GRIDPILOT_SCENARIO=real-day` | `synthetic`, resolved in
  `backend/live/catalog.py`; every live caller that today reads `FIXTURE_PATH` goes through it.
  The default stays `synthetic` until the orchestrator re-records `demo-stream.jsonl` and the
  incident library on the real day, then flips it to `real-day` in one commit. The native v2 API
  (`backend/main.py`, `native_models.py`) is out of scope.

### Gates (tested in `tests/test_real_day_scenario.py`)

1. Baseline solve is feasible with zero unserved energy in all 24 hours.
2. The north→centre corridor (L1 or L2) reaches ≥ 95 % of its limit in at least 2 hours between
   10:00 and 16:00, with solar curtailment > 0: the curtailment story survives.
3. `n_centro` demand peaks between 18:00 and 22:00.
4. Sudden outage of `gas_centro` at 18:00 and of `L3` at 19:00 each cause unserved energy without
   action, and the existing candidate sweep finds ≥ 2 validated options for each.
5. `validate()` passes on the baseline solution.

## 2. Gemini monitor (`agent.note`, optional additive fields)

- Cadence: one monitor note per simulated hour (`kind: "monitor"`), plus an immediate one when
  severity rises. Replaces the canned `generate_periodic_note_es` texts.
- `metrics` are computed by code from the current solution at the current hour; Gemini never
  computes numbers. `text_es` stays digit-free, as every prose field today.
- `severity`: `alert` if unserved > 0 or the solve is not optimal; `watch` if any line ≥ 90 %
  (a corridor saturated by the LP reads exactly 100 % and is congestion, not an alert), reserve
  margin < 10 %, or storage < 20 %; else `info`. `watch` lists the ids being watched.
- Wording by the fast model (`GRIDPILOT_MODEL_FAST`) with a 3 s timeout, at most one call in flight.
  The 1 Hz clock never waits for it. On timeout/error/no key the deterministic text is used and
  `model_execution` says so (`model: "deterministic-monitor"`, `status: "timeout" | "error" | "no_key"`).
  If the model answers after the clock crossed an hour, or fails, the note is worded by code from the
  grid as it is at emission (`status: "stale"` for a late answer). A note that falls due during a call
  sets a flag and the grid is read again when the call returns, so a queued alert is never downgraded.
- The UI labels it "Gemini · monitor"; the badge shows the real `model_execution.model`.

## 3. Ownership on this branch

| Task | Files | Model |
|---|---|---|
| Bus → zone table | `scripts/map_buses_to_zones.py`, `data/processed/cen-sip/bus-zone-2026-08-14.csv` | Haiku 5.5 |
| Real-day scenario + selection | `scripts/build_real_day_scenario.py`, `optimisation/fixtures/real_day_scenario.json`, `backend/live/catalog.py`, `tests/test_real_day_scenario.py` | Sonnet 5.5 high |
| Gemini monitor | new `backend/live/monitor.py`, `backend/live/engine.py` (note loop only), `agent_loop.py` (`generate_periodic_note_es` only), `tests/test_monitor.py` | Sonnet 5.5 xhigh |
| UI | `frontend/src/ui/`, `frontend/src/live/offline.ts`, `frontend/src/live/store.ts` | Sonnet 5.5 medium |
| Contract, merges, recording, verification | this file, `contracts/`, `frontend/src/live/types.ts`, recordings | Opus 5.5 (orchestrator) |

Nobody edits files outside their row. Run `python3 -m pytest -q -p no:cacheprovider` (238 passing
at `db2fe16`) before handing back.
