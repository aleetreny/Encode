"""Comprehensive unit and contract test suite for the GridPilot `agent` module."""

from __future__ import annotations

import asyncio
import copy
import json

import pytest

from agent import (
    CHILEAN_LEGAL_FRAMEWORK,
    REQUIRED_TOOL_NAMES,
    AgentToolkit,
    ToolTraceRecorder,
    estimate_affected_households,
    run_crisis_investigation,
    run_investigation,
)
from agent.solver_fallback import solve_native, validate_solution

ALLOWED_TOOL_EVENT_KEYS = {
    "tool",
    "status",
    "timestamp_utc",
    "execution_mode",
    "live_gemini",
    "note",
    "scope",
    "input_summary",
    "output_summary",
}


def test_run_investigation_strict_p4_contract_sync_and_async() -> None:
    """Verify `run_investigation` satisfies Person 4's strict `AgentResult` contract both sync and async."""
    res_sync = run_investigation(
        "chile-demo-001",
        {"battery_policy": "optimised", "allow_load_shedding": False},
    )

    async def _call_async():
        return await run_investigation(
            "chile-demo-001",
            {"battery_policy": "optimised", "allow_load_shedding": False},
        )

    res_async = asyncio.run(_call_async())

    for result in (res_sync, res_async):
        assert set(result.keys()) == {
            "baseline",
            "candidate",
            "tool_trace",
            "operator_report",
            "model_execution",
        }
        assert result["baseline"]["status"] == "optimal"
        assert result["candidate"]["status"] == "optimal"

        # Canonical baseline and candidate must not retain unsolved modifications or events
        assert result["baseline"]["native_result"]["modifications"] == []
        assert result["baseline"]["native_result"]["events"] == []
        assert result["candidate"]["native_result"]["modifications"] == []
        assert result["candidate"]["native_result"]["events"] == []

        # Model execution attestation
        me = result["model_execution"]
        assert me["provider"] == "google"
        assert me["model"] == "gemini-4-argon"
        assert me["response_id"].startswith("resp-")

        # Tool trace contract
        trace = result["tool_trace"]
        assert len(trace) >= 12
        for ev in trace:
            assert set(ev.keys()).issubset(ALLOWED_TOOL_EVENT_KEYS)
            assert ev["status"] in ("started", "success", "failed", "retry")
            assert ev["timestamp_utc"].endswith("Z")
            assert ev["execution_mode"] == "live"
            assert ev["live_gemini"] is True

        successful_tools = {ev["tool"] for ev in trace if ev["status"] == "success"}
        assert set(REQUIRED_TOOL_NAMES).issubset(successful_tools)

        # Operator report contract
        report = result["operator_report"]
        assert set(report.keys()) == {"summary", "sources", "assumptions", "limitations"}
        assert "77.8 MWh" in report["summary"]
        assert len(report["sources"]) >= 2
        assert len(report["assumptions"]) >= 2
        assert len(report["limitations"]) >= 2


def test_chile_demo_001_physics_and_curtailment_reduction() -> None:
    """Verify baseline vs candidate physics and exact 77.778 MWh curtailment reduction on `chile-demo-001`."""
    toolkit = AgentToolkit()
    scenario = toolkit.load_scenario("chile-demo-001")
    result = run_investigation(
        "chile-demo-001",
        {"battery_policy": "optimised", "allow_load_shedding": False},
    )

    val_base = validate_solution(
        scenario,
        result["baseline"],
        {"battery_policy": "disabled", "allow_load_shedding": False},
    )
    val_cand = validate_solution(
        scenario,
        result["candidate"],
        {"battery_policy": "optimised", "allow_load_shedding": False},
    )

    assert val_base["passed"] is True
    assert val_cand["passed"] is True
    assert val_base["max_residual_mw"] <= 1e-6
    assert val_cand["max_residual_mw"] <= 1e-6

    base_curt = val_base["metrics"]["curtailed_energy_mwh"]
    cand_curt = val_cand["metrics"]["curtailed_energy_mwh"]
    assert round(base_curt - cand_curt, 3) == 77.778
    assert val_cand["metrics"]["assumed_cost_usd"] < val_base["metrics"]["assumed_cost_usd"]


def test_5node_chilean_sen_crisis_and_household_reconnection() -> None:
    """Verify 5-node Chilean SEN candidate sweeps, sudden N-1 outage locking, and household reconnection."""
    dossier = run_crisis_investigation(
        "chile-sen-5node",
        {"battery_policy": "optimised", "allow_load_shedding": False},
    )

    sweeps = {c["candidate_id"]: c for c in dossier["candidate_sweeps"]}
    assert "combined_bess_and_corridor_uprate" in sweeps
    best_sweep = sweeps["combined_bess_and_corridor_uprate"]
    assert best_sweep["passed_validation"] is True
    assert best_sweep["curtailment_reduction_mwh"] > 1300.0
    assert best_sweep["assumed_cost_delta_usd"] < -140000.0

    crisis = dossier["crisis_analysis"]
    assert crisis is not None
    assert crisis["event"]["id"] == "gas_centro"
    assert crisis["event"]["mode"] == "sudden"
    assert crisis["strict_zero_shedding_status"] == "infeasible"
    assert crisis["crisis_unserved_mwh"] == 1977.5
    assert crisis["mitigated_unserved_mwh"] == 1501.55
    assert crisis["energy_restored_mwh"] == 475.95
    assert crisis["households_disconnected_peak"] == 562000
    assert crisis["households_reconnected"] == 111900
    assert crisis["reconnection_rate_pct"] > 19.0
    assert crisis["unmitigated_validation_passed"] is True
    assert crisis["mitigated_validation_passed"] is True

    # Verify autonomous self-correction retry was logged in tool_trace
    retries = [
        ev for ev in dossier["agent_result"]["tool_trace"] if ev["status"] == "retry"
    ]
    assert len(retries) >= 1

    # Verify all 4 Chilean regulatory norms are compliant
    reg_ids = {item["id"] for item in dossier["regulatory_compliance"]}
    assert reg_ids == set(CHILEAN_LEGAL_FRAMEWORK.keys())
    assert all(item["status"] == "compliant" for item in dossier["regulatory_compliance"])


def test_sudden_outage_locks_pre_fault_dispatch_without_hindsight() -> None:
    """Verify `mode='sudden'` locks hours 0..from_hour-1 to the pre-outage dispatch."""
    toolkit = AgentToolkit()
    scenario = toolkit.load_scenario("chile-sen-5node")

    normal = solve_native(scenario, options={"allow_unserved": True})
    sudden = solve_native(
        scenario,
        events=[
            {
                "type": "generator_outage",
                "id": "gas_centro",
                "from_hour": 18,
                "to_hour": 22,
                "mode": "sudden",
            }
        ],
        options={"allow_unserved": True},
    )

    assert normal["status"] == "optimal"
    assert sudden["status"] == "optimal"
    assert sudden["solver"]["solves"] == 2

    # Every generator's output before hour 18 must be identical (no foresight)
    for gid in normal["timeseries"]["generation_mw"]:
        assert (
            normal["timeseries"]["generation_mw"][gid][:18]
            == sudden["timeseries"]["generation_mw"][gid][:18]
        )
    # Battery SOC up to hour 18 must also be locked
    for bid in normal["timeseries"]["battery_soc_mwh"]:
        assert (
            normal["timeseries"]["battery_soc_mwh"][bid][:19]
            == sudden["timeseries"]["battery_soc_mwh"][bid][:19]
        )


def test_validator_rejects_tampered_dispatch_and_redacts_secrets() -> None:
    """Verify independent validator catches physics violations and recorder redacts secrets."""
    recorder = ToolTraceRecorder()
    toolkit = AgentToolkit(recorder=recorder)

    # Record an event containing sensitive keys
    ev = recorder.start(
        "run_optimisation",
        {
            "scenario_id": "chile-demo-001",
            "api_key": "AIzaSySecretKey123456",
            "nested": {"bearer_token": "secret-jwt-token", "safe_param": 42},
        },
    )
    summary_data = json.loads(ev["input_summary"])
    assert summary_data["api_key"] == "[REDACTED]"
    assert summary_data["nested"]["bearer_token"] == "[REDACTED]"
    assert summary_data["nested"]["safe_param"] == 42

    # Tamper with an optimal solution and ensure validate_candidate rejects it
    scenario = toolkit.load_scenario("chile-demo-001")
    sol = toolkit.run_optimisation(
        scenario, {"battery_policy": "optimised", "allow_load_shedding": False}
    )
    tampered = copy.deepcopy(sol)
    tampered["generation_mw_by_generator"]["solar1"][0] += 50.0  # breaks nodal balance & availability

    val = toolkit.validate_candidate(
        scenario, tampered, {"battery_policy": "optimised", "allow_load_shedding": False}
    )
    assert val["passed"] is False
    assert len(val["violations"]) >= 1


def test_native_v2_worker_contract_chile_sen_5node_demo() -> None:
    """Verify `run_investigation` satisfies Person 4's `native_worker.py` v2 contract on `chile-sen-5node-demo`."""
    res = run_investigation(
        "chile-sen-5node-demo",
        {
            "selection_objective": "curtailment_first",
            "options": {"allow_unserved": True, "time_limit_s": 20.0},
        },
    )

    assert "baseline" in res
    assert "candidate" in res
    assert "candidate_definition" in res
    assert "tool_trace" in res
    assert "operator_report" in res
    assert "model_execution" in res

    # Provider attestation
    me = res["model_execution"]
    assert me["provider"] == "google"
    assert me["model"] == "gemini-4-argon"
    assert me["response_id"].startswith("resp-")

    # Tool trace contract (<= 100 events, all 6 required tools succeeded)
    trace = res["tool_trace"]
    assert len(trace) <= 100
    successful_tools = {ev["tool"] for ev in trace if ev["status"] == "success"}
    assert set(REQUIRED_TOOL_NAMES).issubset(successful_tools)

    # Native v2 baseline & candidate solutions
    base = res["baseline"]
    cand = res["candidate"]
    cand_def = res["candidate_definition"]

    assert base["status"] == "optimal"
    assert cand["status"] == "optimal"
    assert base["accepted"] is True
    assert cand["accepted"] is True
    assert base["validation"]["passed"] is True
    assert cand["validation"]["passed"] is True
    assert base["options"] == {"allow_unserved": True, "time_limit_s": 20.0}
    assert cand["options"] == {"allow_unserved": True, "time_limit_s": 20.0}
    assert cand["candidate_id"] == "north_bess"
    assert cand_def["candidate_id"] == "north_bess"

    # Exact curtailment reduction matches Person 3 & Person 4's native demo (631.578947 MWh)
    curt_red = base["metrics"]["curtailment_mwh"] - cand["metrics"]["curtailment_mwh"]
    assert round(curt_red, 3) == 631.579


def test_argon_api_rules_and_function_calling_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify Gemini 4 Argon API rules (thinking_level, background=True, no temperature/top_p/top_k) and function calling."""
    from agent.gemini_client import (
        COMPANION_SUBAGENT_MODEL,
        DEFAULT_AGENT_MODEL,
        FORBIDDEN_ARGON_PARAMS,
        GeminiArgonClient,
        build_argon_config,
    )

    cfg = build_argon_config(thinking_level="high", background=True, include_tools=True)
    assert cfg["thinking_level"] == "high"
    assert cfg["background"] is True
    assert "tools" in cfg
    for forbidden in FORBIDDEN_ARGON_PARAMS:
        assert forbidden not in cfg

    with pytest.raises(ValueError, match="Invalid Gemini 4 Argon thinking_level"):
        build_argon_config(thinking_level="invalid")

    # Simulate a two-turn Gemini 4 Argon REST exchange: turn 1 emits functionCall, turn 2 emits final text + real responseId
    captured_bodies: list[dict] = []
    tool_calls_made: list[tuple[str, dict]] = []

    class _FakeResponse:
        def __init__(self, status_code: int, payload: dict) -> None:
            self.status_code = status_code
            self._payload = payload

        def json(self) -> dict:
            return self._payload

    class _FakeHttpClient:
        def __init__(self, *args, **kwargs) -> None:
            self._turn = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url: str, params: dict | None = None, json: dict | None = None) -> _FakeResponse:
            assert json is not None
            captured_bodies.append(copy.deepcopy(json))
            gen_cfg = json.get("generationConfig") or {}
            # Strictly verify no forbidden parameters are sent over the wire
            for forbidden in FORBIDDEN_ARGON_PARAMS:
                assert forbidden not in gen_cfg
            assert gen_cfg.get("thinkingConfig", {}).get("thinkingLevel") == "HIGH"

            self._turn += 1
            if self._turn == 1:
                return _FakeResponse(
                    200,
                    {
                        "candidates": [
                            {
                                "content": {
                                    "parts": [
                                        {
                                            "functionCall": {
                                                "name": "compare_results",
                                                "args": {
                                                    "baseline_id": "baseline",
                                                    "candidate_id": "north_bess",
                                                },
                                            }
                                        }
                                    ]
                                }
                            }
                        ]
                    },
                )
            return _FakeResponse(
                200,
                {
                    "responseId": "gemini4-argon-live-id-998877",
                    "modelVersion": "gemini-4-argon",
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "text": "Verified north_bess reduces curtailment by 631.6 MWh in simulation (legal_compliance_status=not_certified)."
                                    }
                                ]
                            }
                        }
                    ],
                },
            )

    monkeypatch.setattr("agent.gemini_client.httpx.Client", _FakeHttpClient)
    client = GeminiArgonClient(api_key="test-live-key", thinking_level="high", background=True)
    assert client.model == DEFAULT_AGENT_MODEL
    assert client.companion_model == COMPANION_SUBAGENT_MODEL

    def _executor(name: str, args: dict) -> dict:
        tool_calls_made.append((name, args))
        return {"comparable": True, "curtailment_reduction_mwh": 631.578947}

    narrative, meta = client.synthesise_investigation(
        {"scenario_id": "chile-sen-5node-demo"},
        {},
        {"curtailment_reduction_mwh": 631.578947, "assumed_cost_delta_usd": -46750.0},
        tool_executor=_executor,
    )
    assert len(captured_bodies) == 2
    assert tool_calls_made == [
        ("compare_results", {"baseline_id": "baseline", "candidate_id": "north_bess"})
    ]
    assert meta["provider"] == "google"
    assert meta["model"] == "gemini-4-argon"
    assert meta["response_id"] == "gemini4-argon-live-id-998877"
    assert not meta["response_id"].startswith(("resp-argon-", "resp-google-"))
    assert narrative["thinking_level"] == "high"
    assert narrative["background"] is True


