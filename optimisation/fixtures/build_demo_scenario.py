"""Generate the synthetic demo scenario ``demo_scenario.json``.

Everything here is SYNTHETIC: a 5-node north-south chain loosely shaped like Chile's
system (solar-rich north, demand centre around Santiago, a congested corridor in
between). Person 4 can later replace the profile shapes with CEN-observed hourly
shapes; the field names stay the same.

    python -m optimisation.fixtures.build_demo_scenario
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

OUT = Path(__file__).with_name("demo_scenario.json")
LOCAL = ZoneInfo("America/Santiago")
DAY = datetime(2026, 10, 1, 0, 0, tzinfo=LOCAL)  # synthetic day, not a verified event
T = 24


def _solar(h: int) -> float:
    x = (h + 0.5 - 7.0) / 12.0  # sunrise ~07:00, sunset ~19:00 local
    return max(0.0, math.sin(math.pi * x)) ** 1.3 if 0 < x < 1 else 0.0


def _bump(h: int, centre: float, width: float) -> float:
    return math.exp(-(((h - centre) / width) ** 2))


def _r(values: list[float]) -> list[float]:
    return [round(v, 1) for v in values]


def build() -> dict:
    hours = list(range(T))
    stamps = [
        (DAY + timedelta(hours=h)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") for h in hours
    ]
    solar = [_solar(h) for h in hours]
    wind_nc = [0.30 + 0.25 * _bump(h, 21, 4) + 0.15 * _bump(h, 3, 4) for h in hours]
    wind_sur = [0.45 + 0.20 * math.sin(2 * math.pi * (h - 2) / 24) for h in hours]
    evening = [_bump(h, 20.5, 2.5) for h in hours]
    daytime = [_bump(h, 13, 4) for h in hours]

    return {
        "scenario_id": "chile-sen-5node-demo",
        "mode": "synthetic",
        "time_step_hours": 1,
        "timestamps_utc": stamps,
        "display_timezone": "America/Santiago",
        "provenance": {
            "observed_source_urls": [],
            "observed_fields": [],
            "derived_fields": [],
            "synthetic_fields": [
                "network_topology", "line_limits", "generators", "batteries",
                "demand_mw_by_node", "renewable_availability_mw_by_generator", "objective",
                "emission_factors_t_per_mwh", "households_per_mw",
            ],
            "historical_event_date": None,
            "notes": (
                "Fully synthetic demo day shaped like the Chilean pattern (midday solar surplus in the "
                "north, congested north-south corridor, evening peak in the centre). Not a verified "
                "historical event; to be anchored to CEN-observed profiles by Person 4."
            ),
        },
        "emission_factors_t_per_mwh": {
            "gas": 0.40,
            "coal": 0.95,
            "diesel": 0.75,
            "solar": 0.0,
            "wind": 0.0,
            "hydro": 0.0,
        },
        "nodes": [
            {"id": "n_norte_grande", "label": "Norte Grande (Crucero)", "substation": "S/E Crucero 220 kV", "lat": -22.30, "lon": -69.55, "households_per_mw": 1000, "households_total": 320000},
            {"id": "n_norte_chico", "label": "Norte Chico (Cardones)", "substation": "S/E Cardones 500 kV", "lat": -27.45, "lon": -70.30, "households_per_mw": 1000, "households_total": 280000},
            {"id": "n_centro", "label": "Centro (Polpaico)", "substation": "S/E Polpaico 500 kV", "lat": -33.15, "lon": -70.85, "households_per_mw": 1000, "households_total": 2400000},
            {"id": "n_centro_sur", "label": "Centro-Sur (Charrúa)", "substation": "S/E Charrúa 500 kV", "lat": -36.90, "lon": -72.20, "households_per_mw": 1000, "households_total": 1100000},
            {"id": "n_sur", "label": "Sur (Puerto Montt)", "substation": "S/E Puerto Montt 220 kV", "lat": -41.45, "lon": -72.95, "households_per_mw": 1000, "households_total": 650000},
        ],
        "lines": [
            {"id": "L1", "from": "n_norte_grande", "to": "n_norte_chico", "capacity_mw": 400},
            {"id": "L2", "from": "n_norte_chico", "to": "n_centro", "capacity_mw": 400},
            {"id": "L3", "from": "n_centro", "to": "n_centro_sur", "capacity_mw": 350},
            {"id": "L4", "from": "n_centro_sur", "to": "n_sur", "capacity_mw": 300},
        ],
        "generators": [
            {"id": "solar_ng", "node_id": "n_norte_grande", "technology": "solar",
             "capacity_mw": 700, "variable_cost_usd_per_mwh": 0},
            {"id": "solar_nc", "node_id": "n_norte_chico", "technology": "solar",
             "capacity_mw": 300, "variable_cost_usd_per_mwh": 0},
            {"id": "wind_nc", "node_id": "n_norte_chico", "technology": "wind",
             "capacity_mw": 200, "variable_cost_usd_per_mwh": 0},
            {"id": "gas_ng", "node_id": "n_norte_grande", "technology": "gas",
             "capacity_mw": 350, "variable_cost_usd_per_mwh": 85, "ramp_rate_mw_per_h": 150},
            {"id": "gas_centro", "node_id": "n_centro", "technology": "gas",
             "capacity_mw": 600, "variable_cost_usd_per_mwh": 95, "ramp_rate_mw_per_h": 250},
            {"id": "coal_cs", "node_id": "n_centro_sur", "technology": "coal",
             "capacity_mw": 350, "variable_cost_usd_per_mwh": 60, "ramp_rate_mw_per_h": 60},
            {"id": "hydro_sur", "node_id": "n_sur", "technology": "hydro",
             "capacity_mw": 200, "variable_cost_usd_per_mwh": 25, "ramp_rate_mw_per_h": 150},
            {"id": "wind_sur", "node_id": "n_sur", "technology": "wind",
             "capacity_mw": 200, "variable_cost_usd_per_mwh": 0},
            {"id": "diesel_centro", "node_id": "n_centro", "technology": "diesel",
             "capacity_mw": 150, "variable_cost_usd_per_mwh": 220},
        ],
        "batteries": [
            {"id": "b_centro", "node_id": "n_centro", "power_capacity_mw": 30, "energy_capacity_mwh": 60,
             "min_soc_mwh": 0, "initial_soc_mwh": 30, "charge_efficiency": 0.95, "discharge_efficiency": 0.95},
            {"id": "b_reserve_ng", "node_id": "n_norte_grande", "power_capacity_mw": 150, "energy_capacity_mwh": 600,
             "min_soc_mwh": 0, "initial_soc_mwh": 450, "charge_efficiency": 0.95, "discharge_efficiency": 0.95,
             "standby": True},
            {"id": "b_reserve_centro", "node_id": "n_centro", "power_capacity_mw": 80, "energy_capacity_mwh": 240,
             "min_soc_mwh": 0, "initial_soc_mwh": 180, "charge_efficiency": 0.95, "discharge_efficiency": 0.95,
             "standby": True},
        ],
        "demand_mw_by_node": {
            "n_norte_grande": _r([180 + 10 * d for d in daytime]),
            "n_norte_chico": _r([110 + 30 * e + 15 * d for e, d in zip(evening, daytime)]),
            "n_centro": _r([620 + 330 * e + 120 * d for e, d in zip(evening, daytime)]),
            "n_centro_sur": _r([230 + 80 * e + 30 * d for e, d in zip(evening, daytime)]),
            "n_sur": _r([150 + 50 * e for e in evening]),
        },
        "renewable_availability_mw_by_generator": {
            "solar_ng": _r([700 * s for s in solar]),
            "solar_nc": _r([300 * s for s in solar]),
            "wind_nc": _r([200 * w for w in wind_nc]),
            "wind_sur": _r([200 * w for w in wind_sur]),
        },
        "objective": {
            "unserved_energy_penalty_usd_per_mwh": 10000,
            "curtailment_penalty_usd_per_mwh": 0,
            "battery_throughput_cost_usd_per_mwh": 0.5,
            "transmission_tiebreak_usd_per_mwh": 0.01,
        },
        "events": [],
    }


def main() -> None:
    OUT.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
