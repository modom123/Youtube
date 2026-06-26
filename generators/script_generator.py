"""Script generation using Claude AI (default), DeepSeek (fast/cheap), or Gemini Flash (batch/budget)."""
import json
import re
import queue
import threading
from dataclasses import dataclass, field
from typing import Optional
import anthropic
import config


@dataclass
class ContentScript:
    title: str
    description: str
    hashtags: list
    narration: str
    sections: list
    keywords: list
    content_type: str
    estimated_duration: int  # seconds
    thumbnail_prompt: str
    seo_data: dict = field(default_factory=dict)


def _build_prompt(
    topic: str,
    content_type: str,
    target_duration: int,
    audience: str,
    research_context: str = "",
    tone: str = "",
    keywords: list = None,
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
        "countdown": (
            f"Create a COUNTDOWN / RANKED LIST video script (~{target_duration} seconds / {target_duration//60} minutes). "
            "This is a YouTube-style 'Top N' countdown video. Structure:\n"
            "1) HOOK (0–10s): Tease the #1 spot to create suspense. Example: 'Who scored more goals than any player in history? Stay till the end to find out.'\n"
            "2) INTRO (10–30s): Brief context — why this list matters, what criteria were used.\n"
            "3) COUNTDOWN ENTRIES: Cover EVERY ranked entry from the lowest rank to #1. "
            "For each entry, narrate: the rank number, the name, the key stat/achievement, and one fascinating fact. "
            "Use transitional phrases: 'Coming in at number X...', 'Next up at number Y...', 'But wait — at number Z...'\n"
            "4) #1 REVEAL (last 30s): Build tension before revealing. Make it feel earned.\n"
            "5) OUTRO (15s): Recap the top 3, invite comments ('Comment who you think was robbed'), subscribe CTA.\n\n"
            "CRITICAL: Use REAL names and REAL verified statistics from the research data or your training knowledge. "
            "Do NOT make up numbers. If you have the data, state the exact stat (e.g., '91 goals in a single calendar year'). "
            "Make each entry ~20–30 seconds of narration. The sections array must have one section per ranked entry plus intro/outro."
        ),
        "bumper": (
            "Create a 6-SECOND BUMPER AD script. This is a YouTube bumper ad — unskippable, 6 seconds maximum. "
            "Structure: One single punchy message + brand/product name. No fluff. Every word must earn its place. "
            "The narration should be 10–15 words maximum. One unforgettable visual moment."
        ),
        "commercial_15": (
            "Create a 15-SECOND AD script. Structure: "
            "0–3s: Instant pattern interrupt / problem statement, "
            "3–10s: Product/solution shown in action with key benefit, "
            "10–15s: CTA + brand name. "
            "No wasted words. Write for high energy, fast cuts. Narration ≤ 40 words."
        ),
        "commercial_30": (
            "Create a 30-SECOND TV/DIGITAL AD script. This is the gold standard commercial format. Structure: "
            "0–5s: Hook — emotional or surprising opening, "
            "5–20s: Story or demonstration — show the problem being solved, "
            "20–27s: Product benefit + social proof, "
            "27–30s: Strong CTA + brand name/tagline. "
            "Write cinematic scene descriptions in the sections. Narration ≤ 80 words."
        ),
        "commercial_60": (
            "Create a 60-SECOND BRAND STORY / long-form ad script. Structure: "
            "0–8s: Emotional hook — relatable problem or aspiration, "
            "8–35s: Story arc — character encounters problem, discovers solution, "
            "35–50s: Transformation — show the after state with product, "
            "50–57s: Key features + social proof (stats, testimonial), "
            "57–60s: CTA + brand name + tagline. "
            "This should feel cinematic and emotional, not salesy. Narration ≤ 160 words."
        ),
    }

    research_block = ""
    if research_context:
        research_block = f"""
VERIFIED RESEARCH DATA (use these REAL facts in the script — do NOT make up or change numbers/names):
{research_context}

IMPORTANT: Base the narration on the verified facts above. Include specific names, numbers, and data points from the research. The audience expects accurate, real information.
"""

    tone_block = f"\nTone & Style: {tone}" if tone else ""
    keywords_block = (
        f"\nSEO Keywords to weave naturally into the script: {', '.join(keywords)}"
        if keywords else ""
    )

    return f"""You are a professional social media content creator and scriptwriter with expertise in making factual content highly engaging.

Topic: {topic}
Content Type: {type_instructions.get(content_type, type_instructions["short"])}
Target Audience: {audience}{tone_block}{keywords_block}
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


def _parse_script_json(raw: str, content_type: str, target_duration: int, topic: str) -> "ContentScript":
    """Parse raw JSON string into a ContentScript dataclass."""
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    if json_match:
        raw = json_match.group(1)
    data = json.loads(raw)
    script = ContentScript(
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
    return script


def _attach_seo_data(script: "ContentScript") -> None:
    """Call Google Cloud NLP to extract SEO data from the narration and attach to script."""
    try:
        from generators.google_nlp import extract_seo_data
        seo = extract_seo_data(script.narration)
        if seo:
            script.seo_data = seo
            print(f"[script] SEO data attached: {len(seo.get('suggested_tags', []))} tags, sentiment={seo.get('sentiment')}")
    except Exception as e:
        print(f"[script] SEO extraction failed ({e})")


def generate_script(
    topic: str,
    content_type: str = "short",
    target_duration: int = 60,
    audience: str = "general public",
    custom_instructions: Optional[str] = None,
    research_context: str = "",
    ai_model: str = "claude",
    subscription_tier: str = "starter",
    tone: str = "",
    keywords: list = None,
) -> "ContentScript":
    """
    Generate a complete content script.

    ai_model: "claude" (default, premium quality) or "gemini" (fast & budget for batch).
    subscription_tier: routes free-tier users to cheaper models automatically.
    """
    keywords = keywords or []
    # Inject tone and keywords into custom_instructions so all model branches pick them up
    extra_parts = []
    if tone:
        extra_parts.append(f"Tone/voice: {tone}.")
    if keywords:
        extra_parts.append(f"Naturally weave these SEO keywords into the script: {', '.join(keywords)}.")
    if extra_parts:
        extra = " ".join(extra_parts)
        custom_instructions = (custom_instructions + "\n" + extra) if custom_instructions else extra

    if ai_model == "parallel":
        return generate_script_parallel(
            topic=topic, content_type=content_type, target_duration=target_duration,
            audience=audience, custom_instructions=custom_instructions,
            research_context=research_context, subscription_tier=subscription_tier,
        )
    if ai_model == "deepseek" and getattr(config, "DEEPSEEK_API_KEY", ""):
        script = _generate_script_deepseek(
            topic=topic,
            content_type=content_type,
            target_duration=target_duration,
            audience=audience,
            custom_instructions=custom_instructions,
            research_context=research_context,
        )
    elif ai_model == "qwen" and getattr(config, "QWEN_API_KEY", ""):
        script = _generate_script_qwen(
            topic=topic,
            content_type=content_type,
            target_duration=target_duration,
            audience=audience,
            custom_instructions=custom_instructions,
            research_context=research_context,
        )
    elif ai_model == "groq" and getattr(config, "GROQ_API_KEY", ""):
        script = _generate_script_groq(
            topic=topic,
            content_type=content_type,
            target_duration=target_duration,
            audience=audience,
            custom_instructions=custom_instructions,
            research_context=research_context,
        )
    elif ai_model == "openrouter" and getattr(config, "OPENROUTER_API_KEY", ""):
        script = _generate_script_openrouter(
            topic=topic,
            content_type=content_type,
            target_duration=target_duration,
            audience=audience,
            custom_instructions=custom_instructions,
            research_context=research_context,
        )
    elif ai_model == "gemini" and getattr(config, "GOOGLE_API_KEY", ""):
        script = generate_script_gemini(
            topic=topic,
            content_type=content_type,
            target_duration=target_duration,
            audience=audience,
            custom_instructions=custom_instructions,
            research_context=research_context,
        )
    else:
        script = _generate_script_claude(
            topic=topic,
            content_type=content_type,
            target_duration=target_duration,
            audience=audience,
            custom_instructions=custom_instructions,
            research_context=research_context,
            subscription_tier=subscription_tier,
        )

    # Attach NLP SEO data regardless of which model was used
    _attach_seo_data(script)
    return script


def generate_script_parallel(
    topic: str,
    content_type: str = "short",
    target_duration: int = 60,
    audience: str = "general public",
    custom_instructions: Optional[str] = None,
    research_context: str = "",
    models: list | None = None,
    subscription_tier: str = "starter",
) -> "ContentScript":
    """
    Fire multiple models in parallel and return the first valid result.
    Falls back to sequential if only one model is available.
    models: list of model names to race, e.g. ["deepseek", "groq", "claude"].
            If None, picks 2-3 best available models automatically.
    """
    if not models:
        from generators.ai_router import _available_models, _TYPE_PREFERENCE
        available = _available_models()
        candidates = _TYPE_PREFERENCE.get(content_type, ["claude", "deepseek", "gemini"])
        models = [m for m in candidates if m in available][:3]
    if len(models) <= 1:
        return generate_script(
            topic=topic, content_type=content_type, target_duration=target_duration,
            audience=audience, custom_instructions=custom_instructions,
            research_context=research_context, ai_model=models[0] if models else "claude",
            subscription_tier=subscription_tier,
        )

    result_queue: queue.Queue = queue.Queue()

    def _try_model(model_name: str) -> None:
        try:
            script = generate_script(
                topic=topic, content_type=content_type, target_duration=target_duration,
                audience=audience, custom_instructions=custom_instructions,
                research_context=research_context, ai_model=model_name,
                subscription_tier=subscription_tier,
            )
            result_queue.put((model_name, script))
            print(f"[parallel] {model_name} finished first")
        except Exception as e:
            print(f"[parallel] {model_name} failed: {e}")
            result_queue.put((model_name, None))

    threads = [threading.Thread(target=_try_model, args=(m,), daemon=True) for m in models]
    for t in threads:
        t.start()

    # Collect results; return first non-None (120s timeout per slot)
    SLOT_TIMEOUT = 130
    errors = 0
    for _ in models:
        try:
            model_name, script = result_queue.get(timeout=SLOT_TIMEOUT)
        except queue.Empty:
            break
        if script is not None:
            return script
        errors += 1

    raise RuntimeError(f"All {len(models)} parallel script models failed or timed out")


def _generate_script_claude(
    topic: str,
    content_type: str = "short",
    target_duration: int = 60,
    audience: str = "general public",
    custom_instructions: Optional[str] = None,
    research_context: str = "",
    subscription_tier: str = "starter",
) -> "ContentScript":
    """Generate a complete content script using Claude AI."""
    api_key = config.ANTHROPIC_API_KEY
    if not api_key or not api_key.startswith("sk-"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is missing or invalid (must start with 'sk-'). "
            "Set it in your .env or Render environment variables."
        )

    import httpx
    timeout = httpx.Timeout(80.0, connect=10.0)
    client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=0)

    prompt = _build_prompt(topic, content_type, target_duration, audience, research_context)
    if custom_instructions:
        prompt += f"\n\nAdditional instructions: {custom_instructions}"

    model = config.TIER_CLAUDE_MODEL.get(subscription_tier, "claude-sonnet-4-6")
    _long_formats = {"countdown", "long", "podcast", "commercial_60"}
    max_tok = 8192 if content_type in _long_formats else 4096
    print(f"[script] Calling Claude ({model}) for: {topic[:60]}...")
    try:
        message = client.messages.create(
            model=model,
            max_tokens=max_tok,
            messages=[{"role": "user", "content": prompt}],
        )
    except httpx.TimeoutException as e:
        raise RuntimeError(f"Claude API timed out after 55s: {e}")
    except anthropic.AuthenticationError as e:
        raise RuntimeError(f"Claude API key rejected: {e}")
    except anthropic.APIConnectionError as e:
        raise RuntimeError(f"Cannot reach Claude API: {e}")

    raw = message.content[0].text.strip()
    if not raw:
        raise RuntimeError(f"Claude returned empty response (stop_reason={message.stop_reason})")
    print(f"[script] Claude returned {len(raw)} chars, parsing JSON...")
    return _parse_script_json(raw, content_type, target_duration, topic)


def _generate_script_deepseek(
    topic: str,
    content_type: str = "short",
    target_duration: int = 60,
    audience: str = "general public",
    custom_instructions: Optional[str] = None,
    research_context: str = "",
) -> "ContentScript":
    """Generate script using DeepSeek-V3 (fast, cheap, OpenAI-compatible API)."""
    api_key = getattr(config, "DEEPSEEK_API_KEY", "")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY not set")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com", timeout=80.0, max_retries=0)

        prompt = _build_prompt(topic, content_type, target_duration, audience, research_context)
        if custom_instructions:
            prompt += f"\n\nAdditional instructions: {custom_instructions}"

        _long_formats = {"countdown", "long", "podcast", "commercial_60"}
        max_tok = 8192 if content_type in _long_formats else 4096
        response = client.chat.completions.create(
            model="deepseek-chat",
            max_tokens=max_tok,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        print(f"[script] DeepSeek-V3 generated script for: {topic}")
        return _parse_script_json(raw, content_type, target_duration, topic)
    except Exception as e:
        print(f"[script] DeepSeek generation failed ({e})")
        raise RuntimeError(f"DeepSeek generation failed: {e}")


def _generate_script_qwen(
    topic: str,
    content_type: str = "short",
    target_duration: int = 60,
    audience: str = "general public",
    custom_instructions: Optional[str] = None,
    research_context: str = "",
) -> "ContentScript":
    """Alibaba Qwen via DashScope OpenAI-compatible endpoint."""
    api_key = getattr(config, "QWEN_API_KEY", "")
    if not api_key:
        raise RuntimeError("QWEN_API_KEY not set")
    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            timeout=80.0,
            max_retries=0,
        )
        prompt = _build_prompt(topic, content_type, target_duration, audience, research_context)
        if custom_instructions:
            prompt += f"\n\nAdditional instructions: {custom_instructions}"

        _long_formats = {"countdown", "long", "podcast", "commercial_60"}
        model = "qwen-plus" if content_type in _long_formats else "qwen-turbo"
        response = client.chat.completions.create(
            model=model,
            max_tokens=8192 if content_type in _long_formats else 4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        print(f"[script] Qwen ({model}) generated script for: {topic}")
        return _parse_script_json(raw, content_type, target_duration, topic)
    except Exception as e:
        print(f"[script] Qwen generation failed ({e})")
        raise RuntimeError(f"Qwen generation failed: {e}")


def _generate_script_groq(
    topic: str,
    content_type: str = "short",
    target_duration: int = 60,
    audience: str = "general public",
    custom_instructions: Optional[str] = None,
    research_context: str = "",
) -> "ContentScript":
    """Groq ultra-fast inference (Llama 3.3 70B)."""
    api_key = getattr(config, "GROQ_API_KEY", "")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1", timeout=60.0, max_retries=0)
        prompt = _build_prompt(topic, content_type, target_duration, audience, research_context)
        if custom_instructions:
            prompt += f"\n\nAdditional instructions: {custom_instructions}"

        _long_formats = {"countdown", "long", "podcast", "commercial_60"}
        # Groq's largest context model
        model = "llama-3.3-70b-versatile"
        max_tok = 8000 if content_type in _long_formats else 4096
        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tok,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        print(f"[script] Groq ({model}) generated script for: {topic}")
        return _parse_script_json(raw, content_type, target_duration, topic)
    except Exception as e:
        print(f"[script] Groq generation failed ({e})")
        raise RuntimeError(f"Groq generation failed: {e}")


def _generate_script_openrouter(
    topic: str,
    content_type: str = "short",
    target_duration: int = 60,
    audience: str = "general public",
    custom_instructions: Optional[str] = None,
    research_context: str = "",
) -> "ContentScript":
    """OpenRouter — cycles through multiple free models, skips rate-limited ones."""
    api_key = getattr(config, "OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    from openai import OpenAI
    client = OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        timeout=90.0,
        max_retries=0,
        default_headers={"HTTP-Referer": "https://socialoptimizemachine.com"},
    )
    prompt = _build_prompt(topic, content_type, target_duration, audience, research_context)
    if custom_instructions:
        prompt += f"\n\nAdditional instructions: {custom_instructions}"

    _long_formats = {"countdown", "long", "podcast", "commercial_60"}
    max_tok = 8000 if content_type in _long_formats else 4096

    # Free models on OpenRouter — tried in order, skips rate-limited ones
    free_models = [
        "meta-llama/llama-3.1-8b-instruct:free",
        "mistralai/mistral-7b-instruct:free",
        "google/gemma-3-4b-it:free",
        "meta-llama/llama-3.3-70b-instruct:free",
        "deepseek/deepseek-r1-distill-llama-70b:free",
    ]
    last_err = None
    for model in free_models:
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=max_tok,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.choices[0].message.content.strip()
            print(f"[script] OpenRouter ({model}) generated script for: {topic}")
            return _parse_script_json(raw, content_type, target_duration, topic)
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "rate" in err_str.lower() or "rate-limited" in err_str.lower():
                print(f"[script] OpenRouter {model} rate-limited, trying next free model...")
                last_err = e
                continue
            # Non-rate-limit error — fail immediately
            raise RuntimeError(f"OpenRouter generation failed: {e}")

    raise RuntimeError(f"All OpenRouter free models rate-limited: {last_err}")


def generate_script_gemini(
    topic: str,
    content_type: str = "short",
    target_duration: int = 60,
    audience: str = "general public",
    custom_instructions: Optional[str] = None,
    research_context: str = "",
) -> "ContentScript":
    """
    Generate script using Gemini 2.0 Flash (cheaper, faster for batch jobs).
    """
    api_key = getattr(config, "GOOGLE_API_KEY", "")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set")

    try:
        from google import genai
        from google.genai import types as genai_types
        client = genai.Client(api_key=api_key)

        prompt = _build_prompt(topic, content_type, target_duration, audience, research_context)
        if custom_instructions:
            prompt += f"\n\nAdditional instructions: {custom_instructions}"

        print(f"[script] Calling Gemini Flash for: {topic[:60]}...")
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                http_options=genai_types.HttpOptions(timeout=80_000),
            ),
        )
        raw = response.text.strip()
        print(f"[script] Gemini 2.0 Flash generated script for: {topic}")
        return _parse_script_json(raw, content_type, target_duration, topic)
    except Exception as e:
        print(f"[script] Gemini script generation failed ({e}) — raising")
        raise RuntimeError(f"Gemini generation failed: {e}")


def generate_multi_platform_package(
    topic: str,
    platforms: list,
    audience: str = "general public",
    ai_model: str = "claude",
) -> dict:
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
            ai_model=ai_model,
        )
    return results
