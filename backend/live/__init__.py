"""GridPilot Live Ops package.

Contains configuration guards, provider verification, and the live catalog.
"""

from __future__ import annotations

import os

from backend.live.catalog import build_catalog


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
