# Backend operations

## Current five-node / crisis workflow

The upstream README update is implemented through native v2 endpoints. The default scenario is `chile-sen-5node-demo`; `GET /api/scenario` returns it with `modification_menu`. Native `POST /api/optimise` accepts `candidate`, `events` and `{allow_unserved, time_limit_s}` options and returns the original numerical envelope plus independent `validation` and `accepted`. `POST /api/compare` revalidates both results before comparing.

`python scripts/smoke.py` verifies normal intervention, strict-crisis infeasibility, valid recovery, two complete cached investigations, approval and export. `python scripts/smoke.py --mode deterministic` executes the whole two-stage solver workflow afresh without an LLM. Live mode requires actual provider execution metadata; provider failure can use the matching cached run only with explicit `execution_mode=replay`, `requested_execution_mode=live` and `fallback` fields. Set `settings.allow_cached_fallback=false` to prohibit this behavior.

Normal dispatch can be applied inside the simulation under `autonomous_sced_with_audit_gate`; crisis recovery always awaits the operator decision. Approval updates both the journal and governance state. Household equivalents are derived from per-step unserved MW and a clearly synthetic mapping, with event-window and whole-horizon household-hours kept separate. The RIO-style report records model checks and unassessed legal/security requirements; it is not an official CEN instruction or compliance certificate.

Use [the v2 handoff](../docs/contracts-v2.md) and `contracts/native-client.ts`. The earlier fixed-asset fixtures remain supported only for compatibility. Native replay fixtures are rebuilt with `python scripts/build_crisis_demo.py` and verified by `tests/test_native.py`.

## Install and run

Use Python 3.13 for the pinned environment. From the repository root:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m uvicorn backend.main:create_app --factory --host 127.0.0.1 --port 8000
```

For API runtime only, install `requirements.txt`. Spreadsheet parsing is a development/data-preparation dependency, not required to serve the saved demo. Uvicorn uses the application factory. Do not start `backend.main:app` or add multiple workers.

The server listens locally on port 8000. Interactive endpoints are at `/docs`. Full integration instructions are in `contracts/README.md`. The service does not provide the dashboard assigned to Person 1.

```bash
python -m pytest -q
python scripts/export_contracts.py --check
python scripts/prepare_data.py
python scripts/smoke.py
```

The last command requires the server running. It executes two real HTTP investigations, checks idempotency, verifies results, records a simulation-only approval and downloads the JSON report. `--mode live` is reserved for the installed agent/solver/validator with actual provider credentials.

## Data preparation

`scripts/prepare_data.py` extracts the committed original XLSX using read-only openpyxl. It requires no network. It verifies the raw-file checksum, retains original plant IDs and missing observations, records source cell ranges and exports the evidence and quality controls.

`python scripts/prepare_data.py --download` explicitly refreshes the same official source, validates the candidate before replacing the raw bytes and updates retrieval metadata. Review source changes and all anomalies before committing. Do not substitute missing observations with zeros.

`python scripts/build_demo.py` rebuilds two offline scenarios and their cached outputs using Person 3's integrated production HiGHS solver and independent validator in `optimisation/`. Minor alternate optimal dispatches may vary by solver version; the committed outputs are acceptance-tested with tolerances and served unchanged. Run `scripts/export_contracts.py` after intentional fixture or model changes.

## Environment

Copy `.env.example` for local configuration. Uvicorn does not automatically load it. Export variables in the shell, or supply them through your process manager. Do not commit populated files. The Compose file reads the root `.env` for its explicit variable interpolation.

| Variable | Meaning |
|---|---|
| `GRIDPILOT_DB_PATH` | SQLite journal; default `var/runs.sqlite3` |
| `GRIDPILOT_DATA_DIR` | Optional absolute data-root override |
| `GRIDPILOT_TIMEOUT_SECONDS` | Hard timeout per invocation, default 90 seconds |
| `CORS_ORIGINS` | Comma-separated exact origins; default localhost/127.0.0.1 on 5173 |
| `GRIDPILOT_API_TOKEN` | Operator mutation token; required with at least 24 characters in production |
| `GRIDPILOT_ENV` | Set `production` to enforce token configuration |
| `GRIDPILOT_AGENT_CALLABLE` | Default `agent:run_investigation` |
| `GRIDPILOT_SOLVE_CALLABLE` | Default `backend.p3_adapter:solve`, wrapping Person 3's native solver |
| `GRIDPILOT_VALIDATE_CALLABLE` | Default `backend.p3_adapter:validate`, preserving the native two-argument validator |
| `GEMINI_API_KEY` | Consumed by the future agent adapter, never sent to frontend |

The token protects expensive/mutating operations. Scenario, health, evidence, run polling and report reads are public in this hackathon service. Use only public/synthetic information. The `operator` label is supplied by the caller, not an authenticated personal identity. A production multi-user system would require actual identity, per-run authorization and retention controls.

## Persistence and concurrency

One API process/worker owns the SQLite database. Investigations are queued durably on its filesystem. Atomic `BEGIN IMMEDIATE` transactions protect idempotency, claims and approval revisions. A request snapshots scenario and evidence before queueing. An identical idempotency key returns its existing run; retrying a failed run requires a new key.

Provider/solver work executes in isolated subprocesses with a hard timeout. Direct compute shares one compute slot with investigations and returns 429 while busy. At most eight investigations can be queued/running. This bounds concurrent provider use; it is not a general per-user rate limiter. The operator token should remain limited to the demo session. Worker shutdown kills the active subprocess group. Restart explicitly marks interrupted running investigations failed and retains queued ones.

Polling exposes the final complete trace at completion. Incremental tool streaming, distributed workers and automatic retry of provider charges are deliberately not implemented. Health reports installed adapter availability, not a live provider connectivity test.

## Validation and reports

Every accepted solution must pass backend acceptance checks. Live mode also requires the external independent validator. IDs and dimensions must match the scenario exactly. SOC must have N+1 values, flows N values, and all numeric values must be finite. A disabled-battery baseline must keep charge/discharge zero and meet the same declared final SOC policy/target.

Comparison uses independently recomputed metrics. Cost delta is **candidate minus baseline**, so a negative number means a lower assumed-cost proxy. Curtailment reduction is **baseline minus candidate**, so a positive number means less simulated curtailment. Neither is a real-world saving claim.

The canonical report summary is generated deterministically from those metrics. Agent narrative is retained as generated commentary, with separate status. Reports include source references, evidence snapshot, scenario hash, full dispatch arrays, independent checks, execution mode, timestamps and the operator decision. Failed runs can also be exported for diagnosis.

## Troubleshooting

| Symptom | Action |
|---|---|
| 503 live adapters missing | Install Persons 2/3 modules or explicitly run replay |
| `unverified_live_trace` | Supply actual provider metadata and successful timestamped required tools |
| 401 | Supply the operator token in Authorization, not the Gemini key |
| 409 replay mismatch / failed run | Use supported default replay settings; regenerate cache only after reviewing scenario changes |
| 409 decision conflict | Reload run revision; only one terminal decision is permitted |
| 429 | Wait for compute/queue availability and honor Retry-After |
| `execution_timeout` | Inspect adapter performance; never invent completed metrics |
| `worker_interrupted` | Submit a new run with a new idempotency key |
| `verification_failed` | Inspect validation violations and array units/IDs/SOC convention |
| Historical evidence missing | Use the explicitly synthetic scenario while restoring verified evidence |

Adapter exception text is not returned because provider exceptions can contain secrets. Error codes identify the failure class. Adapter owners should emit safe diagnostic summaries, avoiding secrets and raw prompts.

## Current integration gate

The actual teammate modules are imported on this branch. Follow [demo integration handoff](../docs/demo-integration-handoff.md). Runtime requirements include the current agent imports; its native output and real Google tool loop still need P2 changes. Strict live requests require credentials. Known local hash response IDs are rejected. `scripts/smoke.py --mode live` disables fallback and checks actual execution mode; a replay cannot pass this release gate. Health adapter readiness does not certify provider access or contract compatibility.
