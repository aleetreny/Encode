"""Unit tests for GridPilot Live Ops RIO Report Generator (`backend/live/report.py`)."""

from __future__ import annotations

import asyncio
import pytest

from backend.live.engine import LiveSession
from backend.live.report import render_session_report


def test_live_session_report_generation_with_veto():
    """Test RIO report generation with operator apply followed by jury disruption and operator veto."""
    async def _run():
        session_id = "ses-rio-audit-001"
        session = LiveSession(session_id=session_id)

        # 1. Trigger operator disruption on gas_centro and apply an option
        disrupt_res1 = await session.disrupt("gas_centro", wait_for_options=True)
        inc_id1 = disrupt_res1["incident_id"]
        await session.decide(inc_id1, None, "apply", by="operator")

        # 2. Enable autonomy and trigger jury disruption on L3
        await session.set_autonomy(True)
        disrupt_res2 = await session.disrupt(
            "L3",
            source="jury",
            jury_name="Jurado Test",
            wait_for_options=True,
        )
        inc_id2 = disrupt_res2["incident_id"]

        # 3. Operator vetoes autonomous recommendation
        await session.decide(inc_id2, None, "veto", by="operator")

        # Render reports
        report_md = render_session_report(session, "md")
        report_html = render_session_report(session, "html")

        assert isinstance(report_md, str) and len(report_md) > 500
        assert isinstance(report_html, str) and len(report_html) > 500

        for rep in (report_md, report_html):
            # Session ID and incident IDs
            assert session_id in rep
            assert inc_id1 in rep
            assert inc_id2 in rep

            # Assets & Jury
            assert "gas_centro" in rep
            assert "L3" in rep
            assert "Jurado Test" in rep

            # Author attribution and action
            assert "operator" in rep or "Operador" in rep
            assert "veto" in rep or "Vetada" in rep

            # Validator results
            assert "passed" in rep or "PASS" in rep
            assert "max_residual_mw" in rep

            # Chilean legal citations
            assert "72°-1" in rep
            assert "32/2026" in rep
            assert "117 bis" in rep
            assert "NTSyCS" in rep
            assert "21.505" in rep

            # Provenance labels
            assert "synthetic" in rep
            assert "assumption" in rep
            assert "derived" in rep
            assert "1000" in rep

            # Slogan & Legal disclaimer status
            assert "Física real sobre una red simulada con forma chilena" in rep
            assert "legal_compliance_status = not_certified" in rep

    asyncio.run(_run())


def test_live_session_report_generation_with_autonomous_apply():
    """Test RIO report generation with autonomous decision (gemini_autonomous)."""
    async def _run():
        session_id = "ses-rio-auto-002"
        session = LiveSession(session_id=session_id)

        # Operator disruption on gas_centro
        disrupt_res1 = await session.disrupt("gas_centro", wait_for_options=True)
        inc_id1 = disrupt_res1["incident_id"]
        await session.decide(inc_id1, None, "apply", by="operator")

        # Autonomy enabled and jury disruption on L3
        await session.set_autonomy(True)
        disrupt_res2 = await session.disrupt(
            "L3",
            source="jury",
            jury_name="Jurado Test",
            wait_for_options=True,
        )
        inc_id2 = disrupt_res2["incident_id"]

        # Autonomous apply
        await session.decide(inc_id2, None, "apply", by="gemini_autonomous")

        report_md = render_session_report(session, "md")
        report_html = render_session_report(session, "html")

        for rep in (report_md, report_html):
            assert session_id in rep
            assert inc_id1 in rep
            assert inc_id2 in rep
            assert "gas_centro" in rep
            assert "L3" in rep
            assert "Jurado Test" in rep

            # Both operator and gemini_autonomous attributions present
            assert "operator" in rep or "Operador" in rep
            assert "gemini_autonomous" in rep or "Autónomo" in rep

            # Validator results
            assert "passed" in rep or "PASS" in rep
            assert "max_residual_mw" in rep

            # Citations
            assert "72°-1" in rep
            assert "32/2026" in rep
            assert "117 bis" in rep
            assert "NTSyCS" in rep
            assert "21.505" in rep

            # Provenance
            assert "synthetic" in rep
            assert "assumption" in rep
            assert "derived" in rep
            assert "1000" in rep

    asyncio.run(_run())


def test_live_session_report_empty_session():
    """Verify that an empty or freshly initialized session renders without error."""
    session = LiveSession("clean-session")
    md = render_session_report(session, "md")
    html_rep = render_session_report(session, "html")

    assert "clean-session" in md
    assert "clean-session" in html_rep
    assert "Física real sobre una red simulada con forma chilena" in md
    assert "legal_compliance_status = not_certified" in md
    assert "@media print" in html_rep


def test_invalid_format_raises_value_error():
    """Ensure invalid format parameter raises ValueError."""
    session = LiveSession("error-session")
    with pytest.raises(ValueError, match="Formato no soportado"):
        render_session_report(session, fmt="pdf")
