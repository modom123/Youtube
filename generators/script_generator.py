"""Script generation using Claude AI."""
import json
import re
from dataclasses import dataclass
from typing import Optional
import anthropic
import config


@dataclass
class ContentScript:
    title: str
    description: str
    hashtags: list[str]
    narration: str
    sections: list[dict]
    keywords: list[str]
    content_type: str
    estimated_duration: int  # seconds
    thumbnail_prompt: str


def _build_prompt(
    topic: str,
    content_type: str,
    target_duration: int,
    audience: str,
    research_context: str = "",
) -> str:
    type_instructions = {
        "short": f"Create a punchy, viral SHORT video script (~{target_duration} seconds). Hook in first 3 seconds. Fast-paced, engaging.",
        "long": f"Create a comprehensive LONG-FORM video script (~{target_duration} seconds / {target_duration//60} minutes). Educational and thorough.",
        "podcast": (
            f"Create a full PODCAST EPISODE script (~{target_duration} seconds / {target_duration//60} minutes). "
            "Write in a natural, conversational host voice. Structure: "
            "1) Attention-grabbing cold open / teaser (30s), "
            "2) Warm intro + topic overview (90s), "
            "3) Three to four meaty discussion chapters with transitions, "
            "4) Takeaways + listener CTA (60s), "
            "5) Outro sign-off (30s). "
            "Each chapter must have a distinct focus. Sections must reflect these chapters exactly."
        ),
        "reel": f"Create an Instagram REEL script (~{target_duration} seconds). Visually driven, trend-aware, highly shareable.",
    }

    research_block = ""
    if research_context:
        research_block = f"""
VERIFIED RESEARCH DATA (use these REAL facts in the script — do NOT make up or change numbers/names):
{research_context}

IMPORTANT: Base the narration on the verified facts above. Include specific names, numbers, and data points from the research. The audience expects accurate, real information.
"""

    return f"""You are a professional social media content creator and scriptwriter with expertise in making factual content highly engaging.

Topic: {topic}
Content Type: {type_instructions.get(content_type, type_instructions["short"])}
Target Audience: {audience}
{research_block}
Generate a complete content package. Return ONLY valid JSON in this exact structure:

{{
  "title": "Compelling SEO-optimized title (max 100 chars)",
  "description": "Full platform description with keywords (200-500 chars)",
  "hashtags": ["hashtag1", "hashtag2", ...],
  "narration": "The complete word-for-word narration script. Write naturally for speech. No stage directions here - pure spoken words only.",
  "sections": [
    {{"name": "Hook", "duration": 5, "visual_cue": "Description of what should appear on screen"}},
    {{"name": "Main Content", "duration": 30, "visual_cue": "Description of visuals"}},
    {{"name": "CTA", "duration": 5, "visual_cue": "Call to action visual"}}
  ],
  "keywords": ["keyword1", "keyword2", ...],
  "thumbnail_prompt": "Detailed image generation prompt for a compelling thumbnail. Include style, colors, elements.",
  "estimated_duration": {target_duration}
}}

Make it viral, engaging, and optimized for {content_type} format. The narration should be natural spoken language."""


def generate_script(
    topic: str,
    content_type: str = "short",
    target_duration: int = 60,
    audience: str = "general public",
    custom_instructions: Optional[str] = None,
    research_context: str = "",
) -> ContentScript:
    """Generate a complete content script using Claude, optionally grounded with research."""
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    prompt = _build_prompt(topic, content_type, target_duration, audience, research_context)
    if custom_instructions:
        prompt += f"\n\nAdditional instructions: {custom_instructions}"

    model = "claude-sonnet-4-6"
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()

    # Extract JSON even if wrapped in markdown code blocks
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    if json_match:
        raw = json_match.group(1)

    data = json.loads(raw)

    return ContentScript(
        title=data["title"],
        description=data["description"],
        hashtags=data.get("hashtags", []),
        narration=data["narration"],
        sections=data.get("sections", []),
        keywords=data.get("keywords", []),
        content_type=content_type,
        estimated_duration=data.get("estimated_duration", target_duration),
        thumbnail_prompt=data.get("thumbnail_prompt", f"Professional thumbnail for: {topic}"),
    )


def generate_multi_platform_package(
    topic: str,
    platforms: list[str],
    audience: str = "general public",
) -> dict[str, ContentScript]:
    """Generate optimized scripts for multiple platforms at once."""
    platform_config = {
        "youtube": {"type": "long", "duration": 480},
        "youtube_short": {"type": "short", "duration": 60},
        "tiktok": {"type": "short", "duration": 45},
        "instagram": {"type": "reel", "duration": 30},
        "podcast": {"type": "podcast", "duration": 600},
    }

    results = {}
    for platform in platforms:
        cfg = platform_config.get(platform, {"type": "short", "duration": 60})
        results[platform] = generate_script(
            topic=topic,
            content_type=cfg["type"],
            target_duration=cfg["duration"],
            audience=audience,
        )
    return results
