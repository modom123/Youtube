"""
User Scraper — discovers engagement targets by scraping public platform data.
Finds followers, commenters, and hashtag users for targeted engagement.
Uses platform APIs where available, falls back to public data.
"""
from __future__ import annotations
import re
import time
import requests
from dataclasses import dataclass
from typing import Optional

import config


@dataclass
class ScrapedUser:
    username: str
    platform: str
    profile_url: str = ""
    display_name: str = ""
    followers: int = 0
    bio: str = ""
    relevance_score: float = 0.5

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "platform": self.platform,
            "profile_url": self.profile_url,
            "display_name": self.display_name,
            "followers": self.followers,
            "notes": self.bio[:200] if self.bio else "",
            "relevance_score": self.relevance_score,
        }


def scrape_youtube_commenters(video_id: str, max_results: int = 50) -> list[ScrapedUser]:
    """Scrape commenters from a YouTube video via Data API."""
    if not config.YOUTUBE_CLIENT_ID:
        return []

    try:
        from publishers.youtube_publisher import _get_authenticated_service
        youtube = _get_authenticated_service()
        if not youtube:
            return []

        users = []
        request = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=min(max_results, 100),
            order="relevance",
        )
        response = request.execute()

        for item in response.get("items", []):
            snippet = item["snippet"]["topLevelComment"]["snippet"]
            channel_id = snippet.get("authorChannelId", {}).get("value", "")
            users.append(ScrapedUser(
                username=snippet.get("authorDisplayName", ""),
                platform="youtube",
                profile_url=f"https://youtube.com/channel/{channel_id}" if channel_id else "",
                display_name=snippet.get("authorDisplayName", ""),
                relevance_score=min(1.0, snippet.get("likeCount", 0) / 10 + 0.3),
            ))
        return users[:max_results]

    except Exception as e:
        print(f"[scraper] YouTube commenters error: {e}")
        return []


def scrape_youtube_channel_subscribers(channel_id: str, max_results: int = 50) -> list[ScrapedUser]:
    """Scrape recent subscribers/commenters of a YouTube channel."""
    if not config.YOUTUBE_CLIENT_ID:
        return []

    try:
        from publishers.youtube_publisher import _get_authenticated_service
        youtube = _get_authenticated_service()
        if not youtube:
            return []

        search_resp = youtube.search().list(
            part="snippet",
            channelId=channel_id,
            type="video",
            order="date",
            maxResults=5,
        ).execute()

        all_users = []
        seen = set()
        for video in search_resp.get("items", []):
            vid = video["id"].get("videoId", "")
            if not vid:
                continue
            commenters = scrape_youtube_commenters(vid, max_results=20)
            for user in commenters:
                if user.username not in seen:
                    seen.add(user.username)
                    all_users.append(user)

        return all_users[:max_results]

    except Exception as e:
        print(f"[scraper] YouTube channel subscribers error: {e}")
        return []


def scrape_twitter_followers(username: str, max_results: int = 50) -> list[ScrapedUser]:
    """Scrape followers of a Twitter user via API v2."""
    if not config.TWITTER_API_KEY:
        return []

    try:
        from requests_oauthlib import OAuth1
        auth = OAuth1(
            config.TWITTER_API_KEY, config.TWITTER_API_SECRET,
            config.TWITTER_ACCESS_TOKEN, config.TWITTER_ACCESS_TOKEN_SECRET,
        )

        user_resp = requests.get(
            f"https://api.twitter.com/2/users/by/username/{username}",
            auth=auth,
            params={"user.fields": "id"},
            timeout=15,
        )
        if not user_resp.ok:
            return []

        user_id = user_resp.json().get("data", {}).get("id")
        if not user_id:
            return []

        followers_resp = requests.get(
            f"https://api.twitter.com/2/users/{user_id}/followers",
            auth=auth,
            params={
                "max_results": min(max_results, 100),
                "user.fields": "name,username,public_metrics,description",
            },
            timeout=15,
        )
        if not followers_resp.ok:
            return []

        users = []
        for u in followers_resp.json().get("data", []):
            metrics = u.get("public_metrics", {})
            users.append(ScrapedUser(
                username=u.get("username", ""),
                platform="twitter",
                profile_url=f"https://twitter.com/{u.get('username', '')}",
                display_name=u.get("name", ""),
                followers=metrics.get("followers_count", 0),
                bio=u.get("description", ""),
                relevance_score=min(1.0, metrics.get("followers_count", 0) / 10000 + 0.2),
            ))
        return users[:max_results]

    except Exception as e:
        print(f"[scraper] Twitter followers error: {e}")
        return []


def scrape_twitter_hashtag(hashtag: str, max_results: int = 50) -> list[ScrapedUser]:
    """Find users posting with a specific hashtag on Twitter."""
    if not config.TWITTER_API_KEY:
        return []

    try:
        from requests_oauthlib import OAuth1
        auth = OAuth1(
            config.TWITTER_API_KEY, config.TWITTER_API_SECRET,
            config.TWITTER_ACCESS_TOKEN, config.TWITTER_ACCESS_TOKEN_SECRET,
        )

        tag = hashtag.lstrip("#")
        resp = requests.get(
            "https://api.twitter.com/2/tweets/search/recent",
            auth=auth,
            params={
                "query": f"#{tag} -is:retweet",
                "max_results": min(max_results, 100),
                "expansions": "author_id",
                "user.fields": "name,username,public_metrics,description",
            },
            timeout=15,
        )
        if not resp.ok:
            return []

        users = []
        seen = set()
        for u in resp.json().get("includes", {}).get("users", []):
            if u["username"] in seen:
                continue
            seen.add(u["username"])
            metrics = u.get("public_metrics", {})
            users.append(ScrapedUser(
                username=u.get("username", ""),
                platform="twitter",
                profile_url=f"https://twitter.com/{u.get('username', '')}",
                display_name=u.get("name", ""),
                followers=metrics.get("followers_count", 0),
                bio=u.get("description", ""),
                relevance_score=min(1.0, metrics.get("followers_count", 0) / 10000 + 0.3),
            ))
        return users[:max_results]

    except Exception as e:
        print(f"[scraper] Twitter hashtag error: {e}")
        return []


def scrape_instagram_commenters(media_id: str, max_results: int = 50) -> list[ScrapedUser]:
    """Scrape commenters on an Instagram post via Graph API."""
    if not config.INSTAGRAM_ACCESS_TOKEN:
        return []

    try:
        resp = requests.get(
            f"https://graph.facebook.com/v19.0/{media_id}/comments",
            params={
                "fields": "from{id,username},text,like_count",
                "limit": min(max_results, 50),
                "access_token": config.INSTAGRAM_ACCESS_TOKEN,
            },
            timeout=15,
        )
        if not resp.ok:
            return []

        users = []
        seen = set()
        for comment in resp.json().get("data", []):
            from_user = comment.get("from", {})
            username = from_user.get("username", "")
            if not username or username in seen:
                continue
            seen.add(username)
            users.append(ScrapedUser(
                username=username,
                platform="instagram",
                profile_url=f"https://instagram.com/{username}",
                relevance_score=min(1.0, comment.get("like_count", 0) / 5 + 0.3),
            ))
        return users[:max_results]

    except Exception as e:
        print(f"[scraper] Instagram commenters error: {e}")
        return []


def scrape_by_platform(
    platform: str,
    target: str,
    method: str = "commenters",
    max_results: int = 50,
) -> list[ScrapedUser]:
    """Unified scraping interface."""
    scrapers = {
        ("youtube", "commenters"): lambda: scrape_youtube_commenters(target, max_results),
        ("youtube", "channel"): lambda: scrape_youtube_channel_subscribers(target, max_results),
        ("twitter", "followers"): lambda: scrape_twitter_followers(target, max_results),
        ("twitter", "hashtag"): lambda: scrape_twitter_hashtag(target, max_results),
        ("instagram", "commenters"): lambda: scrape_instagram_commenters(target, max_results),
    }

    key = (platform, method)
    scraper = scrapers.get(key)
    if not scraper:
        print(f"[scraper] No scraper for {platform}/{method}")
        return []

    return scraper()
