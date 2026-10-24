"""Turn the raw SIP snapshot (data/raw/cen-sip) into compact files the demo can load directly.

Outputs, all labelled observed (Coordinador Eléctrico Nacional, SIP API):
- data/processed/cen-sip/day-<date>.json: hourly system totals, generation by technology and
  hourly output of every plant that generated that day.
- data/processed/cen-sip/daily-sums.json: daily energy by technology for the context windows.
No network access; reads only what scripts/cen_sip_snapshot.py downloaded.
"""

import gzip
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "cen-sip"
OUT = ROOT / "data" / "processed" / "cen-sip"
SOURCE = {
    "provenance": "observed",
    "publisher": "Coordinador Eléctrico Nacional (SIP API)",
    "raw_manifest": "data/raw/cen-sip/manifest.json",
}


def rows(dataset):
    out = []
    for page in sorted((RAW / dataset).glob("page-*.json.gz")):
        data = json.loads(gzip.decompress(page.read_bytes()))
        out += data["data"] if isinstance(data, dict) and "data" in data else [data]
    return out


def hour_index(hora):
    """SIP hours are labelled 1..24 (hour ending); index 0 is 00:00–01:00 local time."""
    h = int(hora)
    if not 1 <= h <= 24:
        raise ValueError(f"unexpected hour label {hora}")
    return h - 1


def day(date):
    plants = {}
    by_tech = defaultdict(lambda: [0.0] * 24)
    for r in rows(f"generacion-real/{date}"):
        i = hour_index(r["hora"])
        p = plants.setdefault(r["id_central"], {
            "id_central": r["id_central"], "name": r["central"],
            "technology": r["tipo_tecnologia"], "subtechnology": r.get("subtipo_tecnologia"),
            "pmax_mw": float(r["potencia_maxima"]) if r.get("potencia_maxima") not in (None, "") else None,
            "mw": [0.0] * 24,
        })
        mw = float(r["gen_real_mw"] or 0)
        p["mw"][i] += mw
        by_tech[r["tipo_tecnologia"]][i] += mw

    system = {"gen_bruta_mwh": [None] * 24, "demanda_neta_mwh": [None] * 24, "gen_erv_mwh": [None] * 24}
    for r in rows(f"demanda-neta/{date}"):
        i = hour_index(r["hora"])
        for k in system:
            system[k][i] = r[k]

    total = [round(sum(t[i] for t in by_tech.values()), 1) for i in range(24)]
    return {
        **SOURCE,
        "date": date,
        "timezone": "America/Santiago (SIP hour labels 1–24, hour ending)",
        "system": system,
        "generation_total_mw": total,
        "generation_by_technology_mw": {k: [round(x, 1) for x in v] for k, v in sorted(by_tech.items())},
        "plants": sorted(
            ({**p, "mw": [round(x, 2) for x in p["mw"]]} for p in plants.values() if any(p["mw"])),
            key=lambda p: -max(p["mw"]),
        ),
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for folder in sorted((RAW / "generacion-real").iterdir()):
        if (RAW / "demanda-neta" / folder.name).exists():
            data = day(folder.name)
            (OUT / f"day-{folder.name}.json").write_text(json.dumps(data, ensure_ascii=False) + "\n")
            print(f"day-{folder.name}: {len(data['plants'])} plants, peak {max(data['generation_total_mw'])} MW")
    sums = {}
    for folder in sorted((RAW / "daily-sum").glob("*")):
        (data,) = [json.loads(gzip.decompress(p.read_bytes())) for p in folder.glob("page-*.json.gz")]
        sums[folder.name] = {d["key"]: d["value"] for d in data["data"]}
    if sums:
        (OUT / "daily-sums.json").write_text(json.dumps({**SOURCE, "unit": "MWh per day", "days": sums}, ensure_ascii=False, indent=1) + "\n")
        print(f"daily-sums: {len(sums)} days")


if __name__ == "__main__":
    main()
