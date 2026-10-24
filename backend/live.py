"""Fail closed on missing credentials and known local Gemini impersonations.

Metadata is an adapter attestation, not independent proof of a provider call.
Real end-to-end release still requires observing a successful Google request.
"""

import os


def gemini_configured():
    return bool((os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip())


def verified_provider_metadata(provider):
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
