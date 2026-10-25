# Release runbook — Andes · Operación de la red eléctrica con IA

## Backend público para la demo en vivo (Etapa 4)

- **Frontend público (Cloudflare Pages):** `https://andes-a38.pages.dev`
- **URL pública activa del backend (HTTPS con Gemini 4 Argon y HiGHS en vivo):** `https://hemlock-untold-control.ngrok-free.dev`
- **Variable para recompilar y publicar el frontend en Cloudflare Pages:**
  ```bash
  VITE_API_BASE_URL=https://hemlock-untold-control.ngrok-free.dev/api
  ```
- **Configuración de origen y CORS en el backend (`backend/config.py`, `backend/main.py`, `render.yaml`):**
  - `PUBLIC_ORIGIN=https://andes-a38.pages.dev` (el QR `/api/live/sessions/{id}/qr.svg` apunta a `https://andes-a38.pages.dev/jurado?s={id}`).
  - `CORS_ORIGINS=https://andes-a38.pages.dev,http://localhost:5173,http://127.0.0.1:5173` (habilita peticiones REST y streaming SSE entre orígenes).
  - `GEMINI_API_KEY` se carga exclusivamente desde variables de entorno del servidor / secreto del dashboard (nunca en git).
- **Ping de calentamiento antes de la demo:**
  ```bash
  curl -s -H "ngrok-skip-browser-warning: 1" -H "Origin: https://andes-a38.pages.dev" \
    "https://hemlock-untold-control.ngrok-free.dev/api/health?probe_gemini=true"
  ```
- **Prueba real verificada (Celular `/jurado?s=<id>` → Pantalla grande SSE):**
  - Sala creada (`POST /api/live/sessions`), pantalla grande conectada por SSE (`GET /api/live/sessions/sala-demo-jurado-public/stream` con `Origin: https://andes-a38.pages.dev`) y disparo de central `gas_centro` desde dispositivo móvil (`POST /api/live/sessions/sala-demo-jurado-public/jury/disrupt`).
  - Latencia medida en público HTTPS: `incident.detected` recibido en **`110.9 ms`** y `solution.updated` en **`118.6 ms`** (`< 2000 ms`).

## Local release candidate

Work stays on `feature/data-backend`. Never merge the backend branch into `main` implicitly. Run the tests, schema-drift check and data regeneration. Inspect `git diff` for unintended changes and secrets. Start Uvicorn and run the real HTTP smoke twice. Save the release commit and the passing test evidence in the PR.

```bash
python -m pytest -q
python scripts/build_crisis_demo.py
python scripts/export_contracts.py --check
python scripts/prepare_data.py
git diff --exit-code -- data/processed
python -m uvicorn backend.main:create_app --factory --host 127.0.0.1 --port 8000
# In another terminal:
python scripts/smoke.py
python scripts/smoke.py --mode deterministic
```

The source transformation is deterministic. The raw-source manifest retrieval timestamp changes only on an explicit download. Generated schemas/OpenAPI are checked into `contracts/` for all owners to inspect.

## Container

```bash
docker compose up --build -d
python scripts/smoke.py
docker compose logs api
docker compose down
```

The volume retains history. Do not use `docker compose down -v` unless intentionally deleting the journal. Docker must be installed separately; it was unavailable on the development host. The GitHub workflow contains a Linux image build and HTTP smoke against the actual container.

When `agent/` and `optimisation/` arrive, the image includes them through the repository copy. Add their required pinned packages to the runtime requirements and rerun the full image verification. Do not add development doubles to deployment. Keep one Uvicorn worker and one instance for SQLite.

## Public hosting, when the integrated application is ready

No public deployment is certified by this branch. `render.yaml` is an executable free-service blueprint, not evidence that a Render service exists. Connect an authorized Render account to this repository and branch to create it. Set the exact frontend origin in `CORS_ORIGINS`; retrieve the generated operator token in Render and use it only for the judging session. Do not publish provider keys.

The free blueprint uses ephemeral disk. SQLite survives process restarts on that disk, but not redeploys/replacement. For retained hosted audit history, configure a paid persistent disk and point `GRIDPILOT_DB_PATH` at it, or migrate to a shared database. Do not claim persistent hosted history on the free configuration.

Before judging, open `/api/ready?mode=replay` to warm the service and run `scripts/smoke.py --base-url https://<actual-service>`. Install/configure actual Gemini, solver and validator, then require `/api/ready?mode=live` and **two** successful `scripts/smoke.py --mode live` runs. Readiness checks local configuration; the smoke proves a real request completed. Use the live run report to verify actual model/response metadata and sources. Test the dashboard in a fresh browser at the deployed frontend origin.

## Rollback

Keep the previous successful release SHA. If an integrated build fails, deploy that known-good SHA and run its matching smoke. Preserve the database before schema changes. This initial release has one database schema and no migrations. A rollback from a future schema-changing release requires a tested migration/restore procedure, not simply changing the Git ref.

If provider/network access fails during the demo, explicitly select replay and display its label. Do not hide the failure or describe the cached trace as live. If historical evidence is unavailable, select `synthetic-demo-001` and state that the example is synthetic.

## Final submission gates

1. Merge agreed frontend/agent/optimiser work through reviewed PRs and pin the integrated release commit.
2. Verify observed source evidence separately from all synthetic network inputs.
3. Record an actual live provider invocation and deterministic numerical acceptance.
4. Exercise a real invalid-candidate rejection if included in the pitch.
5. Complete the live path twice and inspect its downloaded report and simulation decision.
6. Record the real three-minute video and insert actual service/video URLs and model IDs in the submission draft.
7. Confirm the deadline against the official event site. The README records Sunday 25 October 2026 at 12:00 Europe/London; London changes clock overnight.
8. Submit using the team's event account. Do not claim submission from a prepared draft alone.

## Native v2 release checks

The default scenario is `chile-sen-5node-demo`; see [contracts v2](contracts-v2.md). Regenerate native fixtures before exporting contracts. Verify normal and sudden-crisis results, strict infeasibility, no-hindsight checks, household dimensions and crisis approval. A live provider failure may fall back only to a matching replay when enabled; its mode must visibly change to replay. A configured credential alone does not certify a successful live agent run.

Before any integrated recording, close the exact remaining [demo integration blockers](demo-integration-handoff.md). Standard `npm run build` now passes; frontend API wiring and genuine Gemini tool calling remain required. The backend smoke saves actual reports with `--report-dir var/demo-verification`. Live smoke must fail when mode is replaced by replay. No key was configured during the current verification, so no Google execution is certified.

The backend workflow also compiles `contracts/native-client.ts` and exercises it with `scripts/smoke-client.cjs` against Uvicorn and the Docker container. See the handoff for equivalent local commands. A passing shared-client test establishes the network contract, not React UI integration.
