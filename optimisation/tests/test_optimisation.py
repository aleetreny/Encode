"""Test suite for the optimisation module (DESIGN.md section 11)."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from optimisation import ScenarioError, compare, load_scenario, modification_menu, solve, validate
from optimisation.fixtures.build_demo_scenario import build

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "demo_scenario.json"

NORTH_BATTERY = {
    "candidate_id": "c_north",
    "modifications": [{"type": "add_battery", "node_id": "n_norte_grande", "power_mw": 150, "energy_mwh": 600}],
}
SOUTH_BATTERY = {
    "candidate_id": "c_south",
    "modifications": [{"type": "add_battery", "node_id": "n_sur", "power_mw": 150, "energy_mwh": 600}],
}
GAS_TRIP = {"type": "generator_outage", "id": "gas_centro", "from_hour": 18, "to_hour": 22, "mode": "sudden"}


@pytest.fixture
def scen() -> dict:
    return load_scenario(FIXTURE)


@pytest.fixture
def base(scen) -> dict:
    return solve(scen)


def ok(scen: dict, sol: dict) -> dict:
    assert sol["status"] == "optimal", sol["message"]
    v = validate(scen, sol)
    assert v["passed"], v["violations"][:5]
    return v


def binding(sol: dict, kind: str, ident: str) -> list[int]:
    return [h for b in sol["binding_constraints"] if b["type"] == kind and b["id"] == ident for h in b["hours"]]


def tiny_scenario(**over) -> dict:
    """Two nodes, one line, solar north, gas south, one battery south."""
    s = {
        "scenario_id": "tiny",
        "time_step_hours": 1,
        "timestamps_utc": [f"2026-10-01T{h:02d}:00:00Z" for h in range(4)],
        "nodes": [{"id": "a"}, {"id": "b"}],
        "lines": [{"id": "L", "from": "a", "to": "b", "capacity_mw": 50}],
        "generators": [
            {"id": "pv", "node_id": "a", "technology": "solar", "capacity_mw": 200, "variable_cost_usd_per_mwh": 0},
            {"id": "gas", "node_id": "b", "technology": "gas", "capacity_mw": 100, "variable_cost_usd_per_mwh": 80},
        ],
        "batteries": [
            {"id": "bat", "node_id": "b", "power_capacity_mw": 20, "energy_capacity_mwh": 40,
             "min_soc_mwh": 0, "initial_soc_mwh": 20, "charge_efficiency": 0.9, "discharge_efficiency": 0.9}
        ],
        "demand_mw_by_node": {"a": [10, 10, 10, 10], "b": [60, 80, 90, 70]},
        "renewable_availability_mw_by_generator": {"pv": [0, 150, 150, 0]},
    }
    s.update(over)
    return s


# ------------------------------------------------------------------ basics


def test_fixture_is_reproducible(scen):
    assert build() == scen, "demo_scenario.json is stale: run python -m optimisation.fixtures.build_demo_scenario"


def test_demo_solves_and_validates(scen, base):
    ok(scen, base)
    assert base["metrics"]["unserved_mwh"] == 0
    assert base["solver"]["solves"] == 1


def test_congestion_causes_curtailment(base):
    assert base["metrics"]["curtailment_mwh"] > 100
    assert len(binding(base, "line_limit", "L2")) >= 4
    assert base["metrics"]["line_hours_at_limit"]["L2"] >= 4


def test_output_is_plain_json(base):
    assert json.loads(json.dumps(base, allow_nan=False)) == base


def test_deterministic(scen):
    a, b = solve(scen, NORTH_BATTERY, [GAS_TRIP]), solve(scen, NORTH_BATTERY, [GAS_TRIP])
    for s in (a, b):
        s["solver"].pop("solve_time_s")
    assert a == b


def test_energy_conservation_every_hour(scen, base):
    ts = base["timeseries"]
    T = len(base["timestamps_utc"])
    for t in range(T):
        supply = sum(v[t] for v in ts["generation_mw"].values())
        supply += sum(v[t] for v in ts["battery_discharge_mw"].values())
        supply -= sum(v[t] for v in ts["battery_charge_mw"].values())
        supply += sum(v[t] for v in ts["unserved_mw"].values())
        demand = sum(v[t] for v in scen["demand_mw_by_node"].values())
        assert supply == pytest.approx(demand, abs=1e-4)


def test_no_simultaneous_charge_discharge(scen):
    for cand in (None, NORTH_BATTERY, SOUTH_BATTERY):
        sol = solve(scen, cand, [GAS_TRIP])
        for bid, ch in sol["timeseries"]["battery_charge_mw"].items():
            dis = sol["timeseries"]["battery_discharge_mw"][bid]
            assert all(min(c, d) <= 1e-6 for c, d in zip(ch, dis))


def test_final_soc_not_below_initial(scen):
    sol = solve(scen, NORTH_BATTERY)
    for b in sol["assets"]["batteries"]:
        soc = sol["timeseries"]["battery_soc_mwh"][b["id"]]
        assert soc[0] == pytest.approx(b["initial_soc_mwh"])
        assert soc[-1] >= b["initial_soc_mwh"] - 1e-6


# ------------------------------------------------------------------ candidates


def test_north_battery_beats_south_battery_on_curtailment(scen, base):
    north, south = solve(scen, NORTH_BATTERY), solve(scen, SOUTH_BATTERY)
    ok(scen, north), ok(scen, south)
    c_n = compare(base, north, validate(scen, base), validate(scen, north))
    c_s = compare(base, south, validate(scen, base), validate(scen, south))
    assert c_n["comparable"] and c_s["comparable"]
    assert c_n["curtailment_reduction_mwh"] > 100
    assert c_n["curtailment_reduction_mwh"] > c_s["curtailment_reduction_mwh"] + 100
    assert north["assets"]["batteries"][-1]["id"] == "c_north_bat1"


def test_line_uprate_candidate(scen, base):
    sol = solve(scen, {"candidate_id": "c_l2", "modifications": [
        {"type": "uprate_line", "line_id": "L2", "new_capacity_mw": 600}]})
    ok(scen, sol)
    assert sol["metrics"]["curtailment_mwh"] < base["metrics"]["curtailment_mwh"]
    assert {ln["id"]: ln["capacity_mw"] for ln in sol["assets"]["lines"]}["L2"] == 600


@pytest.mark.parametrize("cand", [NORTH_BATTERY, SOUTH_BATTERY, {"candidate_id": "c2", "modifications": [
    {"type": "add_battery", "node_id": "n_centro", "power_mw": 50, "energy_mwh": 100},
    {"type": "uprate_line", "line_id": "L3", "new_capacity_mw": 400}]}])
def test_adding_assets_never_increases_objective(scen, base, cand):
    assert solve(scen, cand)["objective"]["total_usd"] <= base["objective"]["total_usd"] + 1e-3


@pytest.mark.parametrize(
    "mods, msg",
    [
        ([{"type": "add_battery", "node_id": "n_sur", "power_mw": 500, "energy_mwh": 1000}], "power_mw"),
        ([{"type": "add_battery", "node_id": "n_sur", "power_mw": 100, "energy_mwh": 50}], "duration"),
        ([{"type": "add_battery", "node_id": "atlantis", "power_mw": 100, "energy_mwh": 200}], "not a node"),
        ([{"type": "uprate_line", "line_id": "L2", "new_capacity_mw": 900}], "new_capacity_mw"),
        ([{"type": "uprate_line", "line_id": "L2", "new_capacity_mw": 300}], "exceed"),
        ([{"type": "build_nuclear_plant"}], "type"),
        ([{"type": "add_battery", "node_id": "n_sur", "power_mw": 50, "energy_mwh": 100, "cost": 0}], "unknown fields"),
        ([{"type": "uprate_line", "line_id": "L1", "new_capacity_mw": 500}] * 3, "at most 2"),
        ([], "non-empty"),
    ],
)
def test_bad_candidates_are_rejected(scen, mods, msg):
    sol = solve(scen, {"candidate_id": "bad", "modifications": mods})
    assert sol["status"] == "error"
    assert msg in sol["message"]
    assert sol["metrics"] is None and sol["timeseries"] is None
    assert not validate(scen, sol)["passed"]


def test_modification_menu(scen):
    menu = modification_menu(scen)
    assert menu["max_modifications"] == 2
    assert "n_norte_grande" in menu["add_battery"]["node_ids"]
    l2 = next(ln for ln in menu["uprate_line"]["lines"] if ln["id"] == "L2")
    assert l2["max_capacity_mw"] == pytest.approx(1.5 * l2["current_capacity_mw"])
    assert "gas_centro" in menu["events"]["generator_ids"]


# ------------------------------------------------------------------ bad input


@pytest.mark.parametrize(
    "mutate, msg",
    [
        (lambda s: s["generators"][0].update(capacity_mw=-5), "capacity_mw"),
        (lambda s: s["demand_mw_by_node"].update(b=[1, 2]), "expected 4"),
        (lambda s: s["generators"][0].update(node_id="zz"), "unknown node"),
        (lambda s: s["lines"].append({"id": "L_dup", "from": "b", "to": "a", "capacity_mw": 10}), "loop"),
        (lambda s: s["lines"].append({"id": "L", "from": "a", "to": "b", "capacity_mw": 10}), "duplicate"),
        (lambda s: s["batteries"][0].update(initial_soc_mwh=99), "initial_soc_mwh"),
        (lambda s: s["renewable_availability_mw_by_generator"].update(pv=[0, 300, 0, 0]), "exceeds capacity"),
        (lambda s: s["demand_mw_by_node"].update(b=[1, 2, float("nan"), 3]), "finite"),
        (lambda s: s.update(objective={"made_up": 1}), "unknown field"),
        (lambda s: s["renewable_availability_mw_by_generator"].pop("pv"), "full capacity day and night"),
        (lambda s: s["timestamps_utc"].__setitem__(1, "banana"), "not an ISO 8601"),
        (lambda s: s["timestamps_utc"].__setitem__(2, "2026-10-01T05:00:00Z"), "not 1 h after"),
        (lambda s: s.update(timestamps_utc=[t.rstrip("Z") for t in s["timestamps_utc"]]), "no timezone"),
    ],
)
def test_bad_input_returns_error(mutate, msg):
    s = tiny_scenario()
    mutate(s)
    sol = solve(s)
    assert sol["status"] == "error", sol
    assert msg in sol["message"]
    with pytest.raises(ScenarioError):
        modification_menu(s)


def test_bad_options_and_events():
    s = tiny_scenario()
    assert "unknown fields" in solve(s, options={"turbo": True})["message"]
    assert "to_hour" in solve(s, events=[{"type": "line_outage", "id": "L", "from_hour": 3, "to_hour": 2}])["message"]
    assert "not a known" in solve(s, events=[{"type": "generator_outage", "id": "x", "from_hour": 0, "to_hour": 1}])["message"]


# ------------------------------------------------------------------ feasibility


def test_insufficient_generation_strict_vs_default():
    s = tiny_scenario(demand_mw_by_node={"a": [10, 10, 10, 10], "b": [60, 80, 400, 70]})
    strict = solve(s, options={"allow_unserved": False})
    assert strict["status"] == "infeasible"
    assert "hour 2" in strict["message"]
    assert not validate(s, strict)["passed"]
    default = solve(s)
    ok(s, default)
    assert default["metrics"]["unserved_mwh"] > 0
    assert binding(default, "unserved_energy", "b") == [2]


def test_battery_starting_empty():
    s = tiny_scenario()
    s["batteries"][0]["initial_soc_mwh"] = 0
    sol = solve(s)
    ok(s, sol)
    assert min(sol["timeseries"]["battery_soc_mwh"]["bat"]) >= -1e-9


def test_battery_shifts_solar_and_reports_losses():
    s = tiny_scenario()
    s["batteries"][0]["node_id"] = "a"  # same side of the congested line as the solar
    sol = solve(s)
    ok(s, sol)
    m = sol["metrics"]
    assert m["battery_charge_mwh"] > 0 and m["battery_discharge_mwh"] > 0
    expected = m["battery_charge_mwh"] * 0.1 + m["battery_discharge_mwh"] * (1 / 0.9 - 1)
    assert m["battery_losses_mwh"] == pytest.approx(expected, abs=1e-5)


def test_round_trip_efficiency_is_split():
    s = tiny_scenario()
    b = s["batteries"][0]
    del b["charge_efficiency"], b["discharge_efficiency"]
    b["round_trip_efficiency"] = 0.81
    sol = solve(s)
    ok(s, sol)
    assert sol["assets"]["batteries"][0]["charge_efficiency"] == pytest.approx(0.9)


# ------------------------------------------------------------------ outages


def test_planned_generator_outage(scen):
    ev = {"type": "generator_outage", "id": "gas_centro", "from_hour": 18, "to_hour": 22, "mode": "planned"}
    sol = solve(scen, events=[ev])
    ok(scen, sol)
    assert sol["timeseries"]["generation_mw"]["gas_centro"][18:22] == [0, 0, 0, 0]
    assert sol["events"] == [ev]
    assert binding(sol, "outage", "gas_centro") == [18, 19, 20, 21]


def test_sudden_outage_has_no_hindsight(scen, base):
    sol = solve(scen, events=[GAS_TRIP])
    ok(scen, sol)
    assert sol["solver"]["solves"] == 2
    for block in ("generation_mw", "battery_charge_mw", "battery_discharge_mw", "line_flow_mw", "unserved_mw"):
        for key, series in sol["timeseries"][block].items():
            assert series[:18] == base["timeseries"][block][key][:18], (block, key)
    assert sol["timeseries"]["generation_mw"]["gas_centro"][18:22] == [0, 0, 0, 0]


def test_planned_outage_is_never_worse_than_sudden(scen):
    planned = solve(scen, events=[{**GAS_TRIP, "mode": "planned"}])
    sudden = solve(scen, events=[GAS_TRIP])
    assert planned["objective"]["total_usd"] <= sudden["objective"]["total_usd"] + 1e-3


def test_sudden_trip_causes_unserved_and_battery_reduces_it(scen):
    base = solve(scen, events=[GAS_TRIP])
    north = solve(scen, NORTH_BATTERY, [GAS_TRIP])
    ok(scen, base), ok(scen, north)
    assert base["metrics"]["unserved_mwh"] > 0
    c = compare(base, north)
    assert c["comparable"] and c["unserved_reduction_mwh"] > 0
    # load is shed where the deficit is, not exported away from
    shed_nodes = {b["id"] for b in base["binding_constraints"] if b["type"] == "unserved_energy"}
    assert shed_nodes == {"n_centro"}


def test_ramp_limit_binds_on_recovery(scen):
    sol = solve(scen, events=[GAS_TRIP])
    gas = sol["timeseries"]["generation_mw"]["gas_centro"]
    assert gas[22] <= 250 + 1e-6
    assert 22 in binding(sol, "ramp_limit", "gas_centro")


def test_line_outage_islands_balance_separately():
    s = tiny_scenario()
    sol = solve(s, events=[{"type": "line_outage", "id": "L", "from_hour": 1, "to_hour": 3}])
    ok(s, sol)
    assert sol["timeseries"]["line_flow_mw"]["L"][1:3] == [0, 0]
    # node a's solar can only serve node a while islanded
    assert sol["timeseries"]["generation_mw"]["pv"][1:3] == [10, 10]


def test_multiple_sudden_events_processed_in_order(scen):
    evs = [GAS_TRIP, {"type": "line_outage", "id": "L3", "from_hour": 12, "to_hour": 14, "mode": "sudden"}]
    sol = solve(scen, events=evs)
    ok(scen, sol)
    assert sol["solver"]["solves"] == 3
    assert [e["from_hour"] for e in sol["events"]] == [12, 18]


def test_scenario_events_are_applied_and_enforced(scen):
    s = copy.deepcopy(scen)
    s["events"] = [{**GAS_TRIP, "mode": "planned"}]
    sol = solve(s)
    ok(s, sol)
    stripped = copy.deepcopy(sol)
    stripped["events"] = []
    assert any(v["check"] == "events_consistent" for v in validate(s, stripped)["violations"])


# ------------------------------------------------------------------ validator


@pytest.mark.parametrize(
    "tamper, check",
    [
        (lambda s: s["timeseries"]["line_flow_mw"]["L2"].__setitem__(12, 450.0), "line_limits"),
        (lambda s: s["timeseries"]["line_flow_mw"]["L3"].__setitem__(3, s["timeseries"]["line_flow_mw"]["L3"][3] + 5), "nodal_balance"),
        (lambda s: s["timeseries"]["generation_mw"]["solar_ng"].__setitem__(12, 9999.0), "generator_bounds"),
        (lambda s: s["timeseries"]["battery_soc_mwh"]["b_centro"].__setitem__(5, 1.0), "soc_dynamics"),
        (lambda s: s["timeseries"]["battery_soc_mwh"]["b_centro"].__setitem__(0, 0.0), "soc_initial"),
        (lambda s: s["metrics"].update(curtailment_mwh=1.0), "metrics_recomputed"),
        (lambda s: s["objective"]["terms"].update(dispatchable_cost_usd=0.0), "metrics_recomputed"),
        (lambda s: s["timeseries"]["curtailment_mw"]["solar_ng"].__setitem__(12, 0.0), "curtailment_consistency"),
        (lambda s: s["timeseries"]["unserved_mw"]["n_sur"].__setitem__(0, -3.0), "unserved_bounds"),
        (lambda s: s["timeseries"]["line_flow_mw"]["L1"].pop(), "shape"),
        (lambda s: s["timeseries"]["generation_mw"]["gas_centro"].__setitem__(4, float("nan")), "shape"),
    ],
)
def test_validator_catches_tampering(scen, base, tamper, check):
    bad = copy.deepcopy(base)
    tamper(bad)
    v = validate(scen, bad)
    assert not v["passed"]
    assert check in {x["check"] for x in v["violations"]}, v["violations"][:5]


def test_validator_catches_simultaneous_charge_discharge():
    s = tiny_scenario()
    sol = solve(s)
    bad = copy.deepcopy(sol)
    ts = bad["timeseries"]
    # charge and discharge 5 MW in hour 0: SOC unchanged except losses -> keep SOC consistent
    ts["battery_charge_mw"]["bat"][0] += 5
    ts["battery_discharge_mw"]["bat"][0] += 5
    assert "simultaneous_charge_discharge" in {x["check"] for x in validate(s, bad)["violations"]}


def test_validator_rejects_ramp_violation():
    s = tiny_scenario()
    s["generators"][1]["ramp_rate_mw_per_h"] = 100
    sol = solve(s)
    ok(s, sol)
    s2 = copy.deepcopy(s)
    s2["generators"][1]["ramp_rate_mw_per_h"] = 1
    assert "ramp_limits" in {x["check"] for x in validate(s2, sol)["violations"]}


def test_validator_does_not_import_solver():
    src = (Path(__file__).resolve().parents[1] / "validate.py").read_text()
    assert "model" not in [line.split()[1].lstrip(".") for line in src.splitlines() if line.startswith("from .")]
    assert "highspy" not in src


# ------------------------------------------------------------------ compare


def test_compare_refuses_unlike_or_invalid(scen, base):
    trip = solve(scen, events=[GAS_TRIP])
    assert not compare(base, trip)["comparable"]
    bad = solve(scen, {"candidate_id": "x", "modifications": [{"type": "nope"}]})
    assert not compare(base, bad)["comparable"]
    north = solve(scen, NORTH_BATTERY)
    c = compare(base, north, validate(scen, base), {"passed": False})
    assert not c["comparable"] and "candidate" in c["reason"]


def test_compare_contents(scen, base):
    north = solve(scen, NORTH_BATTERY)
    c = compare(base, north, validate(scen, base), validate(scen, north))
    assert c["both_valid"] is True
    m = c["metrics"]["curtailment_mwh"]
    assert m["delta"] == pytest.approx(m["candidate"] - m["baseline"])
    assert c["curtailment_reduction_mwh"] == pytest.approx(-m["delta"])
    assert any("Investment cost" in n for n in c["notes"])


# ------------------------------------------------------------------ property test


def _random_radial(rng: np.random.Generator) -> dict:
    n = int(rng.integers(2, 7))
    T = int(rng.integers(2, 10))
    nodes = [{"id": f"n{i}"} for i in range(n)]
    lines = [
        {"id": f"l{i}", "from": f"n{int(rng.integers(0, i))}", "to": f"n{i}", "capacity_mw": float(rng.uniform(0, 200))}
        for i in range(1, n)
    ]
    gens, prof = [], {}
    for i in range(n):
        if rng.random() < 0.7:
            cap = float(rng.uniform(10, 300))
            gens.append({"id": f"pv{i}", "node_id": f"n{i}", "technology": "solar", "capacity_mw": cap})
            prof[f"pv{i}"] = [float(rng.uniform(0, cap)) for _ in range(T)]
        if rng.random() < 0.6:
            g = {"id": f"th{i}", "node_id": f"n{i}", "technology": "gas", "capacity_mw": float(rng.uniform(10, 300)),
                 "variable_cost_usd_per_mwh": float(rng.uniform(20, 200))}
            if rng.random() < 0.5:
                g["ramp_rate_mw_per_h"] = float(rng.uniform(5, 100))
            gens.append(g)
    bats = []
    for i in range(n):
        if rng.random() < 0.4:
            E = float(rng.uniform(1, 200))
            bats.append({"id": f"b{i}", "node_id": f"n{i}", "power_capacity_mw": float(rng.uniform(1, 100)),
                         "energy_capacity_mwh": E, "initial_soc_mwh": float(rng.uniform(0, E)),
                         "charge_efficiency": float(rng.uniform(0.8, 1)), "discharge_efficiency": float(rng.uniform(0.8, 1))})
    dt = float(rng.choice([0.5, 1.0, 2.0]))
    start = datetime(2026, 10, 1, 3, tzinfo=timezone.utc)
    s = {
        "scenario_id": "random", "time_step_hours": dt,
        "timestamps_utc": [(start + timedelta(hours=dt * t)).strftime("%Y-%m-%dT%H:%M:%SZ") for t in range(T)],
        "nodes": nodes, "lines": lines,
        "generators": gens, "batteries": bats,
        "demand_mw_by_node": {f"n{i}": [float(rng.uniform(0, 150)) for _ in range(T)] for i in range(n)},
        "renewable_availability_mw_by_generator": prof,
    }
    if gens and rng.random() < 0.5:
        a = int(rng.integers(0, T))
        s["events"] = [{"type": "generator_outage", "id": gens[int(rng.integers(0, len(gens)))]["id"],
                        "from_hour": a, "to_hour": int(rng.integers(a + 1, T + 1)),
                        "mode": str(rng.choice(["planned", "sudden"]))}]
    return s


@pytest.mark.parametrize("seed", range(40))
def test_random_radial_scenarios_solve_and_validate(seed):
    s = _random_radial(np.random.default_rng(seed))
    sol = solve(s)
    ok(s, sol)


# ------------------------------------------------------------------ backend compatibility


def test_exact_final_soc():
    s = tiny_scenario()
    s["batteries"][0]["node_id"] = "a"
    s["batteries"][0]["final_soc_mwh"] = 20
    sol = solve(s)
    ok(s, sol)
    assert sol["timeseries"]["battery_soc_mwh"]["bat"][-1] == pytest.approx(20)
    bad = copy.deepcopy(sol)
    bad["timeseries"]["battery_soc_mwh"]["bat"][-1] = 25.0
    assert "soc_final" in {x["check"] for x in validate(s, bad)["violations"]}


def test_curtailment_penalty_cannot_buy_battery_cycling():
    """A curtailment penalty with zero throughput cost rewards wasting surplus through
    simultaneous charge/discharge losses; the solver must forbid that exactly."""
    s = tiny_scenario(objective={"curtailment_penalty_usd_per_mwh": 5, "battery_throughput_cost_usd_per_mwh": 0})
    s["batteries"][0].update(node_id="a", initial_soc_mwh=40, final_soc_mwh=40)  # full: can only burn energy
    sol = solve(s)
    ok(s, sol)
    assert sol["solver"]["method"].startswith("MILP")
    ch = sol["timeseries"]["battery_charge_mw"]["bat"]
    dis = sol["timeseries"]["battery_discharge_mw"]["bat"]
    assert all(min(c, d) <= 1e-6 for c, d in zip(ch, dis))


def test_plain_lp_when_no_cycling_incentive(base):
    assert base["solver"]["method"] == "LP"


def test_validate_rejects_solution_solved_with_other_options():
    s = tiny_scenario(demand_mw_by_node={"a": [10, 10, 10, 10], "b": [60, 80, 400, 70]})
    lax = solve(s)  # default allows unserved demand
    assert validate(s, lax)["passed"]
    assert validate(s, lax, {"allow_unserved": True})["passed"]
    strict = validate(s, lax, {"allow_unserved": False})
    assert not strict["passed"]
    assert "options_consistent" in {v["check"] for v in strict["violations"]}


# Hour-by-hour dispatch can legitimately differ between platforms: when several schedules are
# equally cheap (a degenerate optimum), HiGHS on macOS ARM and on Linux may pick different ones.
# These keys depend on that choice; everything else (status, inputs, metrics, objective,
# comparisons, validation verdict) must match, and every stored solution must still validate.
# Summaries (*.summary.json) also carry hour lists and LP prices, which follow the same choice
# (LP duals can be degenerate too).
PLATFORM_DEPENDENT = {"timeseries", "binding_constraints", "line_hours_at_limit", "max_residual_mw",
                      "batteries", "prices_usd_per_mwh", "hours"}


def _same_result(stored, fresh, path="") -> list[str]:
    """Differences between a stored example and freshly computed output, ignoring PLATFORM_DEPENDENT."""
    if isinstance(fresh, dict) and isinstance(stored, dict):
        if set(stored) != set(fresh):
            return [f"{path}: keys differ {sorted(set(stored) ^ set(fresh))}"]
        return [d for k in fresh if k not in PLATFORM_DEPENDENT for d in _same_result(stored[k], fresh[k], f"{path}.{k}")]
    if isinstance(fresh, list) and isinstance(stored, list):
        if len(stored) != len(fresh):
            return [f"{path}: length {len(stored)} != {len(fresh)}"]
        return [d for i, (x, y) in enumerate(zip(stored, fresh)) for d in _same_result(x, y, f"{path}[{i}]")]
    if isinstance(fresh, float) or isinstance(stored, float):
        ok_num = isinstance(stored, (int, float)) and isinstance(fresh, (int, float))
        return [] if ok_num and abs(stored - fresh) <= 1e-6 + 1e-9 * abs(fresh) else [f"{path}: {stored} != {fresh}"]
    return [] if stored == fresh else [f"{path}: {stored!r} != {fresh!r}"]


def test_examples_match_current_code(scen):
    """optimisation/examples/ must be regenerated whenever outputs change (python -m optimisation.demo --write).

    Compared semantically so the check passes on every platform: hourly allocations of a degenerate
    optimum may differ, but each stored solution must validate and match status, inputs, metrics and
    objective exactly (to 1e-6).
    """
    import contextlib
    import io

    from optimisation import demo

    with contextlib.redirect_stdout(io.StringIO()):
        results = demo.run(write=False)
    for name, data in results.items():
        stored = json.loads((demo.EXAMPLES / f"{name}.json").read_text())
        fresh = json.loads(json.dumps(demo.stable(data)))
        diffs = _same_result(stored, fresh)
        assert not diffs, f"examples/{name}.json is stale (run python -m optimisation.demo --write): {diffs[:5]}"
        if stored.get("status") == "optimal" and "timeseries" in stored:
            check = validate(scen, stored, stored["options"])
            assert check["passed"], f"examples/{name}.json no longer validates: {check['violations'][:3]}"
    # every exported case is a real, validated solution
    index = results["index"]["situations"]
    assert set(index) == {"normal", "sudden_outage", "planned_maintenance"}
    for situation in index.values():
        assert set(situation["options"]) == {"baseline", "north_bess", "south_bess", "uprate_l2"}
        assert all(entry["valid"] for entry in situation["options"].values())


# ------------------------------------------------------------------ outage sweep


def test_line_trip_islanding_exporting_plant_uses_emergency_runback(scen):
    """L1 trips while gas_ng exports north->south: the Norte Grande island has more generation
    than demand and gas_ng cannot ramp down fast enough, so it must be run back (cf. EDAG)."""
    trip = {"type": "line_outage", "id": "L1", "from_hour": 6, "to_hour": 10, "mode": "sudden"}
    sol = solve(scen, events=[trip])
    ok(scen, sol)
    assert sol["metrics"]["emergency_runback_mwh"] > 0
    assert 6 in binding(sol, "emergency_runback", "gas_ng")
    assert sol["objective"]["terms"]["emergency_runback_penalty_usd"] == pytest.approx(
        sol["metrics"]["emergency_runback_mwh"] * 1000, rel=1e-6)
    # planned in advance, the plant is ramped down beforehand: no runback needed
    planned = solve(scen, events=[{**trip, "mode": "planned"}])
    ok(scen, planned)
    assert planned["metrics"]["emergency_runback_mwh"] == 0
    assert planned["objective"]["total_usd"] <= sol["objective"]["total_usd"]


def test_validator_rejects_fast_drop_outside_sudden_event_hour(scen):
    sol = solve(scen)
    bad = copy.deepcopy(sol)
    bad["timeseries"]["generation_mw"]["gas_ng"][5] = 0.0  # 350 -> 0 MW without any event
    assert "ramp_limits" in {v["check"] for v in validate(scen, bad)["violations"]}


def test_outage_stress_sweep_quick():
    """Every generator and line, planned and sudden, midday and evening, baseline and one
    candidate, normal and strict mode (python -m optimisation.stress runs the full sweep)."""
    import contextlib
    import io

    from optimisation import stress

    with contextlib.redirect_stdout(io.StringIO()):
        summary = stress.run(quick=True, verbose=False)
    assert summary["passed"], summary["failures"][:5]
    assert summary["cases"] >= 100


def test_validator_accepts_older_solutions_without_runback_fields(scen, base):
    """Solutions saved before emergency runback existed omit its fields; fine when nothing was run back."""
    old = copy.deepcopy(base)
    del old["metrics"]["emergency_runback_mwh"]
    del old["objective"]["terms"]["emergency_runback_penalty_usd"]
    ok(scen, old)
    # ...but a solution that really ran a plant back cannot hide it by omitting the fields
    trip = {"type": "line_outage", "id": "L1", "from_hour": 6, "to_hour": 10, "mode": "sudden"}
    hidden = copy.deepcopy(solve(scen, events=[trip]))
    del hidden["metrics"]["emergency_runback_mwh"]
    del hidden["objective"]["terms"]["emergency_runback_penalty_usd"]
    bad = validate(scen, hidden)
    assert not bad["passed"]
    assert {"emergency_runback_mwh", "emergency_runback_penalty_usd"} <= {v["id"] for v in bad["violations"]}


def test_example_check_tolerates_a_different_equally_good_schedule(scen):
    """Mimics the macOS/Linux difference: same totals, different hourly split -> accepted;
    a changed metric -> rejected."""
    sol = solve(scen, SOUTH_BATTERY, [GAS_TRIP])
    other = copy.deepcopy(sol)
    other["binding_constraints"] = other["binding_constraints"][::-1]
    other["timeseries"]["battery_discharge_mw"]["c_south_bat1"][19] += 1.0  # pretend another split
    assert _same_result(other, sol) == []
    other["metrics"]["unserved_mwh"] += 1.0
    assert _same_result(other, sol) != []


# ------------------------------------------------------------------ nodal prices and summary


def test_solve_output_format_is_unchanged_by_prices(base):
    """Prices are not added to solve() output: consumers compare stored results field by field."""
    assert "price_usd_per_mwh" not in base["timeseries"]


def test_nodal_prices_show_the_bottleneck(scen, base):
    from optimisation import nodal_prices

    p = nodal_prices(scen, base)["price_usd_per_mwh"]
    assert set(p) == {n["id"] for n in scen["nodes"]} and all(len(v) == 24 for v in p.values())
    # midday, L2 full: surplus solar north is worth ~0, the centre pays for gas
    assert p["n_norte_grande"][13] < 1.0 and p["n_centro"][13] == pytest.approx(95.0, abs=0.1)
    # evening: the diesel peaker sets the price everywhere
    assert p["n_centro"][19] == pytest.approx(220.0, abs=0.1)


def test_nodal_price_is_the_penalty_where_demand_is_shed(scen):
    from optimisation import nodal_prices

    sol = solve(scen, events=[GAS_TRIP])
    assert nodal_prices(scen, sol)["price_usd_per_mwh"]["n_centro"][19] == pytest.approx(10000.0, abs=0.1)


def test_prices_before_a_sudden_event_come_from_the_plan(scen, base):
    from optimisation import nodal_prices

    plan = nodal_prices(scen, base)["price_usd_per_mwh"]
    sol = solve(scen, events=[GAS_TRIP])
    for node, series in nodal_prices(scen, sol)["price_usd_per_mwh"].items():
        assert series[:18] == plan[node][:18]


def test_prices_available_after_milp_fallback():
    s = tiny_scenario(objective={"curtailment_penalty_usd_per_mwh": 5, "battery_throughput_cost_usd_per_mwh": 0})
    s["batteries"][0].update(node_id="a", initial_soc_mwh=40, final_soc_mwh=40)
    sol = solve(s)
    ok(s, sol)
    from optimisation import nodal_prices

    assert sol["solver"]["method"].startswith("MILP")
    assert set(nodal_prices(s, sol)["price_usd_per_mwh"]) == {"a", "b"}


def test_summary_is_small_and_copies_numbers_exactly(scen):
    from optimisation import summarise

    trip = solve(scen, events=[GAS_TRIP])
    north = solve(scen, NORTH_BATTERY, [GAS_TRIP])
    tv, nv = validate(scen, trip), validate(scen, north)
    cmp = compare(trip, north, tv, nv)
    from optimisation import nodal_prices

    s = summarise(north, nv, cmp, nodal_prices(scen, north))
    assert len(json.dumps(s)) < 4000 < len(json.dumps(north))
    assert s["validation"]["passed"] is True
    for k in ("curtailment_mwh", "unserved_mwh", "assumed_cost_proxy_usd"):
        assert s["metrics"][k] == pytest.approx(north["metrics"][k], abs=0.05)
    assert s["comparison"]["unserved_reduction_mwh"] == pytest.approx(cmp["unserved_reduction_mwh"], abs=0.05)
    from optimisation.summary import hour_ranges

    assert s["unserved_by_node"]["n_centro"]["hours"] == hour_ranges(binding(north, "unserved_energy", "n_centro"))
    assert s["unserved_by_node"]["n_centro"]["hours"].startswith("18")
    assert s["binding_constraints"][0].startswith("unserved_energy n_centro")
    assert s["prices_usd_per_mwh"]["largest_separation"]["cheapest_node"] == "n_norte_grande"


def test_summary_of_failed_solve_has_reason_and_no_metrics(scen):
    from optimisation import summarise

    strict = solve(scen, events=[GAS_TRIP], options={"allow_unserved": False})
    s = summarise(strict, validate(scen, strict))
    assert s["status"] == "infeasible" and "hour 18" in s["message"]
    assert "metrics" not in s and s["validation"]["passed"] is False
    from optimisation import nodal_prices

    assert nodal_prices(scen, strict)["price_usd_per_mwh"] is None


def test_hour_ranges():
    from optimisation.summary import hour_ranges

    assert hour_ranges([9, 10, 11, 14, 16, 17]) == "9-11, 14, 16-17"
    assert hour_ranges([]) == ""


def test_tour_is_built_from_the_current_examples():
    """optimisation/tour/andes-tour.html embeds the validated example results (python -m optimisation.tour.build_tour)."""
    from optimisation.tour import build_tour

    html = build_tour.OUT.read_text()
    start = html.index("const D=") + len("const D=")
    data = json.loads(html[start:html.index(";\nconst fmt")])
    index = json.loads((build_tour.EXAMPLES / "index.json").read_text())
    for sit, v in index["situations"].items():
        for opt, entry in v["options"].items():
            assert data["cases"][sit][opt]["valid"] is True
            for k in ("curtailment_mwh", "unserved_mwh", "assumed_cost_proxy_usd"):
                assert data["cases"][sit][opt]["metrics"][k] == entry["metrics"][k], "tour is stale: rebuild it"
