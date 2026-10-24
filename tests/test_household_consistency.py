"""Test consistency of household disconnection / reconnection formulas across GridPilot.

Rule (Acceptance Criterion 8):
Una sola fórmula para hogares:
`hogares_sin_luz(nodo, hora) = unserved_mw(nodo, hora) * households_per_mw(nodo)`
donde `households_per_mw` (por defecto 1000, etiquetado `assumption`) viene del escenario.
Nunca se multiplican MWh por hogares/MW.
Cualquier otro número de hogares inconsistente en el repo se corrige o se borra.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from agent.regulatory import (
    compute_household_impact,
    estimate_affected_households,
    estimate_household_impact,
)
from backend.live.agent_loop import compute_solution_dict

REPO_ROOT = Path(__file__).resolve().parent.parent

# Forbidden bogus / inconsistent strings that must never appear in active code or docs
FORBIDDEN_PATTERNS = [
    "243,058",
    "243.058",
    "243058",
    "120,000 hogares",
    "562,000 / 562,000",
]

# Allowlist: only files that document the historical audit or test it
ALLOWED_FILES = {
    REPO_ROOT / "docs" / "household-formula-audit.md",
    REPO_ROOT / "tests" / "test_household_consistency.py",
}


def test_no_forbidden_household_strings_in_repo() -> None:
    """Ensure no bogus legacy household figures linger in frontend, backend, agent, optimisation, or docs."""
    scan_dirs = ["frontend/src", "backend", "agent", "optimisation"]
    scan_files = ["README.md"]

    checked_file_count = 0

    for d in scan_dirs:
        dir_path = REPO_ROOT / d
        assert dir_path.is_dir(), f"Expected directory {dir_path} to exist"
        for root, _, files in os.walk(dir_path):
            for file_name in files:
                if not file_name.endswith((".py", ".ts", ".tsx", ".js", ".json", ".md")):
                    continue
                p = Path(root) / file_name
                if p in ALLOWED_FILES:
                    continue
                checked_file_count += 1
                content = p.read_text(encoding="utf-8", errors="ignore")
                for forbidden in FORBIDDEN_PATTERNS:
                    assert forbidden not in content, (
                        f"Found forbidden inconsistent household string '{forbidden}' in {p.relative_to(REPO_ROOT)}"
                    )

    for f in scan_files:
        p = REPO_ROOT / f
        if p.is_file() and p not in ALLOWED_FILES:
            checked_file_count += 1
            content = p.read_text(encoding="utf-8", errors="ignore")
            for forbidden in FORBIDDEN_PATTERNS:
                assert forbidden not in content, (
                    f"Found forbidden inconsistent household string '{forbidden}' in {p.relative_to(REPO_ROOT)}"
                )

    assert checked_file_count > 20, f"Expected to scan at least 20 files, scanned {checked_file_count}"


def test_backend_live_agent_loop_uses_mw_not_mwh() -> None:
    """Verify backend.live.agent_loop.compute_solution_dict uses power (MW * hh_per_mw), not energy (MWh)."""
    scenario: dict[str, Any] = {
        "timestamps_utc": ["2026-10-25T18:00:00Z", "2026-10-25T19:00:00Z", "2026-10-25T20:00:00Z"],
        "nodes": [
            {
                "id": "n_centro",
                "label": "Centro (Polpaico)",
                "households_per_mw": 1000.0,
                "households_total": 2400000,
            }
        ],
        "generators": [],
        "lines": [],
        "batteries": [],
        "demand_mw_by_node": {
            "n_centro": [500.0, 500.0, 500.0],
        },
    }

    # Hourly unserved power: hour 0 has 10 MW, hour 1 has 25 MW, hour 2 has 0 MW (total = 35 MWh)
    raw_sol: dict[str, Any] = {
        "status": "optimal",
        "timeseries": {
            "generation_mw": {},
            "available_mw": {},
            "line_flow_mw": {},
            "battery_flow_mw": {},
            "battery_soc_mwh": {},
            "unserved_mw": {
                "n_centro": [10.0, 25.0, 0.0],
            },
            "curtailment_mw": {},
            "demand_response_mw": {},
        },
    }
    val_rep = {"passed": True, "violations": [], "max_residual_mw": 0.0}

    solution = compute_solution_dict(
        scenario=scenario,
        raw_sol=raw_sol,
        val_rep=val_rep,
        solution_id="sol-test-hh",
    )

    hh_off = solution["households_off"]["n_centro"]
    # Check each hour is strictly unserved_mw(node, hour) * households_per_mw
    assert hh_off[0] == 10000, f"Hour 0 expected 10,000 households off (10 MW * 1000), got {hh_off[0]}"
    assert hh_off[1] == 25000, f"Hour 1 expected 25,000 households off (25 MW * 1000), got {hh_off[1]}"
    assert hh_off[2] == 0, f"Hour 2 expected 0 households off (0 MW * 1000), got {hh_off[2]}"

    # Total unserved energy is 35 MWh; ensure we did NOT do 35 * 1000 = 35000 in any single hour
    assert all(h != 35000 for h in hh_off)


def test_agent_regulatory_affected_households_uses_peak_mw_not_mwh() -> None:
    """Verify agent.regulatory.estimate_affected_households uses peak MW * households_per_mw, not MWh."""
    # 4-hour outage with 50 MW unserved each hour -> total energy = 200 MWh, peak power = 50 MW
    unserved_before = {
        "n_centro": [50.0, 50.0, 50.0, 50.0],
    }
    # Mitigated: 0 MW unserved -> 0 MWh
    unserved_after = {
        "n_centro": [0.0, 0.0, 0.0, 0.0],
    }

    result = estimate_affected_households(
        unserved_mw_by_node_before=unserved_before,
        unserved_mw_by_node_after=unserved_after,
        time_step_hours=1.0,
        households_per_mw=1000.0,
    )

    # 50 MW peak * 1000 = 50,000 households (NOT 200 MWh * 1000 = 200,000 households)
    assert result["total_households_affected_before"] == 50000
    assert result["total_households_affected_after"] == 0
    assert result["total_households_reconnected"] == 50000
    assert result["total_unserved_mwh_before"] == 200.0
    assert result["total_energy_restored_mwh"] == 200.0


def test_agent_regulatory_compute_household_impact_converts_mwh_to_avg_mw() -> None:
    """Verify compute_household_impact divides unserved MWh by duration to get MW before multiplying."""
    # 200 MWh over 4 hours = 50 MW average deficit
    impact = compute_household_impact(
        baseline_unserved_mwh=200.0,
        candidate_unserved_mwh=50.0,  # 50 MWh over 4 hours = 12.5 MW deficit
        outage_duration_hours=4.0,
        households_per_mw=1000.0,
    )

    # 50 MW * 1000 = 50,000 households
    assert impact["baseline_affected_households_est"] == 50000
    # 12.5 MW * 1000 = 12,500 households
    assert impact["candidate_affected_households_est"] == 12500
    # Restored: (50 - 12.5) MW * 1000 = 37,500 households
    assert impact["reconnected_households_est"] == 37500
    # Energy dimension: 150 MWh * 1000 = 150,000 household-hours (properly labeled as household_hours)
    assert impact["household_hours_saved_est"] == 150000


def test_alias_estimate_and_compute_household_impact() -> None:
    """Verify compute_household_impact and estimate_household_impact are identical."""
    res1 = estimate_household_impact(100.0, 50.0, 2.0, 1000.0)
    res2 = compute_household_impact(100.0, 50.0, 2.0, 1000.0)
    assert res1 == res2
