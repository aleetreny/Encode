"""Core Neuro-Symbolic Orchestrator for GridPilot (Gemini 4 Argon).

Implements:
- `run_investigation(scenario_id, settings)`: Strict Person 4 `AgentResult` contract entrypoint
  (works both synchronously and via `await`).
- `run_crisis_investigation(scenario_id, settings)`: Extended entrypoint returning the canonical
  `agent_result` alongside full N-1 sudden-outage crisis recovery, household reconnection metrics,
  Modification Menu candidate rankings, and Chilean legal compliance audit.
"""

from __future__ import annotations

from typing import Any

from agent.gemini_client import GeminiArgonClient
from agent.regulatory import (
    build_regulatory_compliance_matrix,
    estimate_affected_households,
)
from agent.tools import AgentToolkit, ToolTraceRecorder


class AwaitableDict(dict):
    """Dictionary that can be used directly as a `dict` OR awaited in an `async` workflow."""

    def __await__(self):
        async def _wrap() -> dict[str, Any]:
            return dict(self)

        return _wrap().__await__()


class GridPilotAgent:
    """Autonomous Chilean National Grid Coordinator agent powered by Gemini 4 Argon."""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.recorder = ToolTraceRecorder(execution_mode="live")
        self.toolkit = AgentToolkit(recorder=self.recorder)
        self.gemini = GeminiArgonClient(model=model, api_key=api_key)

    def execute_investigation(
        self,
        scenario_id: str = "chile-demo-001",
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run complete SCED + N-1 sudden crisis investigation and return full dossier."""
        cfg = dict(settings or {})
        # Recording sanitized runtime settings at start of investigation
        candidate_battery_policy = str(cfg.get("battery_policy", "optimised"))
        candidate_allow_shed = bool(cfg.get("allow_load_shedding", False))

        # 1. Load Scenario
        scenario = self.toolkit.load_scenario(scenario_id)

        # 2. Inspect CEN Operational Evidence & Modification Menu
        evidence = self.toolkit.inspect_evidence(
            scenario_id=scenario_id,
            source_id=scenario.get("source_id"),
        )

        # 3. Solve & Validate Canonical Baseline (Batteries Disabled, matching backend_options)
        baseline_settings = {
            "battery_policy": "disabled",
            "allow_load_shedding": candidate_allow_shed,
        }
        baseline = self.toolkit.run_optimisation(
            scenario=scenario,
            settings=baseline_settings,
            run_label="baseline_battery_disabled",
        )
        baseline_validation = self.toolkit.validate_candidate(
            scenario=scenario,
            solution=baseline,
            settings=baseline_settings,
            run_label="baseline_validation",
        )

        # 4. Solve & Validate Canonical Candidate (Batteries Co-Optimised per settings)
        candidate_settings = {
            "battery_policy": candidate_battery_policy,
            "allow_load_shedding": candidate_allow_shed,
        }
        candidate = self.toolkit.run_optimisation(
            scenario=scenario,
            settings=candidate_settings,
            run_label=f"candidate_battery_{candidate_battery_policy}",
        )
        candidate_validation = self.toolkit.validate_candidate(
            scenario=scenario,
            solution=candidate,
            settings=candidate_settings,
            run_label="candidate_validation",
        )

        # Self-correction if candidate is infeasible with allow_load_shedding=False
        if candidate.get("status") != "optimal" and not candidate_allow_shed:
            self.recorder.retry(
                "run_optimisation",
                {
                    "scenario_id": scenario_id,
                    "reason": "Strict zero-shedding dispatch infeasible; enabling NTSyCS EDAC emergency shedding.",
                    "retry_settings": {
                        "battery_policy": candidate_battery_policy,
                        "allow_load_shedding": True,
                    },
                },
            )
            candidate_settings["allow_load_shedding"] = True
            candidate = self.toolkit.run_optimisation(
                scenario=scenario,
                settings=candidate_settings,
                run_label="candidate_emergency_edac_retry",
            )
            candidate_validation = self.toolkit.validate_candidate(
                scenario=scenario,
                solution=candidate,
                settings=candidate_settings,
                run_label="candidate_emergency_edac_validation",
            )

        # 5. Gemini 4 Argon Autonomous Candidate Sweep & Sudden N-1 Crisis Stress-Test
        plan = self.gemini.plan_candidates_and_crisis(scenario=scenario, evidence=evidence)
        candidate_sweeps: list[dict[str, Any]] = []
        for cand_spec in plan.get("candidates", []):
            cid = cand_spec["candidate_id"]
            c_sol = self.toolkit.run_optimisation(
                scenario=scenario,
                settings={"battery_policy": "optimised", "allow_load_shedding": False},
                candidate=cand_spec,
                run_label=f"menu_{cid}",
            )
            c_val = self.toolkit.validate_candidate(
                scenario=scenario,
                solution=c_sol,
                settings={"battery_policy": "optimised", "allow_load_shedding": False},
                run_label=f"validate_{cid}",
            )
            c_comp = self.toolkit.compare_results(
                baseline=baseline,
                candidate=c_sol,
                baseline_validation=baseline_validation,
                candidate_validation=c_val,
            )
            candidate_sweeps.append(
                {
                    "candidate_id": cid,
                    "description": cand_spec.get("description", cid),
                    "modifications": cand_spec.get("modifications", []),
                    "passed_validation": c_val.get("passed", False),
                    "curtailment_reduction_mwh": c_comp.get("curtailment_reduction_mwh", 0.0),
                    "assumed_cost_delta_usd": c_comp.get("assumed_cost_delta_usd", 0.0),
                    "metrics": (c_sol.get("native_result") or {}).get("metrics"),
                }
            )

        # Sudden N-1 Crisis Simulation (Plant Outage + Self-Correction + Household Reconnection)
        crisis_event = plan.get("crisis_event")
        crisis_analysis: dict[str, Any] | None = None
        if crisis_event is not None:
            crisis_ev_Payload = [
                {
                    k: crisis_event[k]
                    for k in ("type", "id", "from_hour", "to_hour", "mode")
                    if k in crisis_event
                }
            ]
            # Step 5a: Attempt sudden crisis under strict zero load-shedding (triggers self-correction if infeasible)
            strict_crisis_sol = self.toolkit.run_optimisation(
                scenario=scenario,
                settings={"battery_policy": "disabled", "allow_load_shedding": False},
                events=crisis_ev_Payload,
                run_label="crisis_strict_zero_shedding",
            )
            if strict_crisis_sol.get("status") != "optimal":
                self.recorder.retry(
                    "run_optimisation",
                    {
                        "scenario_id": scenario_id,
                        "crisis_event_id": crisis_event["id"],
                        "reason": (
                            "Sudden N-1 generator outage exceeds corridor/peaker reserve under strict "
                            "zero-shedding; activating CNE NTSyCS EDAC controlled load-shedding "
                            "(allow_load_shedding=True) and BESS/corridor emergency redispatch."
                        ),
                    },
                )

            # Step 5b: Quantify unmitigated crisis impact (no BESS / no upgrades, EDAC enabled)
            unmitigated_crisis_sol = self.toolkit.run_optimisation(
                scenario=scenario,
                settings={"battery_policy": "disabled", "allow_load_shedding": True},
                events=crisis_ev_Payload,
                run_label="crisis_unmitigated_edac",
            )
            unmitigated_val = self.toolkit.validate_candidate(
                scenario=scenario,
                solution=unmitigated_crisis_sol,
                settings={"battery_policy": "disabled", "allow_load_shedding": True},
                run_label="validate_crisis_unmitigated",
            )

            # Step 5c: Mitigate crisis and reconnect households using BESS + best Modification Menu candidate
            best_cand = None
            if plan.get("candidates"):
                best_cand = plan["candidates"][-1]  # combined BESS + corridor uprate

            mitigated_crisis_sol = self.toolkit.run_optimisation(
                scenario=scenario,
                settings={"battery_policy": "optimised", "allow_load_shedding": True},
                candidate=best_cand,
                events=crisis_ev_Payload,
                run_label="crisis_mitigated_recovery",
            )
            mitigated_val = self.toolkit.validate_candidate(
                scenario=scenario,
                solution=mitigated_crisis_sol,
                settings={"battery_policy": "optimised", "allow_load_shedding": True},
                run_label="validate_crisis_mitigated",
            )

            dt = float(scenario.get("time_step_hours", 1.0))
            unmit_shed = unmitigated_crisis_sol.get("load_shedding_mw_by_node") or {}
            mit_shed = mitigated_crisis_sol.get("load_shedding_mw_by_node") or {}
            hh_impact = estimate_affected_households(
                unserved_mw_by_node_before=unmit_shed,
                unserved_mw_by_node_after=mit_shed,
                time_step_hours=dt,
            )
            crisis_analysis = {
                "event": crisis_event,
                "event_description": crisis_event.get("description", crisis_event["id"]),
                "strict_zero_shedding_status": strict_crisis_sol.get("status"),
                "crisis_unserved_mwh": hh_impact["total_unserved_mwh_before"],
                "mitigated_unserved_mwh": hh_impact["total_unserved_mwh_after"],
                "energy_restored_mwh": hh_impact["total_energy_restored_mwh"],
                "households_disconnected_peak": hh_impact["total_households_affected_before"],
                "households_still_affected": hh_impact["total_households_affected_after"],
                "households_reconnected": hh_impact["total_households_reconnected"],
                "reconnection_rate_pct": hh_impact["reconnection_rate_pct"],
                "recommended_reconfiguration": (
                    best_cand["candidate_id"] if best_cand else "bess_cooptimisation"
                ),
                "household_breakdown_by_node": hh_impact["nodes"],
                "unmitigated_validation_passed": unmitigated_val.get("passed", False),
                "mitigated_validation_passed": mitigated_val.get("passed", False),
                "unmitigated_solution": unmitigated_crisis_sol,
                "mitigated_solution": mitigated_crisis_sol,
            }

        # 6. Compare Canonical Baseline vs Canonical Candidate
        comparison = self.toolkit.compare_results(
            baseline=baseline,
            candidate=candidate,
            baseline_validation=baseline_validation,
            candidate_validation=candidate_validation,
            scenario=scenario,
        )

        # 7. Gemini 4 Argon Executive Synthesis & Operator Report Generation
        crisis_summary_for_llm = (
            {
                k: v
                for k, v in crisis_analysis.items()
                if k not in ("unmitigated_solution", "mitigated_solution")
            }
            if crisis_analysis
            else None
        )
        gemini_narrative, model_execution = self.gemini.synthesise_investigation(
            scenario=scenario,
            evidence=evidence,
            comparison=comparison,
            crisis_analysis=crisis_summary_for_llm,
        )
        operator_report = self.toolkit.generate_operator_report(
            scenario=scenario,
            evidence=evidence,
            comparison=comparison,
            candidate_validation=candidate_validation,
            crisis_analysis=crisis_summary_for_llm,
            candidate_sweeps=candidate_sweeps,
            gemini_narrative=gemini_narrative,
        )

        # Build regulatory compliance matrix
        regulatory_compliance = build_regulatory_compliance_matrix(
            baseline_metrics=comparison.get("baseline_metrics") or {},
            candidate_metrics=comparison.get("candidate_metrics") or {},
            validation_passed=bool(candidate_validation.get("passed", False)),
            household_impact=(
                {
                    "total_households_affected_before": crisis_analysis["households_disconnected_peak"],
                    "total_households_reconnected": crisis_analysis["households_reconnected"],
                    "reconnection_rate_pct": crisis_analysis["reconnection_rate_pct"],
                }
                if crisis_analysis
                else None
            ),
        )

        # Strict Person 4 AgentResult payload (extra="forbid")
        agent_result = {
            "baseline": baseline,
            "candidate": candidate,
            "tool_trace": self.recorder.events,
            "operator_report": operator_report,
            "model_execution": model_execution,
        }

        return {
            "agent_result": agent_result,
            "comparison": comparison,
            "baseline_validation": baseline_validation,
            "candidate_validation": candidate_validation,
            "candidate_sweeps": candidate_sweeps,
            "crisis_analysis": crisis_analysis,
            "regulatory_compliance": regulatory_compliance,
        }


def run_investigation(
    scenario_id: str = "chile-demo-001",
    settings: dict[str, Any] | None = None,
) -> AwaitableDict:
    """Primary entrypoint required by Person 4's backend worker (`agent:run_investigation`).

    Returns an `AwaitableDict` matching `backend.models.AgentResult` (`baseline`, `candidate`,
    `tool_trace`, `operator_report`, `model_execution`). Can be called either synchronously
    (`res = run_investigation(...)`) or asynchronously (`res = await run_investigation(...)`).
    """
    agent = GridPilotAgent()
    full_dossier = agent.execute_investigation(scenario_id=scenario_id, settings=settings)
    return AwaitableDict(full_dossier["agent_result"])


def run_crisis_investigation(
    scenario_id: str = "chile-sen-5node",
    settings: dict[str, Any] | None = None,
) -> AwaitableDict:
    """Extended entrypoint returning the full SCED + N-1 sudden crisis & household reconnection dossier."""
    agent = GridPilotAgent()
    full_dossier = agent.execute_investigation(scenario_id=scenario_id, settings=settings)
    return AwaitableDict(full_dossier)
