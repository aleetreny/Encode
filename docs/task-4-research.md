# Task 4 — research and engineering decisions

Research date: 24 October 2026. Implementation branch: `feature/data-backend`.

## Repository and ownership

The inspected upstream commit was `62101a7cc795e1f0d8c648873c8052a777555b4f`. It contained only the project README. There were no existing agent, optimiser, frontend, contracts, API, deployment credentials or tests to integrate. This branch implements Person 4's boundary and an offline integration path. Production solver and Gemini orchestration remain owned by Persons 3 and 2. During integration, executable Person 3 code arrived at `fbf0fdf` and was merged unchanged into this branch; the native solver/validator are now API-tested.

## Evidence selected

The [CEN 2026 reductions archive](https://www.coordinador.cl/operacion/documentos/reducciones-de-generacion-renovable/reducciones-erv-2026/) describes monthly renewable reduction records processed after month end. At research time its latest listed export was August 2026, with a listed publication date of 30 September 2026. The [downloaded XLSX](https://www.coordinador.cl/wp-content/uploads/2026/10/Reducciones-de-Energia-Eolica-Solar-Hidro-en-el-SEN_Agosto-26-PE-PFV_Publicar.xlsx) is retained byte for byte in `data/raw/`, with SHA-256 and retrieval metadata. Its URL contains an October upload directory. That is recorded separately from the publication date rather than treated as a new event date.

The workbook has nine sheets: monthly summary, daily/hourly wind, solar, run-of-river hydro and reservoir hydro, plus annual accumulations for those technologies. This implementation explicitly extracts solar and wind only. Each daily section has plant rows, hour labels 1–24, plant daily totals and a technology total row. The monthly summary identifies daily curtailment in MWh and the monthly overview in GWh.

The chosen event is **1 August 2026**, selected as the first day in the downloaded monthly workbook, rather than for an attractive simulated effect. It has 77 solar and 56 wind plant rows. Aggregated solar reduction is 6,501.247783333333 MWh and wind reduction is 11,060.926558333333 MWh. These are historical source aggregates, not outcomes or savings from Andes. Coordinates are retained per plant row for auditability.

## Source quality findings

Extraction reads 4,123 plant/day records and 62 technology/day controls. Across the month there are **122 cells containing `-`**, on 29 and 30 August. They are preserved as `null`, never made into observed zeros. Reconciliation to source summaries checks the sum of available numeric cells. It does **not** establish that missing curtailment was zero or that the whole month is complete.

Other source anomalies are retained in the machine-readable quality file:

- Solar hourly Total rows disagree with plant-cell sums on 9, 10, 11 and 13 August. The largest residual is approximately 2,370.05485848 MWh in a single hour on 9 August.
- The solar hour-2 heading for 10 August is the literal character `|`. The extractor permits only this specifically identified layout anomaly, retains the original heading and records that values are accessed by column position.
- The selected 1 August event has no missing observations and reconciles its plant, hourly and daily totals.
- Published monthly summaries reconcile to available plant-cell sums: solar 159,098.3864021798 MWh and wind 157,580.26194666667 MWh, within `1e-4 MWh`.

Unknown layout changes, invalid numeric values, duplicate plant/day keys, broken daily totals, incomplete selected-event observations and source checksum changes stop extraction. The explicit source anomalies above are disclosed, not silently repaired.

## Time and units

The export's hour headings do not, on their own, establish UTC interval boundaries. Observed data therefore retain the original date and hour labels. No observed UTC conversion is asserted. `America/Santiago` is the contextual time zone. Simulator timestamps are explicitly synthetic UTC interval starts. Their use of the historical calendar date does not assert alignment with a particular observed hour.

The simulation uses MW for instantaneous/interval-average power and MWh for energy and SOC. Energy is power multiplied by `time_step_hours`. The reference battery uses symmetric efficiency, `eta_charge = eta_discharge = sqrt(round_trip_efficiency)`, and an explicit final-SOC floor equal to the initial SOC in the integrated demo. Line flows are signed from `from` to `to`. The network is a lossless transport approximation, with no voltage, reactive power, phase angles, AC physics, reserves or contingency constraints.

[Python zoneinfo documentation](https://docs.python.org/3/library/zoneinfo.html) is the basis for using IANA time zones instead of fixed offsets in future time alignment. Before joining additional historical series, confirm CEN's interval boundary, DST treatment, whether MW or MWh is reported, and exact plant identities.

## Generation and demand availability

The [CEN operation page](https://www.coordinador.cl/operacion/graficos/operacion-real/) provides Qlik-based generation and demand views and generation downloads. The interactive export did not yield a verified aligned file during this work. No generation/demand values were invented or joined by fuzzy plant-name matching.

The [developer portal](https://portal.api.coordinador.cl/) states that registration is required and describes API-key/OpenID authentication. The [public SIP documentation](https://portal.api.coordinador.cl/documentacion?service=sipubv2) warns that some endpoints are obsolete. The [SIP OpenAPI document](https://portal.api.coordinador.cl/swagger/spec/sip.json) was retrieved and inspected directly. It declares an API key named `user_key` in the query string, a dated-generation endpoint at `/generacion-real/v3/findByDate`, and estimated-real-demand at `/demanda-real-estimada/v4/findByDate`. Pagination names differ between endpoints. “Estimated real demand” must not be relabelled as a direct measured nodal demand series.

No credentials were available and no authenticated API data were claimed. The demo runs without CEN credentials. The selected evidence motivates a counterfactual; **all network dispatch inputs remain synthetic**. Adding observed demand and generation is a later data-integration step requiring verified exports or credentials and explicit crosswalks. Curtailment by itself is not available generation and cannot be used as such.

## Service architecture

The [FastAPI CORS guide](https://fastapi.tiangolo.com/tutorial/cors/) supports explicit origin, method and header configuration. The API permits configured frontend origins; mutations use an optional operator bearer token, required in production. Gemini credentials remain server-side. CORS is not authentication.

[FastAPI's background-task guidance](https://fastapi.tiangolo.com/tutorial/background-tasks/) distinguishes simple in-process work from heavier jobs. Investigations here are journalled in SQLite and executed in separate Python processes. This allows hard timeouts and termination of a stuck provider or solver without blocking the event loop. Queued jobs survive restart on the same database. Previously running jobs become explicit failures on restart. They are never marked completed by inference.

[SQLite transaction documentation](https://docs.python.org/3/library/sqlite3.html) informs the atomic enqueue, idempotency, claim and decision operations. This release supports **one API process and one local worker per database**. It is not a distributed job queue. Replicas or multiple Uvicorn workers require an external queue and shared database, not an extra `--workers` flag.

Numerical acceptance at the backend boundary checks every submitted array independently of the adapter: dimensions, IDs, balance, limits, renewable availability, SOC, simultaneous battery actions, final SOC and load shedding. Metrics and the report's canonical summary are recomputed from these arrays. Live investigations must additionally pass Person 3's validator. Provider metadata and a timestamped complete tool trace are required before a live investigation is accepted. Adapter-supplied provider IDs are provenance, not independently verified provider billing records.

## Deployment decision and practical limits

The [FastAPI Docker guidance](https://fastapi.tiangolo.com/deployment/docker/) supports a dedicated image and exec-form startup. The image runs as an unprivileged user. A Compose named volume retains SQLite locally. This host does not have a Docker executable, so local verification uses the real Uvicorn process; the GitHub workflow builds and smokes the image on Linux.

The [Render Blueprint reference](https://render.com/docs/blueprint-spec) supports the provided portable deployment configuration. The default blueprint uses a free service and generates an operator token. It does not create a paid disk. On that configuration, hosted state is ephemeral across redeploys. A paid disk or external database is required for durable hosted history. No hosting account or deploy secret was present, so an actual public deployment cannot be certified until an account is connected. Cold-start services must be warmed and smoke-tested before judging.

The [hackathon page](https://www.encodeclub.com/programmes/encode-london-2026) requires a working demo, repository and video. This branch supplies backend reproducibility and a demo script. A cached replay is explicitly not sufficient evidence of a live Gemini investigation, and cannot be submitted as one.

## Updated README integration, 24 October 2026

Upstream commit `1756d68` changes the default workflow to native five-node dispatch, bounded asset modifications and sudden crises. The P3 numerical design is the executable contract. Backend validation additionally checks requested inputs, exact asset identities and unchanged dispatch before sudden events.

Regulatory references are the [CNE technical standards catalogue](https://www.cne.cl/normativas/electrica/normas-tecnicas/), LGSE (BCN 258171), DS32 (BCN 1225248) and [Ley 21.505](https://www.bcn.cl/leychile/navegar?idNorma=1184572). These provide context, not certification of full regulatory compliance. The household factor 1,000 households/MW is a configurable synthetic assumption, not an official conversion. Event-window household-hours and whole-horizon savings must remain separate; dividing whole-day savings by outage duration misstates the event-window average.
