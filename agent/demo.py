"""Interactive CLI demonstration for GridPilot (`python3 -m agent.demo`).

Demonstrates:
1. Canonical SCED Investigation (`chile-demo-001`) — Person 4 Backend Contract (`AgentResult`).
2. 5-Node Chilean SEN Crisis Simulation (`chile-sen-5node`) — Sudden 700 MW Central Gas Plant
   outage (`mode="sudden"`), autonomous self-correction under CNE NTSyCS EDAC, and emergency
   reconnection of affected Chilean households.
"""

from __future__ import annotations

import json
from typing import Any

from agent.orchestrator import run_crisis_investigation, run_investigation


def _print_banner(title: str) -> None:
    line = "=" * 88
    print(f"\n{line}\n{title}\n{line}")


def main() -> None:
    _print_banner("1. CANONICAL SCED INVESTIGATION (`chile-demo-001`) — PERSON 4 BACKEND CONTRACT")
    res_canonical = run_investigation(
        "chile-demo-001",
        {"battery_policy": "optimised", "allow_load_shedding": False},
    )
    print(f"Top-level keys (strict AgentResult): {list(res_canonical.keys())}")
    print(f"Model Execution Attestation        : {res_canonical['model_execution']}")
    print(f"Baseline Status                    : {res_canonical['baseline']['status']}")
    print(f"Candidate Status                   : {res_canonical['candidate']['status']}")
    print(f"Total Tool Trace Events            : {len(res_canonical['tool_trace'])}")
    succ_tools = sorted(
        {ev["tool"] for ev in res_canonical["tool_trace"] if ev["status"] == "success"}
    )
    print(f"Successful Tools Recorded          : {succ_tools}")
    print("\nExecutive Summary (`operator_report.summary`):")
    print(f"  {res_canonical['operator_report']['summary']}")

    _print_banner(
        "2. CHILEAN SEN 5-NODE CRISIS SIMULATION & HOUSEHOLD RECONNECTION (`chile-sen-5node`)"
    )
    dossier = run_crisis_investigation(
        "chile-sen-5node",
        {"battery_policy": "optimised", "allow_load_shedding": False},
    )
    comp = dossier["comparison"]
    b_m = comp["baseline_metrics"]
    c_m = comp["candidate_metrics"]

    print("Normal Day SCED Dispatch (Baseline vs Co-Optimised BESS):")
    print(
        f"  - Solar/Wind Curtailment : {b_m['curtailment_mwh']:.1f} MWh -> {c_m['curtailment_mwh']:.1f} MWh "
        f"(Reduction: {comp['curtailment_reduction_mwh']:.1f} MWh)"
    )
    print(
        f"  - Dispatchable Cost Proxy: ${b_m['assumed_cost_usd']:,.2f} -> ${c_m['assumed_cost_usd']:,.2f} "
        f"(Delta: ${comp['assumed_cost_delta_usd']:+,.2f} USD)"
    )

    print("\nModification Menu Candidate Sweeps:")
    for item in dossier["candidate_sweeps"]:
        print(
            f"  * [{item['candidate_id']}] {item['description']}\n"
            f"    -> Curtailment reduction: {item['curtailment_reduction_mwh']:.1f} MWh | "
            f"Cost delta: ${item['assumed_cost_delta_usd']:+,.2f} USD | "
            f"Physics validated: {item['passed_validation']}"
        )

    crisis: dict[str, Any] | None = dossier.get("crisis_analysis")
    if crisis:
        print("\nSudden N-1 Crisis Simulation (No Hindsight):")
        print(f"  - Contingency Event              : {crisis['event_description']}")
        print(
            f"  - Strict Zero-Shedding Attempt   : {crisis['strict_zero_shedding_status']} "
            "(Autonomous Self-Correction -> NTSyCS EDAC Activated)"
        )
        print(
            f"  - Unmitigated Crisis Unserved    : {crisis['crisis_unserved_mwh']:.1f} MWh "
            f"(~{crisis['households_disconnected_peak']:,} Chilean households disconnected)"
        )
        print(
            f"  - Mitigated Recovery Unserved    : {crisis['mitigated_unserved_mwh']:.1f} MWh "
            f"via `{crisis['recommended_reconfiguration']}`"
        )
        print(
            f"  - Chilean Households Reconnected : {crisis['households_reconnected']:,} / "
            f"{crisis['households_disconnected_peak']:,} ({crisis['reconnection_rate_pct']:.1f}%)"
        )

    print("\nChilean Regulatory Compliance Audit:")
    for rule in dossier["regulatory_compliance"]:
        print(f"  - [{rule['status'].upper()}] {rule['code']} ({rule['title']}): {rule['finding']}")


if __name__ == "__main__":
    main()
