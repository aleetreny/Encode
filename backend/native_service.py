"""Native dispatch, interventions, no-hindsight acceptance and crisis impact reporting.

All dispatch metrics/comparisons come from optimisation; household equivalences are
explicit dimensional conversions, with assumptions retained in every report.
"""

import copy

from optimisation import compare, solve, validate
from optimisation.scenario import build_grid

from backend.models import utc_now, wire
from backend.native_models import Candidate, InvestigationSettings, NativeScenario


def default_candidates():
    return [
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
                {"type": "add_battery", "node_id": "n_sur", "power_mw": 150, "energy_mwh": 600}
            ],
        },
        {
            "candidate_id": "uprate_l2",
            "modifications": [{"type": "uprate_line", "line_id": "L2", "new_capacity_mw": 600}],
        },
    ]


def default_events():
    return [
        {
            "type": "generator_outage",
            "id": "gas_centro",
            "from_hour": 18,
            "to_hour": 22,
            "mode": "sudden",
        }
    ]


def candidate_from_solution(solution):
    if not solution.get("modifications"):
        return None
    mods = []
    for mod in solution["modifications"]:
        allowed = (
            ("type", "node_id", "power_mw", "energy_mwh")
            if mod["type"] == "add_battery"
            else ("type", "line_id", "new_capacity_mw")
        )
        mods.append({key: mod[key] for key in allowed})
    return wire(Candidate(candidate_id=solution["candidate_id"], modifications=mods))


def _prefix_difference(reference, candidate, until):
    failures = []
    for name, values in reference["timeseries"].items():
        count = until + 1 if name == "battery_soc_mwh" else until
        actual = candidate.get("timeseries", {}).get(name, {})
        for asset, series in values.items():
            other = actual.get(asset, [])
            if len(other) < count or any(
                abs(a - b) > 1e-4 for a, b in zip(series[:count], other[:count])
            ):
                failures.append(
                    {
                        "check": "no_hindsight",
                        "id": asset,
                        "hour": until,
                        "detail": f"{name} before sudden event differs from the plan",
                    }
                )
    return failures


def check_solution(scenario, solution, candidate=None, events=None, options=None):
    """Validate effective inputs and independently reproduce each pre-event plan."""
    result = copy.deepcopy(validate(scenario, solution))
    if not result.get("passed"):
        return result
    candidate = candidate if candidate is not None else candidate_from_solution(solution)
    events = events if events is not None else solution.get("events", [])
    options = options if options is not None else solution.get("options", {})
    grid = build_grid(scenario, candidate, events, options)
    violations = result["violations"]
    expected_series = {
        "generation_mw": {g["id"] for g in grid.generators},
        "available_mw": {g["id"] for g in grid.generators},
        "curtailment_mw": {g["id"] for g in grid.generators if g["renewable"]},
        "line_flow_mw": {line["id"] for line in grid.lines},
        "unserved_mw": set(grid.node_ids),
        **{
            key: {b["id"] for b in grid.batteries}
            for key in ("battery_charge_mw", "battery_discharge_mw", "battery_soc_mwh")
        },
    }
    for key, expected in expected_series.items():
        if set(solution["timeseries"].get(key, {})) != expected:
            violations.append(
                {"check": "exact_asset_ids", "detail": f"unexpected/missing asset IDs in {key}"}
            )
    for name, expected in (
        ("candidate_id", grid.candidate_id),
        ("modifications", grid.modifications),
        ("events", grid.events),
        ("options", grid.options),
    ):
        if solution.get(name) != expected:
            violations.append(
                {
                    "check": "requested_inputs",
                    "id": None,
                    "hour": None,
                    "detail": f"solution differs from requested {name}",
                }
            )
    sudden = [ev for ev in grid.events if ev["mode"] == "sudden"]
    known = [ev for ev in grid.events if ev["mode"] == "planned"]
    base = copy.deepcopy(scenario)
    base["events"] = []
    for event in sudden:
        reference = solve(base, candidate=candidate, events=known, options=options)
        if reference["status"] != "optimal":
            violations.append({"check": "no_hindsight", "detail": "pre-event plan is not optimal"})
            break
        violations.extend(_prefix_difference(reference, solution, event["from_hour"]))
        known.append(event)
    result["checks_run"] = list(
        dict.fromkeys([*result.get("checks_run", []), "requested_inputs", "no_hindsight"])
    )
    result["passed"] = not violations
    return result


def solve_checked(scenario, candidate=None, events=None, options=None):
    solution = solve(scenario, candidate=candidate, events=events, options=options)
    checked = check_solution(scenario, solution, candidate, events, options)
    return {**solution, "validation": checked, "accepted": checked["passed"]}


def household_impact(scenario, baseline, candidate, events):
    mapping = scenario["household_mapping"]
    factor = mapping["households_per_mw"]
    dt = scenario["time_step_hours"]
    count = len(scenario["timestamps_utc"])
    window = sorted({t for e in events for t in range(e["from_hour"], e["to_hour"])})
    duration = len(window) * dt
    per_node = {}
    for node, share in mapping["residential_share_by_node"].items():
        before = baseline["timeseries"]["unserved_mw"][node]
        after = candidate["timeseries"]["unserved_mw"][node]
        affected = [v * factor * share for v in before]
        remaining = [v * factor * share for v in after]
        recovered = [a - b for a, b in zip(affected, remaining)]
        per_node[node] = dict(
            baseline_affected_households_equivalent=affected,
            candidate_affected_households_equivalent=remaining,
            net_reconnected_households_equivalent=recovered,
            avoided_household_hours=sum(recovered[t] * dt for t in window),
        )
    total_before = [
        sum(v["baseline_affected_households_equivalent"][t] for v in per_node.values())
        for t in range(count)
    ]
    total_after = [
        sum(v["candidate_affected_households_equivalent"][t] for v in per_node.values())
        for t in range(count)
    ]
    recovered = [a - b for a, b in zip(total_before, total_after)]
    avoided = sum(recovered[t] * dt for t in window)
    return dict(
        mapping=copy.deepcopy(mapping),
        classification="derived_from_simulated_unserved_power_and_synthetic_mapping",
        event_hour_indices=window,
        event_duration_hours=duration,
        baseline_affected_households_equivalent_by_step=total_before,
        candidate_affected_households_equivalent_by_step=total_after,
        net_reconnected_households_equivalent_by_step=recovered,
        avoided_household_hours=avoided,
        horizon_avoided_household_hours=sum(recovered) * dt,
        unique_households_reconnected=None,
        average_households_reconnected_equivalent=avoided / duration if duration else None,
        peak_households_reconnected_equivalent=max((recovered[t] for t in window), default=0),
        by_node=per_node,
        limitations=[
            "Equivalent residential demand, not unique identified households",
            "Household-hours are integrated over the event window, not a household count",
            "No actual distribution feeder switching is modelled",
        ],
    )


def regulatory_assessment(scenario, passed):
    checks = {
        "LGSE": ["nodal_balance", "metrics_recomputed"],
        "DS32": ["ramp_limits", "requested_inputs"],
        "NTSyCS": ["line_limits", "ramp_limits", "unserved_bounds", "no_hindsight"],
        "Ley21505": ["soc_dynamics", "soc_initial", "soc_final", "simultaneous_charge_discharge"],
    }
    return [
        dict(
            reference=r,
            modelled_checks=checks.get(r["id"], []),
            model_constraint_status="passed" if passed else "failed",
            legal_compliance_status="not_certified",
            not_assessed=[
                "full legal compliance",
                "AC voltage/reactive power",
                "frequency and transient stability",
                "full N-1 security",
                "distribution switching and actual EDAC relay behavior",
            ],
        )
        for r in scenario.get("regulatory_framework", [])
    ]


def computational_settings(scenario, settings):
    parsed = InvestigationSettings.model_validate(settings)
    candidates = (
        [wire(c) for c in parsed.candidates]
        if parsed.candidates is not None
        else default_candidates()
    )
    events = (
        [wire(e) for e in parsed.crisis_events]
        if parsed.crisis_events is not None
        else default_events()
    )
    if not candidates or not events:
        raise ValueError(
            "the two-stage investigation requires candidates and at least one crisis event"
        )
    for c in candidates:
        build_grid(scenario, c, events, wire(parsed.options))
    if len({c["candidate_id"] for c in candidates}) != len(candidates):
        raise ValueError("duplicate candidate ID")
    if not parsed.options.allow_unserved:
        raise ValueError(
            "full investigation needs recovery with allow_unserved=true; strict crisis is tested separately"
        )
    return dict(candidates=candidates, crisis_events=events, options=wire(parsed.options))


def investigate(scenario, settings, selected_candidate=None):
    NativeScenario.model_validate(scenario)
    plan = computational_settings(scenario, settings)
    options = plan["options"]
    trace = []

    def record(tool, label, status="success", **extra):
        trace.append(
            dict(
                step=len(trace) + 1,
                tool=tool,
                label=label,
                status=status,
                timestamp_utc=utc_now(),
                driver="deterministic_backend",
                **extra,
            )
        )

    def compute(label, candidate=None, events=None, opts=None):
        result = solve_checked(scenario, candidate, events, opts or options)
        record("run_optimisation", label, result["status"])
        record(
            "validate_candidate", label, "success" if result["validation"]["passed"] else "failed"
        )
        return result

    record("load_scenario", scenario["scenario_id"])
    record("inspect_evidence", "sources_and_modification_menu")
    baseline = compute("baseline_normal")
    if not baseline["validation"]["passed"]:
        raise ValueError("normal baseline did not pass independent validation")
    normal = []
    definitions = list(plan["candidates"])
    if selected_candidate is not None:
        existing = next(
            (c for c in definitions if c["candidate_id"] == selected_candidate["candidate_id"]),
            None,
        )
        if existing and existing["modifications"] != selected_candidate["modifications"]:
            raise ValueError("selected candidate ID conflicts with the configured intervention")
        if existing is None:
            definitions.append(selected_candidate)
    for definition in definitions:
        result = compute(definition["candidate_id"] + "_normal", definition)
        comparison = compare(baseline, result, baseline["validation"], result["validation"])
        normal.append(dict(candidate_definition=definition, solution=result, comparison=comparison))
    strict_options = {**options, "allow_unserved": False}
    strict = compute(
        "crisis_strict_zero_shedding", events=plan["crisis_events"], opts=strict_options
    )
    crisis_baseline = compute("baseline_crisis", events=plan["crisis_events"])
    if not crisis_baseline["validation"]["passed"]:
        raise ValueError("crisis baseline did not pass independent validation")
    choices = []
    for entry in normal:
        if not entry["solution"]["validation"]["passed"]:
            continue
        result = compute(
            entry["candidate_definition"]["candidate_id"] + "_crisis",
            entry["candidate_definition"],
            plan["crisis_events"],
        )
        comparison = compare(
            crisis_baseline, result, crisis_baseline["validation"], result["validation"]
        )
        if comparison["comparable"]:
            choices.append(dict(normal=entry, solution=result, comparison=comparison))
    if not choices:
        raise ValueError("no independently verified crisis candidate")
    if selected_candidate is None:
        winner = max(
            choices,
            key=lambda c: (
                c["comparison"]["unserved_reduction_mwh"],
                c["normal"]["comparison"]["curtailment_reduction_mwh"],
                -c["solution"]["objective"]["total_usd"],
            ),
        )
    else:
        winner = next(
            c
            for c in choices
            if c["normal"]["candidate_definition"]["candidate_id"]
            == selected_candidate["candidate_id"]
        )
    impact = household_impact(scenario, crisis_baseline, winner["solution"], plan["crisis_events"])
    record("compare_results", "normal_and_crisis")
    validations = [
        baseline["validation"],
        winner["normal"]["solution"]["validation"],
        crisis_baseline["validation"],
        winner["solution"]["validation"],
    ]
    return dict(
        baseline=baseline,
        candidate=winner["normal"]["solution"],
        candidate_definition=winner["normal"]["candidate_definition"],
        comparison=winner["normal"]["comparison"],
        candidate_evaluations=normal,
        crisis_analysis=dict(
            event=plan["crisis_events"][0] if len(plan["crisis_events"]) == 1 else None,
            events=plan["crisis_events"],
            baseline=crisis_baseline,
            candidate=winner["solution"],
            comparison=winner["comparison"],
            candidate_evaluations=choices,
            strict_attempt=strict,
            baseline_unserved_mwh=crisis_baseline["metrics"]["unserved_mwh"],
            candidate_unserved_mwh=winner["solution"]["metrics"]["unserved_mwh"],
            unserved_reduction_mwh=winner["comparison"]["unserved_reduction_mwh"],
            household_impact=impact,
            estimated_households_reconnected=impact["average_households_reconnected_equivalent"],
            estimated_households_reconnected_definition="Event-window average residential-equivalent load restored; not unique customers",
        ),
        validation=dict(
            passed=True,
            violations=[],
            max_residual_mw=max(v["max_residual_mw"] for v in validations),
            normal_baseline=validations[0],
            normal_candidate=validations[1],
            crisis_baseline=validations[2],
            crisis_candidate=validations[3],
        ),
        tool_trace=trace,
        computational_settings=plan,
    )


def operator_report(scenario, bundle):
    normal = bundle["comparison"]
    crisis = bundle["crisis_analysis"]
    impact = crisis["household_impact"]
    return dict(
        format="RIO-style simulation decision note; not an official CEN RIO instruction",
        summary=f"Verified model: {normal['curtailment_reduction_mwh']:.6f} MWh less normal curtailment; {crisis['unserved_reduction_mwh']:.6f} MWh less unserved energy over the model horizon.",
        crisis_recovery_plan=f"Simulated intervention {bundle['candidate_definition']['candidate_id']}. Event-window avoided household-hours: {impact['avoided_household_hours']:.6f}; average household-equivalents restored: {impact['average_households_reconnected_equivalent']:.6f}.",
        regulatory_compliance=regulatory_assessment(scenario, True),
        sources=scenario["provenance"].get("observed_source_urls", [])
        + [r["url"] for r in scenario.get("regulatory_framework", [])],
        assumptions=[
            scenario["provenance"]["notes"],
            impact["mapping"]["interpretation"],
            "Investment costs of modifications are excluded",
        ],
        limitations=[
            "Synthetic radial hourly transport model, not an operational SEN digital twin",
            "Modelled constraints are not a certification of Chilean legal compliance",
            "No actual household reconnection, EDAC relay operation or switching is executed",
            "No voltage, frequency, transient stability or full N-1 assessment",
            "No guarantee of eliminating curtailment",
        ],
        normal_comparison=normal,
        crisis_comparison=crisis["comparison"],
        household_impact=impact,
    )
