import pytest

from backend.audit import audit
from backend.models import Options, Solution


def test_reference_comparison(scenario, replay):
    baseline = audit(
        scenario,
        Solution.model_validate(replay["result"]["baseline"]),
        Options(battery_policy="disabled"),
    )
    candidate = audit(scenario, Solution.model_validate(replay["result"]["candidate"]), Options())
    assert baseline.passed and candidate.passed
    assert baseline.metrics.curtailed_energy_mwh == 210
    assert candidate.metrics.curtailed_energy_mwh == pytest.approx(132.222222)
    assert candidate.metrics.unserved_energy_mwh == 0


@pytest.mark.parametrize(
    "field,key,index,value",
    [
        ("line_flows_mw_by_line", "L1", 0, 999),
        ("generation_mw_by_generator", "thermal1", 0, -1),
        ("generation_mw_by_generator", "solar1", 0, 161),
        ("curtailment_mw_by_generator", "solar1", 0, 0),
        ("charge_mw_by_battery", "b1", 0, 31),
        ("discharge_mw_by_battery", "b1", 0, 1),
        ("soc_mwh_by_battery", "b1", 0, 0),
        ("soc_mwh_by_battery", "b1", 1, 0),
        ("soc_mwh_by_battery", "b1", 6, 0),
        ("soc_mwh_by_battery", "b1", 1, 999),
        ("load_shedding_mw_by_node", "south", 0, 1),
    ],
)
def test_tampering_never_gets_metrics(scenario, replay, field, key, index, value):
    candidate = replay["result"]["candidate"]
    candidate[field][key][index] = value
    result = audit(scenario, Solution.model_validate(candidate), Options())
    assert not result.passed and result.violations and result.metrics is None


def test_missing_series_rejected(scenario, replay):
    candidate = replay["result"]["candidate"]
    candidate["line_flows_mw_by_line"].pop("L1")
    assert not audit(scenario, Solution.model_validate(candidate), Options()).passed


def test_battery_disabled_policy(scenario, replay):
    assert not audit(
        scenario,
        Solution.model_validate(replay["result"]["candidate"]),
        Options(battery_policy="disabled"),
    ).passed


def test_infeasible_never_valid(scenario):
    assert not audit(
        scenario, Solution(status="infeasible", reason="not enough supply"), Options()
    ).passed
