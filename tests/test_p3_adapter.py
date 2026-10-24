import asyncio

import pytest

from backend.models import Options, wire
from backend.p3_adapter import FIELDS, canonical_solution, native_scenario


def envelope(replay):
    source = replay["result"]["candidate"]
    return dict(
        status="optimal",
        message=None,
        modifications=[],
        events=[],
        timeseries={native: source[canonical] for canonical, native in FIELDS.items()},
    )


def test_bridge_preserves_explicit_units_and_policy(scenario_json):
    native = native_scenario(scenario_json, wire(Options(battery_policy="disabled")))
    assert native["batteries"][0]["power_capacity_mw"] == 0
    assert native["batteries"][0]["charge_efficiency"] ** 2 == pytest.approx(0.9)
    assert "final_soc_mwh" not in native["batteries"][0]
    assert native["objective"]["curtailment_penalty_usd_per_mwh"] == 1
    assert "curtailment_penalty_usd_per_mwh" not in native


def test_native_mapping_retains_full_envelope(replay):
    native = envelope(replay)
    canonical = canonical_solution(native)
    assert canonical.native_result == native
    assert canonical.soc_mwh_by_battery == native["timeseries"]["battery_soc_mwh"]


def test_bridge_calls_native_validator_and_rejects_tampering(scenario_json, replay, monkeypatch):
    from backend import p3_adapter

    calls = []

    async def invoke(target, *args, **kwargs):
        calls.append((target, args, kwargs))
        if target.endswith(":solve"):
            return envelope(replay)
        return dict(passed=True, violations=[], max_residual_mw=0)

    monkeypatch.setattr(p3_adapter, "invoke", invoke)
    options = wire(Options())
    candidate = asyncio.run(p3_adapter.solve(scenario_json, options))
    assert calls[0][2] == {"options": {"allow_unserved": False}}
    assert asyncio.run(p3_adapter.validate(scenario_json, candidate, options))["passed"]
    assert len(calls[1][1]) == 2  # Native validator keeps Person 3's two-argument signature.
    candidate["line_flows_mw_by_line"]["L1"][0] = 999
    assert not asyncio.run(p3_adapter.validate(scenario_json, candidate, options))["passed"]


@pytest.mark.parametrize("extra", ["events", "modifications"])
def test_unsupported_physics_is_not_silently_stripped(replay, extra):
    native = envelope(replay)
    native[extra] = [{"type": "not-supported-in-v1"}]
    with pytest.raises(ValueError):
        canonical_solution(native)
