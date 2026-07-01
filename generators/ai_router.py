"""
AI Model Router — decides which script engine to use based on
content type, subscription tier, available API keys, and user preference.

Fallback chain per model:
  auto      → picks best available for the job
  deepseek  → deepseek → claude → gemini → groq
  qwen      → qwen → deepseek → claude
  groq      → groq → deepseek → claude
  gemini    → gemini → claude → deepseek
  claude    → claude → deepseek → gemini
"""
from __future__ import annotations
import config

# Which model is best for each content type (quality-first order)
_TYPE_PREFERENCE: dict[str, list[str]] = {
    # Speed-critical short formats: free models first
    "short":         ["groq", "openrouter", "deepseek", "gemini", "claude"],
    "reel":          ["groq", "openrouter", "deepseek", "gemini", "claude"],
    "bumper":        ["groq", "openrouter", "deepseek", "gemini", "claude"],
    "commercial_15": ["groq", "openrouter", "deepseek", "claude", "gemini"],
    # Quality-critical long formats: Claude first, free fallbacks
    "long":          ["claude", "groq", "openrouter", "deepseek", "gemini"],
    "podcast":       ["claude", "groq", "openrouter", "deepseek", "gemini"],
    "countdown":     ["claude", "groq", "openrouter", "deepseek", "gemini"],
    "commercial_30": ["claude", "groq", "openrouter", "deepseek", "gemini"],
    "commercial_60": ["claude", "groq", "openrouter", "deepseek", "gemini"],
}

# Fallback chain when a specific model is chosen but fails / key missing
_FALLBACK: dict[str, list[str]] = {
    "claude":      ["groq", "openrouter", "deepseek", "gemini", "qwen"],
    "deepseek":    ["groq", "openrouter", "claude",   "gemini", "qwen"],
    "qwen":        ["groq", "openrouter", "deepseek", "claude", "gemini"],
    "gemini":      ["groq", "openrouter", "claude",   "deepseek", "qwen"],
    "groq":        ["openrouter", "claude", "deepseek", "gemini", "qwen"],
    "openrouter":  ["groq", "claude", "deepseek", "gemini", "qwen"],
    "auto":        [],  # handled separately
}

# Free-tier always uses free models to keep costs at zero
_FREE_PREFERENCE = ["groq", "openrouter", "deepseek", "gemini", "claude"]


def _available_models() -> set[str]:
    """Return set of models whose API key is configured."""
    available = set()
    ak = getattr(config, "ANTHROPIC_API_KEY", "")
    if ak and ak.startswith("sk-"):
        available.add("claude")
    if getattr(config, "DEEPSEEK_API_KEY", ""):
        available.add("deepseek")
    if getattr(config, "QWEN_API_KEY", ""):
        available.add("qwen")
    if getattr(config, "GOOGLE_API_KEY", ""):
        available.add("gemini")
    if getattr(config, "GROQ_API_KEY", ""):
        available.add("groq")
    if getattr(config, "OPENROUTER_API_KEY", ""):
        available.add("openrouter")
    if not available:
        print("[router] WARNING: No valid API keys found! Set at least one in .env or Render env vars.")
        available.add("claude")
    return available


def route(
    content_type: str = "short",
    subscription_tier: str = "starter",
    user_preference: str = "auto",
) -> str:
    """
    Returns the model name to use for script generation.
    Respects user_preference, falls back intelligently if key is missing.
    """
    available = _available_models()

    # Parallel mode bypasses single-model routing
    if user_preference == "parallel":
        return "parallel"

    if user_preference == "auto":
        # Free tier always gets cheapest model
        if subscription_tier == "free":
            candidates = _FREE_PREFERENCE
        else:
            candidates = _TYPE_PREFERENCE.get(content_type, ["claude", "deepseek", "gemini"])
        for model in candidates:
            if model in available:
                return model
        return "claude"

    # User picked a specific model
    if user_preference in available:
        return user_preference

    # Key not set — walk the fallback chain
    for fallback in _FALLBACK.get(user_preference, []):
        if fallback in available:
            print(f"[router] {user_preference} key missing → falling back to {fallback}")
            return fallback

    return "claude"


def get_model_info() -> list[dict]:
    """Return display info for all models (for UI rendering)."""
    available = _available_models()
    return [
        {
            "id": "auto",
            "name": "Auto (Recommended)",
            "desc": "AI picks the best model for your content type",
            "badge": "smart",
            "available": True,
        },
        {
            "id": "parallel",
            "name": "Parallel Race",
            "desc": "Fires 2-3 models simultaneously — fastest valid result wins",
            "badge": "turbo",
            "available": len(_available_models()) >= 2,
        },
        {
            "id": "claude",
            "name": "Claude (Sonnet)",
            "desc": "Highest quality — best for long-form & commercials",
            "badge": "quality",
            "available": "claude" in available,
        },
        {
            "id": "deepseek",
            "name": "DeepSeek-V3",
            "desc": "Fast Chinese model — 3-5× faster, fraction of the cost",
            "badge": "fast",
            "available": "deepseek" in available,
        },
        {
            "id": "qwen",
            "name": "Qwen (Alibaba)",
            "desc": "Alibaba's flagship — strong multilingual & long-context",
            "badge": "multilingual",
            "available": "qwen" in available,
        },
        {
            "id": "groq",
            "name": "Groq (Llama 3.3)",
            "desc": "Ultra-fast inference — near-instant for short scripts",
            "badge": "ultra-fast",
            "available": "groq" in available,
        },
        {
            "id": "openrouter",
            "name": "OpenRouter (Free)",
            "desc": "Free Llama 3.3 70B via OpenRouter — no cost, no billing",
            "badge": "free",
            "available": "openrouter" in available,
        },
        {
            "id": "gemini",
            "name": "Gemini Flash",
            "desc": "Google's fast model — good for batch generation",
            "badge": "batch",
            "available": "gemini" in available,
        },
    ]
