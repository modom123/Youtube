"""
Engagement Engine — executes cross-platform engagement actions.
Uses platform APIs where available, Playwright browser automation as fallback.
Respects rate limits and spreads actions naturally across time windows.
"""
from __future__ import annotations
import json
import random
import time
from datetime import datetime, timedelta
from typing import Optional

import database as db


PLATFORM_RATE_LIMITS = {
    "youtube":   {"like": 50, "comment": 20, "subscribe": 30},
    "tiktok":    {"like": 100, "comment": 30, "follow": 50},
    "instagram": {"like": 60, "comment": 20, "follow": 30},
    "twitter":   {"like": 50, "reply": 25, "follow": 30, "retweet": 20},
    "linkedin":  {"like": 30, "comment": 15, "connect": 20},
    "threads":   {"like": 50, "reply": 20, "follow": 30},
}


def check_rate_limit(user_id: int, platform: str, action_type: str) -> tuple[bool, str]:
    limits = PLATFORM_RATE_LIMITS.get(platform, {})
    limit = limits.get(action_type, 50)
    today_count = db.get_daily_action_count(user_id)
    if today_count >= limit:
        return False, f"Daily {action_type} limit reached for {platform} ({limit}/day)"
    return True, ""


def queue_engagement_actions(
    user_id: int,
    campaign_id: str,
    actions: list[dict],
) -> list[int]:
    action_ids = []
    for action in actions:
        allowed, err = check_rate_limit(
            user_id, action["platform"], action["action_type"],
        )
        if not allowed:
            continue

        action_id = db.create_engagement_action(
            user_id=user_id,
            platform=action["platform"],
            action_type=action["action_type"],
            target_url=action.get("target_url"),
            target_username=action.get("target_username"),
            target_content_id=action.get("target_content_id"),
            comment_text=action.get("comment_text"),
            campaign_id=campaign_id,
            scheduled_at=action.get("scheduled_at"),
        )
        action_ids.append(action_id)
    return action_ids


def execute_action(action: dict) -> dict:
    """
    Execute a single engagement action.
    Returns {status, message} dict.
    """
    platform = action["platform"]
    action_type = action["action_type"]

    executors = {
        "youtube": _execute_youtube_action,
        "tiktok": _execute_tiktok_action,
        "instagram": _execute_instagram_action,
        "twitter": _execute_twitter_action,
        "linkedin": _execute_linkedin_action,
        "threads": _execute_threads_action,
    }

    executor = executors.get(platform)
    if not executor:
        return {"status": "error", "message": f"Unsupported platform: {platform}"}

    try:
        result = executor(action_type, action)
        db.update_engagement_action(
            action["id"],
            status=result["status"],
            executed_at=datetime.utcnow().isoformat(),
            error_msg=result.get("message", ""),
        )
        return result
    except Exception as e:
        db.update_engagement_action(
            action["id"],
            status="error",
            executed_at=datetime.utcnow().isoformat(),
            error_msg=str(e),
        )
        return {"status": "error", "message": str(e)}


def execute_pending_actions(user_id: int, campaign_id: str = None, batch_size: int = 10):
    """Execute a batch of pending actions with natural delays."""
    actions = db.get_engagement_actions(
        user_id, campaign_id=campaign_id, status="pending", limit=batch_size,
    )

    results = []
    for action in actions:
        result = execute_action(action)
        results.append({"action_id": action["id"], **result})

        delay = random.uniform(15, 45)
        time.sleep(delay)

    if campaign_id:
        completed = sum(1 for r in results if r["status"] == "completed")
        db.update_engagement_campaign(
            campaign_id,
            actions_today=db.get_daily_action_count(user_id, campaign_id),
            total_actions=(
                db.get_engagement_campaign(campaign_id, user_id) or {}
            ).get("total_actions", 0) + completed,
        )

    return results


def _execute_youtube_action(action_type: str, action: dict) -> dict:
    """Execute YouTube engagement via API."""
    import config

    if not config.YOUTUBE_CLIENT_ID:
        return {"status": "skipped", "message": "YouTube API not configured"}

    try:
        from publishers.youtube_publisher import _get_authenticated_service
        youtube = _get_authenticated_service()
        if not youtube:
            return {"status": "error", "message": "YouTube auth failed"}

        if action_type == "like":
            youtube.videos().rate(
                id=action.get("target_content_id", ""),
                rating="like",
            ).execute()
            return {"status": "completed", "message": "Liked video"}

        elif action_type == "comment":
            youtube.commentThreads().insert(
                part="snippet",
                body={
                    "snippet": {
                        "videoId": action.get("target_content_id", ""),
                        "topLevelComment": {
                            "snippet": {
                                "textOriginal": action.get("comment_text", ""),
                            }
                        },
                    }
                },
            ).execute()
            return {"status": "completed", "message": "Comment posted"}

        elif action_type == "subscribe":
            youtube.subscriptions().insert(
                part="snippet",
                body={
                    "snippet": {
                        "resourceId": {
                            "kind": "youtube#channel",
                            "channelId": action.get("target_content_id", ""),
                        }
                    }
                },
            ).execute()
            return {"status": "completed", "message": "Subscribed"}

        return {"status": "skipped", "message": f"Unsupported YouTube action: {action_type}"}

    except Exception as e:
        return {"status": "error", "message": f"YouTube API error: {e}"}


def _execute_tiktok_action(action_type: str, action: dict) -> dict:
    """TikTok engagement — API access limited, queue for manual or browser."""
    return {"status": "queued", "message": f"TikTok {action_type} queued for browser execution"}


def _execute_instagram_action(action_type: str, action: dict) -> dict:
    """Instagram engagement via Graph API (limited to business accounts)."""
    import config

    if not config.INSTAGRAM_ACCESS_TOKEN:
        return {"status": "skipped", "message": "Instagram API not configured"}

    if action_type == "comment" and action.get("target_content_id"):
        import requests
        resp = requests.post(
            f"https://graph.facebook.com/v19.0/{action['target_content_id']}/comments",
            params={
                "message": action.get("comment_text", ""),
                "access_token": config.INSTAGRAM_ACCESS_TOKEN,
            },
            timeout=30,
        )
        if resp.ok:
            return {"status": "completed", "message": "Instagram comment posted"}
        return {"status": "error", "message": f"Instagram API: {resp.text}"}

    return {"status": "queued", "message": f"Instagram {action_type} queued for browser execution"}


def _execute_twitter_action(action_type: str, action: dict) -> dict:
    """Twitter/X engagement via API v2."""
    import config
    if not config.TWITTER_API_KEY:
        return {"status": "skipped", "message": "Twitter API not configured"}

    try:
        from requests_oauthlib import OAuth1
        import requests

        auth = OAuth1(
            config.TWITTER_API_KEY,
            config.TWITTER_API_SECRET,
            config.TWITTER_ACCESS_TOKEN,
            config.TWITTER_ACCESS_TOKEN_SECRET,
        )

        if action_type == "like":
            resp = requests.post(
                "https://api.twitter.com/2/users/me/likes",
                auth=auth,
                json={"tweet_id": action.get("target_content_id", "")},
                timeout=30,
            )
            if resp.ok:
                return {"status": "completed", "message": "Tweet liked"}
            return {"status": "error", "message": f"Twitter API: {resp.text}"}

        elif action_type in ("reply", "comment"):
            resp = requests.post(
                "https://api.twitter.com/2/tweets",
                auth=auth,
                json={
                    "text": action.get("comment_text", ""),
                    "reply": {"in_reply_to_tweet_id": action.get("target_content_id", "")},
                },
                timeout=30,
            )
            if resp.ok:
                return {"status": "completed", "message": "Reply posted"}
            return {"status": "error", "message": f"Twitter API: {resp.text}"}

        elif action_type == "follow":
            resp = requests.post(
                "https://api.twitter.com/2/users/me/following",
                auth=auth,
                json={"target_user_id": action.get("target_content_id", "")},
                timeout=30,
            )
            if resp.ok:
                return {"status": "completed", "message": "Followed user"}
            return {"status": "error", "message": f"Twitter API: {resp.text}"}

        elif action_type == "retweet":
            resp = requests.post(
                "https://api.twitter.com/2/users/me/retweets",
                auth=auth,
                json={"tweet_id": action.get("target_content_id", "")},
                timeout=30,
            )
            if resp.ok:
                return {"status": "completed", "message": "Retweeted"}
            return {"status": "error", "message": f"Twitter API: {resp.text}"}

        return {"status": "skipped", "message": f"Unsupported Twitter action: {action_type}"}

    except Exception as e:
        return {"status": "error", "message": f"Twitter error: {e}"}


def _execute_linkedin_action(action_type: str, action: dict) -> dict:
    """LinkedIn engagement — limited API, queue for browser."""
    return {"status": "queued", "message": f"LinkedIn {action_type} queued for browser execution"}


def _execute_threads_action(action_type: str, action: dict) -> dict:
    """Threads engagement — limited API, queue for browser."""
    return {"status": "queued", "message": f"Threads {action_type} queued for browser execution"}


def generate_engagement_plan(user_id: int, campaign_id: str) -> Optional[dict]:
    """Use the Community Engineer agent to generate today's plan."""
    campaign = db.get_engagement_campaign(campaign_id, user_id)
    if not campaign:
        return None

    from generators.agents import CommunityEngineer

    targets = db.get_engagement_targets(user_id, campaign_id, engaged=False, limit=20)

    agent = CommunityEngineer()
    plan = agent.run(
        niche=campaign.get("target_niche", "general"),
        platforms=json.loads(campaign.get("platforms", "[]")),
        daily_budget=campaign.get("daily_limit", 50),
        existing_targets=[dict(t) for t in targets] if targets else None,
        audience_size="small",
    )

    actions_to_queue = []
    for a in plan.daily_actions:
        actions_to_queue.append({
            "platform": a.platform,
            "action_type": a.action_type,
            "target_username": a.target_username,
            "comment_text": a.comment_text,
            "scheduled_at": a.timing,
        })

    action_ids = queue_engagement_actions(user_id, campaign_id, actions_to_queue)

    return {
        "plan": plan.model_dump(),
        "queued_actions": len(action_ids),
        "total_planned": plan.total_actions,
    }
