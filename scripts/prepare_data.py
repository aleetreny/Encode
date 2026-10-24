"""Reproduce the bundled CEN evidence; no network or credentials needed by default.

Fail closed on unknown layout/data changes, duplicates or broken daily/monthly controls.
Known missing markers remain null; published hourly-total anomalies are disclosed.
Read-only openpyxl extraction: the original workbook is never edited.
"""

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://www.coordinador.cl/wp-content/uploads/2026/10/Reducciones-de-Energia-Eolica-Solar-Hidro-en-el-SEN_Agosto-26-PE-PFV_Publicar.xlsx"
LANDING_URL = "https://www.coordinador.cl/operacion/documentos/reducciones-de-generacion-renovable/reducciones-erv-2026/"
SHEETS = {"solar": "Resumen-DiarioHorario-Solar", "wind": "Resumen-DiarioHorario-Eólico"}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def number(value, context):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"Missing, negative or invalid number: {context}")
    return float(value)


def extract(path):
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    records, controls, anomalies = [], [], []
    try:
        for technology, name in SHEETS.items():
            day, rows, total, header = None, [], None, False

            def finish():
                if day is None:
                    return
                if not rows or total is None:
                    raise ValueError(f"Incomplete day {day} in {name}")
                missing = sum(
                    v is None for r in rows for v in r["curtailed_energy_mwh_by_hour_label"]
                )
                if missing and day == "2026-08-01":
                    raise ValueError("Selected event contains missing observations")
                calculated = [
                    sum(
                        r["curtailed_energy_mwh_by_hour_label"][i]
                        for r in rows
                        if r["curtailed_energy_mwh_by_hour_label"][i] is not None
                    )
                    for i in range(24)
                ]
                hourly_residual = max(abs(a - b) for a, b in zip(calculated, total[0]))
                if hourly_residual > 1e-5 and day == "2026-08-01":
                    raise ValueError(f"Selected event hourly totals mismatch {day} {name}")
                if abs(sum(calculated) - total[1]) > 1e-5:
                    raise ValueError(f"Daily total mismatch {day} {name}")
                controls.append(
                    dict(
                        date=day,
                        technology=technology,
                        plant_count=len(rows),
                        hourly_mwh=calculated,
                        daily_mwh=sum(calculated),
                        source_daily_total_mwh=total[1],
                        source_hourly_total_max_residual_mwh=hourly_residual,
                        missing_observations=missing,
                        coverage="incomplete" if missing else "complete",
                    )
                )

            seen = set()
            for row_number, row in enumerate(workbook[name].values, 1):
                label = row[1]
                if isinstance(label, datetime):
                    finish()
                    day, rows, total, header = label.date().isoformat(), [], None, False
                elif label == "Central/Hora":
                    if list(row[4:28]) != list(range(1, 25)):
                        if (
                            name != "Resumen-DiarioHorario-Solar"
                            or day != "2026-08-10"
                            or list(row[4:28]) != [1, "|", *range(3, 25)]
                        ):
                            raise ValueError("Unexpected hourly header")
                        anomalies.append(
                            dict(
                                date=day,
                                technology=technology,
                                issue="Source hour-2 header is '|'. Values retained by column position, not silently relabelled.",
                            )
                        )
                    source_labels = list(row[4:28])
                    header = True
                elif day and header and isinstance(label, str) and label.strip():
                    values = [
                        None if v == "-" else number(v, f"{name}!{row_number} hour {i + 1}")
                        for i, v in enumerate(row[4:28])
                    ]
                    if label == "Total":
                        if total is not None:
                            raise ValueError("Duplicate total row")
                        total = values, number(row[28], "daily total")
                        continue
                    if total is not None:
                        raise ValueError("Plant appears after total row")
                    key = day, label
                    if key in seen:
                        raise ValueError(f"Duplicate plant/day {key}")
                    seen.add(key)
                    declared = number(row[29], "plant daily total")
                    if abs(sum(v for v in values if v is not None) - declared) > 1e-5:
                        raise ValueError("Plant total mismatch")
                    record = dict(
                        date=day,
                        technology=technology,
                        plant_id=label,
                        curtailed_energy_mwh_by_hour_label=values,
                        source_hour_labels=source_labels,
                        source_sheet=name,
                        source_row=row_number,
                        source_range=f"E{row_number}:AB{row_number}",
                    )
                    records.append(record)
                    rows.append(record)
            finish()
            dates = {c["date"] for c in controls if c["technology"] == technology}
            if dates != {f"2026-08-{d:02d}" for d in range(1, 32)}:
                raise ValueError("Expected complete August coverage")
        # Independent monthly control from a different workbook sheet.
        summary = list(workbook["Resumen-Mensual"].values)
        month_col = next(
            i for i, v in enumerate(summary[12]) if isinstance(v, datetime) and v.month == 8
        )
        reconciliation = {}
        for technology, source_row in (("solar", 15), ("wind", 14)):
            expected = number(summary[source_row - 1][month_col], "monthly GWh") * 1000
            actual = sum(c["daily_mwh"] for c in controls if c["technology"] == technology)
            if abs(expected - actual) > 1e-4:
                raise ValueError("Monthly reconciliation failed")
            reconciliation[technology] = dict(
                calculated_mwh=actual,
                summary_mwh=expected,
                residual_mwh=actual - expected,
                source_cell=f"{openpyxl.utils.get_column_letter(month_col + 1)}{source_row}",
            )
        return records, controls, reconciliation, anomalies
    finally:
        workbook.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--download", action="store_true", help="Explicitly refresh raw source over HTTPS"
    )
    args = parser.parse_args()
    path = ROOT / "data/raw/cen-2026-08.xlsx"
    manifest_path = ROOT / "data/raw/cen-2026-08.manifest.json"
    if args.download:
        with urlopen(
            Request(SOURCE_URL, headers={"User-Agent": "GridPilot-Hackathon/1.0"}), timeout=60
        ) as response:
            content = response.read(10_000_001)
        if len(content) > 10_000_000 or not content.startswith(b"PK"):
            raise ValueError("Not a supported XLSX or download too large")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Parse the candidate before replacing the known-good source.
        candidate = path.with_suffix(".download.xlsx")
        candidate.write_bytes(content)
        extract(candidate)
        candidate.replace(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if manifest_path.exists() and not args.download:
        if json.loads(manifest_path.read_text())["sha256"] != digest:
            raise ValueError("Raw source checksum mismatch")
    else:
        save(
            manifest_path,
            dict(
                source_id="cen-2026-08",
                publisher="Coordinador Eléctrico Nacional",
                source_url=SOURCE_URL,
                landing_url=LANDING_URL,
                publication_date_as_listed="2026-09-30",
                retrieved_at_utc=datetime.now(timezone.utc).isoformat(),
                sha256=digest,
                bytes=path.stat().st_size,
                units="MWh (daily/hourly); GWh (monthly summary)",
                source_timezone="America/Santiago (context; hourly boundary convention unverified)",
                license="Publicly downloadable; no explicit redistribution license established. Preserve attribution.",
                revision_note="Upload URL contains 2026/10; retain listed publication date separately.",
            ),
        )
    records, controls, reconciliation, anomalies = extract(path)
    processed = ROOT / "data/processed"
    processed.mkdir(parents=True, exist_ok=True)
    (processed / "cen-2026-08.plants.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    )
    save(
        processed / "cen-2026-08.quality.json",
        dict(
            source_sha256=digest,
            plant_day_records=len(records),
            day_technology_records=len(controls),
            checks=[
                "31 days per technology",
                "unique plant/day keys",
                "numeric nonnegative observations or explicit null for source '-'",
                "plant published totals versus sum of available cells",
                "complete selected event and its hourly totals",
                "published daily totals",
                "monthly published GWh to available-cell MWh reconciliation",
            ],
            missing_observations=sum(c["missing_observations"] for c in controls),
            incomplete_days=[
                dict(date=c["date"], technology=c["technology"], missing=c["missing_observations"])
                for c in controls
                if c["missing_observations"]
            ],
            source_anomalies=anomalies
            + [
                dict(
                    date=c["date"],
                    technology=c["technology"],
                    issue="Published hourly Total row disagrees with sum of plant cells; plant data retained without alteration.",
                    max_residual_mwh=c["source_hourly_total_max_residual_mwh"],
                )
                for c in controls
                if c["source_hourly_total_max_residual_mwh"] > 1e-5
            ],
            monthly_reconciliation=reconciliation,
        ),
    )
    event = [c for c in controls if c["date"] == "2026-08-01"]
    save(
        processed / "cen-2026-08-01.evidence.json",
        dict(
            evidence_id="cen-2026-08-01",
            source_id="cen-2026-08",
            source_sha256=digest,
            event_date="2026-08-01",
            selection_rule="First calendar day in the latest downloaded monthly export; not selected for simulated improvement.",
            source_urls=[SOURCE_URL, LANDING_URL],
            hour_labels=list(range(1, 25)),
            units="MWh",
            technologies=event,
            classification={
                "plant_cell_values": "observed",
                "technology_aggregates": "derived",
                "simulation_inputs": "synthetic assumptions",
            },
            time_convention="Workbook labels 1..24 are retained as labels. No observed UTC interval mapping is asserted.",
            limitations=[
                "Curtailment is not renewable availability or actual generation.",
                "Generation, demand, network constraints and causal attribution have not been joined.",
                "Historical evidence does not calibrate or validate the illustrative network.",
                "Solar and wind only; hydro sheets excluded explicitly.",
            ],
        ),
    )
    print(json.dumps({"records": len(records), "monthly_reconciliation": reconciliation}, indent=2))


if __name__ == "__main__":
    main()
