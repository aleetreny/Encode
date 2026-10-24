"""Compact, LLM-friendly summary of a solve() result.

A full solution is ~50 KB of JSON (hourly arrays for every asset). Sending that to Gemini is slow,
costly and invites misreading. ``summarise`` condenses it to the facts an operator report needs
(~2-3 KB): status, headline metrics, where and when limits bind, where demand was not served,
what the batteries did, nodal price separation, and the validation / comparison verdicts.

Every number is copied from (or a simple total/average of) the solve, validate and compare outputs;
nothing is estimated. Prices are LP marginal values and are labelled as informational.
"""

from __future__ import annotations

HEADLINE = (
    "curtailment_mwh",
    "unserved_mwh",
    "assumed_cost_proxy_usd",
    "battery_losses_mwh",
    "emergency_runback_mwh",
)
# binding-constraint types worth telling the operator about, most important first
PRIORITY = (
    "unserved_energy",
    "emergency_runback",
    "outage",
    "line_limit",
    "ramp_limit",
    "battery_full",
    "battery_empty",
    "renewable_curtailed",
    "dispatchable_at_capacity",
    "battery_power_limit",
)


def hour_ranges(hours: list[int]) -> str:
    """[9, 10, 11, 14] -> '9-11, 14'."""
    if not hours:
        return ""
    hours = sorted(hours)
    parts, start, prev = [], hours[0], hours[0]
    for h in hours[1:] + [None]:
        if h is not None and h == prev + 1:
            prev = h
            continue
        parts.append(f"{start}-{prev}" if prev != start else f"{start}")
        if h is not None:
            start = prev = h
    return ", ".join(parts)


def _r(x: float, digits: int = 1) -> float:
    v = round(float(x), digits)
    return 0.0 if v == 0 else v


def summarise(
    solution: dict,
    validation: dict | None = None,
    comparison: dict | None = None,
    prices: dict | None = None,
    max_constraints: int = 8,
) -> dict:
    """Condense a ``solve()`` output (plus optional ``validate()``, ``compare()`` and
    ``nodal_prices()`` outputs)."""
    out: dict = {
        "status": solution.get("status"),
        "message": solution.get("message"),
        "scenario_id": solution.get("scenario_id"),
        "candidate_id": solution.get("candidate_id"),
        "modifications": [
            {k: v for k, v in m.items() if k in ("type", "node_id", "line_id", "power_mw", "energy_mwh", "new_capacity_mw")}
            for m in solution.get("modifications") or []
        ],
        "events": solution.get("events") or [],
        "allow_unserved": (solution.get("options") or {}).get("allow_unserved"),
        "units": "MW power, MWh energy, USD assumed-cost proxy (not CEN costs); hours are step indices from 0",
    }
    if validation is not None:
        out["validation"] = {
            "passed": validation.get("passed"),
            "violation_count": validation.get("violation_count", len(validation.get("violations") or [])),
            "first_violations": [v.get("detail") for v in (validation.get("violations") or [])[:3]],
        }
    if solution.get("status") != "optimal":
        return out

    m = solution["metrics"]
    out["metrics"] = {k: _r(m.get(k, 0.0)) for k in HEADLINE}
    out["unserved_by_node"] = {
        b["id"]: {"mwh": _r(m["unserved_mwh_by_node"][b["id"]]), "hours": hour_ranges(b["hours"])}
        for b in solution["binding_constraints"]
        if b["type"] == "unserved_energy"
    }

    ranked = sorted(
        (b for b in solution["binding_constraints"] if b["type"] in PRIORITY),
        key=lambda b: (PRIORITY.index(b["type"]), -len(b["hours"])),
    )
    out["binding_constraints"] = [
        f"{b['type']} {b['id']}: hours {hour_ranges(b['hours'])} ({b['detail']})" for b in ranked[:max_constraints]
    ]
    if len(ranked) > max_constraints:
        out["binding_constraints"].append(f"... {len(ranked) - max_constraints} more in the full solution")

    ts = solution["timeseries"]
    dt = solution.get("time_step_hours") or 1.0
    batteries = {}
    for bid, ch in ts.get("battery_charge_mw", {}).items():
        dis = ts["battery_discharge_mw"][bid]
        batteries[bid] = {
            "charged_mwh": _r(sum(ch) * dt),
            "discharged_mwh": _r(sum(dis) * dt),
            "charging_hours": hour_ranges([t for t, v in enumerate(ch) if v > 1e-6]),
            "discharging_hours": hour_ranges([t for t, v in enumerate(dis) if v > 1e-6]),
        }
    out["batteries"] = batteries

    prices = (prices or {}).get("price_usd_per_mwh")
    if prices:
        nodes = list(prices)
        T = len(prices[nodes[0]])
        spreads = [max(prices[n][t] for n in nodes) - min(prices[n][t] for n in nodes) for t in range(T)]
        worst = max(range(T), key=lambda t: spreads[t])
        out["prices_usd_per_mwh"] = {
            "note": "LP marginal values (cost of 1 MWh more demand at that node and hour); informational, "
                    "not independently validated",
            # median, not mean: a few scarcity hours at the unserved-energy penalty would dominate a mean
            "median_by_node": {n: _r(sorted(prices[n])[T // 2]) for n in nodes},
            "hours_with_price_separation": hour_ranges([t for t in range(T) if spreads[t] > 1.0]),
            "largest_separation": {
                "hour": worst,
                "spread": _r(spreads[worst]),
                "cheapest_node": min(nodes, key=lambda n: prices[n][worst]),
                "most_expensive_node": max(nodes, key=lambda n: prices[n][worst]),
            },
        }

    if comparison is not None:
        out["comparison"] = {
            k: comparison.get(k)
            for k in ("comparable", "reason", "baseline_id", "candidate_id", "curtailment_reduction_mwh",
                      "unserved_reduction_mwh", "assumed_cost_delta_usd", "both_valid")
        }
        for k in ("curtailment_reduction_mwh", "unserved_reduction_mwh", "assumed_cost_delta_usd"):
            if isinstance(out["comparison"][k], (int, float)):
                out["comparison"][k] = _r(out["comparison"][k])
        out["comparison"]["notes"] = comparison.get("notes", [])
    return out
