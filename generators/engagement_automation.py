"""
Official-API engagement automation.

Scope (explicitly user-approved): only act on the user's OWN connected accounts,
using each platform's official, already-authorized API. No bot-driven follow/comment
on other people's content, no scraping, no fingerprint/anti-detect tricks. This is
the same boundary real platform automation tools live within (e.g. auto-replying to
comments on your own video, replying to your own DMs, following back people who
followed you).

Three capabilities, each independently toggleable per platform via automation_settings:
  - auto_reply_comments: reply to new comments on the user's own content
  - auto_reply_dms:       reply to new inbound DMs
  - follow_back:          follow back new followers

Currently implemented for platforms whose official API actually exposes these
endpoints to a third-party app: YouTube (comments) and Twitter/X (comments via
mentions, DMs, follow-back). Other connected platforms either don't expose a
general-purpose comment/DM/follow API to apps like this one (TikTok, LinkedIn,
Threads) or require business-tier scopes not yet requested (Instagram Messaging) —
those are reported as "not supported" rather than faked.
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from typing import Optional

import requests

import config
import database as db

DEFAULT_REPLY_TEMPLATE = "Thanks for watching! 🙌"
MAX_ACTIONS_PER_RUN = 10  # safety cap so a burst of comments doesn't fire a wall of replies at once


def _log_action(user_id, platform, action_type, target_content_id="", target_username="",
                 comment_text="", status="completed", error_msg=""):
    action_id = db.create_engagement_action(
        user_id=user_id, platform=platform, action_type=action_type,
        target_content_id=target_content_id, target_username=target_username,
        comment_text=comment_text, campaign_id=None,
    )
    db.update_engagement_action(
        action_id, status=status, executed_at=datetime.utcnow().isoformat(), error_msg=error_msg,
    )
    return action_id


# ── YouTube ───────────────────────────────────────────────────────────────────

def _youtube_service(account: dict):
    import google.oauth2.credentials
    import google.auth.transport.requests
    import googleapiclient.discovery

    creds = google.oauth2.credentials.Credentials(
        token=account["access_token"],
        refresh_token=account.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config.YOUTUBE_CLIENT_ID,
        client_secret=config.YOUTUBE_CLIENT_SECRET,
        scopes=config.YOUTUBE_SCOPES,
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(google.auth.transport.requests.Request())
        db.upsert_account(
            platform="youtube", username=account["username"], display_name=account.get("display_name"),
            avatar_url=account.get("avatar_url"), access_token=creds.token, refresh_token=creds.refresh_token,
            account_id=account.get("account_id"), followers=account.get("followers", 0),
            user_id=account.get("user_id"),
        )
    return googleapiclient.discovery.build("youtube", "v3", credentials=creds, cache_discovery=False)


def run_youtube_comment_automation(account: dict, settings: dict) -> int:
    """Reply to new top-level comments on the account's own videos. Returns count of replies sent."""
    yt = _youtube_service(account)
    resp = yt.commentThreads().list(
        part="snippet", allThreadsRelatedToChannelId=account["account_id"],
        order="time", maxResults=20, textFormat="plainText",
    ).execute()

    since = settings.get("last_comment_check")
    since_str = since.isoformat() if hasattr(since, "isoformat") else since
    template = settings.get("reply_template") or DEFAULT_REPLY_TEMPLATE

    replied = 0
    newest_seen = since_str
    for item in resp.get("items", []):
        top = item["snippet"]["topLevelComment"]["snippet"]
        published = top.get("publishedAt", "")
        if newest_seen is None or published > newest_seen:
            newest_seen = published
        if since_str and published <= since_str:
            continue
        if top.get("authorChannelId", {}).get("value") == account.get("account_id"):
            continue  # don't reply to ourselves
        if replied >= MAX_ACTIONS_PER_RUN:
            break
        comment_id = item["snippet"]["topLevelComment"]["id"]
        try:
            yt.comments().insert(
                part="snippet",
                body={"snippet": {"parentId": comment_id, "textOriginal": template}},
            ).execute()
            _log_action(account["user_id"], "youtube", "auto_reply_comment",
                        target_content_id=comment_id, target_username=top.get("authorDisplayName", ""),
                        comment_text=template, status="completed")
            replied += 1
        except Exception as e:
            _log_action(account["user_id"], "youtube", "auto_reply_comment",
                        target_content_id=comment_id, status="error", error_msg=str(e))

    db.upsert_automation_settings("youtube", last_comment_check=newest_seen or datetime.now(timezone.utc).isoformat())
    return replied


# ── Twitter / X ───────────────────────────────────────────────────────────────

def _twitter_headers(account: dict) -> dict:
    return {"Authorization": f"Bearer {account['access_token']}", "Content-Type": "application/json"}


def _twitter_refresh(account: dict) -> dict:
    resp = requests.post(
        "https://api.twitter.com/2/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": account.get("refresh_token", ""),
            "client_id": config.TWITTER_CLIENT_ID,
        },
        auth=(config.TWITTER_CLIENT_ID, config.TWITTER_CLIENT_SECRET),
        timeout=20,
    )
    resp.raise_for_status()
    tokens = resp.json()
    db.upsert_account(
        platform="twitter", username=account["username"], display_name=account.get("display_name"),
        avatar_url=account.get("avatar_url"), access_token=tokens["access_token"],
        refresh_token=tokens.get("refresh_token", account.get("refresh_token")),
        account_id=account.get("account_id"), followers=account.get("followers", 0),
        user_id=account.get("user_id"),
    )
    account["access_token"] = tokens["access_token"]
    return account


def _twitter_request(account: dict, method: str, url: str, **kwargs) -> requests.Response:
    resp = requests.request(method, url, headers=_twitter_headers(account), timeout=20, **kwargs)
    if resp.status_code == 401 and account.get("refresh_token"):
        account = _twitter_refresh(account)
        resp = requests.request(method, url, headers=_twitter_headers(account), timeout=20, **kwargs)
    return resp


def run_twitter_comment_automation(account: dict, settings: dict) -> int:
    """Reply to new @mentions (Twitter/X has no separate 'comment on own post' feed —
    replies to your tweets surface as mentions)."""
    me = _twitter_request(account, "GET", "https://api.twitter.com/2/users/me").json()
    user_id = me.get("data", {}).get("id")
    if not user_id:
        return 0

    since_id = settings.get("last_comment_check") or None
    params = {"max_results": 20}
    if isinstance(since_id, str) and since_id.isdigit():
        params["since_id"] = since_id

    resp = _twitter_request(account, "GET", f"https://api.twitter.com/2/users/{user_id}/mentions", params=params)
    if not resp.ok:
        _log_action(account["user_id"], "twitter", "auto_reply_comment", status="error", error_msg=resp.text[:300])
        return 0

    tweets = resp.json().get("data", [])
    template = settings.get("reply_template") or DEFAULT_REPLY_TEMPLATE
    replied = 0
    newest_id = since_id
    for tw in tweets:
        if replied >= MAX_ACTIONS_PER_RUN:
            break
        tweet_id = tw["id"]
        if newest_id is None or int(tweet_id) > int(newest_id):
            newest_id = tweet_id
        r = _twitter_request(account, "POST", "https://api.twitter.com/2/tweets", json={
            "text": template, "reply": {"in_reply_to_tweet_id": tweet_id},
        })
        if r.ok:
            _log_action(account["user_id"], "twitter", "auto_reply_comment",
                        target_content_id=tweet_id, comment_text=template, status="completed")
            replied += 1
        else:
            _log_action(account["user_id"], "twitter", "auto_reply_comment",
                        target_content_id=tweet_id, status="error", error_msg=r.text[:300])

    db.upsert_automation_settings("twitter", last_comment_check=newest_id)
    return replied


def run_twitter_dm_automation(account: dict, settings: dict) -> int:
    me = _twitter_request(account, "GET", "https://api.twitter.com/2/users/me").json()
    user_id = me.get("data", {}).get("id")
    if not user_id:
        return 0

    resp = _twitter_request(account, "GET", f"https://api.twitter.com/2/dm_events",
                             params={"max_results": 20, "dm_event.fields": "sender_id,created_at"})
    if not resp.ok:
        _log_action(account["user_id"], "twitter", "auto_reply_dm", status="error",
                    error_msg=f"DM read failed (needs dm.read scope — reconnect X account): {resp.text[:200]}")
        return 0

    since = settings.get("last_dm_check")
    since_str = since.isoformat() if hasattr(since, "isoformat") else since
    template = settings.get("reply_template") or "Thanks for the message — we'll get back to you soon!"
    events = resp.json().get("data", [])
    replied = 0
    newest = since_str
    for ev in events:
        created = ev.get("created_at", "")
        if newest is None or created > newest:
            newest = created
        if since_str and created <= since_str:
            continue
        if ev.get("sender_id") == user_id:
            continue  # our own outbound message
        if replied >= MAX_ACTIONS_PER_RUN:
            break
        sender = ev["sender_id"]
        r = _twitter_request(account, "POST", f"https://api.twitter.com/2/dm_conversations/with/{sender}/messages",
                              json={"text": template})
        if r.ok:
            _log_action(account["user_id"], "twitter", "auto_reply_dm",
                        target_username=sender, comment_text=template, status="completed")
            replied += 1
        else:
            _log_action(account["user_id"], "twitter", "auto_reply_dm",
                        target_username=sender, status="error", error_msg=r.text[:300])

    db.upsert_automation_settings("twitter", last_dm_check=newest or datetime.now(timezone.utc).isoformat())
    return replied


def run_twitter_follow_back_automation(account: dict, settings: dict) -> int:
    me = _twitter_request(account, "GET", "https://api.twitter.com/2/users/me").json()
    user_id = me.get("data", {}).get("id")
    if not user_id:
        return 0

    resp = _twitter_request(account, "GET", f"https://api.twitter.com/2/users/{user_id}/followers",
                             params={"max_results": 50})
    if not resp.ok:
        _log_action(account["user_id"], "twitter", "follow_back", status="error", error_msg=resp.text[:300])
        return 0

    followers = resp.json().get("data", [])
    known = set(json.loads(settings.get("known_follower_ids") or "[]"))
    new_followers = [f for f in followers if f["id"] not in known]

    followed = 0
    for f in new_followers[:MAX_ACTIONS_PER_RUN]:
        r = _twitter_request(account, "POST", f"https://api.twitter.com/2/users/{user_id}/following",
                              json={"target_user_id": f["id"]})
        if r.ok:
            _log_action(account["user_id"], "twitter", "follow_back",
                        target_username=f.get("username", f["id"]), status="completed")
            followed += 1
        known.add(f["id"])

    all_ids = list(known)[-500:]  # cap to avoid unbounded growth
    db.upsert_automation_settings("twitter", known_follower_ids=json.dumps(all_ids))
    return followed


# ── Dispatcher ────────────────────────────────────────────────────────────────

UNSUPPORTED = {
    "tiktok": "TikTok's public API doesn't expose comment/DM/follow management to third-party apps.",
    "linkedin": "LinkedIn's API doesn't expose general comment/DM/follow automation outside official partners.",
    "threads": "Threads API doesn't yet support comment replies or DMs for third-party apps.",
    "instagram": "Instagram comment auto-reply needs Business/Creator account + additional Graph API scopes not yet connected.",
    "facebook": "Facebook Page comment/DM automation needs additional Graph API scopes not yet connected.",
}

RUNNERS = {
    "youtube": {"auto_reply_comments": run_youtube_comment_automation},
    "twitter": {
        "auto_reply_comments": run_twitter_comment_automation,
        "auto_reply_dms": run_twitter_dm_automation,
        "follow_back": run_twitter_follow_back_automation,
    },
}


def run_all_active_automations() -> list[dict]:
    """Called by the background poller. Runs every enabled automation for every
    connected platform that supports it. Returns a list of per-platform run results."""
    results = []
    accounts_by_platform = {a["platform"]: a for a in db.get_accounts()}

    for settings in db.get_all_automation_settings():
        platform = settings["platform"]
        account = accounts_by_platform.get(platform)
        if not account or not account.get("access_token"):
            continue

        runners = RUNNERS.get(platform, {})
        for capability, runner in runners.items():
            if not settings.get(capability):
                continue
            try:
                count = runner(account, settings)
                results.append({"platform": platform, "capability": capability, "status": "ok", "count": count})
            except Exception as e:
                results.append({"platform": platform, "capability": capability, "status": "error", "error": str(e)})
    return results
