"""Compare two ``solve()`` outputs (baseline vs candidate). See DESIGN.md section 9."""

from __future__ import annotations

from typing import Any

COMPARED_METRICS = (
    "curtailment_mwh",
    "unserved_mwh",
    "renewable_used_mwh",
    "dispatchable_mwh",
    "battery_losses_mwh",
    "assumed_cost_proxy_usd",
)

NOTES = [
    "Investment cost of the modifications is not modelled.",
    "Costs are an assumed-cost proxy on a synthetic, illustrative network, not CEN costs.",
    "Hourly transport model on a radial network; sub-hourly dynamics and reserves are not modelled.",
]


def _r(x: float) -> float:
    v = round(float(x), 6)
    return 0.0 if v == 0 else v


def compare(
    baseline: dict,
    candidate: dict,
    baseline_validation: dict | None = None,
    candidate_validation: dict | None = None,
) -> dict:
    """Deltas between two solutions. Positive ``*_reduction`` means the candidate is better."""
    out: dict[str, Any] = {
        "comparable": False,
        "reason": None,
        "baseline_id": (baseline or {}).get("candidate_id"),
        "candidate_id": (candidate or {}).get("candidate_id"),
        "modifications": (candidate or {}).get("modifications", []),
        "events": (candidate or {}).get("events", []),
        "both_valid": None,
        "metrics": None,
        "curtailment_reduction_mwh": None,
        "unserved_reduction_mwh": None,
        "assumed_cost_delta_usd": None,
        "objective_delta_usd": None,
        "line_hours_at_limit": None,
        "binding_constraints": None,
        "notes": list(NOTES),
    }
    for name, sol in (("baseline", baseline), ("candidate", candidate)):
        if not isinstance(sol, dict) or sol.get("status") != "optimal":
            status = sol.get("status") if isinstance(sol, dict) else None
            out["reason"] = f"{name} is not an optimal solution (status {status!r})"
            return out
    for key in ("scenario_id", "time_step_hours", "timestamps_utc", "events", "options"):
        if baseline.get(key) != candidate.get(key):
            out["reason"] = f"baseline and candidate differ in {key}; they are not like-for-like"
            return out
    if baseline_validation is not None or candidate_validation is not None:
        ok_b = bool(baseline_validation and baseline_validation.get("passed"))
        ok_c = bool(candidate_validation and candidate_validation.get("passed"))
        out["both_valid"] = ok_b and ok_c
        if not out["both_valid"]:
            out["reason"] = "validation failed for " + " and ".join(
                n for n, ok in (("baseline", ok_b), ("candidate", ok_c)) if not ok
            )
            return out

    mb, mc = baseline["metrics"], candidate["metrics"]
    out["metrics"] = {
        k: {"baseline": mb[k], "candidate": mc[k], "delta": _r(mc[k] - mb[k])} for k in COMPARED_METRICS
    }
    out["line_hours_at_limit"] = {
        lid: {"baseline": mb["line_hours_at_limit"].get(lid, 0.0), "candidate": h,
              "delta": _r(h - mb["line_hours_at_limit"].get(lid, 0.0))}
        for lid, h in mc["line_hours_at_limit"].items()
    }
    out.update(
        comparable=True,
        curtailment_reduction_mwh=_r(mb["curtailment_mwh"] - mc["curtailment_mwh"]),
        unserved_reduction_mwh=_r(mb["unserved_mwh"] - mc["unserved_mwh"]),
        assumed_cost_delta_usd=_r(mc["assumed_cost_proxy_usd"] - mb["assumed_cost_proxy_usd"]),
        objective_delta_usd=_r(candidate["objective"]["total_usd"] - baseline["objective"]["total_usd"]),
        binding_constraints={"baseline": baseline["binding_constraints"], "candidate": candidate["binding_constraints"]},
    )
    return out
