"""
ElevenLabs account client — real subscription/quota info, used by Vivian's
finance agent to alert before the character quota runs out and narration
silently degrades to a lower-quality fallback voice.
"""
from __future__ import annotations

import requests

import config


def get_subscription_info() -> dict:
    """Real remaining-character quota for the configured ElevenLabs account,
    via the long-stable /v1/user/subscription endpoint."""
    if not config.ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured")

    resp = requests.get(
        "https://api.elevenlabs.io/v1/user/subscription",
        headers={"xi-api-key": config.ELEVENLABS_API_KEY},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "character_count": data.get("character_count", 0),
        "character_limit": data.get("character_limit", 0),
        "next_reset_unix": data.get("next_character_count_reset_unix"),
        "tier": data.get("tier", ""),
    }
