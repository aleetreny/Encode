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

    def execute_native_v2_investigation(
        self,
        scenario_id: str = "chile-sen-5node-demo",
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run native v2 two-stage SCED + sudden crisis investigation for `backend/native_worker.py`."""
        cfg = dict(settings or {})
        scenario = self.toolkit.load_scenario(scenario_id)
        evidence = self.toolkit.inspect_evidence(
            scenario_id=scenario_id,
            source_id=scenario.get("source_id"),
        )

        raw_opts = cfg.get("options") or {}
        options = {
            "allow_unserved": bool(raw_opts.get("allow_unserved", True)),
            "time_limit_s": float(raw_opts.get("time_limit_s", 20.0)),
        }
        candidates = list(
            cfg.get("candidates")
            or [
                {
                    "candidate_id": "north_bess",
                    "modifications": [
                        {
                            "type": "add_battery",
                            "node_id": "n_norte_grande",
                            "power_mw": 150,
                            "energy_mwh": 600,
                        }
                    ],
                },
                {
                    "candidate_id": "south_bess",
                    "modifications": [
                        {
                            "type": "add_battery",
                            "node_id": "n_sur",
                            "power_mw": 150,
                            "energy_mwh": 600,
                        }
                    ],
                },
                {
                    "candidate_id": "uprate_l2",
                    "modifications": [
                        {"type": "uprate_line", "line_id": "L2", "new_capacity_mw": 600}
                    ],
                },
            ]
        )
        crisis_events = list(
            cfg.get("crisis_events")
            or [
                {
                    "type": "generator_outage",
                    "id": "gas_centro",
                    "from_hour": 18,
                    "to_hour": 22,
                    "mode": "sudden",
                }
            ]
        )

        baseline_normal = self.toolkit.run_native_optimisation(
            scenario,
            candidate=None,
            events=[],
            options=options,
            run_label="baseline_normal",
        )
        val_base_normal = self.toolkit.validate_native_candidate(
            scenario,
            baseline_normal,
            candidate=None,
            events=[],
            options=options,
            run_label="validate_baseline_normal",
        )

        strict_crisis = self.toolkit.run_native_optimisation(
            scenario,
            candidate=None,
            events=crisis_events,
            options={**options, "allow_unserved": False},
            run_label="crisis_strict_zero_shedding",
        )
        if strict_crisis.get("status") != "optimal":
            self.recorder.retry(
                "run_optimisation",
                {
                    "scenario_id": scenario_id,
                    "reason": (
                        "Strict zero-shedding crisis dispatch infeasible; enabling CNE NTSyCS EDAC "
                        "controlled emergency load-shedding and candidate recovery."
                    ),
                },
            )

        crisis_baseline = self.toolkit.run_native_optimisation(
            scenario,
            candidate=None,
            events=crisis_events,
            options=options,
            run_label="baseline_crisis",
        )
        val_crisis_base = self.toolkit.validate_native_candidate(
            scenario,
            crisis_baseline,
            candidate=None,
            events=crisis_events,
            options=options,
            run_label="validate_baseline_crisis",
        )

        evaluated: list[dict[str, Any]] = []
        for cand_def in candidates:
            cid = cand_def["candidate_id"]
            sol_norm = self.toolkit.run_native_optimisation(
                scenario,
                candidate=cand_def,
                events=[],
                options=options,
                run_label=f"{cid}_normal",
            )
            val_norm = self.toolkit.validate_native_candidate(
                scenario,
                sol_norm,
                candidate=cand_def,
                events=[],
                options=options,
                run_label=f"validate_{cid}_normal",
            )
            comp_norm = self.toolkit.compare_native_results(
                baseline_normal,
                sol_norm,
                val_base_normal,
                val_norm,
                run_label=f"compare_{cid}_normal",
            )

            sol_cris = self.toolkit.run_native_optimisation(
                scenario,
                candidate=cand_def,
                events=crisis_events,
                options=options,
                run_label=f"{cid}_crisis",
            )
            val_cris = self.toolkit.validate_native_candidate(
                scenario,
                sol_cris,
                candidate=cand_def,
                events=crisis_events,
                options=options,
                run_label=f"validate_{cid}_crisis",
            )
            comp_cris = self.toolkit.compare_native_results(
                crisis_baseline,
                sol_cris,
                val_crisis_base,
                val_cris,
                run_label=f"compare_{cid}_crisis",
            )
            if val_norm.get("passed") and val_cris.get("passed"):
                evaluated.append(
                    {
                        "candidate_definition": cand_def,
                        "normal_solution": sol_norm,
                        "normal_validation": val_norm,
                        "normal_comparison": comp_norm,
                        "crisis_solution": sol_cris,
                        "crisis_validation": val_cris,
                        "crisis_comparison": comp_cris,
                    }
                )

        if not evaluated:
            raise ValueError("No candidate passed independent native physics validation.")

        selection_objective = str(cfg.get("selection_objective", "crisis_first"))
        if selection_objective == "normal_first":
            winner = max(
                evaluated,
                key=lambda item: (
                    float(item["normal_comparison"].get("curtailment_reduction_mwh", 0.0)),
                    float(item["crisis_comparison"].get("unserved_reduction_mwh", 0.0)),
                    -float((item["normal_solution"].get("objective") or {}).get("total_usd", 0.0)),
                ),
            )
        else:
            winner = max(
                evaluated,
                key=lambda item: (
                    float(item["crisis_comparison"].get("unserved_reduction_mwh", 0.0)),
                    float(item["normal_comparison"].get("curtailment_reduction_mwh", 0.0)),
                    -float((item["crisis_solution"].get("objective") or {}).get("total_usd", 0.0)),
                ),
            )

        dt = float(scenario.get("time_step_hours", 1.0))
        b_shed = (crisis_baseline.get("timeseries") or {}).get("unserved_mw") or {}
        c_shed = (winner["crisis_solution"].get("timeseries") or {}).get("unserved_mw") or {}
        hh_impact = estimate_affected_households(
            unserved_mw_by_node_before=b_shed,
            unserved_mw_by_node_after=c_shed,
            time_step_hours=dt,
        )
        crisis_summary = {
            "event": crisis_events[0] if crisis_events else None,
            "event_description": (
                f"Sudden {crisis_events[0]['type']} on `{crisis_events[0]['id']}` "
                f"(hours [{crisis_events[0]['from_hour']}..{crisis_events[0]['to_hour']}))"
                if crisis_events
                else "Sudden N-1 contingency"
            ),
            "strict_zero_shedding_status": strict_crisis.get("status"),
            "crisis_unserved_mwh": hh_impact["total_unserved_mwh_before"],
            "mitigated_unserved_mwh": hh_impact["total_unserved_mwh_after"],
            "energy_restored_mwh": hh_impact["total_energy_restored_mwh"],
            "households_disconnected_peak": hh_impact["total_households_affected_before"],
            "households_reconnected": hh_impact["total_households_reconnected"],
            "reconnection_rate_pct": hh_impact["reconnection_rate_pct"],
            "recommended_reconfiguration": winner["candidate_definition"]["candidate_id"],
        }

        norm_comp_for_report = {
            "both_valid": True,
            "curtailment_reduction_mwh": winner["normal_comparison"].get(
                "curtailment_reduction_mwh", 0.0
            ),
            "assumed_cost_delta_usd": winner["normal_comparison"].get(
                "cost_delta_usd",
                winner["normal_comparison"].get("assumed_cost_delta_usd", 0.0),
            ),
            "baseline_metrics": baseline_normal.get("metrics") or {},
            "candidate_metrics": winner["normal_solution"].get("metrics") or {},
        }
        def _native_tool_executor(fn_name: str, fn_args: dict[str, Any]) -> dict[str, Any]:
            if fn_name == "load_scenario":
                return {
                    "scenario_id": scenario.get("scenario_id", scenario_id),
                    "schema_version": scenario.get("schema_version", "2.0.0"),
                    "nodes_count": len(scenario.get("nodes", [])),
                }
            if fn_name == "inspect_evidence":
                return {
                    "scenario_id": scenario.get("scenario_id", scenario_id),
                    "modification_menu": evidence.get("modification_menu"),
                    "household_mapping": scenario.get("household_mapping"),
                }
            if fn_name == "run_optimisation":
                req_cand = fn_args.get("candidate")
                req_events = fn_args.get("events") or []
                sol = self.toolkit.run_native_optimisation(
                    scenario,
                    candidate=req_cand if isinstance(req_cand, dict) else None,
                    events=req_events if isinstance(req_events, list) else [],
                    options=options,
                    run_label="gemini_function_call_optimise",
                )
                return {
                    "status": sol.get("status"),
                    "candidate_id": sol.get("candidate_id"),
                    "metrics": sol.get("metrics"),
                }
            if fn_name == "validate_candidate":
                val = self.toolkit.validate_native_candidate(
                    scenario,
                    winner["normal_solution"],
                    candidate=winner["candidate_definition"],
                    events=[],
                    options=options,
                    run_label="gemini_function_call_validate",
                )
                return {"passed": val.get("passed"), "max_residual_mw": val.get("max_residual_mw")}
            if fn_name == "compare_results":
                return dict(winner["normal_comparison"])
            if fn_name == "generate_operator_report":
                return {
                    "recommended_candidate_id": winner["candidate_definition"]["candidate_id"],
                    "status": "ready",
                }
            return {"error": f"Unknown tool {fn_name!r}"}

        gemini_narrative, model_execution = self.gemini.synthesise_investigation(
            scenario=scenario,
            evidence=evidence,
            comparison=norm_comp_for_report,
            crisis_analysis=crisis_summary,
            tool_executor=_native_tool_executor,
        )
        operator_report = self.toolkit.generate_operator_report(
            scenario=scenario,
            evidence=evidence,
            comparison=norm_comp_for_report,
            candidate_validation=winner["normal_validation"],
            crisis_analysis=crisis_summary,
            gemini_narrative=gemini_narrative,
        )

        return {
            "baseline": baseline_normal,
            "candidate": winner["normal_solution"],
            "candidate_definition": winner["candidate_definition"],
            "tool_trace": self.recorder.events[:100],
            "operator_report": operator_report,
            "model_execution": model_execution,
        }


def run_investigation(
    scenario_id: str = "chile-demo-001",
    settings: dict[str, Any] | None = None,
) -> AwaitableDict:
    """Primary entrypoint required by Person 4's backend worker (`agent:run_investigation`).

    Supports both:
    - v1 `backend/worker.py` (`chile-demo-001`, `synthetic-demo-001`) -> strict 5-key `AgentResult`
    - v2 `backend/native_worker.py` (`chile-sen-5node-demo` / `schema_version == '2.0.0'`) -> native v2 bundle
    Can be called either synchronously (`res = run_investigation(...)`) or via `await`.
    """
    cfg = dict(settings or {})
    agent = GridPilotAgent()
    is_native_v2 = scenario_id.endswith("-demo") or any(
        k in cfg
        for k in (
            "candidates",
            "crisis_events",
            "selection_objective",
            "options",
            "allow_cached_fallback",
        )
    )
    if is_native_v2:
        return AwaitableDict(
            agent.execute_native_v2_investigation(scenario_id=scenario_id, settings=cfg)
        )
    full_dossier = agent.execute_investigation(scenario_id=scenario_id, settings=cfg)
    return AwaitableDict(full_dossier["agent_result"])


def run_crisis_investigation(
    scenario_id: str = "chile-sen-5node",
    settings: dict[str, Any] | None = None,
) -> AwaitableDict:
    """Extended entrypoint returning the full SCED + N-1 sudden crisis & household reconnection dossier."""
    agent = GridPilotAgent()
    full_dossier = agent.execute_investigation(scenario_id=scenario_id, settings=settings)
    return AwaitableDict(full_dossier)
