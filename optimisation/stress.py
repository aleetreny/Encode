"""Outage stress sweep: planned maintenance and sudden trips on every asset.

Takes every generator and every line out of service, as planned maintenance and as a
sudden trip, in several time windows, on the baseline grid and on each demo candidate,
in normal and strict mode. Every result must pass these checks:

1. normal mode always solves (`optimal`) and passes the independent validator
2. the outaged plant produces 0 MW / the outaged line carries 0 MW during the outage
3. sudden trip: every hour before the trip is identical to the no-outage plan (no hindsight)
4. knowing in advance never hurts: planned objective <= sudden objective
5. losing an asset never helps: objective with outage >= objective without it
6. adding an asset never hurts: candidate objective <= baseline objective (planned outages)
7. strict mode returns `optimal` (with 0 unserved, validated) or `infeasible` with a reason,
   never `error`; if normal mode served all demand under a planned outage, strict must solve

    python -m optimisation.stress            # full sweep (~1 000 solves, well under a minute)
    python -m optimisation.stress --quick    # reduced sweep (used by the test suite)
"""

from __future__ import annotations

import argparse
import time
from collections import defaultdict

from . import load_scenario, solve, validate
from .demo import CANDIDATES, FIXTURE

TOL = 1e-3  # USD / MW tolerance on objective comparisons and pinned values

WINDOWS = {
    "night (00-04)": (0, 4),
    "morning (06-10)": (6, 10),
    "midday solar (10-14)": (10, 14),
    "evening peak (17-21)": (17, 21),
    "late (20-24)": (20, 24),
}
QUICK_WINDOWS = ("midday solar (10-14)", "evening peak (17-21)")
PINNED_BLOCKS = ("generation_mw", "battery_charge_mw", "battery_discharge_mw", "line_flow_mw", "unserved_mw")


class Sweep:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.cases = 0
        self.solves = 0
        self.stats: dict[tuple[str, str], dict] = defaultdict(
            lambda: {"cases": 0, "with_unserved": 0, "max_unserved_mwh": 0.0, "worst": None,
                     "strict_infeasible": 0}
        )

    def check(self, ok: bool, msg: str) -> bool:
        if not ok:
            self.failures.append(msg)
        return ok


def _events(scen: dict, quick: bool) -> list[tuple[str, dict]]:
    windows = {k: v for k, v in WINDOWS.items() if not quick or k in QUICK_WINDOWS}
    assets = [("generator_outage", g["id"]) for g in scen["generators"]]
    assets += [("line_outage", ln["id"]) for ln in scen["lines"]]
    out = []
    for kind, ident in assets:
        for label, (a, b) in windows.items():
            out.append((label, {"type": kind, "id": ident, "from_hour": a, "to_hour": b}))
    return out


def run(quick: bool = False, verbose: bool = True) -> dict:
    scen = load_scenario(FIXTURE)
    sweep = Sweep()
    t0 = time.perf_counter()
    candidates = [None] + (CANDIDATES[:1] if quick else CANDIDATES)

    for cand in candidates:
        cname = cand["candidate_id"] if cand else "baseline"
        cand_arg = None if cand is None else {k: v for k, v in cand.items() if k != "description"}
        plan = solve(scen, cand_arg)
        sweep.solves += 1
        sweep.check(plan["status"] == "optimal" and validate(scen, plan)["passed"], f"{cname}: no-outage plan failed")
        base_obj = plan["objective"]["total_usd"]

        for window, ev in _events(scen, quick):
            results = {}
            for mode in ("planned", "sudden"):
                event = {**ev, "mode": mode}
                tag = f"{cname} | {mode} {ev['type']} {ev['id']} {window}"
                sweep.cases += 1
                sol = solve(scen, cand_arg, [event])
                sweep.solves += sol["solver"]["solves"]
                results[mode] = sol
                if not sweep.check(sol["status"] == "optimal", f"{tag}: status {sol['status']} ({sol['message']})"):
                    continue
                val = validate(scen, sol, {"allow_unserved": True})
                sweep.check(val["passed"], f"{tag}: validation failed {val['violations'][:2]}")

                a, b = ev["from_hour"], ev["to_hour"]
                if ev["type"] == "generator_outage":
                    out = sol["timeseries"]["generation_mw"][ev["id"]][a:b]
                else:
                    out = sol["timeseries"]["line_flow_mw"][ev["id"]][a:b]
                sweep.check(all(abs(x) <= TOL for x in out), f"{tag}: outaged asset still active {out}")
                sweep.check(sol["objective"]["total_usd"] >= base_obj - TOL,
                            f"{tag}: outage made the objective better ({sol['objective']['total_usd']} < {base_obj})")
                if mode == "sudden":
                    for block in PINNED_BLOCKS:
                        for key, series in sol["timeseries"][block].items():
                            before = plan["timeseries"][block][key][:a]
                            sweep.check(
                                all(abs(x - y) <= TOL for x, y in zip(series[:a], before)),
                                f"{tag}: hindsight - {block}.{key} changed before the trip",
                            )

                st = sweep.stats[(ev["type"], mode)]
                st["cases"] += 1
                uns = sol["metrics"]["unserved_mwh"]
                if uns > TOL:
                    st["with_unserved"] += 1
                if uns > st["max_unserved_mwh"]:
                    st["max_unserved_mwh"], st["worst"] = uns, f"{ev['id']} {window} ({cname})"

                strict = solve(scen, cand_arg, [event], {"allow_unserved": False})
                sweep.solves += max(strict["solver"]["solves"], 1)
                sweep.check(strict["status"] in ("optimal", "infeasible"), f"{tag} strict: status {strict['status']}")
                if strict["status"] == "optimal":
                    sweep.check(validate(scen, strict, {"allow_unserved": False})["passed"], f"{tag} strict: invalid")
                    sweep.check(strict["metrics"]["unserved_mwh"] == 0, f"{tag} strict: unserved demand")
                else:
                    st["strict_infeasible"] += 1
                    sweep.check(bool(strict["message"]), f"{tag} strict: infeasible without a reason")
                    if mode == "planned":
                        sweep.check(uns > TOL, f"{tag} strict: infeasible although normal mode served all demand")

            p, s = results.get("planned"), results.get("sudden")
            if p and s and p["status"] == s["status"] == "optimal":
                sweep.check(p["objective"]["total_usd"] <= s["objective"]["total_usd"] + TOL,
                            f"{cname} | {ev['id']} {window}: planned worse than sudden")

    # adding an asset never hurts under the same planned outage
    if not quick:
        for window, ev in _events(scen, quick):
            event = [{**ev, "mode": "planned"}]
            b = solve(scen, None, event)
            for cand in CANDIDATES:
                c = solve(scen, {k: v for k, v in cand.items() if k != "description"}, event)
                sweep.solves += 2
                sweep.check(c["objective"]["total_usd"] <= b["objective"]["total_usd"] + TOL,
                            f"{cand['candidate_id']} | planned {ev['id']} {window}: candidate worse than baseline")

    # a planned maintenance and a sudden crash on the same day
    combos = [
        [{"type": "generator_outage", "id": "coal_cs", "from_hour": 8, "to_hour": 16, "mode": "planned"},
         {"type": "generator_outage", "id": "gas_centro", "from_hour": 18, "to_hour": 22, "mode": "sudden"}],
        [{"type": "line_outage", "id": "L2", "from_hour": 6, "to_hour": 10, "mode": "planned"},
         {"type": "line_outage", "id": "L3", "from_hour": 19, "to_hour": 21, "mode": "sudden"}],
        [{"type": "generator_outage", "id": "hydro_sur", "from_hour": 0, "to_hour": 24, "mode": "planned"},
         {"type": "generator_outage", "id": "gas_ng", "from_hour": 12, "to_hour": 20, "mode": "sudden"},
         {"type": "line_outage", "id": "L1", "from_hour": 15, "to_hour": 17, "mode": "sudden"}],
    ]
    for evs in combos:
        for cand in candidates:
            cand_arg = None if cand is None else {k: v for k, v in cand.items() if k != "description"}
            sol = solve(scen, cand_arg, evs)
            sweep.cases += 1
            sweep.solves += sol["solver"]["solves"]
            tag = f"combined {[e['id'] for e in evs]} ({cand['candidate_id'] if cand else 'baseline'})"
            if sweep.check(sol["status"] == "optimal", f"{tag}: {sol['status']} {sol['message']}"):
                sweep.check(validate(scen, sol)["passed"], f"{tag}: validation failed")
                
    # 5 new operational levers on evening peak GAS_TRIP
    if not quick:
        scen_standby = dict(scen)
        scen_standby["batteries"] = list(scen.get("batteries", [])) + [{
            "id": "bat_standby", "node_id": "n_centro", "power_capacity_mw": 50, "energy_capacity_mwh": 100,
            "charge_efficiency": 0.95, "discharge_efficiency": 0.95, "initial_soc_mwh": 100, "standby": True
        }]
        
        levers_cand = {
            "candidate_id": "all_5_levers",
            "modifications": [
                {"type": "emergency_rating", "line_id": "L2", "factor": 1.1, "from_hour": 17, "to_hour": 21},
                {"type": "demand_response", "node_id": "n_centro", "max_mw": 50, "from_hour": 17, "to_hour": 21},
                {"type": "hydro_reserve_release", "generator_id": "hydro_sur", "extra_mw": 50, "from_hour": 17, "to_hour": 21},
                {"type": "start_peaker", "generator_id": "diesel_centro", "from_hour": 17, "to_hour": 21},
                {"type": "activate_reserve_bess", "battery_id": "bat_standby", "from_hour": 17, "to_hour": 21},
            ]
        }
        sol = solve(scen_standby, levers_cand, [{"type": "generator_outage", "id": "gas_centro", "from_hour": 17, "to_hour": 21, "mode": "sudden"}])
        sweep.cases += 1
        sweep.solves += sol["solver"]["solves"]
        sweep.check(sol["status"] == "optimal", f"5 new levers: status {sol['status']} ({sol['message']})")

    elapsed = time.perf_counter() - t0
    summary = {
        "passed": not sweep.failures,
        "cases": sweep.cases,
        "solves": sweep.solves,
        "seconds": round(elapsed, 1),
        "failures": sweep.failures[:50],
        "by_outage_type": {f"{k[0]} / {k[1]}": v for k, v in sorted(sweep.stats.items())},
    }
    if verbose:
        _print(summary)
    return summary


def _print(summary: dict) -> None:
    print(f"Outage stress sweep: {summary['cases']} cases, {summary['solves']} solves, {summary['seconds']} s\n")
    print(f"  {'outage / mode':34} {'cases':>5} {'w/ unserved':>11} {'max unserved MWh':>16} "
          f"{'strict infeasible':>17}  worst case")
    for name, st in summary["by_outage_type"].items():
        print(f"  {name:34} {st['cases']:5d} {st['with_unserved']:11d} {st['max_unserved_mwh']:16.1f} "
              f"{st['strict_infeasible']:17d}  {st['worst'] or '-'}")
    if summary["passed"]:
        print("\nAll checks passed: every case solved, validated, respected the outage, "
              "had no hindsight, and planned <= sudden.")
    else:
        print(f"\n{len(summary['failures'])} FAILURES:")
        for f in summary["failures"]:
            print("  -", f)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quick", action="store_true", help="reduced sweep")
    summary = run(quick=parser.parse_args().quick)
    raise SystemExit(0 if summary["passed"] else 1)


if __name__ == "__main__":
    main()
