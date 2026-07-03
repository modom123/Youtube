"""Autopilot — hands-off channel operation.

Each autopilot channel describes a niche, cadence, format, and platform set.
On cadence, the autopilot picks a fresh topic (trends + RSS + what already
performs on this account), creates a normal generation job, and lets the
existing pipeline generate and publish it. The result: a channel that posts
on schedule and gets smarter as analytics accumulate.
"""
import json
from datetime import datetime, timedelta

import config
import database as db
from utils import logger


def _trend_candidates(niche: str) -> list:
    try:
        from generators.google_trends import get_trending_topics
        data = get_trending_topics(niche) or {}
        return (data.get("trending_up") or []) + (data.get("top_queries") or [])
    except Exception:
        return []


def _rss_candidates(rss_url: str) -> list:
    if not rss_url:
        return []
    try:
        from generators.rss_monitor import RSSMonitor
        mon = RSSMonitor()
        mon.add_feed(rss_url)
        items = mon.fetch_all()
        return [item.title for item in items[:15] if getattr(item, "title", "")]
    except Exception:
        return []


def _insight_topics(user_id: int) -> list:
    try:
        from generators.performance_insights import compute_insights
        return (compute_insights(user_id) or {}).get("winning_topics", [])
    except Exception:
        return []


def _dedupe_against_recent(candidates: list, recent_topics: list) -> list:
    recent_lower = [t.lower() for t in recent_topics]

    def is_fresh(c: str) -> bool:
        cl = c.lower().strip()
        if not cl or len(cl) < 4:
            return False
        return not any(cl in r or r in cl for r in recent_lower)

    seen = set()
    fresh = []
    for c in candidates:
        cl = c.lower().strip()
        if is_fresh(c) and cl not in seen:
            seen.add(cl)
            fresh.append(c.strip())
    return fresh


def _refine_topic_with_ai(channel: dict, candidates: list, recent_topics: list) -> str:
    """Turn raw signals into one compelling video topic via Claude. Returns ""
    on any failure so callers can fall back."""
    if not config.ANTHROPIC_API_KEY:
        return ""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, timeout=60, max_retries=1)
        winning = _insight_topics(channel["user_id"])
        prompt = (
            f"You run a {channel['format']} video channel in the niche: {channel['niche']}.\n"
            f"Audience: {channel.get('audience') or 'general public'}.\n"
            + (f"Trending signals right now: {', '.join(candidates[:12])}.\n" if candidates else "")
            + (f"Topics that historically perform well on this channel: {', '.join(winning)}.\n" if winning else "")
            + (f"Recently covered (do NOT repeat): {', '.join(recent_topics[:15])}.\n" if recent_topics else "")
            + "Propose ONE specific, compelling video topic for today. "
              "Reply with the topic title only — no quotes, no explanation."
        )
        response = client.messages.create(
            model=getattr(config, "AUTOPILOT_TOPIC_MODEL", None) or "claude-opus-4-8",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "refusal":
            return ""
        text = next((b.text for b in response.content if b.type == "text"), "")
        topic = text.strip().strip('"').splitlines()[0].strip() if text.strip() else ""
        return topic[:200]
    except Exception as e:
        logger.warn(f"[autopilot] AI topic refinement failed: {e}")
        return ""


def pick_topic(channel: dict) -> str:
    """Pick the next topic for an autopilot channel. Returns "" if no fresh
    topic could be found."""
    recent = db.get_recent_job_topics(channel["user_id"])
    source = channel.get("topic_source") or "auto"

    candidates = []
    if source in ("auto", "rss"):
        candidates += _rss_candidates(channel.get("rss_url") or "")
    if source in ("auto", "trends"):
        candidates += _trend_candidates(channel["niche"])

    fresh = _dedupe_against_recent(candidates, recent)

    # Let Claude turn raw signals into one strong topic (works even with no signals)
    topic = _refine_topic_with_ai(channel, fresh, recent)
    if topic:
        return topic
    if fresh:
        return f"{fresh[0]} — {channel['niche']}"
    return ""


def compute_next_run(channel: dict) -> str:
    hours = max(1, int(channel.get("cadence_hours") or 24))
    return (datetime.utcnow() + timedelta(hours=hours)).isoformat()


def build_job_params(channel: dict, topic: str, subscription_tier: str) -> dict:
    """Params matching what /api/create builds, so autopilot jobs run through
    the identical pipeline (script → media → assembly → publish)."""
    try:
        platforms = json.loads(channel.get("platforms") or "[]")
    except Exception:
        platforms = ["youtube"]
    return {
        "topic": topic,
        "format": channel.get("format") or "short",
        "platforms": platforms,
        "audience": channel.get("audience") or "general public",
        "voice": channel.get("voice") or config.DEFAULT_VOICE,
        "thumbnail_style": channel.get("style") or "fire",
        "privacy": channel.get("privacy") or "public",
        "custom_instructions": None,
        "dry_run": False,
        "cleanup": False,
        "skip_research": False,
        "ai_video_provider": "none",
        "higgsfield_model": "kling3_0",
        "podcast_name": topic,
        "episode_number": 1,
        "guest_name": "",
        "target_duration": None,
        "ad_format": "", "ad_brand": "", "ad_product": "", "ad_benefit": "",
        "ad_cta": "", "ad_style": "cinematic", "ad_platforms": [],
        "doc_style": "natgeo",
        "animation_style": "lego",
        "ai_model": "auto",
        "subscription_tier": subscription_tier,
        "tone": "",
        "keywords": [],
    }
