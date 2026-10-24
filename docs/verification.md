# Verification record

Local verification on 24 October 2026, branch `feature/data-backend`, after integrating upstream README `1756d68`:

- **182 tests passed**, including the complete P3 numerical suite and native v2 API, candidate/outage contracts, no-hindsight checks, unexpected asset rejection, household units, replay/settings binding, hard timeout, truthful fallback, persistence and operator decisions.
- Ruff lint and formatting passed. Both contract clients passed strict TypeScript 5.9.3 compilation.
- JSON Schema and OpenAPI regeneration passed the drift check.
- Re-running the CEN transformation reproduced the processed records and quality findings from the preserved source.
- A fresh Uvicorn server using runtime requirements only completed two replay and two deterministic HTTP investigations, including real native solver calls, strict crisis infeasibility, recovery, independent verification, comparison, approval and report download.
- The default fixture produced 631.578947 MWh normal curtailment reduction and 391.875 MWh whole-horizon crisis unserved-energy reduction. Its four-hour event-window reduction is 267.45 MWh, corresponding to 66,862.5 average household equivalents under the synthetic 1,000 households/MW assumption.

The test runner emits one Starlette/httpx dependency deprecation warning. Actual Uvicorn HTTP tests also pass.

Docker is unavailable locally. The workflow builds the Linux container and exercises the actual HTTP API against it; consult the [pull request checks](https://github.com/aleetreny/Encode/pull/1/checks) for the current commit. Earlier passing CI runs predate native v2 and do not certify this update.

The native numerical solver/validator remains Person 3's implementation. Backend checks supplement physical validation with requested-input matching, asset identity and pre-event causality. Actual Gemini execution, final frontend, public hosting, video and submission remain outside the verified result.
