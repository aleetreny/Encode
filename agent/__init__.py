"""GridPilot Agent Module (`agent`) — Powered by Gemini 4 Argon (`gemini-4-argon`).

Autonomous AI National Grid Coordinator co-pilot for Chile's Sistema Eléctrico Nacional (SEN).
"""

from __future__ import annotations

from agent.gemini_client import (
    COMPANION_SUBAGENT_MODEL,
    DEFAULT_AGENT_MODEL,
    DEFAULT_THINKING_LEVEL,
    FORBIDDEN_ARGON_PARAMS,
    GEMINI_TOOL_DECLARATIONS,
    GeminiArgonClient,
    build_argon_config,
)
from agent.orchestrator import (
    AwaitableDict,
    GridPilotAgent,
    run_crisis_investigation,
    run_investigation,
)
from agent.regulatory import (
    CHILEAN_LEGAL_FRAMEWORK,
    build_regulatory_compliance_matrix,
    estimate_affected_households,
)
from agent.tools import REQUIRED_TOOL_NAMES, AgentToolkit, ToolTraceRecorder

__all__ = [
    "DEFAULT_AGENT_MODEL",
    "REQUIRED_TOOL_NAMES",
    "CHILEAN_LEGAL_FRAMEWORK",
    "AwaitableDict",
    "GeminiArgonClient",
    "GridPilotAgent",
    "AgentToolkit",
    "ToolTraceRecorder",
    "run_investigation",
    "run_crisis_investigation",
    "build_regulatory_compliance_matrix",
    "estimate_affected_households",
]
