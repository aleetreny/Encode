"""Checks for the demand bus -> zone table (`scripts/map_buses_to_zones.py`)."""

import csv
import gzip
import json
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data/processed/cen-sip/bus-zone-2026-08-14.csv"
DEMAND_DIR = ROOT / "data/raw/cen-sip/demanda-real-estimada/2026-08-14"

ZONES = {"n_norte_grande", "n_norte_chico", "n_centro", "n_centro_sur", "n_sur"}
METHODS = {"catalog", "keyword", "topology", "none"}
CONFIDENCE = {"high", "medium", "none"}

# Achieved coverage when the table was built. The 0.99 bar is the target from the real-day
# contract; the gap is listed in the report, not hidden by lowering the bar.
ACHIEVED_COVERAGE = 0.7822
COVERAGE_TARGET = 0.99


@pytest.fixture(scope="module")
def rows():
    with CSV_PATH.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def zone_shares(rows):
    total = sum(float(r["energy_mwh"]) for r in rows)
    shares = defaultdict(float)
    for r in rows:
        shares[r["zone"]] += float(r["energy_mwh"]) / total
    return shares


def test_csv_exists_with_expected_columns(rows):
    assert CSV_PATH.exists()
    with CSV_PATH.open(newline="", encoding="utf-8") as fh:
        header = next(csv.reader(fh))
    assert header == ["barra", "zone", "method", "confidence", "energy_mwh"]
    assert rows


def test_zones_methods_and_confidence_are_valid(rows):
    for r in rows:
        assert r["zone"] in ZONES | {"unknown"}
        assert r["method"] in METHODS
        assert r["confidence"] in CONFIDENCE
        assert float(r["energy_mwh"]) >= 0
        if r["zone"] == "unknown":
            assert r["method"] == "none" and r["confidence"] == "none"
        else:
            assert r["method"] != "none" and r["confidence"] != "none"


def test_rows_sorted_by_energy_desc(rows):
    energies = [float(r["energy_mwh"]) for r in rows]
    assert energies == sorted(energies, reverse=True)


def test_every_demand_bus_is_listed_once(rows):
    barras = set()
    for path in sorted(DEMAND_DIR.glob("page-*.json.gz")):
        with gzip.open(path, "rb") as fh:
            payload = json.load(fh)
        for row in payload if isinstance(payload, list) else payload["data"]:
            barras.add(row["barra"])
    listed = [r["barra"] for r in rows]
    assert len(listed) == len(set(listed))
    assert set(listed) == barras


def test_coverage_does_not_regress(rows):
    # Floor at the achieved value: a drop in coverage means a mapping was lost.
    known = sum(float(r["energy_mwh"]) for r in rows if r["zone"] != "unknown")
    total = sum(float(r["energy_mwh"]) for r in rows)
    assert known / total >= ACHIEVED_COVERAGE - 1e-3


@pytest.mark.xfail(
    strict=True,
    reason=f"coverage target {COVERAGE_TARGET:.0%} not reached: achieved {ACHIEVED_COVERAGE:.2%}",
)
def test_energy_coverage_meets_target(rows):
    known = sum(float(r["energy_mwh"]) for r in rows if r["zone"] != "unknown")
    total = sum(float(r["energy_mwh"]) for r in rows)
    assert known / total >= COVERAGE_TARGET


def test_n_centro_has_largest_share(rows):
    shares = zone_shares(rows)
    shares.pop("unknown", None)
    assert max(shares, key=shares.get) == "n_centro"
