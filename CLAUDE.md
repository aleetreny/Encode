# CLAUDE.md

Guidance for Claude (and humans) working in this repository.

## Project

**GridPilot** — Encode London Hackathon, 24–25 Oct 2026 (deadline Sun 25 Oct 12:00 Europe/London).
An AI copilot that turns a Chilean renewable-curtailment episode into an audited, constraint-checked
*what-if* study. Gemini investigates and explains; deterministic code optimises and validates; a human
approves the plan **in simulation only**. Full proposal: `README.md`.

## Ownership — Live Ops Integration Phase (`feature/live-ops`)

| Path | Owner | Notes |
|---|---|---|
| `frontend/src/ui/`, `frontend/src/styles/`, `/` route | Claude (Visual Designer) | Visual design consuming frozen `contracts/live.schema.json` & `frontend/src/live/` |
| `frontend/src/live/`, `/jurado`, `/dev`, `/explicar` | Antigravity (`alonsoquezadar`) | Live contract types, SSE client, store, offline replay, unstyled jury & dev pages |
| `agent/`, `optimisation/`, `backend/`, `data/`, `contracts/`, `scripts/` | Antigravity (`alonsoquezadar`) | Live Ops engine, Gemini 4 Argon loop, operational LP levers, independent validator, RIO report, deployment |

- Integration branch: `feature/live-ops` (merging `feature/data-backend`, `feature/agent`, `feature/frontend`, `feature/optimisation`).
- Never rewrite history or force-push on `feature/*`.
- Frozen live contract lives in `contracts/live.schema.json` and `frontend/src/live/types.ts`. Only optional additive fields are allowed after freeze, documented in `docs/live-contract-changelog.md`.

## Commit authorship

- **Antigravity (`alonsoquezadar`)**: Commits on `feature/live-ops` and `live-ops/*` use the repository owner's git identity (`alonsoquezadar <a.a.quezada@lse.ac.uk>`).
- **Historical `feature/optimisation` rule for Claude**: Commits Claude made directly for Bernardo on `feature/optimisation` used `Bernardo Guterres <bernardomloguterres@gmail.com>` with no AI attribution headers.

## Non-negotiable rules

- **Numbers come from code.** Every MW, MWh, USD and pass/fail comes from `optimisation/` (or data
  loading). Gemini never invents or computes metrics.
- **Observed vs synthetic vs simulated** must always be labelled and never mixed up.
- **Units:** MW = power, MWh = energy (MW × `time_step_hours`). Money is an *assumed-cost proxy*.
- **Times:** ISO 8601 UTC internally; display Chile local time (`America/Santiago`).
- **No real-world actions.** Approve/Reject only changes simulation state.
- **No secrets in git.** The Gemini key lives only in backend environment variables.
- Never return false success, placeholder metrics or a hidden failure; report `infeasible`/`error`.

## Optimisation module (Person 3)

Python ≥ 3.11, HiGHS via `highspy`, NumPy, pytest.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r optimisation/requirements.txt
pytest optimisation/tests -q              # full test suite
python -m optimisation.demo               # end-to-end demo run printed to the terminal
python -m optimisation.demo --write       # also refresh optimisation/examples/*.json
python -m optimisation.stress             # outage sweep: every asset, planned + sudden (must pass)
```

Before changing anything in `optimisation/`, read the developer guide (Part B) in
`optimisation/README.md`: invariants, how to extend, testing and the pre-push checklist.

Public API (`from optimisation import ...`):
- `solve(scenario, candidate=None, events=None, options=None)` → solution dict
- `validate(scenario, solution, options=None)` → validation dict (independent of the solver code)
- `compare(baseline, candidate, baseline_validation=None, candidate_validation=None)` → comparison dict
- `modification_menu(scenario)` → allowed candidate modifications and bounds (for the agent prompt)
- `load_scenario(path)` → scenario dict

Layout:
- `optimisation/scenario.py` — input checks, normalisation, candidate modifications, events
- `optimisation/model.py` — LP construction and HiGHS solve (incl. sudden-outage re-dispatch)
- `optimisation/validate.py` — independent validator (must never import `model.py`)
- `optimisation/compare.py` — deltas between two solutions
- `optimisation/stress.py` — outage sweep (planned maintenance and sudden crashes on every asset)
- `optimisation/README.md` — plain-language explanation + developer guide (start here)
- `optimisation/fixtures/` — synthetic demo scenario and its generator script
- `optimisation/examples/` — example outputs for Persons 1, 2, 4 to code against
- `optimisation/tests/` — pytest suite

Conventions: keep functions pure and JSON-in/JSON-out (no NumPy types in outputs); keep the problem
an LP (binaries only in the automatic charge/discharge exclusivity fallback); any change to inputs/outputs must be reflected in `optimisation/DESIGN.md` and the
example files in the same commit; run the full test suite before every push.
