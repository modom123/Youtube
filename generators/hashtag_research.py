"""
Hashtag Research — volume, difficulty, trending analysis.
Discovers optimal hashtags for reach and engagement across platforms.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

import requests
import config


@dataclass
class HashtagResult:
    tag: str
    platform: str
    volume: int = 0
    difficulty: float = 0.0  # 0-1, lower = easier to rank
    trending: bool = False
    related_tags: list[str] = field(default_factory=list)
    category: str = ""
    score: float = 0.0  # computed: high volume + low difficulty = high score

    def compute_score(self) -> float:
        vol_score = min(1.0, self.volume / 1_000_000) if self.volume > 0 else 0.1
        diff_score = 1.0 - self.difficulty
        trend_bonus = 0.2 if self.trending else 0.0
        self.score = round((vol_score * 0.4 + diff_score * 0.4 + trend_bonus) * 10, 2)
        return self.score


def research_hashtags_youtube(
    topic: str,
    max_results: int = 20,
) -> list[HashtagResult]:
    """Research hashtags via YouTube search suggestions and video tags."""
    if not config.YOUTUBE_CLIENT_ID:
        return _fallback_hashtags(topic, "youtube", max_results)

    results = []
    try:
        from publishers.youtube_publisher import _get_authenticated_service
        youtube = _get_authenticated_service()
        if not youtube:
            return _fallback_hashtags(topic, "youtube", max_results)

        search_resp = youtube.search().list(
            part="snippet",
            q=topic,
            type="video",
            order="viewCount",
            maxResults=25,
        ).execute()

        tag_counts: dict[str, int] = {}
        for item in search_resp.get("items", []):
            vid = item["id"].get("videoId", "")
            if not vid:
                continue
            try:
                video_resp = youtube.videos().list(
                    part="snippet,statistics",
                    id=vid,
                ).execute()
                for v in video_resp.get("items", []):
                    tags = v["snippet"].get("tags", [])
                    int(v["statistics"].get("viewCount", 0))
                    for tag in tags[:15]:
                        tag_lower = tag.lower().strip()
                        if tag_lower:
                            tag_counts[tag_lower] = tag_counts.get(tag_lower, 0) + 1
            except Exception:
                continue

        sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
        for tag, count in sorted_tags[:max_results]:
            hr = HashtagResult(
                tag=tag,
                platform="youtube",
                volume=count * 1000,
                difficulty=min(1.0, count / 20),
                trending=count >= 5,
                category=topic,
            )
            hr.compute_score()
            results.append(hr)

    except Exception as e:
        print(f"[hashtag] YouTube research error: {e}")
        return _fallback_hashtags(topic, "youtube", max_results)

    return results


def research_hashtags_twitter(
    topic: str,
    max_results: int = 20,
) -> list[HashtagResult]:
    """Research hashtags via Twitter API trending and search."""
    if not config.TWITTER_API_KEY:
        return _fallback_hashtags(topic, "twitter", max_results)

    try:
        from requests_oauthlib import OAuth1
        auth = OAuth1(
            config.TWITTER_API_KEY, config.TWITTER_API_SECRET,
            config.TWITTER_ACCESS_TOKEN, config.TWITTER_ACCESS_TOKEN_SECRET,
        )

        resp = requests.get(
            "https://api.twitter.com/2/tweets/search/recent",
            auth=auth,
            params={
                "query": topic,
                "max_results": 100,
                "tweet.fields": "public_metrics,entities",
            },
            timeout=15,
        )
        if not resp.ok:
            return _fallback_hashtags(topic, "twitter", max_results)

        tag_stats: dict[str, dict] = {}
        for tweet in resp.json().get("data", []):
            entities = tweet.get("entities", {})
            metrics = tweet.get("public_metrics", {})
            for ht in entities.get("hashtags", []):
                tag = ht["tag"].lower()
                if tag not in tag_stats:
                    tag_stats[tag] = {"count": 0, "total_engagement": 0}
                tag_stats[tag]["count"] += 1
                tag_stats[tag]["total_engagement"] += (
                    metrics.get("like_count", 0) + metrics.get("retweet_count", 0)
                )

        results = []
        for tag, stats in sorted(tag_stats.items(), key=lambda x: x[1]["count"], reverse=True)[:max_results]:
            hr = HashtagResult(
                tag=tag,
                platform="twitter",
                volume=stats["count"] * 500,
                difficulty=min(1.0, stats["total_engagement"] / 10000),
                trending=stats["count"] >= 5,
                category=topic,
            )
            hr.compute_score()
            results.append(hr)
        return results

    except Exception as e:
        print(f"[hashtag] Twitter research error: {e}")
        return _fallback_hashtags(topic, "twitter", max_results)


def research_hashtags_instagram(
    topic: str,
    max_results: int = 20,
) -> list[HashtagResult]:
    """Research Instagram hashtags via Graph API."""
    if not config.INSTAGRAM_ACCESS_TOKEN:
        return _fallback_hashtags(topic, "instagram", max_results)

    try:
        resp = requests.get(
            "https://graph.facebook.com/v19.0/ig_hashtag_search",
            params={
                "q": topic.replace(" ", ""),
                "user_id": config.INSTAGRAM_ACCOUNT_ID,
                "access_token": config.INSTAGRAM_ACCESS_TOKEN,
            },
            timeout=15,
        )
        if not resp.ok:
            return _fallback_hashtags(topic, "instagram", max_results)

        results = []
        for ht in resp.json().get("data", [])[:max_results]:
            ht_id = ht.get("id", "")
            detail_resp = requests.get(
                f"https://graph.facebook.com/v19.0/{ht_id}",
                params={
                    "fields": "name,media_count",
                    "access_token": config.INSTAGRAM_ACCESS_TOKEN,
                },
                timeout=15,
            )
            if detail_resp.ok:
                detail = detail_resp.json()
                media_count = detail.get("media_count", 0)
                hr = HashtagResult(
                    tag=detail.get("name", topic),
                    platform="instagram",
                    volume=media_count,
                    difficulty=min(1.0, media_count / 10_000_000),
                    trending=False,
                    category=topic,
                )
                hr.compute_score()
                results.append(hr)
        return results

    except Exception as e:
        print(f"[hashtag] Instagram research error: {e}")
        return _fallback_hashtags(topic, "instagram", max_results)


def _fallback_hashtags(topic: str, platform: str, count: int) -> list[HashtagResult]:
    """Generate reasonable hashtag suggestions without API access."""
    words = re.sub(r"[^\w\s]", "", topic.lower()).split()
    tags = []

    tags.append(topic.replace(" ", "").lower())
    for w in words:
        if len(w) >= 3:
            tags.append(w)

    suffixes = ["tips", "hacks", "tutorial", "guide", "101",
                 "community", "daily", "life", "2026"]
    for w in words[:2]:
        for suffix in suffixes[:3]:
            tags.append(f"{w}{suffix}")

    seen = set()
    results = []
    for tag in tags:
        if tag in seen or len(tag) < 3:
            continue
        seen.add(tag)
        hr = HashtagResult(
            tag=tag,
            platform=platform,
            volume=0,
            difficulty=0.5,
            category=topic,
        )
        hr.compute_score()
        results.append(hr)
        if len(results) >= count:
            break

    return results


def research_all_platforms(topic: str, max_per_platform: int = 10) -> dict[str, list[HashtagResult]]:
    """Research hashtags across all platforms."""
    return {
        "youtube": research_hashtags_youtube(topic, max_per_platform),
        "twitter": research_hashtags_twitter(topic, max_per_platform),
        "instagram": research_hashtags_instagram(topic, max_per_platform),
    }


def get_best_hashtags(topic: str, platform: str = None, count: int = 15) -> list[str]:
    """Get the best hashtags for a topic, sorted by score."""
    if platform:
        researchers = {
            "youtube": research_hashtags_youtube,
            "twitter": research_hashtags_twitter,
            "instagram": research_hashtags_instagram,
        }
        func = researchers.get(platform, lambda t, c: _fallback_hashtags(t, platform, c))
        results = func(topic, count * 2)
    else:
        all_results = research_all_platforms(topic, count)
        results = [r for rs in all_results.values() for r in rs]

    results.sort(key=lambda r: r.score, reverse=True)
    return [f"#{r.tag}" for r in results[:count]]
