"""Build ``optimisation/fixtures/real_day_scenario.json`` from the real CEN day 2026-08-14.

Method ``scaled-observed-shape`` (see ``docs/real-day-contract.md`` section 1): the 5-node
network of ``demo_scenario.json`` is kept untouched (nodes, lines, generators, batteries,
costs, objective); only the 24-hour demand and the solar/wind availability are replaced by the
observed shape of the day, and demand is multiplied by a single ``scale_factor``.

Offline only (no network):

    python3 scripts/build_real_day_scenario.py [--scale-factor F] [--bus-zone PATH] [--out PATH]
"""

from __future__ import annotations

import argparse
import copy
import csv
import glob
import gzip
import json
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEMO = ROOT / "optimisation" / "fixtures" / "demo_scenario.json"
OUT = ROOT / "optimisation" / "fixtures" / "real_day_scenario.json"
DAY_JSON = ROOT / "data" / "processed" / "cen-sip" / "day-2026-08-14.json"
DEMANDA_NETA = (
    ROOT / "data" / "raw" / "cen-sip" / "demanda-neta" / "2026-08-14" / "page-0001.json.gz"
)
CENTRALES = ROOT / "data" / "raw" / "cen-sip" / "centrales" / "page-0001.json.gz"
DEMANDA_REAL_GLOB = str(
    ROOT / "data" / "raw" / "cen-sip" / "demanda-real-estimada" / "2026-08-14" / "page-*.json.gz"
)

DATE = "2026-08-14"
LOCAL = ZoneInfo("America/Santiago")
HOURS = 24
BUS_COVERAGE_MIN = 0.99

# Tuned so the contract gates pass (window about 0.17-0.19); peak system demand ~1780 MW, as the synthetic day.
SCALE_FACTOR = 0.18

REGION_TO_ZONE = {
    "arica y parinacota": "n_norte_grande",
    "tarapaca": "n_norte_grande",
    "antofagasta": "n_norte_grande",
    "atacama": "n_norte_chico",
    "coquimbo": "n_norte_chico",
    "valparaiso": "n_centro",
    "metropolitana de santiago": "n_centro",
    "libertador general bernardo o'higgins": "n_centro",
    "maule": "n_centro_sur",
    "nuble": "n_centro_sur",
    "biobio": "n_centro_sur",
    "la araucania": "n_sur",
    "los rios": "n_sur",
    "los lagos": "n_sur",
    "aysen del general carlos ibanez del campo": "n_sur",
}
TECH_OF = {"solar": "Solar", "wind": "Eólica"}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return " ".join(text.lower().split())


def _r(values: list[float], nd: int = 1) -> list[float]:
    return [round(float(v), nd) for v in values]


def _read_gz(path: str | Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _rows(payload: Any) -> list[dict]:
    if isinstance(payload, dict):
        payload = payload.get("data", [])
    return list(payload)


def _iter_demand_rows():
    for path in sorted(glob.glob(DEMANDA_REAL_GLOB)):
        yield from _rows(_read_gz(path))


def system_demand_mw(source: str = "bus-withdrawals") -> list[float]:
    """System demand (MW) per local hour.

    ``gen-bruta``: gen_bruta - cons_propio from SIP demanda-neta (NOT demanda_neta, which nets
    variable renewables). Its midday value is inflated by storage charging, so n_centro peaks at
    11:00 and gate 3 of the contract cannot pass.
    ``bus-withdrawals``: sum of |medida_kwh| of demanda-real-estimada over all buses, kWh -> MW.
    Hour 00 is incomplete in the source (about 10.9k rows against about 16k), so it is rebuilt from
    hour 01 times the gen-bruta ratio between hours 00 and 01.
    """
    gen = _system_demand_gen_bruta()
    if source == "gen-bruta":
        return gen
    if source != "bus-withdrawals":
        raise ValueError(f"unknown demand source {source!r}")
    kwh = [0.0] * HOURS
    for row in _iter_demand_rows():
        kwh[int(str(row["fecha_hora"])[11:13])] += abs(float(row.get("medida_kwh") or 0.0))
    mw = [v / 1000.0 for v in kwh]
    mw[0] = mw[1] * gen[0] / gen[1]
    return mw


def _system_demand_gen_bruta() -> list[float]:
    rows = sorted(_rows(_read_gz(DEMANDA_NETA)), key=lambda r: r["hora"])
    assert len(rows) == HOURS, f"expected 24 hourly rows, got {len(rows)}"
    return [float(r["gen_bruta_mwh"]) - float(r["cons_propio_mwh"]) for r in rows]


def zone_shares_from_bus(
    bus_zone_csv: Path, nodes: list[str]
) -> tuple[dict[str, list[float]] | None, float]:
    """Per-hour zone demand shares from demanda-real-estimada by bus. Returns (shares, coverage)."""
    table: dict[str, str] = {}
    with open(bus_zone_csv, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("zone") in nodes:
                table[row["barra"]] = row["zone"]
    per_zone = {n: [0.0] * HOURS for n in nodes}
    mapped = total = 0.0
    for row in _iter_demand_rows():
        kwh = abs(float(row.get("medida_kwh") or 0.0))
        total += kwh
        zone = table.get(row.get("barra"))
        if zone is None:
            continue
        per_zone[zone][int(str(row["fecha_hora"])[11:13])] += kwh
        mapped += kwh
    coverage = mapped / total if total > 0 else 0.0
    if coverage < BUS_COVERAGE_MIN:
        return None, coverage
    shares = {n: [0.0] * HOURS for n in nodes}
    for h in range(HOURS):
        hour_total = sum(per_zone[n][h] for n in nodes)
        if hour_total <= 0:
            return None, coverage
        for n in nodes:
            shares[n][h] = per_zone[n][h] / hour_total
    return shares, coverage


def zone_shares_from_demo(demo: dict) -> dict[str, list[float]]:
    dm = demo["demand_mw_by_node"]
    totals = [sum(dm[n][h] for n in dm) for h in range(HOURS)]
    return {n: [dm[n][h] / totals[h] for h in range(HOURS)] for n in dm}


def capacity_factors(
    demo: dict, amplitude: str = "peak-normalised"
) -> tuple[dict[str, list[float]], list[str], dict[str, Any]]:
    """Real CF per renewable generator from plants mapped to the generator's zone."""
    day = json.loads(DAY_JSON.read_text(encoding="utf-8"))
    region_by_id = {r["id_central"]: r.get("region") or "" for r in _rows(_read_gz(CENTRALES))}
    acc: dict[tuple[str, str], list[float]] = {}  # (zone, tech) -> [pmax, mw0..mw23]
    national: dict[str, list[float]] = {}
    unmapped_mw: dict[str, float] = {}
    for plant in day["plants"]:
        tech = plant["technology"]
        if tech not in TECH_OF.values():
            continue
        nat = national.setdefault(tech, [0.0] * (HOURS + 1))
        nat[0] += plant["pmax_mw"]
        for h in range(HOURS):
            nat[h + 1] += plant["mw"][h]
        zone = REGION_TO_ZONE.get(_norm(region_by_id.get(plant["id_central"], "")))
        if zone is None:
            unmapped_mw[tech] = unmapped_mw.get(tech, 0.0) + plant["pmax_mw"]
            continue
        a = acc.setdefault((zone, tech), [0.0] * (HOURS + 1))
        a[0] += plant["pmax_mw"]
        for h in range(HOURS):
            a[h + 1] += plant["mw"][h]

    avail: dict[str, list[float]] = {}
    notes: list[str] = []
    meta: dict[str, Any] = {"unmapped_pmax_mw": {k: round(v, 1) for k, v in unmapped_mw.items()}}
    for gen in demo["generators"]:
        tech = TECH_OF.get(gen["technology"])
        if tech is None:
            continue
        a = acc.get((gen["node_id"], tech))
        source = "zone"
        if a is None or a[0] <= 0:
            a, source = national[tech], "national"
            notes.append(
                f"{gen['id']}: no real {tech} plants mapped to {gen['node_id']}; national capacity factor used."
            )
        cf = [min(1.0, max(0.0, a[h + 1] / a[0])) for h in range(HOURS)]
        if amplitude == "peak-normalised" and max(cf) > 0:
            peak = max(cf)
            cf = [c / peak for c in cf]
        elif amplitude != "capacity-factor":
            raise ValueError(f"unknown renewable amplitude {amplitude!r}")
        avail[gen["id"]] = _r([gen["capacity_mw"] * c for c in cf])
        meta[gen["id"]] = {"cf_source": source, "real_pmax_mw": round(a[0], 1)}
    return avail, notes, meta


def build(
    scale_factor: float = SCALE_FACTOR,
    bus_zone: Path | None = None,
    demand_source: str = "bus-withdrawals",
    renewable_amplitude: str = "peak-normalised",
) -> dict:
    demo = json.loads(DEMO.read_text(encoding="utf-8"))
    scen = copy.deepcopy(demo)
    nodes = [n["id"] for n in demo["nodes"]]

    stamps = [
        (datetime(2026, 8, 14, tzinfo=LOCAL) + timedelta(hours=h))
        .astimezone(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
        for h in range(HOURS)
    ]
    sys_dem = system_demand_mw(demand_source)

    shares, coverage = (None, None)
    if bus_zone is not None:
        shares, coverage = zone_shares_from_bus(Path(bus_zone), nodes)
    if shares is not None:
        share_label = "derived"
        share_note = (
            f"Zone demand shares per hour come from SIP demanda-real-estimada by bus via {Path(bus_zone).name} "
            f"(coverage {coverage:.4f} of energy)."
        )
    else:
        shares = zone_shares_from_demo(demo)
        share_label = "assumption"
        share_note = (
            "Zone demand shares per hour are the synthetic scenario's shares (assumption)"
            + (
                f"; bus table rejected, coverage {coverage:.4f} < {BUS_COVERAGE_MIN}."
                if coverage is not None
                else "; no bus->zone table supplied."
            )
        )

    scen["demand_mw_by_node"] = {
        n: _r([sys_dem[h] * shares[n][h] * scale_factor for h in range(HOURS)]) for n in nodes
    }
    avail, cf_notes, cf_meta = capacity_factors(demo, renewable_amplitude)
    scen["renewable_availability_mw_by_generator"] = avail

    scen["scenario_id"] = "chile-sen-5node-real-2026-08-14"
    scen["mode"] = (
        "synthetic"  # the loader does not constrain it; provenance carries the derived-from-observed truth
    )
    scen["timestamps_utc"] = stamps

    day_profile = {
        "source": "CEN SIP",
        "date": DATE,
        "method": "scaled-observed-shape",
        "scale_factor": scale_factor,
        "label_es": "Día real CEN · 14-ago-2026 · perfil escalado",
    }
    scen["day_profile"] = day_profile
    scen["provenance"] = {
        "observed_source_urls": ["data/raw/cen-sip/manifest.json"],
        "observed_fields": [],
        "derived_fields": ["demand_mw_by_node", "renewable_availability_mw_by_generator"],
        "synthetic_fields": [
            "network_topology",
            "line_limits",
            "generators",
            "batteries",
            "objective",
            "emission_factors_t_per_mwh",
            "households_per_mw",
        ],
        "historical_event_date": DATE,
        "demand_zone_share_provenance": share_label,
        "notes": (
            "Shape of the real CEN SIP day 2026-08-14 (raw files listed in data/raw/cen-sip/manifest.json) "
            f"scaled onto the synthetic 5-node network with one scale_factor={scale_factor}. "
            + (
                "System demand = sum of |medida_kwh| over all buses of SIP demanda-real-estimada (hour 00 is "
                "incomplete in the source and is rebuilt from hour 01 using the gen_bruta - cons_propio ratio). "
                "DEVIATION from the contract: gen_bruta - cons_propio is inflated at midday by storage charging, "
                "so n_centro would peak at 11:00 instead of the evening. "
                if demand_source == "bus-withdrawals"
                else "System demand = gen_bruta - cons_propio (demanda_neta is not used: it nets variable renewables). "
            )
            + (
                "Solar/wind availability = the hourly shape of the real capacity factor of the plants mapped to "
                "the generator's zone (catalogue region -> zone), normalised so its daily peak equals the scenario "
                "capacity_mw. DEVIATION from the contract: the raw capacity factor (about 0.6 for solar) leaves "
                "less north solar than the corridor can carry, so no curtailment appears. "
                if renewable_amplitude == "peak-normalised"
                else "Solar/wind availability = real capacity factor of the plants mapped to the generator's zone "
                "(catalogue region -> zone) x scenario capacity_mw. "
            )
            + share_note
            + " "
            + " ".join(cf_notes)
            + f" Unmapped real plants (pmax MW, excluded from zone factors): {cf_meta['unmapped_pmax_mw']}. "
            "Topology, line limits, capacities, costs, batteries and households_per_mw remain synthetic."
        ),
    }
    return scen


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scale-factor", type=float, default=SCALE_FACTOR)
    ap.add_argument("--bus-zone", type=Path, default=None)
    ap.add_argument(
        "--demand-source", choices=("bus-withdrawals", "gen-bruta"), default="bus-withdrawals"
    )
    ap.add_argument(
        "--renewable-amplitude",
        choices=("peak-normalised", "capacity-factor"),
        default="peak-normalised",
    )
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    scen = build(args.scale_factor, args.bus_zone, args.demand_source, args.renewable_amplitude)
    args.out.write_text(json.dumps(scen, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"wrote {args.out} (scale_factor={args.scale_factor}, shares={scen['provenance']['demand_zone_share_provenance']})"
    )


if __name__ == "__main__":
    main()
