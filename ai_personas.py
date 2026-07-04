"""
AI Personas & Avatars — create, manage, and use AI-powered virtual presenters.

Personas combine appearance, voice, personality, and speaking style into
reusable characters that present videos. They integrate with Higgsfield
(Seedance 2.0, Marketing Studio) for avatar video generation and with
the existing TTS pipeline for voiceover.
"""
import logging
from typing import Optional

import database as db

log = logging.getLogger("ai_personas")

# ── Preset Personas (available to all users) ─────────────────────────────────

PRESET_PERSONAS = [
    {
        "name": "Alex — The Tech Expert",
        "avatar_style": "professional",
        "gender": "male",
        "age_range": "28-35",
        "ethnicity": "diverse",
        "appearance_desc": "Clean-cut professional look, casual tech startup attire, friendly demeanor",
        "voice_id": "ErXwobaYiN019PkySvjV",
        "personality": "Knowledgeable, approachable, slightly nerdy, loves explaining complex topics simply",
        "speaking_style": "conversational, uses analogies, enthusiastic about tech",
        "niche": "technology",
        "model_preference": "seedance_2_0",
    },
    {
        "name": "Maya — The Storyteller",
        "avatar_style": "creative",
        "gender": "female",
        "age_range": "25-32",
        "ethnicity": "diverse",
        "appearance_desc": "Warm expressive face, creative casual style, natural and relatable",
        "voice_id": "21m00Tcm4TlvDq8ikWAM",
        "personality": "Empathetic, engaging, naturally curious, great at building emotional connections",
        "speaking_style": "narrative-driven, uses vivid language, draws the viewer in",
        "niche": "lifestyle",
        "model_preference": "seedance_2_0",
    },
    {
        "name": "James — The Authority",
        "avatar_style": "executive",
        "gender": "male",
        "age_range": "35-45",
        "ethnicity": "diverse",
        "appearance_desc": "Polished executive look, confident posture, business professional attire",
        "voice_id": "pNInz6obpgDQGcFmaJgB",
        "personality": "Authoritative, trustworthy, data-driven, inspires confidence",
        "speaking_style": "clear and direct, uses statistics, structured arguments",
        "niche": "business",
        "model_preference": "seedance_2_0",
    },
    {
        "name": "Sofia — The Coach",
        "avatar_style": "wellness",
        "gender": "female",
        "age_range": "28-38",
        "ethnicity": "diverse",
        "appearance_desc": "Approachable fitness/wellness look, athletic casual, bright and energetic",
        "voice_id": "XB0fDUnXU5powFXDhCwa",
        "personality": "Motivating, supportive, high-energy, makes people feel capable",
        "speaking_style": "encouraging, action-oriented, uses 'you' language, upbeat",
        "niche": "fitness",
        "model_preference": "seedance_2_0",
    },
    {
        "name": "Ryan — The Reviewer",
        "avatar_style": "casual",
        "gender": "male",
        "age_range": "22-30",
        "ethnicity": "diverse",
        "appearance_desc": "Casual Gen-Z style, relaxed and authentic, streetwear aesthetic",
        "voice_id": "TxGEqnHWrfWFTfGW9XjX",
        "personality": "Honest, witty, opinionated but fair, pop culture savvy",
        "speaking_style": "casual slang okay, quick-paced, uses humor, reaction-style",
        "niche": "entertainment",
        "model_preference": "marketing_studio_video",
    },
    {
        "name": "Dr. Chen — The Educator",
        "avatar_style": "academic",
        "gender": "female",
        "age_range": "35-50",
        "ethnicity": "diverse",
        "appearance_desc": "Professional academic look, smart casual, glasses optional, warm and knowledgeable",
        "voice_id": "oWAxZDx7w5VEj9dCyTzz",
        "personality": "Patient, thorough, breaks down complex topics, encouraging of learning",
        "speaking_style": "clear and structured, uses examples and analogies, measured pace",
        "niche": "education",
        "model_preference": "seedance_2_0",
    },
    {
        "name": "Marcus — The Hustler",
        "avatar_style": "entrepreneur",
        "gender": "male",
        "age_range": "25-35",
        "ethnicity": "diverse",
        "appearance_desc": "Sharp modern style, confident energy, startup founder aesthetic",
        "voice_id": "nPczCjzI2devNBz1zQrb",
        "personality": "Driven, passionate, no-nonsense, shares real numbers and results",
        "speaking_style": "fast-paced, urgent, uses FOMO, story-driven with proof points",
        "niche": "finance",
        "model_preference": "marketing_studio_video",
    },
    {
        "name": "Luna — The Creative",
        "avatar_style": "artistic",
        "gender": "female",
        "age_range": "22-30",
        "ethnicity": "diverse",
        "appearance_desc": "Artistic creative look, colorful style, expressive and unique",
        "voice_id": "ThT5KcBeYPX3keUQqHPh",
        "personality": "Imaginative, trend-aware, aesthetically driven, inspires creativity",
        "speaking_style": "visual language, poetic at times, enthusiastic about design and aesthetics",
        "niche": "creative",
        "model_preference": "seedance_2_0",
    },
]

# Models best suited for avatar/persona video generation
AVATAR_MODELS = {
    "seedance_2_0": {
        "name": "Seedance 2.0",
        "description": "Best for identity-consistent avatar videos. Maintains face/body across clips.",
        "strengths": ["Face consistency", "Natural motion", "Reference image support"],
        "cost_tier": "medium",
    },
    "marketing_studio_video": {
        "name": "Marketing Studio",
        "description": "Optimized for TikTok/Reels product ads with avatar presenters.",
        "strengths": ["Product showcase", "UGC style", "Short-form optimized"],
        "cost_tier": "medium",
    },
    "cinematic_studio_3_0": {
        "name": "Cinema Studio 3.0",
        "description": "Highest quality cinematic avatar. Best for long-form, premium content.",
        "strengths": ["Cinema quality", "Best visuals", "Dramatic compositions"],
        "cost_tier": "high",
    },
    "kling3_0": {
        "name": "Kling 3.0",
        "description": "Multi-shot with audio. Good balance of quality and speed.",
        "strengths": ["Multi-shot", "Built-in audio", "4K support"],
        "cost_tier": "medium",
    },
    "minimax_hailuo": {
        "name": "Minimax Hailuo",
        "description": "Natural physics and emotion. Good for talking-head content.",
        "strengths": ["Natural emotion", "Realistic physics", "Expressive faces"],
        "cost_tier": "low",
    },
}


def init_preset_personas():
    """Seed preset personas into the database (idempotent)."""
    existing = db.get_personas(user_id=0)
    existing_names = {p["name"] for p in existing if p.get("is_preset")}
    for preset in PRESET_PERSONAS:
        if preset["name"] not in existing_names:
            db.create_persona(user_id=0, is_preset=1, **preset)
            log.info("Created preset persona: %s", preset["name"])


def get_all_personas(user_id: int) -> list:
    """Get all personas available to a user (presets + custom)."""
    return db.get_personas(user_id)


def get_persona(persona_id: str, user_id: int) -> Optional[dict]:
    return db.get_persona(persona_id, user_id)


def create_custom_persona(user_id: int, name: str, **kwargs) -> str:
    """Create a custom persona for a user."""
    allowed_fields = {
        "avatar_style", "gender", "age_range", "ethnicity", "appearance_desc",
        "voice_id", "personality", "speaking_style", "niche", "reference_image",
        "model_preference",
    }
    filtered = {k: v for k, v in kwargs.items() if k in allowed_fields}
    return db.create_persona(user_id, name, **filtered)


def update_persona(persona_id: str, user_id: int, **kwargs) -> None:
    allowed_fields = {
        "name", "avatar_style", "gender", "age_range", "ethnicity",
        "appearance_desc", "voice_id", "personality", "speaking_style",
        "niche", "reference_image", "model_preference",
    }
    filtered = {k: v for k, v in kwargs.items() if k in allowed_fields}
    db.update_persona(persona_id, user_id, **filtered)


def delete_persona(persona_id: str, user_id: int) -> None:
    db.delete_persona(persona_id, user_id)


def build_avatar_prompt(persona: dict, scene_description: str,
                        format_type: str = "talking_head") -> str:
    """
    Build a video generation prompt that incorporates the persona's
    appearance and style for avatar video generation.
    """
    appearance = persona.get("appearance_desc", "professional looking person")
    gender = persona.get("gender", "person")
    age = persona.get("age_range", "adult")
    _style = persona.get("avatar_style", "professional")

    gender_word = {"male": "man", "female": "woman"}.get(gender, "person")

    format_templates = {
        "talking_head": (
            f"A {age} year old {gender_word}, {appearance}. "
            f"Looking directly at camera, speaking to the viewer with natural gestures. "
            f"Professional studio lighting, shallow depth of field, "
            f"upper body framing. {scene_description}"
        ),
        "presenter": (
            f"A {age} year old {gender_word}, {appearance}. "
            f"Standing and presenting, using hand gestures for emphasis. "
            f"Professional backdrop, full body or waist-up shot. "
            f"{scene_description}"
        ),
        "reaction": (
            f"A {age} year old {gender_word}, {appearance}. "
            f"Reacting expressively to something off-screen, "
            f"natural lighting, close-up face shot, authentic emotion. "
            f"{scene_description}"
        ),
        "ugc_style": (
            f"A {age} year old {gender_word}, {appearance}. "
            f"Selfie-style, handheld camera, casual home or outdoor setting, "
            f"natural lighting, speaking directly to camera as if filming a testimonial. "
            f"{scene_description}"
        ),
        "product_showcase": (
            f"A {age} year old {gender_word}, {appearance}. "
            f"Holding and presenting a product, enthusiastic expression, "
            f"clean background, product clearly visible, well-lit. "
            f"{scene_description}"
        ),
    }

    return format_templates.get(format_type, format_templates["talking_head"])


def build_persona_script_context(persona: dict) -> str:
    """
    Generate context instructions for the Narrative Designer agent
    so it writes scripts matching the persona's personality and speaking style.
    """
    return (
        f"PERSONA CONTEXT — Write this script as if spoken by: {persona.get('name', 'Host')}\n"
        f"Personality: {persona.get('personality', 'friendly')}\n"
        f"Speaking style: {persona.get('speaking_style', 'conversational')}\n"
        f"Niche expertise: {persona.get('niche', 'general')}\n"
        f"The narration should sound natural in this persona's voice. "
        f"Match their tone, vocabulary level, and energy."
    )


def get_avatar_models() -> dict:
    """Return available avatar-capable models with descriptions."""
    return AVATAR_MODELS


def get_recommended_model(persona: dict) -> str:
    """Get the recommended AI model for a persona."""
    pref = persona.get("model_preference", "seedance_2_0")
    if pref in AVATAR_MODELS:
        return pref
    return "seedance_2_0"


def generate_avatar_clips(
    persona: dict,
    scene_descriptions: list[str],
    output_dir: str,
    format_type: str = "talking_head",
    aspect_ratio: str = "16:9",
    max_clips: int = 5,
) -> list[str]:
    """
    Generate avatar video clips using the persona's preferred model.
    Returns list of file paths to generated clips.
    """
    from pathlib import Path
    from generators.ai_video_generator import generate_higgsville_clips

    model_id = get_recommended_model(persona)
    prompts = []
    for scene in scene_descriptions[:max_clips]:
        prompt = build_avatar_prompt(persona, scene, format_type)
        prompts.append(prompt)

    if not prompts:
        return []

    db.increment_persona_use(persona["id"])

    clips = generate_higgsville_clips(
        prompts=prompts,
        output_dir=Path(output_dir),
        model_id=model_id,
        aspect_ratio=aspect_ratio,
        duration=5,
    )

    return [str(c) for c in clips]
