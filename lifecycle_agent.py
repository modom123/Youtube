"""
Lifecycle Agent — automated onboarding, checkout recovery, and retention flows.

Runs as a background thread, checking all users periodically and sending
contextual notifications via email + in-app based on where they are in
the customer journey.
"""
import threading
import time
import logging
from datetime import datetime, timedelta

import config
import database as db
from notifications import send_notification

log = logging.getLogger("lifecycle")

TRIAL_DURATION_DAYS = 14
CHECK_INTERVAL_SECONDS = 600  # 10 minutes


# ── Lifecycle email content ──────────────────────────────────────────────────

LIFECYCLE_MESSAGES = {
    "welcome": {
        "title": "Welcome to Social Optimize Machine!",
        "body": (
            "You're all set — 3 AI-generated videos per month, publish to 3 platforms, "
            "no credit card required. Head to the Create page to make your first video."
        ),
        "link": "/create",
    },
    "onboard_first_video": {
        "title": "Ready to create your first video?",
        "body": (
            "You signed up but haven't created a video yet. It only takes a few clicks — "
            "pick a topic and our 5-agent AI pipeline handles the rest: script, voiceover, "
            "stock media, thumbnail, and assembly."
        ),
        "link": "/create",
    },
    "onboard_connect_platform": {
        "title": "Connect your channels to auto-publish",
        "body": (
            "Great job creating a video! Now connect YouTube, TikTok, or Instagram "
            "so your next video publishes automatically. No more downloading and re-uploading."
        ),
        "link": "/dashboard",
    },
    "trial_halfway": {
        "title": "Your free trial is halfway through",
        "body": (
            "You have 7 days left on your free trial. Upgrade now to unlock more videos, "
            "AI credits, and multi-platform publishing."
        ),
        "link": "/billing",
    },
    "trial_3days": {
        "title": "3 days left on your free trial",
        "body": (
            "Your free trial ends in 3 days. Upgrade to Starter ($29.99/mo) to keep creating — "
            "you'll get 15 videos/month, 150 AI credits, 8 platforms, and full studio access."
        ),
        "link": "/billing",
    },
    "trial_1day": {
        "title": "Last day of your free trial!",
        "body": (
            "Your trial ends tomorrow. Don't lose your creative momentum — "
            "upgrade now and your usage resets immediately with your new plan's limits."
        ),
        "link": "/billing",
    },
    "trial_expired": {
        "title": "Your free trial has ended",
        "body": (
            "Your 14-day trial is over, but your account is still here. "
            "Upgrade to any plan to pick up right where you left off. "
            "All your videos and settings are waiting for you."
        ),
        "link": "/billing",
    },
    "checkout_abandoned": {
        "title": "You didn't finish checking out",
        "body": (
            "Looks like you started upgrading but didn't finish. "
            "No worries — your spot is still open. Click below to pick up where you left off."
        ),
        "link": "/billing",
    },
    "inactive_7d": {
        "title": "We miss you! Your AI video studio is waiting",
        "body": (
            "It's been a week since your last visit. Your content calendar is empty — "
            "come back and create something. Trending topics are updated daily."
        ),
        "link": "/create",
    },
    "inactive_30d": {
        "title": "Still there? Your account is ready when you are",
        "body": (
            "It's been a month since you logged in. We've added new features — "
            "batch video creation, multi-language dubbing, and more AI video models. "
            "Come take a look."
        ),
        "link": "/dashboard",
    },
    "usage_75pct": {
        "title": "You're at 75% of your monthly video limit",
        "body": (
            "You've used most of your videos for this month. "
            "Consider upgrading to get more capacity before you hit the limit."
        ),
        "link": "/billing",
    },
    "upgrade_thankyou": {
        "title": "Welcome to {tier}! Here's what's new",
        "body": (
            "Thanks for upgrading! Your new plan includes {features}. "
            "Your usage has been reset so you can start creating right away."
        ),
        "link": "/create",
    },
}


def _send_lifecycle(user_id: int, event_key: str, extra_data: dict = None):
    if db.has_lifecycle_event(user_id, event_key):
        return False
    msg = LIFECYCLE_MESSAGES.get(event_key)
    if not msg:
        return False
    title = msg["title"]
    body = msg["body"]
    if extra_data:
        title = title.format_map(extra_data)
        body = body.format_map(extra_data)
    send_notification(user_id, f"lifecycle_{event_key}", {
        "title": title,
        "body": body,
        "link": msg["link"],
    })
    db.record_lifecycle_event(user_id, event_key)
    log.info("Sent lifecycle event '%s' to user %d", event_key, user_id)
    return True


# ── Lifecycle checks ─────────────────────────────────────────────────────────

def _check_onboarding(user):
    user_id = user["id"]
    created = datetime.fromisoformat(user["created_at"])
    hours_since_signup = (datetime.now() - created).total_seconds() / 3600

    _send_lifecycle(user_id, "welcome")

    if hours_since_signup >= 24 and user.get("completed_jobs", 0) == 0:
        _send_lifecycle(user_id, "onboard_first_video")

    if (user.get("completed_jobs", 0) >= 1
            and user.get("connected_platforms", 0) == 0
            and hours_since_signup >= 2):
        _send_lifecycle(user_id, "onboard_connect_platform")


def _check_trial(user):
    if user.get("subscription_tier") != "free":
        return
    user_id = user["id"]
    trial_end_str = user.get("trial_ends_at")
    if not trial_end_str:
        return

    trial_end = datetime.fromisoformat(trial_end_str)
    now = datetime.now()
    days_left = (trial_end - now).days

    if days_left <= 7 and days_left > 3:
        _send_lifecycle(user_id, "trial_halfway")
    elif days_left <= 3 and days_left > 1:
        _send_lifecycle(user_id, "trial_3days")
    elif days_left <= 1 and days_left >= 0:
        _send_lifecycle(user_id, "trial_1day")
    elif days_left < 0:
        _send_lifecycle(user_id, "trial_expired")


def _check_abandoned_checkouts():
    abandoned = db.get_abandoned_checkouts(minutes_ago=30)
    for event in abandoned:
        user_id = event["user_id"]
        db.mark_checkout_abandoned(event["id"])
        _send_lifecycle(user_id, "checkout_abandoned")


def _check_inactive(user):
    user_id = user["id"]
    last_active = user.get("last_active_at")
    if not last_active:
        last_active = user.get("created_at")
    if not last_active:
        return

    last_dt = datetime.fromisoformat(last_active)
    days_inactive = (datetime.now() - last_dt).days

    if days_inactive >= 30:
        _send_lifecycle(user_id, "inactive_30d")
    elif days_inactive >= 7:
        _send_lifecycle(user_id, "inactive_7d")


def _check_usage(user):
    if user.get("subscription_tier") == "free":
        return
    user_id = user["id"]
    tier = config.TIERS.get(user.get("subscription_tier"), config.TIERS["free"])
    limit = tier["videos_per_month"]
    if limit <= 0:
        return
    used = user.get("videos_used", 0)
    if used >= int(limit * 0.75) and used < limit:
        _send_lifecycle(user_id, "usage_75pct")


def run_lifecycle_cycle():
    try:
        users = db.get_users_for_lifecycle()
        for user in users:
            try:
                _check_onboarding(user)
                _check_trial(user)
                _check_inactive(user)
                _check_usage(user)
            except Exception as e:
                log.warning("Lifecycle error for user %d: %s", user["id"], e)

        _check_abandoned_checkouts()
    except Exception as e:
        log.error("Lifecycle cycle failed: %s", e)


def _lifecycle_loop():
    log.info("Lifecycle agent started (interval=%ds)", CHECK_INTERVAL_SECONDS)
    while True:
        run_lifecycle_cycle()
        time.sleep(CHECK_INTERVAL_SECONDS)


def start_lifecycle_agent():
    t = threading.Thread(target=_lifecycle_loop, daemon=True, name="lifecycle-agent")
    t.start()
    return t


# ── Triggered events (called from other modules) ────────────────────────────

def on_user_registered(user_id: int):
    trial_end = (datetime.now() + timedelta(days=TRIAL_DURATION_DAYS)).isoformat()
    db.update_user(user_id, trial_ends_at=trial_end)
    db.upsert_onboarding(user_id, welcome_seen=1)
    _send_lifecycle(user_id, "welcome")


def on_checkout_started(user_id: int, tier: str, stripe_session_id: str = None):
    db.create_checkout_event(user_id, tier, stripe_session_id)


def on_checkout_completed(user_id: int, tier: str):
    db.complete_checkout_event(user_id, tier)
    db.upsert_onboarding(user_id, upgraded=1)
    tier_info = config.TIERS.get(tier, {})
    features = ", ".join(tier_info.get("features", []))
    _send_lifecycle(user_id, "upgrade_thankyou", {
        "tier": tier_info.get("label", tier.title()),
        "features": features,
    })


def on_first_video_created(user_id: int):
    db.upsert_onboarding(user_id, first_video_created=1)


def on_platform_connected(user_id: int):
    db.upsert_onboarding(user_id, platform_connected=1)


def on_first_publish(user_id: int):
    db.upsert_onboarding(user_id, first_publish=1)
