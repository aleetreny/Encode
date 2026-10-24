import pytest
from pydantic import ValidationError

from backend.models import Scenario


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["timestamps_utc"].__setitem__(0, "2026-08-01T14:00:00"),
        lambda d: d["timestamps_utc"].__setitem__(0, "2026-08-01T14:00:00-04:00"),
        lambda d: d["timestamps_utc"].__setitem__(1, d["timestamps_utc"][0]),
        lambda d: d["demand_mw_by_node"]["north"].pop(),
        lambda d: d["demand_mw_by_node"]["north"].__setitem__(0, -1),
        lambda d: d["demand_mw_by_node"]["north"].__setitem__(0, float("nan")),
        lambda d: d["nodes"].append(d["nodes"][0]),
        lambda d: d["lines"][0].__setitem__("from", "unknown"),
        lambda d: d["generators"][0].__setitem__("node_id", "unknown"),
        lambda d: d["renewable_availability_mw_by_generator"]["solar1"].__setitem__(0, 9999),
        lambda d: d["batteries"][0].__setitem__("round_trip_efficiency", 0),
        lambda d: d["batteries"][0].__setitem__("initial_soc_mwh", 999),
        lambda d: d["provenance"].__setitem__("evidence_id", None),
        lambda d: d.__setitem__("unrecognised", 4),
    ],
)
def test_invalid_scenario_rejected(scenario_json, change):
    change(scenario_json)
    with pytest.raises(ValidationError):
        Scenario.model_validate(scenario_json)


def test_contract_roundtrip(scenario_json):
    parsed = Scenario.model_validate(scenario_json)
    assert Scenario.model_validate_json(parsed.model_dump_json(by_alias=True)) == parsed
