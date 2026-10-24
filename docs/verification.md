# Verification record

Local verification on 24 October 2026, branch `feature/data-backend`:

- **61 tests passed**, covering the source pipeline, malformed contracts, physics tampering, async/sync adapters, hard timeout, secret-safe failures, idempotency, concurrent decisions, restart recovery, synthetic fallback, replay labelling and the native P3 bridge.
- Ruff lint and formatting checks passed. The TypeScript contract client passed strict TypeScript 5.9.3 compilation.
- JSON Schema and OpenAPI regeneration passed the drift check.
- Original CEN source checksum matched. Re-running the offline transformation produced the same processed records and quality findings.
- A real Uvicorn server completed two HTTP smoke runs with numerical verification, comparison, approval and report download.
- A second clean virtual environment with **runtime requirements only** also completed two HTTP smoke runs with production mutation authentication enabled. Serving the cached demo requires neither openpyxl nor SciPy nor provider credentials.
- Installed Python dependencies passed `pip check`.

The test runner emits one dependency deprecation warning: the installed Starlette test client currently supports `httpx` but recommends its newer transport package. This does not affect the actual Uvicorn/HTTP smoke path.

No real Gemini call, production numerical-module execution, final frontend, public hosting deployment, actual demo video or submission is certified by these checks. The native bridge is checked against test doubles based on Person 3's published design; executable solver code was not yet present on its branch. Docker was unavailable locally; image build/smoke is configured in GitHub Actions and must pass there before claiming container verification.
