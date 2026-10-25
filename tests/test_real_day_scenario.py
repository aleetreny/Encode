"""Gates of ``docs/real-day-contract.md`` section 1 against the real-day fixture, plus the scenario switch."""

from __future__ import annotations

import csv
import glob
import gzip
import json
import sys
from pathlib import Path

import pytest

from backend.live import catalog as catalog_mod
from backend.live.agent_loop import (
    prepare_scenario_and_events,
    run_incident_evaluation,
    to_contract_solution,
)
from backend.live.catalog import (
    FIXTURE_PATH,
    REAL_DAY_FIXTURE_PATH,
    SYNTHETIC_DAY_PROFILE,
    build_catalog,
    scenario_path,
)
from optimisation import load_scenario, solve, validate

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_real_day_scenario as builder  # noqa: E402

NODES = ["n_norte_grande", "n_norte_chico", "n_centro", "n_centro_sur", "n_sur"]


@pytest.fixture(scope="module")
def scenario() -> dict:
    return load_scenario(REAL_DAY_FIXTURE_PATH)


@pytest.fixture(scope="module")
def baseline(scenario):
    return solve(scenario, options={"allow_unserved": True})


def _outage(scenario: dict, kind: str, asset: str, from_hour: int) -> tuple[float, dict]:
    disruptions = [
        {"type": kind, "asset_id": asset, "from_hour": from_hour, "to_hour": from_hour + 4, "source": "jury"}
    ]
    scen, events = prepare_scenario_and_events(scenario, disruptions)
    raw = solve(scen, events=events, options={"allow_unserved": True})
    base = to_contract_solution(scen, raw, validate(scen, raw), "sol_no_action")
    result = run_incident_evaluation(
        incident_id="inc_test",
        scenario=scenario,
        active_disruptions=disruptions,
        base_sol=base,
        from_hour=from_hour,
        to_hour=from_hour + 4,
        emit_thought=lambda _t: None,
        emit_tool_call=lambda _c: None,
        allow_live_gemini=False,
    )
    return raw["metrics"]["unserved_mwh"], result


# ------------------------------------------------------------------ structure


def test_same_network_as_synthetic_demo(scenario):
    demo = load_scenario(FIXTURE_PATH)
    for key in ("nodes", "lines", "generators", "batteries", "objective", "emission_factors_t_per_mwh"):
        assert scenario[key] == demo[key], key
    assert scenario["scenario_id"] == "chile-sen-5node-real-2026-08-14"
    assert scenario["provenance"]["historical_event_date"] == "2026-08-14"
    assert set(scenario["provenance"]["derived_fields"]) == {
        "demand_mw_by_node",
        "renewable_availability_mw_by_generator",
    }
    # 2026-08-14 00:00 America/Santiago is UTC-4 (winter)
    assert scenario["timestamps_utc"][0] == "2026-08-14T04:00:00Z"
    assert len(scenario["timestamps_utc"]) == 24
    profile = scenario["day_profile"]
    assert profile["method"] == "scaled-observed-shape" and profile["source"] == "CEN SIP"
    assert profile["date"] == "2026-08-14" and profile["scale_factor"] == 0.18


def test_committed_fixture_is_reproducible(scenario):
    assert builder.build() == scenario


# ---------------------------------------------------------------------- gates


def test_gate1_baseline_feasible_no_unserved(baseline):
    assert baseline["status"] == "optimal"
    assert baseline["metrics"]["unserved_mwh"] == 0.0
    assert all(v == 0.0 for per_node in baseline["timeseries"]["unserved_mw"].values() for v in per_node)


def test_gate2_corridor_saturates_with_curtailment_at_midday(baseline):
    flows = baseline["timeseries"]["line_flow_mw"]
    hours = [h for h in range(10, 17) if any(abs(flows[k][h]) / 400.0 >= 0.95 for k in ("L1", "L2"))]
    assert len(hours) >= 2, hours
    ts = baseline["timeseries"]
    solar = [g for g in ts["available_mw"] if g.startswith("solar")]
    midday_solar_curtailment = sum(
        ts["available_mw"][g][h] - ts["generation_mw"][g][h] for g in solar for h in range(10, 17)
    )
    assert midday_solar_curtailment > 1.0, midday_solar_curtailment  # the midday solar-curtailment story


def test_gate3_centro_peaks_in_the_evening(scenario):
    centro = scenario["demand_mw_by_node"]["n_centro"]
    assert 18 <= centro.index(max(centro)) <= 22


@pytest.mark.parametrize(
    "kind,asset,hour", [("generator_outage", "gas_centro", 18), ("line_outage", "L3", 19)]
)
def test_gate4_outage_hurts_and_sweep_finds_options(scenario, kind, asset, hour):
    unserved, result = _outage(scenario, kind, asset, hour)
    assert unserved > 0.0
    assert result["candidates_passed"] >= 2
    assert len(result["options"]) == 2
    assert all(opt["validation"]["passed"] for opt in result["options"])


def test_gate5_validator_passes_on_baseline(scenario, baseline):
    report = validate(scenario, baseline)
    assert report["passed"], report


# ------------------------------------------------------------ builder inputs


def _bus_names() -> list[str]:
    names: set[str] = set()
    for path in glob.glob(builder.DEMANDA_REAL_GLOB):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            payload = json.load(fh)
        for row in payload["data"] if isinstance(payload, dict) else payload:
            names.add(row["barra"])
    return sorted(names)


def _write_bus_csv(path: Path, buses: list[str]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["barra", "zone", "method", "confidence", "energy_mwh"])
        for i, bus in enumerate(buses):
            writer.writerow([bus, NODES[i % 5], "test", "high", 1.0])


def test_bus_path_uses_measured_zone_shares(tmp_path):
    csv_path = tmp_path / "bus-zone.csv"
    _write_bus_csv(csv_path, _bus_names())
    scen = builder.build(bus_zone=csv_path)
    assert scen["provenance"]["demand_zone_share_provenance"] == "derived"
    assert "coverage" in scen["provenance"]["notes"]
    demand = scen["demand_mw_by_node"]
    assert demand != builder.build()["demand_mw_by_node"]
    assert all(sum(demand[n][h] for n in NODES) > 0 for h in range(24))


def test_low_bus_coverage_falls_back_to_assumption(tmp_path):
    csv_path = tmp_path / "bus-zone.csv"
    _write_bus_csv(csv_path, _bus_names()[:3])
    scen = builder.build(bus_zone=csv_path)
    assert scen["provenance"]["demand_zone_share_provenance"] == "assumption"
    assert scen["demand_mw_by_node"] == builder.build()["demand_mw_by_node"]


# --------------------------------------------------------------------- switch


def test_switch_defaults_to_real_day(monkeypatch):
    monkeypatch.delenv("GRIDPILOT_SCENARIO", raising=False)
    assert scenario_path() == REAL_DAY_FIXTURE_PATH
    assert build_catalog()["day_profile"]["method"] == "scaled-observed-shape"


def test_switch_selects_synthetic(monkeypatch):
    monkeypatch.setenv("GRIDPILOT_SCENARIO", "synthetic")
    assert scenario_path() == FIXTURE_PATH
    assert catalog_mod.FIXTURE_PATH == FIXTURE_PATH
    cat = build_catalog()
    assert cat["scenario_id"] == "chile-sen-5node-demo"
    assert cat["day_profile"] == SYNTHETIC_DAY_PROFILE


def test_switch_selects_real_day(monkeypatch):
    monkeypatch.setenv("GRIDPILOT_SCENARIO", "real-day")
    assert scenario_path() == REAL_DAY_FIXTURE_PATH
    cat = build_catalog()
    assert cat["scenario_id"] == "chile-sen-5node-real-2026-08-14"
    assert cat["day_profile"]["method"] == "scaled-observed-shape"
    assert cat["day_profile"]["scale_factor"] == 0.18


def test_switch_rejects_unknown_value(monkeypatch):
    monkeypatch.setenv("GRIDPILOT_SCENARIO", "nope")
    with pytest.raises(ValueError):
        scenario_path()


def test_engine_uses_the_switch(monkeypatch):
    from backend.live.engine import LiveSession

    monkeypatch.setenv("GRIDPILOT_SCENARIO", "real-day")
    session = LiveSession("sess_real_day", allow_live_gemini=False)
    assert session.scenario["scenario_id"] == "chile-sen-5node-real-2026-08-14"
    assert session.catalog["day_profile"]["date"] == "2026-08-14"


def test_real_day_catalog_labels_demand_as_derived(monkeypatch):
    monkeypatch.setenv("GRIDPILOT_SCENARIO", "real-day")
    prov = build_catalog()["provenance"]
    assert prov["demand_mw"] == "derived"
    assert prov["renewable_availability_mw"] == "derived"
    monkeypatch.setenv("GRIDPILOT_SCENARIO", "synthetic")
    assert build_catalog()["provenance"]["demand_mw"] == "synthetic"


def test_a_selected_missing_fixture_fails_instead_of_turning_synthetic(monkeypatch, tmp_path):
    monkeypatch.setenv("GRIDPILOT_SCENARIO", "real-day")
    monkeypatch.setattr(catalog_mod, "REAL_DAY_FIXTURE_PATH", tmp_path / "missing.json")
    with pytest.raises(FileNotFoundError):
        build_catalog()
