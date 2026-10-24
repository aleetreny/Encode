# Task 4 — implementation and release checklist

`DONE` means implemented and checked locally. `EXTERNAL` means it depends on another owner's module, an account or the final integrated product. These are execution records, not claims that the whole hackathon submission is finished.

## A. Repository and delivery boundary

| ID | Subtask and acceptance criterion | State |
|---|---|---|
| 4.01 | Inspect upstream files and ownership; record starting commit | DONE |
| 4.02 | Work exclusively on `feature/data-backend` | DONE |
| 4.03 | Preserve frontend, agent and production optimisation ownership | DONE |
| 4.04 | Define the runnable offline path and explicit live failure behavior | DONE |
| 4.05 | Record assumptions, architecture choices and external dependencies | DONE |

## B. Historical evidence

| ID | Subtask and acceptance criterion | State |
|---|---|---|
| 4.06 | Locate an official downloadable monthly CEN export | DONE |
| 4.07 | Download and preserve original source bytes | DONE |
| 4.08 | Record URL, listed publication, retrieval time, byte count and SHA-256 | DONE |
| 4.09 | Inventory sheets, source units and hour headings | DONE |
| 4.10 | Extract solar/wind plant/day observations with cell coordinates | DONE |
| 4.11 | Preserve missing values as null; identify incomplete dates | DONE |
| 4.12 | Detect duplicate identifiers, unexpected layout and non-finite/negative data | DONE |
| 4.13 | Reconcile plant/day, technology/day and monthly summary controls | DONE |
| 4.14 | Record published total-row and heading anomalies without silent repair | DONE |
| 4.15 | Select one complete historical day using a documented rule | DONE |
| 4.16 | Retain observed dates/hour labels without inventing UTC alignment | DONE |
| 4.17 | Distinguish source aggregates from synthetic dispatch inputs | DONE |
| 4.18 | Verify public API authentication and inspect current SIP schema | DONE |
| 4.19 | Obtain aligned observed generation and demand plus plant crosswalk | EXTERNAL: exports/credentials and verified temporal conventions |
| 4.20 | Make data preparation reproducible without network | DONE |

## C. Contracts and fixtures

| ID | Subtask and acceptance criterion | State |
|---|---|---|
| 4.21 | Implement version 1 scenario models with bounded dimensions | DONE |
| 4.22 | Validate references, unique IDs, UTC clock, step lengths and availability | DONE |
| 4.23 | Fix SOC boundaries, battery efficiency and line sign conventions | DONE |
| 4.24 | Implement solve, validation, agent, run and decision schemas | DONE |
| 4.25 | Export JSON Schema and actual FastAPI OpenAPI | DONE |
| 4.26 | Fail CI on schema drift | DONE |
| 4.27 | Supply historically contextualised and fully synthetic scenarios | DONE |
| 4.28 | Generate feasible cached baseline/candidate outputs with the production HiGHS module | DONE |
| 4.29 | Mark cached fixtures and traces explicitly as replay without live Gemini | DONE |
| 4.30 | Supply a browser TypeScript API client and integration instructions | DONE |

## D. API and workflow

| ID | Subtask and acceptance criterion | State |
|---|---|---|
| 4.31 | Scenario catalog and selected-scenario endpoint | DONE |
| 4.32 | Source-evidence endpoint with an ID allowlist | DONE |
| 4.33 | Optimisation route with isolated production-solver adapter | DONE |
| 4.34 | Validation route combining external validator and backend checks | DONE |
| 4.35 | Investigation enqueue and status polling | DONE |
| 4.36 | SQLite journal and atomic worker claims | DONE |
| 4.37 | Idempotency key reuse and conflicting-input rejection | DONE |
| 4.38 | Bounded queue and compute serialization | DONE |
| 4.39 | Hard subprocess timeout and process-group cleanup | DONE |
| 4.40 | Recover queued jobs and fail interrupted running jobs honestly | DONE |
| 4.41 | Snapshot scenario/evidence before queueing | DONE |
| 4.42 | Check all dispatch arrays independently before accepting metrics | DONE |
| 4.43 | Require external numerical validation in live mode | DONE |
| 4.44 | Require live execution metadata and complete timestamped tool trace | DONE |
| 4.45 | Recompute comparison and canonical report summary deterministically | DONE |
| 4.46 | Approve/reject only verified completed simulations | DONE |
| 4.47 | Reject stale revisions and repeated decisions atomically | DONE |
| 4.48 | Export JSON with source evidence, snapshots, assumptions and validation | DONE |
| 4.49 | Preserve decision identity label, time, note and simulation-only scope | DONE |
| 4.50 | Integrate actual Gemini agent implementation | EXTERNAL: Person 2 |
| 4.51 | Integrate actual solver and its independent validator | DONE: merged Person 3 branch into this branch; actual API solve/validate verified |
| 4.52 | Connect actual frontend through the contract client | EXTERNAL: Person 1 |

## E. Operational checks

| ID | Subtask and acceptance criterion | State |
|---|---|---|
| 4.53 | Explicit CORS origins and allowed headers | DONE |
| 4.54 | Server-side secret configuration and production mutation authentication | DONE |
| 4.55 | Limit request bodies including chunked uploads | DONE |
| 4.56 | Avoid echoing invalid inputs and provider exceptions containing secrets | DONE |
| 4.57 | Health plus explicit live/replay readiness endpoints | DONE |
| 4.58 | Request IDs and basic request logs without bodies or authorization | DONE |
| 4.59 | Pin runtime and development dependencies | DONE |
| 4.60 | Non-root Docker image, local persistent Compose volume and health check | DONE: image build and container smoke passed in CI |
| 4.61 | Free Render blueprint with documented ephemeral-storage behavior | DONE |
| 4.62 | Meaningful tests for tampering, failure, concurrency and approval | DONE |
| 4.63 | Real HTTP smoke twice with approval and downloaded report | DONE locally |
| 4.64 | GitHub workflow for tests, contract drift, data regeneration and container smoke | DONE: push and pull-request runs passed |
| 4.65 | Public backend URL and remote smoke test | EXTERNAL: hosting account |

## F. Submission and release

| ID | Subtask and acceptance criterion | State |
|---|---|---|
| 4.66 | Reproduction instructions from a clean Python environment | DONE |
| 4.67 | Handoff guide for all three owners, including exact function signatures | DONE: refreshed after importing current P1/P2/P3 sources |
| 4.68 | Demo script and factual submission draft | DONE |
| 4.69 | Troubleshooting, warm-up, rollback and final release gate | DONE |
| 4.70 | Final live integrated application tested twice | BLOCKED: native Gemini tool loop, credential and frontend wiring; see demo-integration-handoff.md |
| 4.71 | Record actual product video with live Gemini and visible verification | EXTERNAL: integrated product |
| 4.72 | Fill final public URL/video/model fields and submit entry | EXTERNAL: product, video and submission account |

## Release gate

Do not promote this branch's replay to a live-agent claim. The current teammate sources are merged on this branch. Close the agent/frontend blockers in demo-integration-handoff.md, validate actual provider execution and deliberately demonstrate a rejected invalid candidate. Run `scripts/smoke.py --mode live` twice against the public URL. Verify the frontend in a fresh browser. Check the exported report and operator decision, record the real video and only then complete the submission.

## G. Updated README: native workflow v2

| ID | Subtask and acceptance criterion | State |
|---|---|---|
| 4.73 | Audit upstream README 1756d68 and native P3 design | DONE |
| 4.74 | Generate five-node, 24-hour SEN-shaped scenario | DONE |
| 4.75 | Keep historical CEN context separate from synthetic profiles | DONE |
| 4.76 | Expose native scenario and asset modification menu | DONE |
| 4.77 | Type bounded battery and line candidates | DONE |
| 4.78 | Type planned and sudden outages | DONE |
| 4.79 | Expose native optimisation with requested inputs | DONE |
| 4.80 | Independently validate native outputs | DONE |
| 4.81 | Reject unexpected assets in dispatch arrays | DONE |
| 4.82 | Verify no hindsight before sudden events | DONE |
| 4.83 | Revalidate both results before comparison | DONE |
| 4.84 | Define configurable synthetic household factor | DONE |
| 4.85 | Support per-node residential shares | DONE |
| 4.86 | Separate instantaneous household equivalents | DONE |
| 4.87 | Compute event-window household-hours | DONE |
| 4.88 | Compute whole-horizon household-hours | DONE |
| 4.89 | Avoid claiming unique households reconnected | DONE |
| 4.90 | Evaluate normal baseline and alternatives | DONE |
| 4.91 | Evaluate strict crisis infeasibility explicitly | DONE |
| 4.92 | Evaluate recovery with load shedding | DONE |
| 4.93 | Select intervention using verified crisis metrics | DONE |
| 4.94 | Bind replay to scenario hash and settings | DONE |
| 4.95 | Provide deterministic full workflow without provider | DONE |
| 4.96 | Require genuine live agent provenance | DONE |
| 4.97 | Relabel allowed live failure fallback as replay | DONE |
| 4.98 | Keep crisis decisions subject to operator approval | DONE |
| 4.99 | Synchronize decision and governance audit state | DONE |
| 4.100 | Export RIO-style report without legal certification | DONE |
| 4.101 | Publish native schemas and strict TypeScript client | DONE |
| 4.102 | Retain v1 compatibility for existing callers | DONE |
| 4.103 | Test native contracts, tampering, timeout and fallback | DONE |
| 4.104 | Update handoff, demo and release documentation | DONE |
