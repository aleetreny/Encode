# Verification record

Local verification on 24 October 2026, branch `feature/data-backend`:

- **164 tests passed**, including Person 3's complete numerical suite plus backend/data/API coverage of malformed contracts, physics tampering, async/sync adapters, hard timeout, secret-safe failures, idempotency, concurrent decisions, restart recovery, synthetic fallback and replay labelling.
- Ruff lint and formatting checks passed. The TypeScript contract client passed strict TypeScript 5.9.3 compilation.
- JSON Schema and OpenAPI regeneration passed the drift check.
- Original CEN source checksum matched. Re-running the offline transformation produced the same processed records and quality findings.
- A real Uvicorn server completed two HTTP smoke runs with numerical verification, comparison, approval and report download. The final smoke also invokes the production HiGHS solver and its independent validator for both battery policies through the HTTP API.
- A second clean virtual environment with **runtime requirements only** also completed two HTTP smoke runs with production mutation authentication enabled. Serving the cached demo requires neither openpyxl nor SciPy nor provider credentials.
- Installed Python dependencies passed `pip check`.

The test runner emits one dependency deprecation warning: the installed Starlette test client currently supports `httpx` but recommends its newer transport package. This does not affect the actual Uvicorn/HTTP smoke path.

GitHub Actions also passed on the implementation commit, including the actual Linux Docker image build and two HTTP investigations against the running container: [verified run](https://github.com/aleetreny/Encode/actions/runs/40111205826). The pull-request-triggered run passed independently as well. Docker remained unavailable on the local host.

Executable Person 3 code arrived during integration at commit `fbf0fdf` and was merged unchanged into `feature/data-backend`. Actual native solver/validator calls now pass both directly and through the API. The cached fixtures are regenerated from that production module, replacing the initial independent reference generator. The test exposed an invalid cycling result under the earlier objective; the final explicit scenario uses curtailment penalty 0, battery throughput cost 0.5 and an initial-SOC floor, matching the native numerical assumptions.

No real Gemini call, final frontend, public hosting deployment, actual demo video or submission is certified by these checks. Review the PR's checks for verification of the final integration commit; the linked initial CI run predates the numerical-module merge.
