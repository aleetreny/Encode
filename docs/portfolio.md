# Portfolio edition

The public edition is a static, interactive replay. It requires no Google credentials,
Python service, tunnel or continuously running computer. It does not compute new
solutions in the browser. All outage choices come from committed solver results.

## Run and build

```sh
cd frontend
npm ci
npm run verify:portfolio
npm run dev
npm run build:portfolio
```

Deploy `frontend/dist` to static hosting with SPA routing (`/about` serves `index.html`).
The default build also uses portfolio mode. `VITE_PORTFOLIO_MODE=false` explicitly
restores the original backend connection; `npm run build:live` sets that mode.
For a live build, configure `VITE_API_BASE_URL` in `frontend/.env.live.local` and follow
the backend runbook. No provider secret belongs in a frontend environment variable.

## What visitors can do

- Watch the recorded walkthrough and pause/resume it.
- Select a plant or line and open its recorded four-hour outage.
- Compare two independently validated options and apply either recorded solution.
- Veto a plan, restart the walkthrough, pan and zoom the visualisation.
- Read `/about` for the original architecture, team scope and data limitations.

Each selected outage replaces the previous case. The demo jumps to the closest
library hour (09, 12, 13, 18, 19, 20); it does not combine successive faults or pretend
to solve arbitrary clock times. The original walkthrough cannot overwrite an option
chosen in a library case. Missing cases and invalid plans report an error.

The public edition identifies replay results and disables the backend-only jury room,
autonomy switch and developer pages. The original implementation remains available
in live mode. Recorded prose is historical output, not a fresh Gemini response.

## Preservation

Tag `portfolio-original-published-2026-10-25` points to `1494129`, the latest published hackathon
version used as the base for this edition. No original feature branch was changed.
Solver, validator, Google adapter, backend,
reports, provenance and Git authorship remain intact.

A historical demonstration video can be linked from `/about` when an actual recording
is available. No video or personal contribution claims have been invented.
