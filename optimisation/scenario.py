"""Scenario loading, input checks, candidate modifications and outage events.

This module only handles data: it turns a raw scenario dict (plus an optional
candidate and events) into a checked, normalised ``Grid``. Both the solver
(``model.py``) and the independent validator (``validate.py``) start from here.
"""

from __future__ import annotations

import copy
import json
import math
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_OBJECTIVE = {
    "unserved_energy_penalty_usd_per_mwh": 10000.0,
    "curtailment_penalty_usd_per_mwh": 0.0,
    "battery_throughput_cost_usd_per_mwh": 0.5,
    "transmission_tiebreak_usd_per_mwh": 0.01,
    "emergency_runback_penalty_usd_per_mwh": 1000.0,
}

DEFAULT_EMISSION_FACTORS = {
    "gas": 0.40,
    "coal": 0.95,
    "diesel": 0.75,
    "solar": 0.0,
    "wind": 0.0,
    "hydro": 0.0,
}

DEFAULT_LIMITS = {
    "max_modifications": 2,
    "add_battery": {
        "power_mw_min": 10.0,
        "power_mw_max": 150.0,
        "duration_h_min": 1.0,
        "duration_h_max": 6.0,
        "initial_soc_fraction": 0.5,
        "charge_efficiency": 0.95,
        "discharge_efficiency": 0.95,
    },
    "uprate_line": {"max_factor": 1.5},
    "emergency_rating": {"max_factor": 1.20, "max_window_hours": 4},
    "demand_response": {"max_mw": 200.0, "default_cost_usd_per_mwh": 300.0},
    "hydro_reserve_release": {"max_extra_mw": 150.0, "default_water_value_usd_per_mwh": 120.0},
    "start_peaker": {"overdrive_factor": 1.5, "startup_delay_hours": 1},
}

DEFAULT_OPTIONS = {"allow_unserved": True, "time_limit_s": 30.0}

EVENT_TYPES = ("generator_outage", "line_outage")
EVENT_MODES = ("planned", "sudden")
WEATHER_DRIVEN = ("solar", "wind")  # must come with an hourly availability profile


class ScenarioError(ValueError):
    """Raised for any invalid scenario, candidate, event or option."""


@dataclass
class Grid:
    """Checked, normalised network ready to be optimised or validated."""

    scenario_id: str
    T: int
    dt: float
    timestamps: list[str]
    node_ids: list[str]
    lines: list[dict]
    generators: list[dict]
    batteries: list[dict]
    demand: np.ndarray  # (N, T) MW
    avail: np.ndarray  # (G, T) MW, 0 during outages
    gen_online: np.ndarray  # (G, T) bool
    line_cap: np.ndarray  # (L, T) MW, 0 during outages
    gen_cost: np.ndarray  # (G, T) float
    dr_cap: np.ndarray  # (N, T) float
    dr_cost: np.ndarray  # (N, T) float
    emission_factors: dict[str, float]
    runback_hours: set[int]  # hours where a sudden event starts: units may drop faster than ramp
    objective: dict
    options: dict
    candidate_id: str = "baseline"
    modifications: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)

    @property
    def node_index(self) -> dict[str, int]:
        return {n: i for i, n in enumerate(self.node_ids)}


# ---------------------------------------------------------------- helpers


def _fail(msg: str) -> None:
    raise ScenarioError(msg)


def _num(value: Any, what: str, *, lo: float | None = None, hi: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{what} must be a number, got {value!r}")
    x = float(value)
    if not math.isfinite(x):
        _fail(f"{what} must be finite, got {value!r}")
    if lo is not None and x < lo:
        _fail(f"{what} must be >= {lo}, got {x}")
    if hi is not None and x > hi:
        _fail(f"{what} must be <= {hi}, got {x}")
    return x


def _series(values: Any, T: int, what: str) -> np.ndarray:
    if not isinstance(values, (list, tuple)):
        _fail(f"{what} must be a list of {T} numbers")
    if len(values) != T:
        _fail(f"{what} has {len(values)} values, expected {T}")
    return np.array([_num(v, f"{what}[{t}]", lo=0.0) for t, v in enumerate(values)], dtype=float)


def _unique_ids(items: list[dict], kind: str) -> list[str]:
    ids = []
    for i, item in enumerate(items):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            _fail(f"{kind}[{i}] needs a non-empty string 'id'")
        ids.append(item["id"])
    dupes = sorted({x for x in ids if ids.count(x) > 1})
    if dupes:
        _fail(f"duplicate {kind} ids: {dupes}")
    return ids


def load_scenario(path: str | Path) -> dict:
    """Read a scenario JSON file."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------- candidates


def _limits(scenario: dict) -> dict:
    limits = copy.deepcopy(DEFAULT_LIMITS)
    for key, value in (scenario.get("modification_limits") or {}).items():
        if isinstance(value, dict) and isinstance(limits.get(key), dict):
            limits[key].update(value)
        else:
            limits[key] = value
    return limits


def modification_menu(scenario: dict) -> dict:
    """Allowed candidate modifications and outage events, for the agent prompt."""
    base = build_grid(scenario)
    limits = _limits(scenario)
    bat = limits["add_battery"]
    return {
        "max_modifications": limits["max_modifications"],
        "add_battery": {
            "node_ids": list(base.node_ids),
            "power_mw": [bat["power_mw_min"], bat["power_mw_max"]],
            "duration_h": [bat["duration_h_min"], bat["duration_h_max"]],
            "initial_soc_fraction": bat["initial_soc_fraction"],
            "charge_efficiency": bat["charge_efficiency"],
            "discharge_efficiency": bat["discharge_efficiency"],
        },
        "uprate_line": {
            "lines": [
                {
                    "id": ln["id"],
                    "from": ln["from"],
                    "to": ln["to"],
                    "current_capacity_mw": ln["capacity_mw"],
                    "max_capacity_mw": round(ln["capacity_mw"] * limits["uprate_line"]["max_factor"], 6),
                }
                for ln in base.lines
            ]
        },
        "emergency_rating": {
            "max_factor": limits["emergency_rating"]["max_factor"],
            "max_window_hours": limits["emergency_rating"]["max_window_hours"],
        },
        "demand_response": {
            "max_mw": limits["demand_response"]["max_mw"],
            "default_cost_usd_per_mwh": limits["demand_response"]["default_cost_usd_per_mwh"],
        },
        "activate_reserve_bess": {
            "description": "Activate a battery on standby",
        },
        "hydro_reserve_release": {
            "max_extra_mw": limits["hydro_reserve_release"]["max_extra_mw"],
            "default_water_value_usd_per_mwh": limits["hydro_reserve_release"]["default_water_value_usd_per_mwh"],
        },
        "start_peaker": {
            "overdrive_factor": limits["start_peaker"]["overdrive_factor"],
            "startup_delay_hours": limits["start_peaker"]["startup_delay_hours"],
        },
        "events": {
            "types": list(EVENT_TYPES),
            "modes": list(EVENT_MODES),
            "generator_ids": [g["id"] for g in base.generators],
            "line_ids": [ln["id"] for ln in base.lines],
            "hours": [0, base.T],
        },
    }


def apply_candidate(scenario: dict, candidate: dict | None) -> tuple[dict, str, list[dict]]:
    """Return (modified scenario copy, candidate_id, normalised modifications)."""
    if candidate is None:
        return scenario, "baseline", []
    if not isinstance(candidate, dict):
        _fail("candidate must be an object with 'candidate_id' and 'modifications'")
    unknown = set(candidate) - {"candidate_id", "modifications", "description"}
    if unknown:
        _fail(f"candidate has unknown fields: {sorted(unknown)}")
    cid = candidate.get("candidate_id")
    if not isinstance(cid, str) or not cid or cid == "baseline":
        _fail("candidate_id must be a non-empty string other than 'baseline'")
    mods = candidate.get("modifications")
    limits = _limits(scenario)
    if not isinstance(mods, list) or not mods:
        _fail("candidate.modifications must be a non-empty list")
    planning_mods = [
        m for m in mods if isinstance(m, dict) and m.get("type") in ("add_battery", "uprate_line")
    ]
    if len(planning_mods) > limits["max_modifications"]:
        _fail(f"at most {limits['max_modifications']} modifications per candidate, got {len(planning_mods)}")
    if len(mods) > max(limits["max_modifications"], 8):
        _fail(f"at most {max(limits['max_modifications'], 8)} modifications per candidate, got {len(mods)}")

    out = copy.deepcopy(scenario)
    node_ids = {n.get("id") for n in out.get("nodes", [])}
    lines = {ln.get("id"): ln for ln in out.get("lines", [])}
    out.setdefault("batteries", [])
    normalised: list[dict] = []
    uprated: set[str] = set()
    n_bat = 0
    for i, mod in enumerate(mods):
        where = f"modifications[{i}]"
        if not isinstance(mod, dict):
            _fail(f"{where} must be an object")
        kind = mod.get("type")
        if kind == "add_battery":
            extra = set(mod) - {"type", "node_id", "power_mw", "energy_mwh"}
            if extra:
                _fail(f"{where} has unknown fields: {sorted(extra)}")
            lim = limits["add_battery"]
            if mod.get("node_id") not in node_ids:
                _fail(f"{where}.node_id {mod.get('node_id')!r} is not a node in this scenario")
            power = _num(mod.get("power_mw"), f"{where}.power_mw", lo=lim["power_mw_min"], hi=lim["power_mw_max"])
            energy = _num(mod.get("energy_mwh"), f"{where}.energy_mwh", lo=0.0)
            duration = energy / power
            if not (lim["duration_h_min"] - 1e-9 <= duration <= lim["duration_h_max"] + 1e-9):
                _fail(
                    f"{where}: duration energy_mwh/power_mw = {duration:.3g} h must be within "
                    f"{lim['duration_h_min']}-{lim['duration_h_max']} h"
                )
            n_bat += 1
            bat_id = f"{cid}_bat{n_bat}"
            out["batteries"].append(
                {
                    "id": bat_id,
                    "node_id": mod["node_id"],
                    "power_capacity_mw": power,
                    "energy_capacity_mwh": energy,
                    "min_soc_mwh": 0.0,
                    "initial_soc_mwh": energy * lim["initial_soc_fraction"],
                    "final_soc_mwh": None,
                    "charge_efficiency": lim["charge_efficiency"],
                    "discharge_efficiency": lim["discharge_efficiency"],
                    "added_by_candidate": cid,
                }
            )
            normalised.append(
                {"type": "add_battery", "node_id": mod["node_id"], "power_mw": power,
                 "energy_mwh": energy, "battery_id": bat_id}
            )
        elif kind == "uprate_line":
            extra = set(mod) - {"type", "line_id", "new_capacity_mw"}
            if extra:
                _fail(f"{where} has unknown fields: {sorted(extra)}")
            lid = mod.get("line_id")
            if lid not in lines:
                _fail(f"{where}.line_id {lid!r} is not a line in this scenario")
            if lid in uprated:
                _fail(f"{where}: line {lid} is uprated more than once")
            current = _num(lines[lid].get("capacity_mw"), f"line {lid}.capacity_mw", lo=0.0)
            cap_max = current * limits["uprate_line"]["max_factor"]
            new = _num(mod.get("new_capacity_mw"), f"{where}.new_capacity_mw", hi=cap_max)
            if new <= current:
                _fail(f"{where}.new_capacity_mw must exceed the current {current} MW")
            uprated.add(lid)
            lines[lid]["capacity_mw"] = new
            normalised.append(
                {"type": "uprate_line", "line_id": lid, "previous_capacity_mw": current, "new_capacity_mw": new}
            )
        elif kind in ("emergency_rating", "demand_response", "activate_reserve_bess", "hydro_reserve_release", "start_peaker"):
            T = len(scenario.get("timestamps_utc") or [])
            if T <= 0:
                _fail("scenario timestamps_utc must not be empty")
            from_hour = mod.get("from_hour", 0)
            to_hour = mod.get("to_hour", T)
            if not isinstance(from_hour, int) or isinstance(from_hour, bool) or not isinstance(to_hour, int) or isinstance(to_hour, bool):
                _fail(f"{where}.from_hour and to_hour must be integers")
            if not (0 <= from_hour < to_hour <= T):
                _fail(f"{where}: need 0 <= from_hour < to_hour <= {T}")
            
            if kind == "emergency_rating":
                extra = set(mod) - {"type", "line_id", "factor", "from_hour", "to_hour"}
                if extra: _fail(f"{where} has unknown fields")
                lid = mod.get("line_id")
                if lid not in lines: _fail(f"{where}.line_id not found")
                factor = _num(mod.get("factor"), f"{where}.factor", lo=1.000001, hi=limits["emergency_rating"]["max_factor"])
                if to_hour - from_hour > limits["emergency_rating"]["max_window_hours"]:
                    _fail(f"{where} window too large")
                normalised.append({"type": "emergency_rating", "line_id": lid, "factor": factor, "from_hour": from_hour, "to_hour": to_hour})
            elif kind == "demand_response":
                extra = set(mod) - {"type", "node_id", "max_mw", "from_hour", "to_hour", "cost_usd_per_mwh"}
                if extra: _fail(f"{where} has unknown fields")
                nid = mod.get("node_id")
                if nid not in node_ids: _fail(f"{where}.node_id not found")
                max_mw = _num(mod.get("max_mw"), f"{where}.max_mw", lo=1e-6, hi=limits["demand_response"]["max_mw"])
                cost_usd = _num(mod.get("cost_usd_per_mwh", limits["demand_response"]["default_cost_usd_per_mwh"]), f"{where}.cost_usd_per_mwh", lo=0.0, hi=5000.0)
                normalised.append({"type": "demand_response", "node_id": nid, "max_mw": max_mw, "from_hour": from_hour, "to_hour": to_hour, "cost_usd_per_mwh": cost_usd})
            elif kind == "activate_reserve_bess":
                extra = set(mod) - {"type", "battery_id", "from_hour", "to_hour"}
                if extra: _fail(f"{where} has unknown fields")
                bid = mod.get("battery_id")
                found = None
                for b in out["batteries"]:
                    if b.get("id") == bid:
                        found = b
                        break
                if not found or not found.get("standby"):
                    _fail(f"{where}.battery_id {bid!r} is not a standby battery")
                found["standby"] = False
                found["active_from_hour"] = from_hour
                found["active_to_hour"] = to_hour
                found["final_soc_mwh"] = float(found.get("min_soc_mwh", 0.0))
                found["added_by_candidate"] = cid
                normalised.append({"type": "activate_reserve_bess", "battery_id": bid, "from_hour": from_hour, "to_hour": to_hour})
            elif kind == "hydro_reserve_release":
                extra = set(mod) - {"type", "generator_id", "extra_mw", "from_hour", "to_hour", "water_value_usd_per_mwh"}
                if extra: _fail(f"{where} has unknown fields")
                gid = mod.get("generator_id")
                found = False
                for g in out.get("generators", []):
                    if g.get("id") == gid and str(g.get("technology", "")).lower() == "hydro":
                        found = True
                        break
                if not found:
                    _fail(f"{where}.generator_id {gid!r} is not a hydro generator")
                extra_mw = _num(mod.get("extra_mw"), f"{where}.extra_mw", lo=1e-6, hi=limits["hydro_reserve_release"]["max_extra_mw"])
                water_val = _num(mod.get("water_value_usd_per_mwh", limits["hydro_reserve_release"]["default_water_value_usd_per_mwh"]), f"{where}.water_value_usd_per_mwh", lo=0.0, hi=5000.0)
                normalised.append({"type": "hydro_reserve_release", "generator_id": gid, "extra_mw": extra_mw, "from_hour": from_hour, "to_hour": to_hour, "water_value_usd_per_mwh": water_val})
            elif kind == "start_peaker":
                extra = set(mod) - {"type", "generator_id", "from_hour", "to_hour"}
                if extra: _fail(f"{where} has unknown fields")
                gid = mod.get("generator_id")
                found = False
                for g in out.get("generators", []):
                    if g.get("id") == gid and str(g.get("technology", "")).lower() == "diesel":
                        found = True
                        break
                if not found:
                    _fail(f"{where}.generator_id {gid!r} is not a diesel generator")
                if to_hour - from_hour < 2:
                    _fail(f"{where} needs at least 2 hours window")
                normalised.append({"type": "start_peaker", "generator_id": gid, "from_hour": from_hour, "to_hour": to_hour})
        else:
            _fail(f"{where}.type must be one of the allowed types, got {kind!r}")
    return out, cid, normalised


# ---------------------------------------------------------------- events


def normalise_events(events: Any, T: int, gen_ids: set[str], line_ids: set[str]) -> list[dict]:
    if events is None:
        return []
    if not isinstance(events, list):
        _fail("events must be a list")
    out = []
    for i, ev in enumerate(events):
        where = f"events[{i}]"
        if not isinstance(ev, dict):
            _fail(f"{where} must be an object")
        extra = set(ev) - {"type", "id", "from_hour", "to_hour", "mode", "description"}
        if extra:
            _fail(f"{where} has unknown fields: {sorted(extra)}")
        kind = ev.get("type")
        if kind not in EVENT_TYPES:
            _fail(f"{where}.type must be one of {EVENT_TYPES}, got {kind!r}")
        valid_ids = gen_ids if kind == "generator_outage" else line_ids
        if ev.get("id") not in valid_ids:
            _fail(f"{where}.id {ev.get('id')!r} is not a known {'generator' if kind == 'generator_outage' else 'line'}")
        mode = ev.get("mode", "planned")
        if mode not in EVENT_MODES:
            _fail(f"{where}.mode must be one of {EVENT_MODES}, got {mode!r}")
        a, b = ev.get("from_hour"), ev.get("to_hour")
        if not all(isinstance(x, int) and not isinstance(x, bool) for x in (a, b)):
            _fail(f"{where}.from_hour and to_hour must be integers")
        if not (0 <= a < b <= T):
            _fail(f"{where}: need 0 <= from_hour < to_hour <= {T}, got {a}..{b}")
        item = {"type": kind, "id": ev["id"], "from_hour": a, "to_hour": b, "mode": mode}
        if item not in out:
            out.append(item)
    out.sort(key=lambda e: (e["from_hour"], e["type"], e["id"], e["mode"]))
    return out


def merge_events(scenario: dict, events: Any) -> list[Any]:
    merged = list(scenario.get("events") or [])
    if events is not None:
        if not isinstance(events, list):
            _fail("events must be a list")
        merged += events
    return merged


def normalise_options(options: Any) -> dict:
    opts = dict(DEFAULT_OPTIONS)
    if options is None:
        return opts
    if not isinstance(options, dict):
        _fail("options must be an object")
    extra = set(options) - set(DEFAULT_OPTIONS)
    if extra:
        _fail(f"options has unknown fields: {sorted(extra)}")
    if "allow_unserved" in options:
        if not isinstance(options["allow_unserved"], bool):
            _fail("options.allow_unserved must be true or false")
        opts["allow_unserved"] = options["allow_unserved"]
    if "time_limit_s" in options:
        opts["time_limit_s"] = _num(options["time_limit_s"], "options.time_limit_s", lo=0.1, hi=600)
    return opts


# ---------------------------------------------------------------- grid


def _check_time_axis(stamps: list[str], dt: float) -> None:
    """Timestamps must be timezone-aware ISO 8601, exactly ``dt`` hours apart."""
    times = []
    for i, s in enumerate(stamps):
        try:
            t = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            _fail(f"timestamps_utc[{i}] = {s!r} is not an ISO 8601 timestamp")
        if t.tzinfo is None:
            _fail(f"timestamps_utc[{i}] = {s!r} has no timezone; use UTC, e.g. 2026-10-01T03:00:00Z")
        times.append(t)
    step = timedelta(hours=dt)
    for i in range(1, len(times)):
        if abs(times[i] - times[i - 1] - step) > timedelta(seconds=1):
            _fail(f"timestamps_utc[{i}] is not {dt:g} h after timestamps_utc[{i - 1}]")


def _check_radial(node_ids: list[str], lines: list[dict]) -> None:
    parent = {n: n for n in node_ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for ln in lines:
        a, b = find(ln["from"]), find(ln["to"])
        if a == b:
            _fail(
                f"line {ln['id']} closes a loop; only radial (loop-free) networks are supported "
                "because the transport model equals DC power flow only without loops"
            )
        parent[a] = b


def build_grid(
    scenario: dict,
    candidate: dict | None = None,
    events: Any = None,
    options: Any = None,
    *,
    include_scenario_events: bool = True,
) -> Grid:
    """Check the scenario, apply the candidate and events, and return a ``Grid``.

    ``events`` is the list of events to apply. When ``include_scenario_events`` is
    true, the scenario's own ``events`` are merged in first.
    """
    if not isinstance(scenario, dict):
        _fail("scenario must be a JSON object")
    scen, cid, mods = apply_candidate(scenario, candidate)

    sid = scen.get("scenario_id")
    if not isinstance(sid, str) or not sid:
        _fail("scenario_id must be a non-empty string")
    dt = _num(scen.get("time_step_hours"), "time_step_hours", lo=1e-9)
    stamps = scen.get("timestamps_utc")
    if not isinstance(stamps, list) or not stamps or not all(isinstance(s, str) for s in stamps):
        _fail("timestamps_utc must be a non-empty list of ISO 8601 strings")
    T = len(stamps)
    _check_time_axis(stamps, dt)

    nodes = scen.get("nodes") or []
    if not isinstance(nodes, list) or not nodes:
        _fail("nodes must be a non-empty list")
    node_ids = _unique_ids(nodes, "node")
    node_set = set(node_ids)

    lines = []
    raw_lines = scen.get("lines") or []
    _unique_ids(raw_lines, "line")
    for ln in raw_lines:
        lid = ln["id"]
        if ln.get("from") not in node_set or ln.get("to") not in node_set:
            _fail(f"line {lid} connects unknown nodes {ln.get('from')!r} -> {ln.get('to')!r}")
        if ln["from"] == ln["to"]:
            _fail(f"line {lid} connects node {ln['from']} to itself")
        lines.append(
            {"id": lid, "from": ln["from"], "to": ln["to"],
             "capacity_mw": _num(ln.get("capacity_mw"), f"line {lid}.capacity_mw", lo=0.0)}
        )
    _check_radial(node_ids, lines)

    avail_raw = scen.get("renewable_availability_mw_by_generator") or {}
    if not isinstance(avail_raw, dict):
        _fail("renewable_availability_mw_by_generator must be an object")
    raw_gens = scen.get("generators") or []
    gen_ids = _unique_ids(raw_gens, "generator")
    unknown_profiles = set(avail_raw) - set(gen_ids)
    if unknown_profiles:
        _fail(f"renewable availability given for unknown generators: {sorted(unknown_profiles)}")
    generators = []
    avail_rows = []
    for g in raw_gens:
        gid = g["id"]
        if g.get("node_id") not in node_set:
            _fail(f"generator {gid} is at unknown node {g.get('node_id')!r}")
        cap = _num(g.get("capacity_mw"), f"generator {gid}.capacity_mw", lo=0.0)
        cost = _num(g.get("variable_cost_usd_per_mwh", 0.0), f"generator {gid}.variable_cost_usd_per_mwh", lo=0.0)
        renewable = gid in avail_raw
        if not renewable and str(g.get("technology", "")).lower() in WEATHER_DRIVEN:
            _fail(
                f"generator {gid} is {g['technology']} but has no entry in "
                "renewable_availability_mw_by_generator; without it, it would run at full capacity day and night"
            )
        ramp = g.get("ramp_rate_mw_per_h")
        if ramp is not None:
            if renewable:
                _fail(f"generator {gid}: ramp_rate_mw_per_h is only supported for dispatchable generators")
            ramp = _num(ramp, f"generator {gid}.ramp_rate_mw_per_h", lo=0.0)
        if renewable:
            profile = _series(avail_raw[gid], T, f"renewable_availability_mw_by_generator.{gid}")
            if (profile > cap + 1e-9).any():
                _fail(f"generator {gid}: availability exceeds capacity_mw {cap}")
        else:
            profile = np.full(T, cap)
        generators.append(
            {"id": gid, "node_id": g["node_id"], "technology": str(g.get("technology", "unknown")),
             "capacity_mw": cap, "variable_cost_usd_per_mwh": cost, "renewable": renewable,
             "ramp_rate_mw_per_h": ramp}
        )
        avail_rows.append(profile)

    batteries = []
    raw_bats = scen.get("batteries") or []
    _unique_ids(raw_bats, "battery")
    for b in raw_bats:
        bid = b["id"]
        if b.get("node_id") not in node_set:
            _fail(f"battery {bid} is at unknown node {b.get('node_id')!r}")
        P = _num(b.get("power_capacity_mw"), f"battery {bid}.power_capacity_mw", lo=0.0)
        E = _num(b.get("energy_capacity_mwh"), f"battery {bid}.energy_capacity_mwh", lo=0.0)
        smin = _num(b.get("min_soc_mwh", 0.0), f"battery {bid}.min_soc_mwh", lo=0.0, hi=E)
        s0 = _num(b.get("initial_soc_mwh"), f"battery {bid}.initial_soc_mwh", lo=smin, hi=E)
        s_end = b.get("final_soc_mwh")
        if s_end is not None:
            s_end = _num(s_end, f"battery {bid}.final_soc_mwh", lo=smin, hi=E)
        if "charge_efficiency" in b or "discharge_efficiency" in b:
            eta_c = _num(b.get("charge_efficiency"), f"battery {bid}.charge_efficiency", lo=1e-6, hi=1.0)
            eta_d = _num(b.get("discharge_efficiency"), f"battery {bid}.discharge_efficiency", lo=1e-6, hi=1.0)
        elif "round_trip_efficiency" in b:
            rte = _num(b["round_trip_efficiency"], f"battery {bid}.round_trip_efficiency", lo=1e-6, hi=1.0)
            eta_c = eta_d = math.sqrt(rte)
        else:
            _fail(f"battery {bid} needs charge_efficiency and discharge_efficiency")
        if b.get("standby") is True:
            continue
        batteries.append(
            {"id": bid, "node_id": b["node_id"], "power_capacity_mw": P, "energy_capacity_mwh": E,
             "min_soc_mwh": smin, "initial_soc_mwh": s0, "final_soc_mwh": s_end, "charge_efficiency": eta_c,
             "discharge_efficiency": eta_d, "added_by_candidate": b.get("added_by_candidate"),
             "active_from_hour": int(b.get("active_from_hour", 0)),
             "active_to_hour": int(b.get("active_to_hour", T))}
        )

    dem_raw = scen.get("demand_mw_by_node") or {}
    if not isinstance(dem_raw, dict):
        _fail("demand_mw_by_node must be an object")
    unknown_dem = set(dem_raw) - node_set
    if unknown_dem:
        _fail(f"demand given for unknown nodes: {sorted(unknown_dem)}")
    demand = np.zeros((len(node_ids), T))
    for i, n in enumerate(node_ids):
        if n in dem_raw:
            demand[i] = _series(dem_raw[n], T, f"demand_mw_by_node.{n}")

    objective = dict(DEFAULT_OBJECTIVE)
    for key, value in (scen.get("objective") or {}).items():
        if key not in DEFAULT_OBJECTIVE:
            _fail(f"objective has unknown field {key!r}")
        objective[key] = _num(value, f"objective.{key}", lo=0.0)

    raw_events = merge_events(scen, events) if include_scenario_events else (events or [])
    evs = normalise_events(raw_events, T, set(gen_ids), {ln["id"] for ln in lines})

    emission_factors = dict(DEFAULT_EMISSION_FACTORS)
    for k, v in (scen.get("emission_factors_t_per_mwh") or {}).items():
        emission_factors[k.lower()] = _num(v, f"emission_factors_t_per_mwh.{k}", lo=0.0)

    avail = np.array(avail_rows, dtype=float).reshape(len(generators), T)
    gen_online = np.ones_like(avail, dtype=bool)
    line_cap = np.array([[ln["capacity_mw"]] * T for ln in lines], dtype=float).reshape(len(lines), T)
    gen_cost = np.array([[g["variable_cost_usd_per_mwh"]] * T for g in generators], dtype=float).reshape(len(generators), T)
    dr_cap = np.zeros((len(node_ids), T), dtype=float)
    dr_cost = np.full((len(node_ids), T), 300.0, dtype=float)
    g_idx = {g["id"]: i for i, g in enumerate(generators)}
    l_idx = {ln["id"]: i for i, ln in enumerate(lines)}
    n_idx = {n: i for i, n in enumerate(node_ids)}
    
    for ev in evs:
        sl = slice(ev["from_hour"], ev["to_hour"])
        if ev["type"] == "generator_outage":
            avail[g_idx[ev["id"]], sl] = 0.0
            gen_online[g_idx[ev["id"]], sl] = False
        else:
            line_cap[l_idx[ev["id"]], sl] = 0.0

    limits = _limits(scenario)
    for mod in mods:
        kind = mod.get("type")
        from_hour = mod.get("from_hour", 0)
        to_hour = mod.get("to_hour", T)
        if kind == "emergency_rating":
            lid = mod["line_id"]
            factor = mod["factor"]
            for t in range(from_hour, to_hour):
                if line_cap[l_idx[lid], t] > 0:
                    line_cap[l_idx[lid], t] = lines[l_idx[lid]]["capacity_mw"] * factor
        elif kind == "demand_response":
            node_idx = n_idx[mod["node_id"]]
            max_mw = mod["max_mw"]
            cost_usd = mod.get("cost_usd_per_mwh", limits["demand_response"]["default_cost_usd_per_mwh"])
            for t in range(from_hour, to_hour):
                dr_cap[node_idx, t] = min(demand[node_idx, t], dr_cap[node_idx, t] + max_mw)
                dr_cost[node_idx, t] = cost_usd
        elif kind == "hydro_reserve_release":
            gid = mod["generator_id"]
            extra_mw = mod["extra_mw"]
            water_val = mod.get("water_value_usd_per_mwh", limits["hydro_reserve_release"]["default_water_value_usd_per_mwh"])
            for t in range(from_hour, to_hour):
                if gen_online[g_idx[gid], t]:
                    avail[g_idx[gid], t] += extra_mw
                    gen_cost[g_idx[gid], t] = water_val
        elif kind == "start_peaker":
            gid = mod["generator_id"]
            for t in range(from_hour, to_hour):
                if t == from_hour:
                    avail[g_idx[gid], t] = 0.0
                elif gen_online[g_idx[gid], t]:
                    avail[g_idx[gid], t] = generators[g_idx[gid]]["capacity_mw"] * limits["start_peaker"]["overdrive_factor"]

    return Grid(
        scenario_id=sid, T=T, dt=dt, timestamps=list(stamps), node_ids=node_ids, lines=lines,
        generators=generators, batteries=batteries, demand=demand, avail=avail,
        gen_online=gen_online, line_cap=line_cap, gen_cost=gen_cost, dr_cap=dr_cap, dr_cost=dr_cost, emission_factors=emission_factors,
        objective=objective,
        runback_hours={ev["from_hour"] for ev in evs if ev["mode"] == "sudden" and ev["from_hour"] > 0},
        options=normalise_options(options), candidate_id=cid, modifications=mods, events=evs,
    )
