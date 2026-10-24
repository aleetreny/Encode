# CEN data snapshot (SIP API)

A fixed download of real Coordinador Eléctrico Nacional data, so the demo never calls the API live.
Everything here is **observed** data from the CEN SIP API, retrieved on 24 October 2026.

## What is in it

| Dataset | Dates | Use in the demo |
|---|---|---|
| `generacion-real` (hourly output of every plant) | 2025-02-24, **2025-02-25**, 2026-08-14, 2026-10-14 | Real plant-by-plant dispatch; the blackout collapse and recovery |
| `demanda-neta` (hourly system totals) | same days | System generation and net demand per hour |
| `instrucciones-sscc` (ancillary-service instructions) | 2025-02-25, 2026-10-14 | What operators instructed during the day |
| `limitaciones-transmision` | 2025-02-25, 2026-10-14 | Transmission limitations declared that day |
| `costo-marginal-real` (by bus, 15-minute) | 2025-02-25, 2026-10-14 (143,032 and 153,016 rows) | Prices across the map |
| `demanda-real-estimada` (hourly, by bus and withdrawal) | 2026-08-14 (392,746 rows, 539 buses) | Real demand split across the network (for zoning). Latest published month is August 2026 |
| `daily-sum` (energy per technology per day) | 2025-02-10 → 2025-03-10, 2026-07-26 → 2026-10-23 | Context charts |
| `ens-2025-2026` (unsupplied energy per failure report) | Returns January 2025 only | Real outage records (see limits) |
| `centrales`, `lineas-transmision` (catalogues) | current (1,362 plants, 1,741 lines) | Join SIP plant ids to Infotécnica codes (`CE…`) |

The exact list, row counts and checksums are in `data/raw/cen-sip/manifest.json`.

**2025-02-25 is the national blackout.** In the real data, generation falls from 12,202 MW
(13:00–14:00) to 2,607 MW (15:00–16:00) and 68 MW (16:00–17:00), then recovers slowly, led by southern hydro
(Ralco, El Toro), to about 3,958 MW by 23:00–24:00. 2025-02-24 is the normal day before; 2026-08-14 and 2026-10-14
are recent normal days (August pairs with the bus-level demand and the August 2026 curtailment data).

## Layout

- `data/raw/cen-sip/<dataset>/<date>/page-NNNN.json.gz`: API pages exactly as returned, minus
  contact fields (emails, addresses, RUTs), which are dropped before saving.
- `data/raw/cen-sip/manifest.json`: endpoint, parameters, URL **without** the key, rows, pages,
  SHA-256 and retrieval time per dataset.
- `data/processed/cen-sip/day-<date>.json`: hourly system totals, generation by technology and the
  hourly output of each plant that generated (`scripts/cen_sip_process.py`).
- `data/processed/cen-sip/daily-sums.json`: daily energy by technology.

## Reproduce

```bash
# key in COORDINADOR_API_KEY or in an env file (never committed)
python3 scripts/cen_sip_snapshot.py scripts/cen_sip_plans/02-days.json --env-file .env.local
python3 scripts/cen_sip_process.py
```

Downloads resume page by page; pages already on disk are not fetched again.

## API facts learned the hard way

- Authentication is the `user_key` query parameter on `https://sipub.api.coordinador.cl`.
  A wrong key returns 403 `Authentication failed`.
- **Pages start at 1.** `page=0` returns 502 `Internal server error`.
- Up to 5,000 rows per page work (`pageSize` on v3 endpoints, `limit` on v4).
- Calls take 2–30 s. Use a timeout of at least 90 s and retry 502/504 with backoff.
- 27 of the 95 routes are deprecated. `cotas-embalses-reales` still returns 500; use `embalse-real`.
- `demanda-real-estimada` is published about two months late: September and October 2026 return 0 rows.
- Large v4 queries report one page more than they serve (second-to-last page short, last empty).
  For bus-level demand the API announced 397,746 rows and served 392,746 (98.7%). Every served page
  is saved; treat these sets as near-complete, which is enough for zone weights and price maps.
- `energia-no-suministrada` currently holds 2024 and January 2025 only; the February 2025 blackout
  is not there, so the blackout is documented here through generation and demand instead.

## Limits

- Hour labels are 1–24 (hour ending), local Chile time.
- Plant names are SIP names (`TER NEHUENCO`); join to Infotécnica through the `centrales` catalogue.
- Source: Coordinador Eléctrico Nacional. Attribute it wherever the data is shown.
