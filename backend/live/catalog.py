"""GridPilot Live Ops Catalog module.

Provides `build_catalog()` which loads the scenario fixture and produces the
canonical Catalog matching `contracts/live.schema.json`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "optimisation" / "fixtures" / "demo_scenario.json"
REAL_DAY_FIXTURE_PATH = ROOT / "optimisation" / "fixtures" / "real_day_scenario.json"

SYNTHETIC_DAY_PROFILE: dict[str, str] = {
    "source": "synthetic",
    "date": "2026-10-01",
    "method": "synthetic",
    "label_es": "Synthetic day with a Chilean shape",
}


def scenario_path() -> Path:
    """Scenario fixture selected by env ``GRIDPILOT_SCENARIO`` (``real-day`` default, ``synthetic``)."""
    choice = os.getenv("GRIDPILOT_SCENARIO", "real-day").strip().lower() or "real-day"
    if choice == "synthetic":
        return FIXTURE_PATH
    if choice == "real-day":
        return REAL_DAY_FIXTURE_PATH
    raise ValueError(f"GRIDPILOT_SCENARIO must be 'synthetic' or 'real-day', got {choice!r}")


GEN_NAMES = {
    "solar_ng": "Crucero Solar Norte Grande",
    "solar_nc": "Atacama Solar Norte Chico",
    "wind_nc": "Punta Palmeras Wind",
    "gas_ng": "Mejillones Combined Cycle",
    "gas_centro": "Nehuenco Combined Cycle Centro",
    "coal_cs": "Santa María Coronel Coal Plant",
    "hydro_sur": "Ralco Chapo Reservoir Sur",
    "wind_sur": "Llanquihue Wind Farm",
    "diesel_centro": "Renca Backup Diesel Turbine",
}

BAT_NAMES = {
    "b_centro": "Polpaico Operating BESS",
    "b_reserve_ng": "Crucero Reserve BESS Norte Grande",
    "b_reserve_centro": "Polpaico Reserve BESS Centro",
}

DEFAULT_EMISSION_FACTORS: dict[str, float] = {
    "gas": 0.40,
    "coal": 0.95,
    "diesel": 0.75,
    "solar": 0.0,
    "wind": 0.0,
    "hydro": 0.0,
}

LEVERS: list[dict[str, str]] = [
    {
        "type": "emergency_rating",
        "label_es": "Emergency Thermal Rating",
        "description_es": "Temporarily raises the transfer capacity of a trunk line during the critical window.",
    },
    {
        "type": "demand_response",
        "label_es": "Industrial Demand Response",
        "description_es": "Compensated, voluntary cut of industrial load without disconnecting homes.",
    },
    {
        "type": "activate_reserve_bess",
        "label_es": "Activate Standby Reserve BESS",
        "description_es": "Brings strategic reserve battery banks online to inject power immediately.",
    },
    {
        "type": "hydro_reserve_release",
        "label_es": "Hydro Reserve Release",
        "description_es": "Dispatches extra reservoir head in the south, pricing in the opportunity cost of water.",
    },
    {
        "type": "start_peaker",
        "label_es": "Fast Turbine Start (Peaker)",
        "description_es": "Starts a fast backup thermal unit, with a cold-start synchronisation delay.",
    },
    {
        "type": "add_battery",
        "label_es": "BESS Storage (Planning)",
        "description_es": "Adds storage capacity for solar arbitrage and peak support.",
    },
    {
        "type": "uprate_line",
        "label_es": "Trunk Corridor Upgrade",
        "description_es": "Permanently raises the nominal capacity of a congested transmission line.",
    },
]

STRESS_RECIPES: list[dict[str, Any]] = [
    {
        "id": "terremoto_norte",
        "title_es": "Norte Grande Earthquake",
        "description_es": "A severe quake disconnects corridor L1 and the northern combined-cycle plant.",
        "events": [
            {"type": "line_outage", "id": "L1", "duration_hours": 4, "mode": "sudden"},
            {"type": "generator_outage", "id": "gas_ng", "duration_hours": 4, "mode": "sudden"},
        ],
    },
    {
        "id": "incendio_forestal_centro_sur",
        "title_es": "Centro-Sur Wildfire",
        "description_es": "A fire under the 500 kV corridor trips trunk line L3 between Polpaico and Charrúa.",
        "events": [
            {"type": "line_outage", "id": "L3", "duration_hours": 4, "mode": "sudden"},
        ],
    },
    {
        "id": "sequia_hidrica_sur",
        "title_es": "Southern Drought",
        "description_es": "Southern reservoir unavailable during the evening ramp.",
        "events": [
            {"type": "generator_outage", "id": "hydro_sur", "duration_hours": 6, "mode": "sudden"},
        ],
    },
    {
        "id": "ola_calor_santiago",
        "title_es": "Santiago Heatwave",
        "description_es": "Main thermal plant trips at the metropolitan evening peak.",
        "events": [
            {"type": "generator_outage", "id": "gas_centro", "duration_hours": 4, "mode": "sudden"},
        ],
    },
]

JURY_CARDS: list[dict[str, Any]] = [
    {
        "id": "trip_gas_centro",
        "title_es": "Trip Centro Gas Plant",
        "subtitle_es": "Takes 600 MW of thermal generation out at Polpaico for 4 hours",
        "action": {
            "type": "generator_outage",
            "id": "gas_centro",
            "duration_hours": 4,
        },
    },
    {
        "id": "trip_l2",
        "title_es": "Cut Trunk Line L2 Norte-Centro",
        "subtitle_es": "Opens the 400 MW corridor between Cardones and Polpaico",
        "action": {
            "type": "line_outage",
            "id": "L2",
            "duration_hours": 4,
        },
    },
    {
        "id": "trip_l3",
        "title_es": "Cut Trunk Line L3 Centro-Sur",
        "subtitle_es": "Opens the 350 MW line between Polpaico and Charrúa",
        "action": {
            "type": "line_outage",
            "id": "L3",
            "duration_hours": 4,
        },
    },
    {
        "id": "trip_coal_cs",
        "title_es": "Trip Centro-Sur Coal Plant",
        "subtitle_es": "Disconnects 350 MW of baseload at Charrúa for 4 hours",
        "action": {
            "type": "generator_outage",
            "id": "coal_cs",
            "duration_hours": 4,
        },
    },
    {
        "id": "stress_terremoto",
        "title_es": "Simulate Northern Earthquake",
        "subtitle_es": "Simultaneous failure of L1 and Norte Grande Gas",
        "action": {
            "type": "stress_recipe",
            "recipe_id": "terremoto_norte",
        },
    },
]

ASSUMPTIONS: dict[str, Any] = {
    "households_per_mw": 1000,
    "emission_factors_t_per_mwh": {
        "gas": 0.40,
        "coal": 0.95,
        "diesel": 0.75,
        "solar": 0.0,
        "wind": 0.0,
        "hydro": 0.0,
    },
    "voll_usd_per_mwh": 10000.0,
    "demand_response_cost_usd_per_mwh": 300.0,
    "hydro_water_value_usd_per_mwh": 120.0,
}


def build_catalog(scenario: dict | None = None) -> dict[str, Any]:
    """Build and return a canonical Live Ops Catalog dict matching contracts/live.schema.json."""
    if scenario is None:
        path = scenario_path()
        if path.is_file():
            with open(path, encoding="utf-8") as f:
                scen = json.load(f)
        elif path == FIXTURE_PATH:
            from optimisation.fixtures.build_demo_scenario import build
            scen = build()
        else:
            # An explicitly selected day that is missing must fail, not quietly become the synthetic one.
            raise FileNotFoundError(f"Selected scenario fixture is missing: {path}")
    else:
        scen = scenario

    scenario_id = str(scen.get("scenario_id", "chile-sen-5node-demo"))
    emission_factors = scen.get("emission_factors_t_per_mwh", DEFAULT_EMISSION_FACTORS)

    # 1. Nodes (CatalogNode)
    nodes = []
    for n in scen.get("nodes", []):
        nid = n["id"]
        label = n.get("label", nid)
        nodes.append(
            {
                "id": nid,
                "label": label,
                "name": label,
                "substation": n.get("substation", f"S/E {label}"),
                "lat": float(n["lat"]),
                "lon": float(n["lon"]),
                "households_per_mw": int(n.get("households_per_mw", 1000)),
                "households_total": int(n.get("households_total", 0)),
                "provenance": "assumption",
            }
        )

    # 2. Lines (CatalogLine)
    lines = []
    for ln in scen.get("lines", []):
        lid = ln["id"]
        from_n = ln.get("from") or ln.get("from_node", "")
        to_n = ln.get("to") or ln.get("to_node", "")
        lines.append(
            {
                "id": lid,
                "from_node": from_n,
                "to_node": to_n,
                "from": from_n,
                "to": to_n,
                "capacity_mw": float(ln["capacity_mw"]),
                "disruptable": True,
            }
        )

    # 3. Generators (CatalogGenerator)
    generators = []
    for g in scen.get("generators", []):
        gid = g["id"]
        tech = str(g.get("technology", "unknown"))
        ef = float(emission_factors.get(tech, DEFAULT_EMISSION_FACTORS.get(tech, 0.0)))
        ramp = g.get("ramp_rate_mw_per_h")
        generators.append(
            {
                "id": gid,
                "name": GEN_NAMES.get(gid, gid),
                "node_id": g["node_id"],
                "technology": tech,
                "capacity_mw": float(g["capacity_mw"]),
                "variable_cost_usd_per_mwh": float(g.get("variable_cost_usd_per_mwh", 0.0)),
                "ramp_rate_mw_per_h": float(ramp) if ramp is not None else None,
                "emission_factor_t_per_mwh": ef,
                "disruptable": True,
            }
        )

    # 4. Batteries (CatalogBattery)
    batteries = []
    for b in scen.get("batteries", []):
        bid = b["id"]
        p_cap = float(b["power_capacity_mw"])
        e_cap = float(b["energy_capacity_mwh"])
        batteries.append(
            {
                "id": bid,
                "name": BAT_NAMES.get(bid, bid),
                "node_id": b["node_id"],
                "power_capacity_mw": p_cap,
                "power_mw": p_cap,
                "energy_capacity_mwh": e_cap,
                "energy_mwh": e_cap,
                "initial_soc_mwh": float(b.get("initial_soc_mwh", 0.0)),
                "standby": bool(b.get("standby", False)),
            }
        )

    observed_shape = (scen.get("day_profile") or {}).get("method") == "scaled-observed-shape"
    catalog: dict[str, Any] = {
        "scenario_id": scenario_id,
        "nodes": nodes,
        "lines": lines,
        "generators": generators,
        "batteries": batteries,
        "levers": LEVERS,
        "stress_recipes": STRESS_RECIPES,
        "jury_cards": JURY_CARDS,
        "assumptions": dict(ASSUMPTIONS),
        "day_profile": dict(scen.get("day_profile") or SYNTHETIC_DAY_PROFILE),
        "provenance": {
            "nodes_coordinates": "derived",
            "households_per_mw": "assumption",
            "households_total": "assumption",
            "generators": "synthetic",
            "batteries": "synthetic",
            "lines": "synthetic",
            "demand_mw": "derived" if observed_shape else "synthetic",
            "renewable_availability_mw": "derived" if observed_shape else "synthetic",
            "emission_factors": "assumption",
        },
    }

    return catalog
