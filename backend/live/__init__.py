"""GridPilot Live Ops package.

Contains configuration guards, provider verification, and the live catalog.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from backend.live.catalog import build_catalog

_REPO_ROOT = Path(__file__).resolve().parents[2]
if "pytest" not in sys.modules and "PYTEST_CURRENT_TEST" not in os.environ:
    for _env_file in (_REPO_ROOT / ".env.local", _REPO_ROOT / ".env"):
        if _env_file.is_file():
            for _line in _env_file.read_text(encoding="utf-8").splitlines():
                _s = _line.strip()
                if not _s or _s.startswith("#") or "=" not in _s:
                    continue
                _k, _v = _s.split("=", 1)
                _k = _k.strip()
                _v = _v.strip().strip('"').strip("'")
                if _k and _v:
                    os.environ.setdefault(_k, _v)


def gemini_configured() -> bool:
    return bool((os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip())


def verified_provider_metadata(provider: object) -> bool:
    if not isinstance(provider, dict):
        return False
    response_id = provider.get("response_id")
    model = provider.get("model")
    return (
        provider.get("provider") == "google"
        and isinstance(model, str)
        and bool(model.strip())
        and isinstance(response_id, str)
        and bool(response_id.strip())
        # Current agent creates these hashes locally without contacting Google;
        # its REST path also synthesizes an ID if the API omits responseId.
        and not response_id.startswith(("resp-argon-", "resp-google-"))
    )


class MissingGeminiCredentials(Exception):
    """Typed configuration failure; no provider request has been attempted."""


__all__ = [
    "MissingGeminiCredentials",
    "build_catalog",
    "gemini_configured",
    "verified_provider_metadata",
]
