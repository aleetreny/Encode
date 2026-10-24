"""GridPilot Live Ops - RIO Regulatory Session Report Generator.

Generates audit-grade operational reports in Markdown and printable HTML
matching Chilean CEN (Coordinador Eléctrico Nacional) RIO
(Registro de Instrucciones Operativas) conventions and legal frameworks.
"""

from __future__ import annotations

import html
from typing import Any

from agent.regulatory import (
    CHILEAN_LEGAL_FRAMEWORK,
    CHILEAN_REGULATORY_SOURCES,
    HOUSEHOLDS_PER_MW_SUBSTAT,
)

SLOGAN_NEURO_SYMBOLIC = (
    "Física real sobre una red simulada con forma chilena. "
    "Gemini decide; los números los calcula y los valida código determinista."
)

LEGAL_DISCLAIMER_STATUS = "legal_compliance_status = not_certified"
LEGAL_DISCLAIMER_TEXT = (
    "Soporte de decisión en simulación; ninguna acción sobre SCADA real. "
    "Este informe ha sido generado por el prototipo neuro-simbólico GridPilot Live Ops "
    "con fines exclusivamente analíticos y demostrativos en entorno simulado. "
    "No constituye una orden de maniobra ni reemplaza los procedimientos oficiales de despacho "
    "del Coordinador Eléctrico Nacional (CEN)."
)


def _get_attr(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _format_author(by: str) -> str:
    if by == "gemini_autonomous":
        return "Gemini 4 Argon Autónomo (gemini_autonomous)"
    if by == "operator":
        return "Operador Humano (operator)"
    return f"{by} (Operador)"


def _format_action(decision: str) -> str:
    if decision == "apply":
        return "Aplicada (apply)"
    if decision == "veto":
        return "Vetada por Operador (veto)"
    return str(decision)


def _extract_report_context(session: Any) -> dict[str, Any]:
    session_id = str(_get_attr(session, "session_id", "demo-session"))
    catalog = _get_attr(session, "catalog", {}) or {}
    scenario_id = str(catalog.get("scenario_id", "chile-sen-5node-demo"))
    hour = float(_get_attr(session, "hour", 0.0))
    grid_state = str(_get_attr(session, "grid_state", "normal")).lower()
    autonomy = bool(_get_attr(session, "autonomy", False))

    # Incidents
    inc_raw = _get_attr(session, "incident_records", {})
    if isinstance(inc_raw, dict):
        incidents = list(inc_raw.values())
    elif isinstance(inc_raw, list):
        incidents = list(inc_raw)
    else:
        incidents = []

    # If active_events has something not yet recorded, track it
    active_events = list(_get_attr(session, "active_events", []) or [])
    recorded_event_ids = {
        inc.get("disruption", {}).get("event_id")
        for inc in incidents
        if isinstance(inc, dict) and isinstance(inc.get("disruption"), dict)
    }
    for ev in active_events:
        if isinstance(ev, dict) and ev.get("event_id") not in recorded_event_ids:
            incidents.append(
                {
                    "incident_id": f"inc_active_{ev.get('asset_id', 'unknown')}",
                    "disruption": ev,
                    "from_hour": ev.get("from_hour", int(hour)),
                    "to_hour": ev.get("to_hour", int(hour) + 4),
                    "impact": {
                        "unserved_mw_peak": 0.0,
                        "households_off_peak": 0,
                        "nodes_affected": [],
                        "lines_overloaded": [],
                    },
                }
            )

    # Decisions
    decision_log = list(_get_attr(session, "decision_log", []) or [])

    # Provenance and Assumptions
    provenance = catalog.get("provenance") or {
        "nodes_coordinates": "derived",
        "households_per_mw": "assumption",
        "households_total": "assumption",
        "generators": "synthetic",
        "batteries": "synthetic",
        "lines": "synthetic",
        "demand_mw": "synthetic",
        "emission_factors": "assumption",
    }
    assumptions = catalog.get("assumptions") or {
        "households_per_mw": HOUSEHOLDS_PER_MW_SUBSTAT,
        "emission_factors_t_per_mwh": {
            "gas": 0.40,
            "coal": 0.95,
            "diesel": 0.75,
            "solar": 0.0,
            "wind": 0.0,
            "hydro": 0.0,
        },
        "voll_usd_per_mwh": 10000.0,
        "demand_response_cost_usd_per_mwh": 300.0,
        "hydro_water_value_usd_per_mwh": 120.0,
    }

    return {
        "session_id": session_id,
        "scenario_id": scenario_id,
        "hour": hour,
        "grid_state": grid_state,
        "autonomy": autonomy,
        "incidents": incidents,
        "decision_log": decision_log,
        "active_events": active_events,
        "provenance": provenance,
        "assumptions": assumptions,
    }


def _render_markdown(ctx: dict[str, Any]) -> str:
    lines: list[str] = []

    # 1. Encabezado Ejecutivo
    lines.append("# REGISTRO DE INSTRUCCIONES OPERATIVAS (RIO)")
    lines.append("## Reporte de Auditoría y Despacho en Simulación — Sistema Eléctrico Nacional (SEN)\n")
    lines.append(f"> *{SLOGAN_NEURO_SYMBOLIC}*\n")

    autonomy_str = (
        "Habilitado — Gemini 4 Argon Autónomo (gemini_autonomous)"
        if ctx["autonomy"]
        else "Deshabilitado — Control Manual Operador Humano (operator)"
    )
    hour_formatted = f"{ctx['hour']:.2f} h (T={int(ctx['hour']):02d}:{int((ctx['hour'] % 1) * 60):02d})"

    lines.append("### Encabezado Ejecutivo")
    lines.append(f"- **ID de Sesión (`session_id`)**: `{ctx['session_id']}`")
    lines.append(f"- **Escenario (`scenario_id`)**: `{ctx['scenario_id']}`")
    lines.append(f"- **Hora Simulada Actual (`hour`)**: `{hour_formatted}`")
    lines.append(f"- **Estado NTSyCS (`grid_state`)**: `{ctx['grid_state'].upper()}`")
    lines.append(f"- **Modo Autónomo (`autonomy`)**: `{autonomy_str}`")
    lines.append(f"- **Total Incidentes Registrados**: `{len(ctx['incidents'])}`")
    lines.append(f"- **Total Decisiones Operativas**: `{len(ctx['decision_log'])}`\n")

    # 2. Línea de Tiempo de Incidentes y Contingencias
    lines.append("---")
    lines.append("### Línea de Tiempo de Incidentes y Contingencias\n")
    if not ctx["incidents"]:
        lines.append("*No se registraron contingencias operativas durante esta sesión.*\n")
    else:
        for idx, inc in enumerate(ctx["incidents"], start=1):
            inc_id = inc.get("incident_id", f"inc_{idx}")
            disruption = inc.get("disruption") or {}
            event_id = disruption.get("event_id", inc.get("event_id", "ev_unknown"))
            asset_id = disruption.get("asset_id", inc.get("asset_id", "unknown_asset"))
            fault_type = disruption.get("type", inc.get("type", "falla_desconocida"))
            from_h = inc.get("from_hour", disruption.get("from_hour", 0))
            to_h = inc.get("to_hour", disruption.get("to_hour", 0))
            source = disruption.get("source", inc.get("source", "operator"))
            jury_name = disruption.get("jury_name") or inc.get("jury_name")

            if jury_name:
                origin_str = f"Jurado ({source}): Jurado Test ({jury_name})" if "Jurado Test" not in str(jury_name) else f"Jurado ({source}): {jury_name}"
            else:
                origin_str = f"Operador ({source})" if source == "operator" else f"Script / Sistema ({source})"

            impact = inc.get("impact") or {}
            unserved_mw_peak = float(impact.get("unserved_mw_peak", 0.0))
            hh_peak = int(impact.get("households_off_peak", 0))
            nodes_aff = impact.get("nodes_affected") or []
            nodes_str = ", ".join(nodes_aff) if nodes_aff else "Ninguno"
            lines_ov = impact.get("lines_overloaded") or []
            lines_str = ", ".join(lines_ov) if lines_ov else "Ninguna"

            lines.append(f"#### Incidente #{idx}: `{inc_id}` ({asset_id})")
            lines.append(f"- **ID de Incidente**: `{inc_id}`")
            lines.append(f"- **ID de Evento**: `{event_id}`")
            lines.append(f"- **Activo Afectado**: `{asset_id}`")
            lines.append(f"- **Tipo de Falla**: `{fault_type}`")
            lines.append(f"- **Ventana Horaria**: `T={from_h:02d}:00 – T={to_h:02d}:00` ({to_h - from_h} horas)")
            lines.append(f"- **Origen del Disparo**: `{origin_str}`")
            lines.append(f"- **Pico de Potencia No Suministrada**: `{unserved_mw_peak:.2f} MW`")
            lines.append(f"- **Pico de Hogares Afectados**: `{hh_peak:,} hogares`")
            lines.append(f"- **Nodos Afectados**: `{nodes_str}`")
            lines.append(f"- **Líneas Sobrecargadas (>95%)**: `{lines_str}`\n")

    # 3. Registro de Decisiones Operativas y Validaciones Físicas
    lines.append("---")
    lines.append("### Registro de Decisiones Operativas y Validaciones Físicas\n")
    if not ctx["decision_log"]:
        lines.append("*No se registraron decisiones ni intervenciones operativas durante esta sesión.*\n")
    else:
        for idx, dec in enumerate(ctx["decision_log"], start=1):
            target_inc_id = dec.get("incident_id", "inc_unknown")
            chosen_opt_id = dec.get("option_id", "opt_unknown")
            by = dec.get("by", "operator")
            author_str = _format_author(by)
            decision = dec.get("decision", "apply")
            action_str = _format_action(decision)
            hour_dec = dec.get("hour", ctx["hour"])
            ts_utc = dec.get("ts_utc", "N/A")

            # Levers
            opt_data = dec.get("option") or {}
            levers = opt_data.get("levers") or dec.get("levers") or []

            # Metrics
            metrics = dec.get("metrics") or opt_data.get("metrics") or {}
            hh_rec = metrics.get("households_reconnected", 0)
            unserved_avoided = float(metrics.get("unserved_mwh_avoided", 0.0))
            cost_delta = float(metrics.get("cost_delta_usd", 0.0))
            co2_delta = float(metrics.get("co2_delta_t", 0.0))
            max_line_loading = float(metrics.get("max_line_loading_pct", 0.0))

            # Independent validation
            val = dec.get("validation") or opt_data.get("validation") or {}
            val_passed = bool(val.get("passed", False))
            max_res = float(val.get("max_residual_mw", 0.0))
            violations = val.get("violations") or []
            violations_str = ", ".join(violations) if violations else "Ninguna (0 violaciones)"
            val_status_str = "PASSED (PASS)" if val_passed else "FAILED (FAIL)"

            lines.append(f"#### Decisión #{idx}: Plan `{chosen_opt_id}` ({action_str})")
            lines.append(f"- **Incidente Asociado**: `{target_inc_id}`")
            lines.append(f"- **Identificador de Opción**: `{chosen_opt_id}`")
            lines.append(f"- **Autor de la Decisión**: **{author_str}**")
            lines.append(f"- **Acción Ejecutada**: **{action_str}**")
            lines.append(f"- **Hora Simulada y Timestamp**: `T={hour_dec:.2f} h` (`{ts_utc}`)")

            # Levers detail
            if levers:
                levers_desc = "; ".join(
                    f"{lv.get('type')}:{lv.get('target_id')} (T={lv.get('from_hour')}-{lv.get('to_hour')})"
                    for lv in levers
                )
                lines.append(f"- **Palancas Aplicadas (`levers`)**: `{levers_desc}`")
            else:
                lines.append("- **Palancas Aplicadas (`levers`)**: `Ninguna (no-action o vetada)`")

            # Metrics detail
            lines.append("- **Métricas Verificadas por Código Determinista**:")
            lines.append(f"  - Hogares Reconectados (`households_reconnected`): `{hh_rec:,}`")
            lines.append(f"  - Energía No Suministrada Evitada (`unserved_mwh_avoided`): `{unserved_avoided:.2f} MWh`")
            lines.append(f"  - Variación de Costo (`cost_delta_usd`): `${cost_delta:,.2f} USD`")
            lines.append(f"  - Variación de Emisiones (`co2_delta_t`): `{co2_delta:.2f} tCO₂`")
            lines.append(f"  - Carga Máxima de Línea Troncal (`max_line_loading_pct`): `{max_line_loading:.1f}%`")

            # Validator detail
            lines.append("- **Resultado del Validador Independiente**:")
            lines.append(f"  - Estado de Validación Física: **{val_status_str}** (`passed={val_passed}`)")
            lines.append(f"  - Residuo Nodal Máximo (`max_residual_mw`): `{max_res:.6e} MW`")
            lines.append(f"  - Violaciones Físicas: `{violations_str}`\n")

    # 4. Procedencia de Datos y Supuestos Explícitos
    lines.append("---")
    lines.append("### Procedencia de Datos y Supuestos Explícitos\n")
    lines.append("#### Fórmula Determinista de Afectación Residencial:")
    lines.append("```text")
    lines.append("hogares_sin_luz(nodo, hora) = unserved_mw(nodo, hora) × households_per_mw(nodo)")
    lines.append("```")
    lines.append(
        "- Factor de conversión residencial: `households_per_mw = 1000` "
        "(Clasificación: `assumption` / `derived`, equivalente a ~1.0 kW de demanda coincidente por hogar en subestación)."
    )

    lines.append("\n#### Factores de Emisión de CO₂ por Tecnología:")
    lines.append("- Gas Natural (`gas`): `0.40` tCO₂/MWh (`gas: 0.40`, clasificación: `assumption`)")
    lines.append("- Carbón (`coal`): `0.95` tCO₂/MWh (`coal: 0.95`, clasificación: `assumption`)")
    lines.append("- Diésel (`diesel`): `0.75` tCO₂/MWh (`diesel: 0.75`, clasificación: `assumption`)")
    lines.append("- Solar / Eólica / Hidráulica: `0.00` tCO₂/MWh (`assumption`)")

    lines.append("\n#### Topología y Perfiles del Escenario:")
    lines.append(
        "- Topología de 5 barras SEN (Crucero, Atacama, Cardones, Polpaico, Charrúa) "
        "y curvas horarias de demanda/recurso renovable: clasificación `synthetic`."
    )

    lines.append("\n#### Matriz Completa de Procedencia (`session.catalog.provenance`):")
    lines.append("| Componente / Parámetro | Clasificación de Procedencia | Justificación / Fuente |")
    lines.append("| :--- | :--- | :--- |")
    for key, prov_val in ctx["provenance"].items():
        lines.append(f"| `{key}` | `{prov_val}` | Catálogo del sistema simulado SEN |")

    lines.append("\n#### Supuestos Económicos y Operativos (`session.catalog.assumptions`):")
    lines.append(f"- `households_per_mw`: `1000` (`assumption`)")
    lines.append(f"- `voll_usd_per_mwh`: `${ctx['assumptions'].get('voll_usd_per_mwh', 10000.0):,.2f} USD/MWh` (`assumption`)")
    lines.append(f"- `demand_response_cost_usd_per_mwh`: `${ctx['assumptions'].get('demand_response_cost_usd_per_mwh', 300.0):,.2f} USD/MWh` (`assumption`)")
    lines.append(f"- `hydro_water_value_usd_per_mwh`: `${ctx['assumptions'].get('hydro_water_value_usd_per_mwh', 120.0):,.2f} USD/MWh` (`assumption`)\n")

    # 5. Marco Regulatorio Chileno y Descargo de Responsabilidad
    lines.append("---")
    lines.append("### Marco Regulatorio Chileno y Descargo de Responsabilidad\n")
    lines.append("#### Articulado Legal Aplicable al Despacho y Coordinación del SEN:")
    lines.append(
        f"1. **{CHILEAN_LEGAL_FRAMEWORK['LGSE-ART-72-1']['code']}** ({CHILEAN_LEGAL_FRAMEWORK['LGSE-ART-72-1']['title']}):\n"
        f"   - Principio: {CHILEAN_LEGAL_FRAMEWORK['LGSE-ART-72-1']['principle']}\n"
        f"   - Cita explícita: **LGSE DFL N° 4/2006 Art. 72°-1** (Coordinación segura y a mínimo costo del SEN)."
    )
    lines.append(
        f"2. **{CHILEAN_LEGAL_FRAMEWORK['DS-32-2026-ART-117-BIS']['code']}** ({CHILEAN_LEGAL_FRAMEWORK['DS-32-2026-ART-117-BIS']['title']}):\n"
        f"   - Principio: {CHILEAN_LEGAL_FRAMEWORK['DS-32-2026-ART-117-BIS']['principle']}\n"
        f"   - Cita explícita: **DS N° 32/2026 Art. 117 bis** (Despacho económico con restricciones de seguridad SCED y recorte renovable)."
    )
    lines.append(
        f"3. **{CHILEAN_LEGAL_FRAMEWORK['NTSYCS-N1-EDAC']['code']}** ({CHILEAN_LEGAL_FRAMEWORK['NTSYCS-N1-EDAC']['title']}):\n"
        f"   - Principio: {CHILEAN_LEGAL_FRAMEWORK['NTSYCS-N1-EDAC']['principle']}\n"
        f"   - Cita explícita: **Norma Técnica de Seguridad y Calidad de Servicio (NTSyCS - CNE)** (Estados Normal, Alerta, Emergencia y Recuperación; criterio N-1 y EDAC)."
    )
    lines.append(
        f"4. **{CHILEAN_LEGAL_FRAMEWORK['LEY-21505-SAE']['code']}** ({CHILEAN_LEGAL_FRAMEWORK['LEY-21505-SAE']['title']}):\n"
        f"   - Principio: {CHILEAN_LEGAL_FRAMEWORK['LEY-21505-SAE']['principle']}\n"
        f"   - Cita explícita: **Ley N° 21.505 / DS N° 70/2023** (Sistemas de Almacenamiento de Energía BESS)."
    )

    lines.append("\n#### Fuentes Regulatorias y Enlaces Oficiales:")
    for src in CHILEAN_REGULATORY_SOURCES:
        lines.append(f"- <{src}>")

    lines.append(f"\n#### Descargo de Responsabilidad Legal (`{LEGAL_DISCLAIMER_STATUS}`):")
    lines.append(f"> **Estado de Certificación Legal**: `{LEGAL_DISCLAIMER_STATUS}`")
    lines.append(f"> ")
    lines.append(f"> {LEGAL_DISCLAIMER_TEXT}\n")

    return "\n".join(lines)


def _render_html(ctx: dict[str, Any]) -> str:
    session_id_esc = html.escape(ctx["session_id"])
    scenario_id_esc = html.escape(ctx["scenario_id"])
    grid_state_esc = html.escape(ctx["grid_state"].upper())
    autonomy_str = (
        "Habilitado — Gemini 4 Argon Autónomo (gemini_autonomous)"
        if ctx["autonomy"]
        else "Deshabilitado — Control Manual Operador Humano (operator)"
    )
    hour_formatted = f"{ctx['hour']:.2f} h (T={int(ctx['hour']):02d}:{int((ctx['hour'] % 1) * 60):02d})"

    # CSS with embedded @media print
    css = """
    <style>
      :root {
        --primary: #0f172a;
        --secondary: #334155;
        --accent: #2563eb;
        --accent-light: #eff6ff;
        --success: #166534;
        --success-bg: #dcfce7;
        --warning: #92400e;
        --warning-bg: #fef3c7;
        --danger: #991b1b;
        --danger-bg: #fee2e2;
        --border: #cbd5e1;
        --bg: #f8fafc;
        --card-bg: #ffffff;
      }
      * { box-sizing: border-box; }
      body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
        line-height: 1.6;
        color: var(--secondary);
        background-color: var(--bg);
        margin: 0;
        padding: 2.5rem 1.5rem;
      }
      .container {
        max-width: 960px;
        margin: 0 auto;
        background: var(--card-bg);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 2.5rem 3rem;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);
      }
      header {
        border-bottom: 2px solid var(--border);
        padding-bottom: 1.5rem;
        margin-bottom: 2rem;
      }
      h1 {
        font-size: 1.8rem;
        color: var(--primary);
        margin: 0 0 0.5rem 0;
        letter-spacing: -0.02em;
      }
      h2 {
        font-size: 1.25rem;
        color: var(--secondary);
        margin: 0 0 1rem 0;
        font-weight: 500;
      }
      h3 {
        font-size: 1.2rem;
        color: var(--primary);
        border-bottom: 1px solid var(--border);
        padding-bottom: 0.4rem;
        margin-top: 2rem;
        margin-bottom: 1rem;
      }
      h4 {
        font-size: 1.05rem;
        color: var(--primary);
        margin-top: 1.2rem;
        margin-bottom: 0.5rem;
      }
      p { margin: 0.5rem 0; }
      .slogan {
        font-style: italic;
        background: var(--accent-light);
        border-left: 4px solid var(--accent);
        padding: 0.8rem 1.2rem;
        margin: 1rem 0;
        color: #1e3a8a;
        font-size: 0.95rem;
        border-radius: 0 4px 4px 0;
      }
      .meta-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
        gap: 1rem;
        background: #f1f5f9;
        padding: 1.2rem;
        border-radius: 6px;
        margin: 1.5rem 0;
        font-size: 0.92rem;
      }
      .meta-item { display: flex; flex-direction: column; }
      .meta-label { font-size: 0.78rem; text-transform: uppercase; color: #64748b; font-weight: 600; letter-spacing: 0.05em; }
      .meta-val { font-weight: 600; color: var(--primary); margin-top: 0.2rem; }
      table {
        width: 100%;
        border-collapse: collapse;
        margin: 1rem 0 1.5rem 0;
        font-size: 0.9rem;
      }
      th, td {
        border: 1px solid var(--border);
        padding: 0.6rem 0.8rem;
        text-align: left;
      }
      th {
        background-color: #f8fafc;
        color: var(--primary);
        font-weight: 600;
      }
      tr:nth-child(even) td { background-color: #fafbfc; }
      .badge {
        display: inline-block;
        padding: 0.2rem 0.55rem;
        border-radius: 4px;
        font-size: 0.8rem;
        font-weight: 600;
      }
      .badge-pass { background: var(--success-bg); color: var(--success); }
      .badge-fail { background: var(--danger-bg); color: var(--danger); }
      .badge-warn { background: var(--warning-bg); color: var(--warning); }
      .card {
        border: 1px solid var(--border);
        border-radius: 6px;
        padding: 1rem 1.2rem;
        margin-bottom: 1.2rem;
        background: #ffffff;
      }
      .card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 1px solid #f1f5f9;
        padding-bottom: 0.5rem;
        margin-bottom: 0.8rem;
      }
      code {
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        background: #f1f5f9;
        padding: 0.15rem 0.35rem;
        border-radius: 3px;
        font-size: 0.88em;
        color: #0f172a;
      }
      pre {
        background: #0f172a;
        color: #f8fafc;
        padding: 0.8rem 1rem;
        border-radius: 6px;
        overflow-x: auto;
        font-size: 0.88rem;
      }
      pre code {
        background: transparent;
        color: inherit;
        padding: 0;
      }
      .disclaimer-box {
        background: var(--warning-bg);
        border: 1px solid #fde68a;
        border-left: 4px solid #f59e0b;
        padding: 1rem 1.2rem;
        border-radius: 4px;
        margin: 1.5rem 0;
        font-size: 0.9rem;
        color: var(--warning);
      }
      @media print {
        body {
          background: #ffffff;
          padding: 0;
          font-size: 10pt;
          color: #000000;
        }
        .container {
          border: none;
          box-shadow: none;
          padding: 0;
          max-width: 100%;
        }
        .slogan { border-left-color: #000; background: #eee; color: #000; }
        .meta-grid { background: #f8f8f8; border: 1px solid #ccc; }
        th { background-color: #eee !important; color: #000; }
        .card { page-break-inside: avoid; border: 1px solid #ccc; }
        .page-break { page-break-before: always; }
        a { color: #000; text-decoration: underline; }
        @page {
          margin: 1.5cm;
          size: A4 portrait;
        }
      }
    </style>
    """

    out: list[str] = [
        "<!DOCTYPE html>",
        "<html lang=\"es\">",
        "<head>",
        "  <meta charset=\"utf-8\">",
        "  <title>RIO Reporte de Sesión - GridPilot Live Ops</title>",
        css,
        "</head>",
        "<body>",
        "<div class=\"container\">",
        "  <header>",
        "    <h1>REGISTRO DE INSTRUCCIONES OPERATIVAS (RIO)</h1>",
        "    <h2>Sistema Eléctrico Nacional (SEN) — Coordinación de Seguridad y Despacho Económico</h2>",
        f"    <div class=\"slogan\">{html.escape(SLOGAN_NEURO_SYMBOLIC)}</div>",
        "  </header>",
        "",
        "  <section id=\"encabezado-ejecutivo\">",
        "    <h3>Encabezado Ejecutivo</h3>",
        "    <div class=\"meta-grid\">",
        f"      <div class=\"meta-item\"><span class=\"meta-label\">Session ID</span><span class=\"meta-val\"><code>{session_id_esc}</code></span></div>",
        f"      <div class=\"meta-item\"><span class=\"meta-label\">Escenario</span><span class=\"meta-val\"><code>{scenario_id_esc}</code></span></div>",
        f"      <div class=\"meta-item\"><span class=\"meta-label\">Hora Simulada</span><span class=\"meta-val\">{hour_formatted}</span></div>",
        f"      <div class=\"meta-item\"><span class=\"meta-label\">Estado NTSyCS</span><span class=\"meta-val\"><span class=\"badge badge-pass\">{grid_state_esc}</span></span></div>",
        f"      <div class=\"meta-item\"><span class=\"meta-label\">Modo Autónomo</span><span class=\"meta-val\">{html.escape(autonomy_str)}</span></div>",
        f"      <div class=\"meta-item\"><span class=\"meta-label\">Total Contingencias</span><span class=\"meta-val\">{len(ctx['incidents'])}</span></div>",
        f"      <div class=\"meta-item\"><span class=\"meta-label\">Decisiones RIO</span><span class=\"meta-val\">{len(ctx['decision_log'])}</span></div>",
        "    </div>",
        "  </section>",
        "",
        "  <section id=\"linea-tiempo\">",
        "    <h3>Línea de Tiempo de Incidentes y Contingencias</h3>",
    ]

    # Incidents in HTML
    if not ctx["incidents"]:
        out.append("    <p><em>No se registraron contingencias operativas durante esta sesión.</em></p>")
    else:
        for idx, inc in enumerate(ctx["incidents"], start=1):
            inc_id = inc.get("incident_id", f"inc_{idx}")
            disruption = inc.get("disruption") or {}
            event_id = disruption.get("event_id", inc.get("event_id", "ev_unknown"))
            asset_id = disruption.get("asset_id", inc.get("asset_id", "unknown_asset"))
            fault_type = disruption.get("type", inc.get("type", "falla_desconocida"))
            from_h = inc.get("from_hour", disruption.get("from_hour", 0))
            to_h = inc.get("to_hour", disruption.get("to_hour", 0))
            source = disruption.get("source", inc.get("source", "operator"))
            jury_name = disruption.get("jury_name") or inc.get("jury_name")

            if jury_name:
                origin_str = f"Jurado ({source}): Jurado Test ({jury_name})" if "Jurado Test" not in str(jury_name) else f"Jurado ({source}): {jury_name}"
            else:
                origin_str = f"Operador ({source})" if source == "operator" else f"Script / Sistema ({source})"

            impact = inc.get("impact") or {}
            unserved_mw_peak = float(impact.get("unserved_mw_peak", 0.0))
            hh_peak = int(impact.get("households_off_peak", 0))
            nodes_aff = impact.get("nodes_affected") or []
            nodes_str = ", ".join(nodes_aff) if nodes_aff else "Ninguno"
            lines_ov = impact.get("lines_overloaded") or []
            lines_str = ", ".join(lines_ov) if lines_ov else "Ninguna"

            out.extend([
                f"    <div class=\"card\">",
                f"      <div class=\"card-header\">",
                f"        <strong>Incidente #{idx}: <code>{html.escape(inc_id)}</code> ({html.escape(asset_id)})</strong>",
                f"        <span class=\"badge badge-warn\">{html.escape(fault_type)}</span>",
                f"      </div>",
                f"      <ul>",
                f"        <li><strong>ID de Incidente</strong>: <code>{html.escape(inc_id)}</code></li>",
                f"        <li><strong>ID de Evento</strong>: <code>{html.escape(event_id)}</code></li>",
                f"        <li><strong>Activo Afectado</strong>: <code>{html.escape(asset_id)}</code></li>",
                f"        <li><strong>Tipo de Falla</strong>: <code>{html.escape(fault_type)}</code></li>",
                f"        <li><strong>Ventana Horaria</strong>: <code>T={from_h:02d}:00 – T={to_h:02d}:00</code> ({to_h - from_h} horas)</li>",
                f"        <li><strong>Origen del Disparo</strong>: {html.escape(origin_str)}</li>",
                f"        <li><strong>Pico de Potencia No Suministrada</strong>: <code>{unserved_mw_peak:.2f} MW</code></li>",
                f"        <li><strong>Pico de Hogares Afectados</strong>: <code>{hh_peak:,} hogares</code></li>",
                f"        <li><strong>Nodos Afectados</strong>: <code>{html.escape(nodes_str)}</code></li>",
                f"        <li><strong>Líneas Sobrecargadas (>95%)</strong>: <code>{html.escape(lines_str)}</code></li>",
                f"      </ul>",
                f"    </div>",
            ])

    out.extend([
        "  </section>",
        "",
        "  <section id=\"decisiones-operativas\">",
        "    <h3>Registro de Decisiones Operativas y Validaciones Físicas</h3>",
    ])

    # Decisions in HTML
    if not ctx["decision_log"]:
        out.append("    <p><em>No se registraron decisiones ni intervenciones operativas durante esta sesión.</em></p>")
    else:
        for idx, dec in enumerate(ctx["decision_log"], start=1):
            target_inc_id = dec.get("incident_id", "inc_unknown")
            chosen_opt_id = dec.get("option_id", "opt_unknown")
            by = dec.get("by", "operator")
            author_str = _format_author(by)
            decision = dec.get("decision", "apply")
            action_str = _format_action(decision)
            hour_dec = dec.get("hour", ctx["hour"])
            ts_utc = dec.get("ts_utc", "N/A")

            opt_data = dec.get("option") or {}
            levers = opt_data.get("levers") or dec.get("levers") or []

            metrics = dec.get("metrics") or opt_data.get("metrics") or {}
            hh_rec = metrics.get("households_reconnected", 0)
            unserved_avoided = float(metrics.get("unserved_mwh_avoided", 0.0))
            cost_delta = float(metrics.get("cost_delta_usd", 0.0))
            co2_delta = float(metrics.get("co2_delta_t", 0.0))
            max_line_loading = float(metrics.get("max_line_loading_pct", 0.0))

            val = dec.get("validation") or opt_data.get("validation") or {}
            val_passed = bool(val.get("passed", False))
            max_res = float(val.get("max_residual_mw", 0.0))
            violations = val.get("violations") or []
            violations_str = ", ".join(violations) if violations else "Ninguna (0 violaciones)"
            badge_class = "badge-pass" if val_passed else "badge-fail"
            val_status_str = "PASSED (PASS)" if val_passed else "FAILED (FAIL)"

            levers_desc = (
                "; ".join(
                    f"{lv.get('type')}:{lv.get('target_id')} (T={lv.get('from_hour')}-{lv.get('to_hour')})"
                    for lv in levers
                )
                if levers
                else "Ninguna (no-action o vetada)"
            )

            out.extend([
                f"    <div class=\"card\">",
                f"      <div class=\"card-header\">",
                f"        <strong>Decisión #{idx}: Plan <code>{html.escape(chosen_opt_id)}</code></strong>",
                f"        <span class=\"badge {badge_class}\">{html.escape(action_str)}</span>",
                f"      </div>",
                f"      <p><strong>Incidente Asociado</strong>: <code>{html.escape(target_inc_id)}</code> | <strong>Opción</strong>: <code>{html.escape(chosen_opt_id)}</code></p>",
                f"      <p><strong>Autor de la Decisión</strong>: <strong>{html.escape(author_str)}</strong></p>",
                f"      <p><strong>Acción Ejecutada</strong>: <strong>{html.escape(action_str)}</strong></p>",
                f"      <p><strong>Hora Simulada</strong>: <code>T={hour_dec:.2f} h</code> (<code>{html.escape(ts_utc)}</code>)</p>",
                f"      <p><strong>Palancas Aplicadas (<code>levers</code>)</strong>: <code>{html.escape(levers_desc)}</code></p>",
                f"      <h4>Métricas Verificadas por Código Determinista:</h4>",
                f"      <ul>",
                f"        <li>Hogares Reconectados (<code>households_reconnected</code>): <strong>{hh_rec:,}</strong></li>",
                f"        <li>Energía No Suministrada Evitada (<code>unserved_mwh_avoided</code>): <strong>{unserved_avoided:.2f} MWh</strong></li>",
                f"        <li>Variación de Costo (<code>cost_delta_usd</code>): <strong>${cost_delta:,.2f} USD</strong></li>",
                f"        <li>Variación de Emisiones (<code>co2_delta_t</code>): <strong>{co2_delta:.2f} tCO₂</strong></li>",
                f"        <li>Carga Máxima de Línea (<code>max_line_loading_pct</code>): <strong>{max_line_loading:.1f}%</strong></li>",
                f"      </ul>",
                f"      <h4>Resultado del Validador Independiente:</h4>",
                f"      <ul>",
                f"        <li>Estado de Validación Física: <span class=\"badge {badge_class}\"><strong>{val_status_str}</strong></span> (<code>passed={val_passed}</code>)</li>",
                f"        <li>Residuo Nodal Máximo (<code>max_residual_mw</code>): <code>{max_res:.6e} MW</code></li>",
                f"        <li>Violaciones Físicas: <code>{html.escape(violations_str)}</code></li>",
                f"      </ul>",
                f"    </div>",
            ])

    out.extend([
        "  </section>",
        "",
        "  <section id=\"procedencia-supuestos\">",
        "    <h3>Procedencia de Datos y Supuestos Explícitos</h3>",
        "    <h4>Fórmula Determinista de Afectación Residencial:</h4>",
        "    <pre><code>hogares_sin_luz(nodo, hora) = unserved_mw(nodo, hora) × households_per_mw(nodo)</code></pre>",
        "    <p>Factor de conversión residencial: <code>households_per_mw = 1000</code> (Clasificación: <code>assumption</code> / <code>derived</code>, equivalente a 1.0 kW de demanda coincidente por hogar en subestación).</p>",
        "    <h4>Factores de Emisión de CO₂ por Tecnología:</h4>",
        "    <ul>",
        "      <li>Gas Natural (<code>gas</code>): <code>0.40</code> tCO₂/MWh (<code>gas: 0.40</code>, clasificación: <code>assumption</code>)</li>",
        "      <li>Carbón (<code>coal</code>): <code>0.95</code> tCO₂/MWh (<code>coal: 0.95</code>, clasificación: <code>assumption</code>)</li>",
        "      <li>Diésel (<code>diesel</code>): <code>0.75</code> tCO₂/MWh (<code>diesel: 0.75</code>, clasificación: <code>assumption</code>)</li>",
        "      <li>Solar / Eólica / Hidráulica: <code>0.00</code> tCO₂/MWh (clasificación: <code>assumption</code>)</li>",
        "    </ul>",
        "    <h4>Topología y Perfiles del Escenario:</h4>",
        "    <p>Topología de 5 barras SEN y curvas horarias de demanda y recurso renovable: clasificación <code>synthetic</code>.</p>",
        "    <h4>Matriz de Procedencia (<code>session.catalog.provenance</code>):</h4>",
        "    <table>",
        "      <thead><tr><th>Parámetro / Componente</th><th>Clasificación</th><th>Fuente</th></tr></thead>",
        "      <tbody>",
    ])

    for k, v in ctx["provenance"].items():
        out.append(f"        <tr><td><code>{html.escape(k)}</code></td><td><code>{html.escape(str(v))}</code></td><td>Catálogo SEN GridPilot</td></tr>")

    out.extend([
        "      </tbody>",
        "    </table>",
        "    <h4>Supuestos Económicos y Operativos (<code>session.catalog.assumptions</code>):</h4>",
        "    <ul>",
        "      <li><code>households_per_mw</code>: <code>1000</code> (<code>assumption</code>)</li>",
        f"      <li><code>voll_usd_per_mwh</code>: <code>${ctx['assumptions'].get('voll_usd_per_mwh', 10000.0):,.2f} USD/MWh</code> (<code>assumption</code>)</li>",
        f"      <li><code>demand_response_cost_usd_per_mwh</code>: <code>${ctx['assumptions'].get('demand_response_cost_usd_per_mwh', 300.0):,.2f} USD/MWh</code> (<code>assumption</code>)</li>",
        f"      <li><code>hydro_water_value_usd_per_mwh</code>: <code>${ctx['assumptions'].get('hydro_water_value_usd_per_mwh', 120.0):,.2f} USD/MWh</code> (<code>assumption</code>)</li>",
        "    </ul>",
        "  </section>",
        "",
        "  <section id=\"marco-regulatorio\">",
        "    <h3>Marco Regulatorio Chileno y Descargo de Responsabilidad</h3>",
        "    <ol>",
        f"      <li><strong>{html.escape(CHILEAN_LEGAL_FRAMEWORK['LGSE-ART-72-1']['code'])}</strong> ({html.escape(CHILEAN_LEGAL_FRAMEWORK['LGSE-ART-72-1']['title'])}):<br>{html.escape(CHILEAN_LEGAL_FRAMEWORK['LGSE-ART-72-1']['principle'])}<br><em>Cita: LGSE DFL N° 4/2006 Art. 72°-1 (Coordinación segura y a mínimo costo del SEN)</em></li>",
        f"      <li><strong>{html.escape(CHILEAN_LEGAL_FRAMEWORK['DS-32-2026-ART-117-BIS']['code'])}</strong> ({html.escape(CHILEAN_LEGAL_FRAMEWORK['DS-32-2026-ART-117-BIS']['title'])}):<br>{html.escape(CHILEAN_LEGAL_FRAMEWORK['DS-32-2026-ART-117-BIS']['principle'])}<br><em>Cita: DS N° 32/2026 Art. 117 bis (Despacho económico con restricciones de seguridad SCED y recorte renovable)</em></li>",
        f"      <li><strong>{html.escape(CHILEAN_LEGAL_FRAMEWORK['NTSYCS-N1-EDAC']['code'])}</strong> ({html.escape(CHILEAN_LEGAL_FRAMEWORK['NTSYCS-N1-EDAC']['title'])}):<br>{html.escape(CHILEAN_LEGAL_FRAMEWORK['NTSYCS-N1-EDAC']['principle'])}<br><em>Cita: Norma Técnica de Seguridad y Calidad de Servicio (NTSyCS - CNE) (Estados Normal, Alerta, Emergencia y Recuperación; criterio N-1 y EDAC)</em></li>",
        f"      <li><strong>{html.escape(CHILEAN_LEGAL_FRAMEWORK['LEY-21505-SAE']['code'])}</strong> ({html.escape(CHILEAN_LEGAL_FRAMEWORK['LEY-21505-SAE']['title'])}):<br>{html.escape(CHILEAN_LEGAL_FRAMEWORK['LEY-21505-SAE']['principle'])}<br><em>Cita: Ley N° 21.505 / DS N° 70/2023 (Sistemas de Almacenamiento de Energía BESS)</em></li>",
        "    </ol>",
        "    <h4>Fuentes Regulatorias y Enlaces Oficiales:</h4>",
        "    <ul>",
    ])

    for src in CHILEAN_REGULATORY_SOURCES:
        src_esc = html.escape(src)
        out.append(f"      <li><a href=\"{src_esc}\" target=\"_blank\" rel=\"noreferrer\">{src_esc}</a></li>")

    out.extend([
        "    </ul>",
        "    <div class=\"disclaimer-box\">",
        f"      <strong>Estado de Cumplimiento Legal: <code>{html.escape(LEGAL_DISCLAIMER_STATUS)}</code></strong><br>",
        f"      {html.escape(LEGAL_DISCLAIMER_TEXT)}",
        "    </div>",
        "  </section>",
        "</div>",
        "</body>",
        "</html>",
    ])

    return "\n".join(out)


def render_session_report(session: Any, fmt: str = "md") -> str:
    """Render a comprehensive RIO audit session report in Markdown or HTML.

    Parameters
    ----------
    session : Any
        LiveSession instance or session-like dictionary containing Live Ops state.
    fmt : str, default="md"
        Desired output format: "md" (Markdown) or "html" (Printable HTML).

    Returns
    -------
    str
        Rendered report document.
    """
    ctx = _extract_report_context(session)
    fmt_clean = fmt.strip().lower()

    if fmt_clean in ("md", "markdown"):
        return _render_markdown(ctx)
    if fmt_clean in ("html", "htm"):
        return _render_html(ctx)

    raise ValueError(f"Formato no soportado: {fmt!r}. Formatos válidos: 'md', 'html'.")
