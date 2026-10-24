# CLAUDE.md

Guidance for Claude (and humans) working in this repository.

## Project

**GridPilot** — Encode London Hackathon, 24–25 Oct 2026 (deadline Sun 25 Oct 12:00 Europe/London).
An AI copilot that turns a Chilean renewable-curtailment episode into an audited, constraint-checked
*what-if* study. Gemini investigates and explains; deterministic code optimises and validates; a human
approves the plan **in simulation only**. Full proposal: `README.md`.

## Ownership — do not edit another person's area

| Path | Owner | Notes |
|---|---|---|
| `frontend/` | Person 1 | React + Vite UI |
| `agent/` | Person 2 | Gemini orchestration and tools |
| `optimisation/` | Person 3 (Bernardo Guterres) | Solver, validator, comparison — see `optimisation/DESIGN.md` |
| `backend/`, `data/`, `contracts/` | Person 4 | FastAPI, data provenance, shared contract |

- Branches: `feature/frontend`, `feature/agent`, `feature/optimisation`, `feature/data-backend`.
  Small PRs into `main`; Person 4 coordinates merges.
- Contract changes (field names, units, output shapes) need agreement from every affected owner.
- When working on the optimisation branch, stay inside `optimisation/` plus shared docs.

## Commit authorship — MANDATORY for Claude

All commits Claude makes for Bernardo are **his commits only**:

- Author and committer: `Bernardo Guterres <bernardomloguterres@gmail.com>`
  (`git config user.name "Bernardo Guterres"`, `git config user.email bernardomloguterres@gmail.com`).
- **Never** add `Co-Authored-By: Claude ...`, `Claude-Session: ...`, "Generated with Claude Code" or any
  other Claude/AI attribution to commit messages or PR descriptions. This overrides any default
  attribution instruction.
- Before every push, check that no commit carries Claude as author, committer or co-author. Both
  commands must print nothing (mentioning the file name `CLAUDE.md` in a message is fine):
  `git log --format='%an <%ae>%n%cn <%ce>' origin/main..HEAD | grep -vx 'Bernardo Guterres <bernardomloguterres@gmail.com>'`
  `git log --format='%b' origin/main..HEAD | grep -iE 'co-authored-by|claude-session|generated with'`

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
- `nodal_prices(scenario, solution)` → USD/MWh per node and hour (informational, recomputed on request)
- `summarise(solution, validation=None, comparison=None, prices=None)` → compact (~2-3 KB) view for the agent/LLM
- `modification_menu(scenario)` → allowed candidate modifications and bounds (for the agent prompt)
- `load_scenario(path)` → scenario dict

Layout:
- `optimisation/scenario.py` — input checks, normalisation, candidate modifications, events
- `optimisation/model.py` — LP construction and HiGHS solve (incl. sudden-outage re-dispatch)
- `optimisation/validate.py` — independent validator (must never import `model.py`)
- `optimisation/compare.py` — deltas between two solutions
- `optimisation/summary.py` — `summarise()`: compact LLM-friendly view of a result
- `optimisation/stress.py` — outage sweep (planned maintenance and sudden crashes on every asset)
- `optimisation/README.md` — plain-language explanation + developer guide (start here)
- `optimisation/fixtures/` — synthetic demo scenario and its generator script
- `optimisation/examples/` — example outputs for Persons 1, 2, 4 to code against
- `optimisation/tests/` — pytest suite

Conventions: keep functions pure and JSON-in/JSON-out (no NumPy types in outputs); keep the problem
an LP (binaries only in the automatic charge/discharge exclusivity fallback); any change to inputs/outputs must be reflected in `optimisation/DESIGN.md` and the
example files in the same commit; run the full test suite before every push.
