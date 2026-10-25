"""Map every CEN demand bus (barra) of 2026-08-14 to one of the 5 SEN zones.

Offline and deterministic (stdlib only, never touches the network). Reads:
- data/raw/cen-sip/demanda-real-estimada/2026-08-14/page-*.json.gz  (demand rows, signed kWh)
- data/raw/cen-sip/centrales/page-0001.json.gz                       (plant catalogue)

Writes data/processed/cen-sip/bus-zone-2026-08-14.csv with columns
barra,zone,method,confidence,energy_mwh (sorted by energy, descending).

Methods, in order:
1. catalog  (confidence high): the bus name matches a plant connection point (`punto_conexion`)
   of the catalogue; the zone is the zone of the majority region of those plants.
2. keyword  (confidence medium): hand-written table of Chilean substations and cities below.
3. topology (confidence medium): the bus is one end of a transmission line whose other end is
   already mapped, and every mapped neighbour sits in the same zone. Lines come from the CEN
   transmission-line catalogue (`nombre` = "END A - END B 220KV").
4. unknown  (confidence none): anything left. Never guessed silently.

Energy per bus = sum of |medida_kwh| over all rows of the bus, in MWh. Absolute values are used
because withdrawals are signed negative. This is an allocation key, not a metered total.
"""

from __future__ import annotations

import csv
import glob
import gzip
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMAND_DIR = ROOT / "data/raw/cen-sip/demanda-real-estimada/2026-08-14"
CATALOG_PATH = ROOT / "data/raw/cen-sip/centrales/page-0001.json.gz"
LINES_PATH = ROOT / "data/raw/cen-sip/lineas-transmision/page-0001.json.gz"
OUT_PATH = ROOT / "data/processed/cen-sip/bus-zone-2026-08-14.csv"

ZONES = ("n_norte_grande", "n_norte_chico", "n_centro", "n_centro_sur", "n_sur")
REGION_TO_ZONE = {
    "Arica y Parinacota": "n_norte_grande",
    "Tarapacá": "n_norte_grande",
    "Antofagasta": "n_norte_grande",
    "Atacama": "n_norte_chico",
    "Coquimbo": "n_norte_chico",
    "Valparaíso": "n_centro",
    "Metropolitana de Santiago": "n_centro",
    "Libertador General Bernardo O'Higgins": "n_centro",
    "Maule": "n_centro_sur",
    "Ñuble": "n_centro_sur",
    "Biobío": "n_centro_sur",
    "La Araucanía": "n_sur",
    "Los Ríos": "n_sur",
    "Los Lagos": "n_sur",
    "Aysén del General Carlos Ibáñez del Campo": "n_sur",
}

# Hand-written substation / city names (normalised: upper case, no accents, no punctuation).
# Each key is the bus base name with dots and spaces removed, so "D.ALMAGRO" and
# "DIEGO DE ALMAGRO" both reach the same zone through their own keys.
KEYWORD_ZONE = {
    # Norte Grande: Arica y Parinacota, Tarapacá, Antofagasta
    "ARICA": "n_norte_grande",
    "CDARICA": "n_norte_grande",
    "AHOSPICIO": "n_norte_grande",
    "PARINACOTA": "n_norte_grande",
    "POZOALMONTE": "n_norte_grande",
    "PALMONTE": "n_norte_grande",
    "TARAPACA": "n_norte_grande",
    "CRUCERO": "n_norte_grande",
    "LAGUNAS": "n_norte_grande",
    "NUEVACHUQUICAMATA": "n_norte_grande",
    "CHUQUICAMATA": "n_norte_grande",
    "CALAMA": "n_norte_grande",
    "ANTOFAGASTA": "n_norte_grande",
    "MEJILLONES": "n_norte_grande",
    "TOCOPILLA": "n_norte_grande",
    "CTAMAYA": "n_norte_grande",
    "CDTAMAYA": "n_norte_grande",
    "KM6": "n_norte_grande",
    "RTOMIC": "n_norte_grande",
    "MMH": "n_norte_grande",
    "CELPACIFICO": "n_sur",
    "SGORDA": "n_norte_grande",
    "SALAR": "n_norte_grande",
    "CENTELLA": "n_norte_grande",
    "ENCUENTRO": "n_norte_grande",
    "COLLAHUASI": "n_norte_grande",
    "PALLATA": "n_norte_grande",
    "MINERO": "n_norte_grande",
    "ESCONDIDA": "n_norte_grande",
    "COLOSO": "n_norte_grande",
    "ATACAMA": "n_norte_chico",
    # Norte Chico: Atacama, Coquimbo
    "DIEGODEALMAGRO": "n_norte_chico",
    "DALMAGRO": "n_norte_chico",
    "CARDONES": "n_norte_chico",
    "COPIAPO": "n_norte_chico",
    "VALLENAR": "n_norte_chico",
    "HUASCO": "n_norte_chico",
    "MAITENCILLO": "n_norte_chico",
    "PANDEAZUCAR": "n_norte_chico",
    "PAZUCAR": "n_norte_chico",
    "LASERENA": "n_norte_chico",
    "OVALLE": "n_norte_chico",
    "LOSVILOS": "n_norte_chico",
    "LVILOS": "n_norte_chico",
    "ILLAPEL": "n_norte_chico",
    "COMBARBALA": "n_norte_chico",
    "PUNITAQUI": "n_norte_chico",
    "ANDACOLLO": "n_norte_chico",
    "PAIHUANO": "n_norte_chico",
    "CHANARAL": "n_norte_chico",
    "CALDERA": "n_norte_chico",
    # Centro: Valparaíso, Metropolitana, O'Higgins
    "QUILLOTA": "n_centro",
    "POLPAICO": "n_centro",
    "ALTOJAHUEL": "n_centro",
    "AJAHUEL": "n_centro",
    "CERRONAVIA": "n_centro",
    "LOAGUIRRE": "n_centro",
    "CHENA": "n_centro",
    "RANCAGUA": "n_centro",
    "SANFERNANDO": "n_centro",
    "VALPARAISO": "n_centro",
    "SANANTONIO": "n_centro",
    "SANTONIO": "n_centro",
    "SANTIAGO": "n_centro",
    "MAIPU": "n_centro",
    "PUDAHUEL": "n_centro",
    "CHACABUCO": "n_centro",
    "LAMPA": "n_centro",
    "VITACURA": "n_centro",
    "LAREINA": "n_centro",
    "APOQUINDO": "n_centro",
    "SANJOAQUIN": "n_centro",
    "SJOAQUIN": "n_centro",
    "LMAQUIS": "n_centro",
    "SANCRISTOBAL": "n_centro",
    "BATUCO": "n_centro",
    "MACUL": "n_centro",
    "SANPABLO": "n_centro",
    "LOBOZA": "n_centro",
    "RECOLETA": "n_centro",
    "SANJOSE": "n_centro",
    "LACISTERNA": "n_centro",
    "SANBERNARDO": "n_centro",
    "BUIN": "n_centro",
    "PAINE": "n_centro",
    "MELIPILLA": "n_centro",
    "CASABLANCA": "n_centro",
    "LOVALLEDOR": "n_centro",
    "ALTAMIRANO": "n_centro",
    "PIRQUE": "n_centro",
    "CERRILLOS": "n_centro",
    "CHIMBARONGO": "n_centro",
    "SANTAROSA": "n_centro",
    "SANTAROSAS": "n_centro",
    "ADECORDOVA": "n_centro",
    "ALONSODECORDOVA": "n_centro",
    "SANTARAQUEL": "n_centro",
    "SANTAELENA": "n_centro",
    "PAJARITOS": "n_centro",
    "LOSDOMINICOS": "n_centro",
    "CLUBHIPICO": "n_centro",
    "LASCONDES": "n_centro",
    "CONCHALI": "n_centro",
    "CHICUREO": "n_centro",
    "LOSMAQUIS": "n_centro",
    "LAPINTANA": "n_centro",
    "LAPINTANA2": "n_centro",
    "ISLADMAIPO": "n_centro",
    "NANCAGUA": "n_centro",
    "CACHAPOAL": "n_centro",
    "PAPUDO": "n_centro",
    "LOSANDES": "n_centro",
    "LOANDES": "n_centro",
    # Centro Sur: Maule, Ñuble, Biobío
    "ITAHUE": "n_centro_sur",
    "TALCA": "n_centro_sur",
    "LINARES": "n_centro_sur",
    "CHILLAN": "n_centro_sur",
    "CHARRUA": "n_centro_sur",
    "CONCEPCION": "n_centro_sur",
    "HUALPEN": "n_centro_sur",
    "LOSANGELES": "n_centro_sur",
    "CURICO": "n_centro_sur",
    "CURICO2": "n_centro_sur",
    "MELIPULLI": "n_centro_sur",
    "PARRAL": "n_centro_sur",
    "CAUQUENES": "n_centro_sur",
    "CONSTIT": "n_centro_sur",
    "CONSTITUCION": "n_centro_sur",
    "LICANTEN": "n_centro_sur",
    "MAULE": "n_centro_sur",
    "CABRERO": "n_centro_sur",
    "TUCAPEL": "n_centro_sur",
    "LOTA": "n_centro_sur",
    "CORONEL": "n_centro_sur",
    "LEBU": "n_centro_sur",
    "PENCO": "n_centro_sur",
    "CURANILAHUE": "n_centro_sur",
    "CANETE": "n_centro_sur",
    "PANGUILEMO": "n_centro_sur",
    "CHIGUAYANTE": "n_centro_sur",
    "COLBUN": "n_centro_sur",
    "SANNICOLAS": "n_centro_sur",
    "QUIRIHUE": "n_centro_sur",
    "ANCOA": "n_centro_sur",
    "VICTORIA": "n_sur",
    # Sur: La Araucanía, Los Ríos, Los Lagos, Aysén
    "TEMUCO": "n_sur",
    "CAUTIN": "n_sur",
    "PITRUFQUEN": "n_sur",
    "VILLARRICA": "n_sur",
    "PUCON": "n_sur",
    "ANGOL": "n_sur",
    "LAUTARO": "n_sur",
    "LLAIMA": "n_sur",
    "CUNCO": "n_sur",
    "MELIPEUCO": "n_sur",
    "CURACAUTIN": "n_sur",
    "COLLIPULLI": "n_sur",
    "VALDIVIA": "n_sur",
    "LOSRIOS": "n_sur",
    "PANGUIPULLI": "n_sur",
    "LANCO": "n_sur",
    "LONCOCHE": "n_sur",
    "LONCOCHE2": "n_sur",
    "PAILLACO": "n_sur",
    "OSORNO": "n_sur",
    "PUERTOMONTT": "n_sur",
    "PMONTT": "n_sur",
    "PUERTOVARAS": "n_sur",
    "PVARAS": "n_sur",
    "FRUTILLAR": "n_sur",
    "LLANQUIHUE": "n_sur",
    "CALBUCO": "n_sur",
    "ANCUD": "n_sur",
    "CHONCHI": "n_sur",
    "CASTRO": "n_sur",
    "DALCAHUE": "n_sur",
    "QUELLON": "n_sur",
    "PUERTOAYSEN": "n_sur",
    "COYHAIQUE": "n_sur",
    "AYSEN": "n_sur",
}


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalise_tokens(text: str) -> list[str]:
    """Upper-case, accents removed, every non-alphanumeric character is a separator."""
    return re.findall(r"[A-Z0-9]+", strip_accents(text).upper())


def bus_base(barra: str) -> str:
    """Drop trailing voltage (e.g. `______220`, ` 110`) and return the base name."""
    base = re.sub(r"_+\d{2,3}$", "", barra.strip())
    base = re.sub(r"\s+\d{2,3}$", "", base)
    return base


def bus_compact(base: str) -> str:
    return "".join(normalise_tokens(base))


def load_rows() -> list[dict]:
    rows: list[dict] = []
    for path in sorted(glob.glob(str(DEMAND_DIR / "page-*.json.gz"))):
        with gzip.open(path, "rb") as fh:
            payload = json.load(fh)
        rows.extend(payload if isinstance(payload, list) else payload["data"])
    return rows


def load_lines() -> list[dict]:
    with gzip.open(LINES_PATH, "rb") as fh:
        payload = json.load(fh)
    return payload if isinstance(payload, list) else payload["data"]


def load_catalog() -> list[dict]:
    with gzip.open(CATALOG_PATH, "rb") as fh:
        payload = json.load(fh)
    return payload if isinstance(payload, list) else payload["data"]


def build_catalog_index(catalog: list[dict]) -> dict[tuple[str, ...], Counter]:
    """Map every contiguous token run of a connection point to a Counter of plant regions."""
    by_point: dict[str, Counter] = defaultdict(Counter)
    for plant in catalog:
        point = (plant.get("punto_conexion") or "").strip()
        region = (plant.get("region") or "").strip()
        if point and region in REGION_TO_ZONE:
            by_point[point][region] += 1
    index: dict[tuple[str, ...], Counter] = defaultdict(Counter)
    for point, regions in by_point.items():
        tokens = normalise_tokens(point)
        for size in range(1, min(len(tokens), 6) + 1):
            for start in range(len(tokens) - size + 1):
                key = tuple(tokens[start : start + size])
                index[key].update(regions)
    return index


def map_by_catalog(base: str, index: dict[tuple[str, ...], Counter]) -> str | None:
    tokens = tuple(normalise_tokens(base))
    if not tokens or len("".join(tokens)) < 4:
        return None
    regions = index.get(tokens)
    if not regions:
        return None
    region, _ = regions.most_common(1)[0]
    return REGION_TO_ZONE[region]


def map_by_keyword(base: str) -> str | None:
    return KEYWORD_ZONE.get(bus_compact(base))


def line_endpoints(name: str) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    """Split a transmission line name "END A - END B 220KV" into two token tuples."""
    if " - " not in name:
        return None
    left, right = name.split(" - ", 1)
    ends = []
    for part in (left, right):
        part = re.sub(r"\[[^\]]*\]", "", part)
        part = re.sub(r"\s+\d+\s*KV.*$", "", part, flags=re.IGNORECASE)
        part = re.sub(r"^(TAP OFF|TAP|S/E)\s+", "", part.strip(), flags=re.IGNORECASE)
        ends.append(tuple(normalise_tokens(part)))
    if not all(ends):
        return None
    return ends[0], ends[1]


def map_by_topology(
    unmapped: set[tuple[str, ...]],
    mapped: dict[tuple[str, ...], str],
    lines: list[dict],
) -> dict[tuple[str, ...], str]:
    """Zone of an unmapped bus when all its mapped line neighbours agree on one zone."""
    neighbours: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for line in lines:
        ends = line_endpoints(line.get("nombre") or "")
        if ends is None:
            continue
        a, b = ends
        for near, far in ((a, b), (b, a)):
            if near in unmapped and far in mapped:
                neighbours[near].add(mapped[far])
    return {key: zones.pop() for key, zones in neighbours.items() if len(zones) == 1}


def main() -> int:
    rows = load_rows()
    catalog = load_catalog()
    index = build_catalog_index(catalog)

    energy_kwh: dict[str, float] = defaultdict(float)
    for row in rows:
        value = row.get("medida_kwh")
        if value is None or value == "":
            continue
        energy_kwh[row["barra"]] += abs(float(value))

    lines = load_lines()
    bases = {barra: bus_base(barra) for barra in energy_kwh}
    zone_of: dict[str, tuple[str, str, str]] = {}
    for barra, base in bases.items():
        zone = map_by_catalog(base, index)
        if zone:
            zone_of[barra] = (zone, "catalog", "high")
            continue
        zone = map_by_keyword(base)
        if zone:
            zone_of[barra] = (zone, "keyword", "medium")

    # Topology passes until nothing new: keyed by the base-name tokens, so one name counts once.
    while True:
        mapped = {tuple(normalise_tokens(bases[b])): z[0] for b, z in zone_of.items()}
        unmapped = {tuple(normalise_tokens(bases[b])) for b in energy_kwh if b not in zone_of}
        inferred = map_by_topology(unmapped, mapped, lines)
        added = 0
        for barra in energy_kwh:
            if barra in zone_of:
                continue
            zone = inferred.get(tuple(normalise_tokens(bases[barra])))
            if zone:
                zone_of[barra] = (zone, "topology", "medium")
                added += 1
        if not added:
            break

    results = []
    for barra, kwh in energy_kwh.items():
        zone, method, confidence = zone_of.get(barra, ("unknown", "none", "none"))
        results.append((barra, zone, method, confidence, kwh / 1000.0))

    results.sort(key=lambda r: (-r[4], r[0]))
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["barra", "zone", "method", "confidence", "energy_mwh"])
        for barra, zone, method, confidence, mwh in results:
            writer.writerow([barra, zone, method, confidence, f"{mwh:.3f}"])

    total = sum(r[4] for r in results)
    known = sum(r[4] for r in results if r[1] != "unknown")
    print(f"buses: {len(results)}  total energy: {total:.1f} MWh")
    print(f"coverage (energy with a known zone): {known / total:.4%}")
    for zone in ZONES:
        share = sum(r[4] for r in results if r[1] == zone) / total
        print(f"  {zone:<16} {share:7.2%}")
    unknown = [r for r in results if r[1] == "unknown"]
    if unknown:
        print(f"unknown buses: {len(unknown)}; top 10 by energy:")
        for barra, _, _, _, mwh in unknown[:10]:
            print(f"  {barra:<24} {mwh:10.1f} MWh")
    print(f"wrote {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
