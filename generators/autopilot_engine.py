"""
Autopilot — fully automated recurring content generation + posting.

Pure scheduling math (compute_next_run_at) plus the Claude call that picks a
fresh, non-repeating topic within a user's niche (generate_topic). The actual
job creation / video generation / post scheduling glue lives in app.py
alongside the other studio job runners, reusing the same pipeline as manual
/api/create — this module only owns the two pieces that are safe to unit
test without Flask or a DB connection.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import anthropic

import config

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def compute_next_run_at(days_of_week: list[int], post_time: str, lead_minutes: int,
                         now: datetime | None = None) -> datetime:
    """Return the next UTC datetime generation should KICK OFF — i.e. the next
    matching day/post_time minus lead_minutes — strictly after `now`.

    days_of_week: ints 0=Monday..6=Sunday. Empty list means every day.
    post_time: "HH:MM" in UTC (the time content should actually be posted).
    """
    now = now or datetime.utcnow()
    days = days_of_week or list(range(7))
    hour, minute = (int(p) for p in post_time.split(":"))

    for offset in range(8):  # a full week + 1, guarantees a match
        candidate_date = (now + timedelta(days=offset)).date()
        if candidate_date.weekday() not in days:
            continue
        post_dt = datetime.combine(candidate_date, datetime.min.time()).replace(hour=hour, minute=minute)
        run_dt = post_dt - timedelta(minutes=lead_minutes)
        if run_dt > now:
            return run_dt
    # Unreachable given the 8-day sweep covers every weekday at least once,
    # but fail safe rather than raise inside a background loop.
    return now + timedelta(days=1)


def generate_topic(niche: str, recent_topics: list[str], tier: str = "pro") -> str:
    """Ask Claude for one specific, non-repeating video topic for this niche."""
    client = _get_client()
    model = config.TIER_CLAUDE_MODEL.get(tier, "claude-sonnet-4-6")
    avoid = "\n".join(f"- {t}" for t in recent_topics[-20:]) or "(none yet — this is the first video)"
    prompt = (
        f"You generate a single specific, engaging short-form video topic for a content "
        f"channel in this niche: \"{niche}\".\n\n"
        f"Topics already covered recently — do NOT repeat these or anything too similar:\n{avoid}\n\n"
        "Reply with ONLY the topic/title as one plain line. No quotes, no numbering, no "
        "explanation. It must be a specific, hook-worthy angle, not a generic restatement "
        "of the niche itself."
    )
    resp = client.messages.create(
        model=model, max_tokens=100, messages=[{"role": "user", "content": prompt}]
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    return text.strip().strip('"').split("\n")[0][:200]
