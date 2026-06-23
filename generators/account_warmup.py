"""
Account Warmup — gradual activity ramp-up for new social accounts.
Prevents detection by slowly increasing engagement over days/weeks.
"""
from __future__ import annotations
import json
import math
from datetime import datetime, timedelta
from typing import Optional

import database as db


WARMUP_PROFILES = {
    "conservative": {
        "duration_days": 21,
        "start_pct": 0.05,
        "ramp_curve": "logarithmic",
        "actions_per_day_max": {
            "youtube":   {"like": 50, "comment": 20, "subscribe": 30},
            "tiktok":    {"like": 100, "comment": 30, "follow": 50},
            "instagram": {"like": 60, "comment": 20, "follow": 30},
            "twitter":   {"like": 50, "reply": 25, "follow": 30},
            "linkedin":  {"like": 30, "comment": 15, "connect": 20},
            "threads":   {"like": 50, "reply": 20, "follow": 30},
        },
    },
    "moderate": {
        "duration_days": 14,
        "start_pct": 0.10,
        "ramp_curve": "linear",
        "actions_per_day_max": {
            "youtube":   {"like": 50, "comment": 20, "subscribe": 30},
            "tiktok":    {"like": 100, "comment": 30, "follow": 50},
            "instagram": {"like": 60, "comment": 20, "follow": 30},
            "twitter":   {"like": 50, "reply": 25, "follow": 30},
            "linkedin":  {"like": 30, "comment": 15, "connect": 20},
            "threads":   {"like": 50, "reply": 20, "follow": 30},
        },
    },
    "aggressive": {
        "duration_days": 7,
        "start_pct": 0.20,
        "ramp_curve": "linear",
        "actions_per_day_max": {
            "youtube":   {"like": 50, "comment": 20, "subscribe": 30},
            "tiktok":    {"like": 100, "comment": 30, "follow": 50},
            "instagram": {"like": 60, "comment": 20, "follow": 30},
            "twitter":   {"like": 50, "reply": 25, "follow": 30},
            "linkedin":  {"like": 30, "comment": 15, "connect": 20},
            "threads":   {"like": 50, "reply": 20, "follow": 30},
        },
    },
}


def get_warmup_multiplier(
    account_created_at: str,
    profile: str = "conservative",
) -> float:
    """
    Returns a 0.0-1.0 multiplier for how much of the daily limit
    this account should use based on its age and warmup profile.
    """
    cfg = WARMUP_PROFILES.get(profile, WARMUP_PROFILES["conservative"])
    duration = cfg["duration_days"]
    start_pct = cfg["start_pct"]
    curve = cfg["ramp_curve"]

    try:
        created = datetime.fromisoformat(account_created_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return 1.0

    now = datetime.utcnow()
    if created.tzinfo:
        now = now.replace(tzinfo=created.tzinfo)

    age_days = (now - created).days

    if age_days >= duration:
        return 1.0

    if age_days < 0:
        return start_pct

    progress = age_days / duration

    if curve == "logarithmic":
        multiplier = start_pct + (1.0 - start_pct) * (math.log(1 + progress * 9) / math.log(10))
    elif curve == "exponential":
        multiplier = start_pct + (1.0 - start_pct) * (progress ** 2)
    else:
        multiplier = start_pct + (1.0 - start_pct) * progress

    return min(1.0, max(start_pct, multiplier))


def get_warmed_limits(
    platform: str,
    account_created_at: str,
    profile: str = "conservative",
) -> dict[str, int]:
    """Get the current daily limits adjusted for warmup stage."""
    cfg = WARMUP_PROFILES.get(profile, WARMUP_PROFILES["conservative"])
    max_limits = cfg["actions_per_day_max"].get(platform, {})
    multiplier = get_warmup_multiplier(account_created_at, profile)

    return {
        action: max(1, int(limit * multiplier))
        for action, limit in max_limits.items()
    }


def get_warmup_status(account_created_at: str, profile: str = "conservative") -> dict:
    """Get human-readable warmup status for an account."""
    cfg = WARMUP_PROFILES.get(profile, WARMUP_PROFILES["conservative"])
    duration = cfg["duration_days"]
    multiplier = get_warmup_multiplier(account_created_at, profile)

    try:
        created = datetime.fromisoformat(account_created_at.replace("Z", "+00:00"))
        age_days = (datetime.utcnow() - created).days
    except (ValueError, AttributeError):
        age_days = duration

    if age_days >= duration:
        phase = "fully_warmed"
        days_remaining = 0
    elif multiplier < 0.25:
        phase = "initial"
        days_remaining = duration - age_days
    elif multiplier < 0.50:
        phase = "early"
        days_remaining = duration - age_days
    elif multiplier < 0.75:
        phase = "mid"
        days_remaining = duration - age_days
    else:
        phase = "late"
        days_remaining = duration - age_days

    return {
        "phase": phase,
        "multiplier": round(multiplier, 3),
        "age_days": age_days,
        "duration_days": duration,
        "days_remaining": max(0, days_remaining),
        "pct_complete": min(100, int(age_days / duration * 100)),
        "profile": profile,
    }


def should_rest(account_created_at: str, profile: str = "conservative") -> bool:
    """Check if the account should take a rest day (natural pattern)."""
    try:
        created = datetime.fromisoformat(account_created_at.replace("Z", "+00:00"))
        age_days = (datetime.utcnow() - created).days
    except (ValueError, AttributeError):
        return False

    if age_days < 3:
        return age_days % 2 == 1
    if age_days < 7:
        return age_days % 3 == 0

    return False
