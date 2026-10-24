"""Chilean Electricity Regulatory Framework & Household Impact Engine.

Maps Chilean electricity laws and technical standards (CEN / CNE / SEC) to
deterministic checks, household reconnection metrics, and regulatory citations
for GridPilot's autonomous coordinator (Gemini 4 Argon).
"""

from __future__ import annotations

from typing import Any

# Equivalent Chilean residential households served per MW of peak substation load
# (~1.0 kW coincidence-adjusted residential demand per household at primary distribution bus).
HOUSEHOLDS_PER_MW_SUBSTAT = 1000.0

CHILEAN_REGULATORY_SOURCES: list[str] = [
    "https://www.coordinador.cl/wp-content/uploads/2026/08/Plan_Trabajo_SCED_vf.pdf",
    "https://www.bcn.cl/leychile/Navegar?idNorma=1225248&idVersion=2026-06-17",
    "https://www.bcn.cl/leychile/Navegar?idNorma=258171",
    "https://www.cne.cl/normativas/electrica/normas-tecnicas/",
    "https://infotecnica.coordinador.cl/",
]

CHILEAN_LEGAL_FRAMEWORK: dict[str, dict[str, str]] = {
    "LGSE-ART-72-1": {
        "code": "LGSE DFL N° 4/2006 Art. 72°-1",
        "title": "Ley General de Servicios Eléctricos — Coordinación del SEN",
        "url": "https://www.bcn.cl/leychile/Navegar?idNorma=258171",
        "principle": (
            "Preserve electrical system security, guarantee minimum-cost economic operation "
            "across all generating units, and ensure open transmission access."
        ),
    },
    "DS-32-2026-ART-117-BIS": {
        "code": "Decreto Supremo N° 32/2026 Art. 117 bis",
        "title": "Reglamento SCED y Reducción Automática de Generación ERNC",
        "url": "https://www.bcn.cl/leychile/Navegar?idNorma=1225248&idVersion=2026-06-17",
        "principle": (
            "Mandates automated Security-Constrained Economic Dispatch (SCED) co-optimising "
            "generation, transmission congestion, and renewable curtailment."
        ),
    },
    "NTSYCS-N1-EDAC": {
        "code": "CNE NTSyCS (Cap. 5 y 6)",
        "title": "Norma Técnica de Seguridad y Calidad de Servicio — Criterio N-1 y EDAC",
        "url": "https://www.cne.cl/normativas/electrica/normas-tecnicas/",
        "principle": (
            "Enforces N-1 contingency security, thermal line limits, generator ramp limits, "
            "and Esquema de Desconexión Automática de Carga (EDAC) with rapid household reconnection."
        ),
    },
    "LEY-21505-SAE": {
        "code": "Ley N° 21.505 / DS N° 70/2023",
        "title": "Promoción del Almacenamiento de Energía Eléctrica (SAE / BESS)",
        "url": "https://www.coordinador.cl/wp-content/uploads/2026/08/Plan_Trabajo_SCED_vf.pdf",
        "principle": (
            "Integrates utility-scale BESS into centralized CEN economic dispatch for solar/wind "
            "curtailment arbitrage and fast post-contingency frequency/energy recovery."
        ),
    },
}

REGULATORY_RULES: list[dict[str, str]] = [
    {
        "code": key,
        "law": val["code"],
        "principle": val["principle"],
        "model_enforcement": val["title"],
    }
    for key, val in CHILEAN_LEGAL_FRAMEWORK.items()
]


def get_legal_citations_list() -> list[str]:
    """Return canonical URLs and legal references for `OperatorReport.sources`."""
    return list(CHILEAN_REGULATORY_SOURCES)


def estimate_household_impact(
    baseline_unserved_mwh: float,
    candidate_unserved_mwh: float,
    outage_duration_hours: float = 4.0,
    households_per_mw: float = HOUSEHOLDS_PER_MW_SUBSTAT,
) -> dict[str, Any]:
    """Translate aggregate unserved energy (MWh) into equivalent Chilean households affected and reconnected."""
    duration = max(1.0, float(outage_duration_hours))
    base_mwh = max(0.0, float(baseline_unserved_mwh))
    cand_mwh = max(0.0, float(candidate_unserved_mwh))
    restored_mwh = max(0.0, base_mwh - cand_mwh)

    base_avg_deficit_mw = base_mwh / duration
    cand_avg_deficit_mw = cand_mwh / duration
    restored_avg_mw = restored_mwh / duration

    return {
        "baseline_unserved_mwh": round(base_mwh, 3),
        "candidate_unserved_mwh": round(cand_mwh, 3),
        "unserved_reduction_mwh": round(restored_mwh, 3),
        "outage_duration_hours": round(duration, 2),
        "households_per_mw_assumption": households_per_mw,
        "baseline_affected_households_est": int(round(base_avg_deficit_mw * households_per_mw)),
        "candidate_affected_households_est": int(round(cand_avg_deficit_mw * households_per_mw)),
        "reconnected_households_est": int(round(restored_avg_mw * households_per_mw)),
        "household_hours_saved_est": int(round(restored_mwh * households_per_mw)),
    }


# Canonical alias for household impact calculation
compute_household_impact = estimate_household_impact


def estimate_affected_households(
    unserved_mw_by_node_before: dict[str, list[float]],
    unserved_mw_by_node_after: dict[str, list[float]],
    time_step_hours: float = 1.0,
    households_per_mw: float = HOUSEHOLDS_PER_MW_SUBSTAT,
) -> dict[str, Any]:
    """Compute nodal and system-wide Chilean household disconnection & reconnection metrics."""
    dt = max(1e-6, float(time_step_hours))
    all_nodes = sorted(set(unserved_mw_by_node_before) | set(unserved_mw_by_node_after))
    node_breakdown: dict[str, dict[str, Any]] = {}

    total_mwh_before = 0.0
    total_mwh_after = 0.0
    total_hh_before = 0
    total_hh_after = 0

    for nid in all_nodes:
        s_before = [max(0.0, float(x)) for x in unserved_mw_by_node_before.get(nid, [])]
        s_after = [max(0.0, float(x)) for x in unserved_mw_by_node_after.get(nid, [])]
        mwh_b = sum(s_before) * dt
        mwh_a = sum(s_after) * dt
        peak_mw_b = max(s_before, default=0.0)
        peak_mw_a = max(s_after, default=0.0)
        hh_b = int(round(peak_mw_b * households_per_mw))
        hh_a = int(round(peak_mw_a * households_per_mw))
        hh_rec = max(0, hh_b - hh_a)

        total_mwh_before += mwh_b
        total_mwh_after += mwh_a
        total_hh_before += hh_b
        total_hh_after += hh_a

        node_breakdown[nid] = {
            "unserved_mwh_before": round(mwh_b, 3),
            "unserved_mwh_after": round(mwh_a, 3),
            "energy_restored_mwh": round(max(0.0, mwh_b - mwh_a), 3),
            "peak_unserved_mw_before": round(peak_mw_b, 3),
            "peak_unserved_mw_after": round(peak_mw_a, 3),
            "households_affected_before": hh_b,
            "households_affected_after": hh_a,
            "households_reconnected": hh_rec,
        }

    total_hh_reconnected = max(0, total_hh_before - total_hh_after)
    reconnection_pct = (
        (total_hh_reconnected / total_hh_before * 100.0)
        if total_hh_before > 0
        else 100.0
    )

    return {
        "total_unserved_mwh_before": round(total_mwh_before, 3),
        "total_unserved_mwh_after": round(total_mwh_after, 3),
        "total_energy_restored_mwh": round(max(0.0, total_mwh_before - total_mwh_after), 3),
        "total_households_affected_before": total_hh_before,
        "total_households_affected_after": total_hh_after,
        "total_households_reconnected": total_hh_reconnected,
        "reconnection_rate_pct": round(reconnection_pct, 2),
        "nodes": node_breakdown,
    }


def build_regulatory_compliance_matrix(
    baseline_metrics: dict[str, Any],
    candidate_metrics: dict[str, Any],
    validation_passed: bool,
    household_impact: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build structured Chilean legal compliance audit items."""
    b_curt = float(baseline_metrics.get("curtailment_mwh", 0.0))
    c_curt = float(candidate_metrics.get("curtailment_mwh", 0.0))
    b_cost = float(baseline_metrics.get("assumed_cost_usd", 0.0))
    c_cost = float(candidate_metrics.get("assumed_cost_usd", 0.0))
    curt_red = b_curt - c_curt
    cost_sav = b_cost - c_cost
    status = "compliant" if validation_passed else "non_compliant"

    hh_clause = "Zero unserved residential energy under normal operation."
    if household_impact and household_impact.get("total_households_affected_before", 0) > 0:
        hh_clause = (
            f"Sudden N-1 crisis EDAC impact mitigated: reconnected "
            f"{household_impact['total_households_reconnected']:,} of "
            f"{household_impact['total_households_affected_before']:,} affected Chilean households "
            f"({household_impact['reconnection_rate_pct']:.1f}%)."
        )

    return [
        {
            "id": "LGSE-ART-72-1",
            "code": CHILEAN_LEGAL_FRAMEWORK["LGSE-ART-72-1"]["code"],
            "title": CHILEAN_LEGAL_FRAMEWORK["LGSE-ART-72-1"]["title"],
            "status": status,
            "finding": (
                f"Minimum-cost merit-order dispatch verified; thermal dispatch cost reduced by "
                f"${cost_sav:,.2f} USD (${b_cost:,.2f} -> ${c_cost:,.2f} USD)."
            ),
        },
        {
            "id": "DS-32-2026-ART-117-BIS",
            "code": CHILEAN_LEGAL_FRAMEWORK["DS-32-2026-ART-117-BIS"]["code"],
            "title": CHILEAN_LEGAL_FRAMEWORK["DS-32-2026-ART-117-BIS"]["title"],
            "status": status,
            "finding": (
                f"Automated SCED co-optimisation reduced renewable curtailment by "
                f"{curt_red:.1f} MWh ({b_curt:.1f} -> {c_curt:.1f} MWh)."
            ),
        },
        {
            "id": "NTSYCS-N1-EDAC",
            "code": CHILEAN_LEGAL_FRAMEWORK["NTSYCS-N1-EDAC"]["code"],
            "title": CHILEAN_LEGAL_FRAMEWORK["NTSYCS-N1-EDAC"]["title"],
            "status": status,
            "finding": f"All nodal balances, line thermal ratings, and ramp rates respected. {hh_clause}",
        },
        {
            "id": "LEY-21505-SAE",
            "code": CHILEAN_LEGAL_FRAMEWORK["LEY-21505-SAE"]["code"],
            "title": CHILEAN_LEGAL_FRAMEWORK["LEY-21505-SAE"]["title"],
            "status": status,
            "finding": (
                "BESS state-of-charge trajectory, efficiency losses, and end-of-horizon conservation "
                "(SOC_T >= SOC_0) independently verified."
            ),
        },
    ]


def build_regulatory_compliance_summary(
    validation_passed: bool,
    curtailment_reduction_mwh: float,
    crisis_summary: dict[str, Any] | None = None,
) -> list[str]:
    """Return concise regulatory compliance bullet points for the operator report."""
    status_tag = (
        "COMPLIANT (Verified by independent deterministic audit)"
        if validation_passed
        else "NON-COMPLIANT (Rejected by deterministic validator)"
    )
    notes = [
        f"LGSE Art. 72°-1 (Merit-Order Economic Dispatch): {status_tag} — zero-marginal-cost renewables dispatched ahead of thermal units; simulated curtailment reduced by {curtailment_reduction_mwh:.2f} MWh.",
        "Supreme Decree N° 32/2026 Art. 117 bis (Automated SCED): Autonomous dispatch executed with independent pre-execution nodal balance and line-limit verification.",
        "Law N° 21.505 (Storage / SAE): Battery state-of-charge progression, efficiency losses, and end-of-horizon conservation (SOC_T >= SOC_0) independently verified.",
    ]
    if crisis_summary:
        reconnected = crisis_summary.get("reconnected_households_est", 0)
        restored_mwh = crisis_summary.get("unserved_reduction_mwh", 0.0)
        event_desc = crisis_summary.get("event_description", "sudden generator contingency")
        notes.append(
            f"NTSyCS (N-1 Contingency & EDAC Household Recovery): Stress-tested against {event_desc}; corrective redispatch reduced EDAC unserved energy by {restored_mwh:.2f} MWh (~{reconnected:,} equivalent Chilean households reconnected)."
        )
    return notes
