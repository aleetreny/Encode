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
    "label_es": "Día sintético con forma chilena",
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
    "solar_ng": "Solar Crucero Norte Grande",
    "solar_nc": "Solar Atacama Norte Chico",
    "wind_nc": "Eólica Punta Palmeras",
    "gas_ng": "Ciclo Combinado Mejillones",
    "gas_centro": "Ciclo Combinado Nehuenco Centro",
    "coal_cs": "Termoeléctrica Santa María Coronel",
    "hydro_sur": "Embalse Ralco Chapo Sur",
    "wind_sur": "Parque Eólico Llanquihue",
    "diesel_centro": "Turbina Diésel Respaldo Renca",
}

BAT_NAMES = {
    "b_centro": "BESS Polpaico Operativo",
    "b_reserve_ng": "BESS Reserva Crucero Norte Grande",
    "b_reserve_centro": "BESS Reserva Polpaico Centro",
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
        "label_es": "Límite Térmico de Emergencia",
        "description_es": "Incrementa temporalmente la capacidad de transporte de una línea troncal durante la ventana crítica.",
    },
    {
        "type": "demand_response",
        "label_es": "Respuesta de Demanda Industrial",
        "description_es": "Recorte voluntario de carga industrial compensada sin desconectar hogares residenciales.",
    },
    {
        "type": "activate_reserve_bess",
        "label_es": "Activar BESS de Reserva en Standby",
        "description_es": "Conecta bancos de baterías estratégicos en reserva para inyectar potencia inmediata.",
    },
    {
        "type": "hydro_reserve_release",
        "label_es": "Liberación de Reserva Hídrica",
        "description_es": "Despacha cota adicional de embalse en el sur valorizando el costo de oportunidad del agua.",
    },
    {
        "type": "start_peaker",
        "label_es": "Arranque de Turbina Rápida (Peaker)",
        "description_es": "Inicia unidad térmica de respaldo rápido con retraso de sincronización desde frío.",
    },
    {
        "type": "add_battery",
        "label_es": "Almacenamiento BESS (Planificación)",
        "description_es": "Incorpora capacidad de almacenamiento para arbitraje solar y soporte de punta.",
    },
    {
        "type": "uprate_line",
        "label_es": "Ampliación de Corredor Troncal",
        "description_es": "Aumenta la capacidad nominal permanente de una línea de transmisión congestionada.",
    },
]

STRESS_RECIPES: list[dict[str, Any]] = [
    {
        "id": "terremoto_norte",
        "title_es": "Terremoto Norte Grande",
        "description_es": "Sismo severo desconecta corredor L1 y ciclo combinado del norte.",
        "events": [
            {"type": "line_outage", "id": "L1", "duration_hours": 4, "mode": "sudden"},
            {"type": "generator_outage", "id": "gas_ng", "duration_hours": 4, "mode": "sudden"},
        ],
    },
    {
        "id": "incendio_forestal_centro_sur",
        "title_es": "Incendio Forestal Centro-Sur",
        "description_es": "Incendio bajo corredor 500 kV dispara troncal L3 entre Polpaico y Charrúa.",
        "events": [
            {"type": "line_outage", "id": "L3", "duration_hours": 4, "mode": "sudden"},
        ],
    },
    {
        "id": "sequia_hidrica_sur",
        "title_es": "Sequía Hídrica Sur",
        "description_es": "Indisponibilidad de embalse en el sur durante rampa vespertina.",
        "events": [
            {"type": "generator_outage", "id": "hydro_sur", "duration_hours": 6, "mode": "sudden"},
        ],
    },
    {
        "id": "ola_calor_santiago",
        "title_es": "Ola de Calor en Santiago",
        "description_es": "Disparo de central térmica principal en pleno peak vespertino metropolitano.",
        "events": [
            {"type": "generator_outage", "id": "gas_centro", "duration_hours": 4, "mode": "sudden"},
        ],
    },
]

JURY_CARDS: list[dict[str, Any]] = [
    {
        "id": "trip_gas_centro",
        "title_es": "Derribar Central Gas Centro",
        "subtitle_es": "Saca 600 MW térmicos en Polpaico por 4 horas",
        "action": {
            "type": "generator_outage",
            "id": "gas_centro",
            "duration_hours": 4,
        },
    },
    {
        "id": "trip_l2",
        "title_es": "Cortar Troncal L2 Norte-Centro",
        "subtitle_es": "Abre corredor de 400 MW entre Cardones y Polpaico",
        "action": {
            "type": "line_outage",
            "id": "L2",
            "duration_hours": 4,
        },
    },
    {
        "id": "trip_l3",
        "title_es": "Cortar Troncal L3 Centro-Sur",
        "subtitle_es": "Abre línea de 350 MW entre Polpaico y Charrúa",
        "action": {
            "type": "line_outage",
            "id": "L3",
            "duration_hours": 4,
        },
    },
    {
        "id": "trip_coal_cs",
        "title_es": "Disparar Carbonera Centro-Sur",
        "subtitle_es": "Desconecta 350 MW base en Charrúa por 4 horas",
        "action": {
            "type": "generator_outage",
            "id": "coal_cs",
            "duration_hours": 4,
        },
    },
    {
        "id": "stress_terremoto",
        "title_es": "Simular Terremoto Norte",
        "subtitle_es": "Falla simultánea de L1 y Gas Norte Grande",
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
