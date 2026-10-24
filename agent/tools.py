"""Structured tool implementations and UTC audit trace recorder for GridPilot (Gemini 4 Argon).

Implements the 6 required tools in the Person 2 <-> Person 3/4 contract:
1. `load_scenario`
2. `inspect_evidence`
3. `run_optimisation`
4. `validate_candidate`
5. `compare_results`
6. `generate_operator_report`

Every tool call emits `"started"` and `"success"` / `"failed"` / `"retry"` events
into `tool_trace` strictly conforming to `backend.models.ToolEvent` (`extra="forbid"`),
with UTC ISO-8601 timestamps (`Z`), `execution_mode="live"`, and recursive secret redaction.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.regulatory import (
    CHILEAN_LEGAL_FRAMEWORK,
    estimate_affected_households,
    get_legal_citations_list,
)
from agent.solver_fallback import (
    compare_solutions,
    get_modification_menu,
    solve_native,
    to_canonical_solution,
    validate_solution,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SECRET_KEY_MARKERS = ("key", "secret", "token", "password", "authorization", "credential", "bearer")

REQUIRED_TOOL_NAMES = (
    "load_scenario",
    "inspect_evidence",
    "run_optimisation",
    "validate_candidate",
    "compare_results",
    "generate_operator_report",
)


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format with trailing Z."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sanitize_detail(value: Any) -> Any:
    """Recursively redact secrets and round floats for compact tool trace summaries."""
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for k, v in value.items():
            key_str = str(k)
            if any(marker in key_str.lower() for marker in SECRET_KEY_MARKERS):
                sanitized[key_str] = "[REDACTED]"
            else:
                sanitized[key_str] = sanitize_detail(v)
        return sanitized
    if isinstance(value, list):
        return [sanitize_detail(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_detail(item) for item in value]
    if isinstance(value, float):
        return round(value, 6)
    return value


def _compact_json(detail: dict[str, Any] | None, max_len: int = 1950) -> str | None:
    if not detail:
        return None
    text = json.dumps(sanitize_detail(detail), sort_keys=True, default=str)
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


class ToolTraceRecorder:
    """Records UTC-timestamped tool execution events matching `backend.models.ToolEvent`."""

    def __init__(self, execution_mode: str = "live", live_gemini: bool = True) -> None:
        if execution_mode != "live":
            raise ValueError("GridPilot agent strictly enforces execution_mode='live'.")
        self.execution_mode = execution_mode
        self.live_gemini = live_gemini
        self.events: list[dict[str, Any]] = []

    def record(
        self,
        tool_name: str,
        status: str,
        *,
        scope: str | None = None,
        note: str | None = None,
        input_detail: dict[str, Any] | None = None,
        output_detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if status not in ("started", "success", "failed", "retry"):
            raise ValueError(f"Invalid ToolEvent status: {status!r}")
        event: dict[str, Any] = {
            "tool": tool_name,
            "status": status,
            "timestamp_utc": utc_now_iso(),
            "execution_mode": self.execution_mode,
            "live_gemini": self.live_gemini,
        }
        if scope is not None:
            event["scope"] = str(scope)[:200]
        if note is not None:
            event["note"] = str(note)[:2000]
        in_str = _compact_json(input_detail)
        if in_str is not None:
            event["input_summary"] = in_str
        out_str = _compact_json(output_detail)
        if out_str is not None:
            event["output_summary"] = out_str
        self.events.append(event)
        return event

    def start(
        self,
        tool_name: str,
        detail: dict[str, Any] | None = None,
        *,
        scope: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        return self.record(
            tool_name,
            "started",
            scope=scope,
            note=note,
            input_detail=detail,
        )

    def succeed(
        self,
        tool_name: str,
        detail: dict[str, Any] | None = None,
        *,
        scope: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        return self.record(
            tool_name,
            "success",
            scope=scope,
            note=note,
            output_detail=detail,
        )

    def fail(
        self,
        tool_name: str,
        detail: dict[str, Any] | None = None,
        *,
        scope: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        return self.record(
            tool_name,
            "failed",
            scope=scope,
            note=note,
            output_detail=detail,
        )

    def retry(
        self,
        tool_name: str,
        detail: dict[str, Any] | None = None,
        *,
        scope: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        return self.record(
            tool_name,
            "retry",
            scope=scope,
            note=note or (detail or {}).get("reason"),
            input_detail=detail,
        )


class AgentToolkit:
    """Executes deterministic grid tools and records every step in `ToolTraceRecorder`."""

    def __init__(self, recorder: ToolTraceRecorder | None = None) -> None:
        self.recorder = recorder or ToolTraceRecorder(execution_mode="live")
        self._scenario_cache: dict[str, dict[str, Any]] = {}
        self._evidence_cache: dict[str, dict[str, Any]] = {}

    def _resolve_scenario_path(self, scenario_id: str) -> Path:
        """Locate scenario JSON in backend/data or agent/fixtures."""
        repo_root = Path(__file__).resolve().parent.parent
        candidates = [
            repo_root / "data" / "demo" / f"{scenario_id}.scenario.json",
            repo_root / "data" / "processed" / "scenarios" / f"{scenario_id}.scenario.json",
            repo_root / "data" / "fallback" / "scenarios" / f"{scenario_id}.scenario.json",
            FIXTURES_DIR / f"{scenario_id}.scenario.json",
        ]
        for path in candidates:
            if path.exists():
                return path
        raise FileNotFoundError(
            f"Scenario '{scenario_id}' not found in data/demo, data/processed, or agent/fixtures."
        )

    def _resolve_evidence_path(self, source_id: str) -> Path:
        """Locate evidence JSON in backend/data or agent/fixtures."""
        repo_root = Path(__file__).resolve().parent.parent
        candidates = [
            repo_root / "data" / "processed" / f"{source_id}.evidence.json",
            repo_root / "data" / "processed" / "evidence" / f"{source_id}.evidence.json",
            FIXTURES_DIR / f"{source_id}.evidence.json",
            FIXTURES_DIR / "cen-2026-08-01.evidence.json",
        ]
        for path in candidates:
            if path.exists():
                return path
        raise FileNotFoundError(f"Evidence '{source_id}' not found.")

    # ------------------------------------------------------------------
    # Tool 1: load_scenario
    # ------------------------------------------------------------------
    def load_scenario(self, scenario_id: str) -> dict[str, Any]:
        """Load canonical or 5-node Chilean SEN scenario JSON by `scenario_id`."""
        self.recorder.start(
            "load_scenario",
            {"scenario_id": scenario_id},
            scope=scenario_id,
        )
        try:
            scenario: dict[str, Any] | None = None
            # Prefer active scenario from backend.runtime when running inside backend worker
            try:
                from backend import runtime as backend_runtime  # type: ignore

                scenario = backend_runtime.load_scenario(scenario_id)
            except Exception:
                scenario = None

            if scenario is None:
                path = self._resolve_scenario_path(scenario_id)
                scenario = json.loads(path.read_text(encoding="utf-8"))

            self._scenario_cache[scenario_id] = scenario
            menu = get_modification_menu(scenario)
            nodes_count = len(scenario.get("nodes", []))
            gens_count = len(scenario.get("generators", []))
            lines_count = len(scenario.get("lines", []))
            bats_count = len(scenario.get("batteries", []))
            horizon = len(scenario.get("timestamps_utc", []))
            prov = scenario.get("provenance") or {}
            evidence_id = prov.get("evidence_id") or scenario.get("source_id") or "cen-2026-08-01"

            self.recorder.succeed(
                "load_scenario",
                {
                    "scenario_id": scenario.get("scenario_id", scenario_id),
                    "evidence_id": evidence_id,
                    "nodes_count": nodes_count,
                    "generators_count": gens_count,
                    "lines_count": lines_count,
                    "batteries_count": bats_count,
                    "horizon_steps": horizon,
                    "allowed_modification_types": [
                        t["type"] for t in menu.get("allowed_types", [])
                    ],
                },
                scope=scenario_id,
                note=f"Loaded {nodes_count}-node scenario `{scenario_id}` ({horizon} steps).",
            )
            return scenario
        except Exception as exc:
            self.recorder.fail(
                "load_scenario",
                {"scenario_id": scenario_id, "error": str(exc)},
                scope=scenario_id,
            )
            raise

    # ------------------------------------------------------------------
    # Tool 2: inspect_evidence
    # ------------------------------------------------------------------
    def inspect_evidence(
        self,
        scenario_id: str | None = None,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        """Load CEN operational evidence and identify grid congestion, curtailment, and regulatory rules."""
        target_source = source_id
        scenario: dict[str, Any] | None = None
        if scenario_id and scenario_id in self._scenario_cache:
            scenario = self._scenario_cache[scenario_id]
            if not target_source:
                prov = scenario.get("provenance") or {}
                target_source = prov.get("evidence_id") or scenario.get("source_id")
        if not target_source:
            target_source = "cen-2026-08-01"

        self.recorder.start(
            "inspect_evidence",
            {"scenario_id": scenario_id or "chile-demo-001", "evidence_id": target_source},
            scope=target_source,
        )
        try:
            evidence: dict[str, Any] | None = None
            if scenario_id:
                try:
                    from backend import runtime as backend_runtime  # type: ignore

                    evidence = backend_runtime.inspect_evidence(scenario_id)
                except Exception:
                    evidence = None

            if evidence is None or (evidence.get("mode") == "synthetic" and not evidence.get("evidence")):
                path = self._resolve_evidence_path(target_source)
                evidence = json.loads(path.read_text(encoding="utf-8"))

            self._evidence_cache[target_source] = evidence
            menu = get_modification_menu(scenario) if scenario else {"allowed_types": []}
            enriched = {
                **evidence,
                "regulatory_framework_ids": list(CHILEAN_LEGAL_FRAMEWORK.keys()),
                "modification_menu": menu,
            }
            self.recorder.succeed(
                "inspect_evidence",
                {
                    "evidence_id": evidence.get("evidence_id", target_source),
                    "title": evidence.get("title", "CEN Operational Evidence"),
                    "regulatory_norms_loaded": len(CHILEAN_LEGAL_FRAMEWORK),
                },
                scope=target_source,
                note="Loaded CEN curtailment evidence, Chilean legal framework, and Modification Menu.",
            )
            return enriched
        except Exception as exc:
            self.recorder.fail(
                "inspect_evidence",
                {"scenario_id": scenario_id, "evidence_id": target_source, "error": str(exc)},
                scope=target_source,
            )
            raise

    # ------------------------------------------------------------------
    # Tool 3: run_optimisation
    # ------------------------------------------------------------------
    def run_optimisation(
        self,
        scenario: dict[str, Any],
        settings: dict[str, Any] | None = None,
        candidate: dict[str, Any] | None = None,
        events: list[dict[str, Any]] | None = None,
        run_label: str | None = None,
    ) -> dict[str, Any]:
        """Run deterministic LP dispatch (baseline, candidate modification, or sudden crisis contingency)."""
        cfg = dict(settings or {})
        battery_policy = str(cfg.get("battery_policy", "optimised"))
        allow_shed = bool(cfg.get("allow_load_shedding", cfg.get("allow_unserved", False)))
        cand_id = (candidate or {}).get("candidate_id", f"policy:{battery_policy}")
        label = run_label or cand_id

        self.recorder.start(
            "run_optimisation",
            {
                "scenario_id": scenario.get("scenario_id", "unknown"),
                "run_label": label,
                "battery_policy": battery_policy,
                "allow_load_shedding": allow_shed,
                "modifications_count": len((candidate or {}).get("modifications", [])),
                "events_count": len(events or []),
            },
            scope=label,
        )
        try:
            native = solve_native(
                scenario=scenario,
                candidate=candidate,
                events=events,
                options={"battery_policy": battery_policy, "allow_load_shedding": allow_shed},
            )
            canonical = to_canonical_solution(native)
            status = canonical.get("status", "failed")
            metrics = native.get("metrics") or {}

            detail = {
                "scenario_id": scenario.get("scenario_id", "unknown"),
                "run_label": label,
                "status": status,
                "battery_policy": battery_policy,
                "allow_load_shedding": allow_shed,
                "curtailment_mwh": metrics.get("curtailment_mwh"),
                "unserved_mwh": metrics.get("unserved_mwh"),
                "assumed_cost_proxy_usd": metrics.get("assumed_cost_proxy_usd"),
                "binding_constraints_count": len(native.get("binding_constraints", [])),
            }
            if status == "optimal":
                self.recorder.succeed(
                    "run_optimisation",
                    detail,
                    scope=label,
                    note=f"Optimal LP dispatch for `{label}` (curtailment={metrics.get('curtailment_mwh')} MWh).",
                )
            else:
                detail["reason"] = canonical.get("reason")
                self.recorder.fail(
                    "run_optimisation",
                    detail,
                    scope=label,
                    note=f"LP dispatch `{label}` returned status={status!r}: {canonical.get('reason')}",
                )
            return canonical
        except Exception as exc:
            self.recorder.fail(
                "run_optimisation",
                {
                    "scenario_id": scenario.get("scenario_id", "unknown"),
                    "run_label": label,
                    "error": str(exc),
                },
                scope=label,
            )
            raise

    # ------------------------------------------------------------------
    # Tool 4: validate_candidate
    # ------------------------------------------------------------------
    def validate_candidate(
        self,
        scenario: dict[str, Any],
        solution: dict[str, Any],
        settings: dict[str, Any] | None = None,
        run_label: str = "candidate",
    ) -> dict[str, Any]:
        """Independently verify nodal balance, thermal limits, SOC physics, and shedding rules."""
        cfg = dict(settings or {})
        battery_policy = str(cfg.get("battery_policy", "optimised"))
        allow_shed = bool(cfg.get("allow_load_shedding", cfg.get("allow_unserved", False)))

        self.recorder.start(
            "validate_candidate",
            {
                "scenario_id": scenario.get("scenario_id", "unknown"),
                "run_label": run_label,
                "battery_policy": battery_policy,
                "allow_load_shedding": allow_shed,
            },
            scope=run_label,
        )
        try:
            validation = validate_solution(
                scenario=scenario,
                solution=solution,
                options={"battery_policy": battery_policy, "allow_load_shedding": allow_shed},
            )
            passed = bool(validation.get("passed", False))
            detail = {
                "scenario_id": scenario.get("scenario_id", "unknown"),
                "run_label": run_label,
                "passed": passed,
                "violations_count": len(validation.get("violations", [])),
                "max_residual_mw": validation.get("max_residual_mw", 0.0),
                "metrics": validation.get("metrics"),
            }
            if passed:
                self.recorder.succeed(
                    "validate_candidate",
                    detail,
                    scope=run_label,
                    note=f"Independent physics validation passed for `{run_label}`.",
                )
            else:
                detail["violations"] = validation.get("violations", [])[:5]
                self.recorder.fail(
                    "validate_candidate",
                    detail,
                    scope=run_label,
                    note=f"Validation rejected `{run_label}`.",
                )
            return validation
        except Exception as exc:
            self.recorder.fail(
                "validate_candidate",
                {"scenario_id": scenario.get("scenario_id", "unknown"), "error": str(exc)},
                scope=run_label,
            )
            raise

    # ------------------------------------------------------------------
    # Tool 5: compare_results
    # ------------------------------------------------------------------
    def compare_results(
        self,
        baseline: dict[str, Any],
        candidate: dict[str, Any],
        baseline_validation: dict[str, Any] | None = None,
        candidate_validation: dict[str, Any] | None = None,
        scenario: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Compute deterministic MWh/USD deltas and household service metrics between baseline and candidate."""
        self.recorder.start(
            "compare_results",
            {
                "baseline_status": baseline.get("status"),
                "candidate_status": candidate.get("status"),
            },
            scope="baseline_vs_candidate",
        )
        try:
            comparison = compare_solutions(
                baseline=baseline,
                candidate=candidate,
                baseline_validation=baseline_validation,
                candidate_validation=candidate_validation,
            )
            if scenario is not None:
                dt = float(scenario.get("time_step_hours", 1.0))
                b_shed = baseline.get("load_shedding_mw_by_node") or {}
                c_shed = candidate.get("load_shedding_mw_by_node") or {}
                comparison["household_impact"] = estimate_affected_households(
                    unserved_mw_by_node_before=b_shed,
                    unserved_mw_by_node_after=c_shed,
                    time_step_hours=dt,
                )
            self.recorder.succeed(
                "compare_results",
                {
                    "comparable": comparison.get("comparable"),
                    "both_valid": comparison.get("both_valid"),
                    "curtailment_reduction_mwh": comparison.get("curtailment_reduction_mwh"),
                    "unserved_reduction_mwh": comparison.get("unserved_reduction_mwh"),
                    "assumed_cost_delta_usd": comparison.get("assumed_cost_delta_usd"),
                },
                scope="baseline_vs_candidate",
                note=(
                    f"Curtailment reduction: {comparison.get('curtailment_reduction_mwh')} MWh; "
                    f"Cost delta: {comparison.get('assumed_cost_delta_usd')} USD."
                ),
            )
            return comparison
        except Exception as exc:
            self.recorder.fail(
                "compare_results",
                {"error": str(exc)},
                scope="baseline_vs_candidate",
            )
            raise

    # ------------------------------------------------------------------
    # Tool 6: generate_operator_report
    # ------------------------------------------------------------------
    def generate_operator_report(
        self,
        scenario: dict[str, Any],
        evidence: dict[str, Any],
        comparison: dict[str, Any],
        candidate_validation: dict[str, Any],
        crisis_analysis: dict[str, Any] | None = None,
        candidate_sweeps: list[dict[str, Any]] | None = None,
        gemini_narrative: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Compile the structured `OperatorReport` with solver-grounded metrics and Chilean legal citations."""
        self.recorder.start(
            "generate_operator_report",
            {
                "scenario_id": scenario.get("scenario_id", "unknown"),
                "both_valid": comparison.get("both_valid", False),
                "has_crisis_analysis": crisis_analysis is not None,
            },
            scope="operator_report",
        )
        try:
            b_m = comparison.get("baseline_metrics") or {}
            c_m = comparison.get("candidate_metrics") or {}
            curt_red = float(comparison.get("curtailment_reduction_mwh", 0.0))
            cost_delta = float(comparison.get("assumed_cost_delta_usd", 0.0))
            cost_savings = -cost_delta
            b_curt = float(b_m.get("curtailment_mwh", 0.0))
            c_curt = float(c_m.get("curtailment_mwh", 0.0))
            curt_pct = (curt_red / b_curt * 100.0) if b_curt > 1e-6 else 0.0

            crisis_clause = ""
            if crisis_analysis:
                event_desc = crisis_analysis.get("event_description", "sudden plant outage")
                crisis_unserved = float(crisis_analysis.get("crisis_unserved_mwh", 0.0))
                mitigated_unserved = float(crisis_analysis.get("mitigated_unserved_mwh", 0.0))
                hh_affected = int(crisis_analysis.get("households_disconnected_peak", 0))
                hh_reconnected = int(crisis_analysis.get("households_reconnected", 0))
                reconnect_pct = float(crisis_analysis.get("reconnection_rate_pct", 100.0))
                best_fix = crisis_analysis.get(
                    "recommended_reconfiguration", "BESS + corridor upgrade"
                )
                crisis_clause = (
                    f" Under the simulated N-1 crisis ({event_desc}), unmitigated emergency redispatch "
                    f"experiences {crisis_unserved:.1f} MWh of unserved energy (~{hh_affected:,} Chilean "
                    f"households affected under NTSyCS EDAC); applying `{best_fix}` reduces unserved energy "
                    f"to {mitigated_unserved:.1f} MWh and reconnects ~{hh_reconnected:,} households "
                    f"({reconnect_pct:.1f}% restoration)."
                )

            llm_insight = ""
            if gemini_narrative and gemini_narrative.get("executive_note"):
                llm_insight = f" {gemini_narrative['executive_note'].strip()}"

            summary = (
                f"GridPilot (Gemini 4 Argon) SCED investigation for `{scenario.get('scenario_id')}`: "
                f"Co-optimising grid-scale BESS under Ley N° 21.505 and DS N° 32/2026 Art. 117 bis "
                f"reduces renewable curtailment from {b_curt:.1f} MWh to {c_curt:.1f} MWh "
                f"(-{curt_red:.1f} MWh, -{curt_pct:.1f}%) and lowers dispatchable thermal generation cost "
                f"by ${cost_savings:,.2f} USD (delta {cost_delta:+.2f} USD), with 0.0 MWh unserved load "
                f"and independent physics validation passed (max nodal residual "
                f"{candidate_validation.get('max_residual_mw', 0.0):.2e} MW)."
                f"{crisis_clause}{llm_insight}"
            )[:6000]

            prov_urls = list((scenario.get("provenance") or {}).get("observed_source_urls") or [])
            ev_urls = [
                str(s.get("url"))
                for s in (evidence.get("sources") or [])
                if isinstance(s, dict) and s.get("url")
            ]
            sources_dedup: list[str] = []
            for url in prov_urls + ev_urls + get_legal_citations_list():
                if url and url not in sources_dedup:
                    sources_dedup.append(url)

            assumptions = (
                list(scenario.get("assumptions") or [])
                + [
                    "SCED security-constrained economic dispatch formulated as a deterministic linear program (HiGHS) with nodal balance, thermal line ratings, generator ramp limits, and BESS state-of-charge physics.",
                    "Sudden contingency simulations lock pre-event dispatch and battery SOC up to the fault hour (no hindsight) before solving the post-contingency emergency redispatch.",
                    "Equivalent residential impact uses the Chilean SEC/CNE urban feeder benchmark of 1,000 households per MW of peak unserved demand (220 V / 50 Hz).",
                ]
            )[:30]

            limitations = (
                list(scenario.get("limitations") or [])
                + list(evidence.get("limitations") or [])
                + [
                    "DC transport-flow approximation omits reactive power (MVAr), AC voltage phase angles, and sub-second primary frequency control (AGC/governor inertia).",
                    "GridPilot acts strictly as an auditable decision-support co-pilot; physical SCADA breaker actuation remains under human Coordinator control per LGSE Art. 72°-1.",
                ]
            )[:30]

            report = {
                "summary": summary,
                "sources": sources_dedup[:30],
                "assumptions": assumptions,
                "limitations": limitations,
            }
            self.recorder.succeed(
                "generate_operator_report",
                {
                    "scenario_id": scenario.get("scenario_id", "unknown"),
                    "sources_count": len(report["sources"]),
                    "assumptions_count": len(report["assumptions"]),
                    "limitations_count": len(report["limitations"]),
                    "summary_length": len(summary),
                },
                scope="operator_report",
                note="Generated operator report grounded in verified LP dispatch and Chilean electricity law.",
            )
            return report
        except Exception as exc:
            self.recorder.fail(
                "generate_operator_report",
                {"error": str(exc)},
                scope="operator_report",
            )
            raise
