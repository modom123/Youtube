"""Performance feedback loop — publish → measure → learn → generate better.

Pulls post-publish metrics for a user's published videos, distills what is
working on *their* channel (topics, formats, titles), and produces a compact
instructions block that gets injected into the next script generation. This
is the loop that point tools (clippers, schedulers) don't close.
"""
from statistics import median

import config
import database as db


# ── Metrics ingestion ─────────────────────────────────────────────────────────

def refresh_user_analytics(user_id: int) -> int:
    """Pull fresh stats for the user's published YouTube videos into
    analytics_cache. Returns the number of videos refreshed. Raises on
    API/auth errors so callers can surface them."""
    published = db.get_published_videos(user_id=user_id)
    if not published:
        return 0
    accounts = db.get_accounts(user_id=user_id)
    account = next((a for a in accounts if a["platform"] == "youtube" and a.get("access_token")), None)
    if not account:
        return 0

    from google.oauth2.credentials import Credentials
    import googleapiclient.discovery

    creds = Credentials(
        token=account["access_token"], refresh_token=account.get("refresh_token"),
        client_id=config.YOUTUBE_CLIENT_ID, client_secret=config.YOUTUBE_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
    )
    yt = googleapiclient.discovery.build("youtube", "v3", credentials=creds)
    yt_videos = [v for v in published if v["platform"] == "youtube" and v.get("video_id")]
    refreshed = 0
    for chunk_start in range(0, len(yt_videos), 50):
        chunk = yt_videos[chunk_start:chunk_start + 50]
        ids = ",".join(v["video_id"] for v in chunk)
        resp = yt.videos().list(part="statistics,contentDetails", id=ids).execute()
        titles = {v["video_id"]: v.get("title") or "" for v in chunk}
        for item in resp.get("items", []):
            stats = item.get("statistics", {})
            views = int(stats.get("viewCount", 0))
            likes = int(stats.get("likeCount", 0))
            comments = int(stats.get("commentCount", 0))
            revenue = round(views / 1000 * 2.0, 2)
            db.upsert_analytics(
                user_id=user_id, video_id=item["id"], platform="youtube",
                title=titles.get(item["id"], ""),
                views=views, likes=likes, comments=comments, revenue_estimate=revenue,
            )
            refreshed += 1
    return refreshed


# ── Insight extraction ────────────────────────────────────────────────────────

MIN_VIDEOS_FOR_INSIGHTS = 3


def compute_insights(user_id: int) -> dict:
    """Distill per-account performance patterns from analytics + job metadata.

    Returns {} until there is enough data (>= MIN_VIDEOS_FOR_INSIGHTS videos
    with views), so early accounts aren't steered by noise."""
    rows = db.get_analytics_joined(user_id)
    scored = [r for r in rows if (r.get("views") or 0) > 0]
    if len(scored) < MIN_VIDEOS_FOR_INSIGHTS:
        return {}

    scored.sort(key=lambda r: r["views"], reverse=True)
    med = median(r["views"] for r in scored)
    winners = [r for r in scored if r["views"] >= max(med * 1.5, 1)][:10]

    # Formats ranked by average views
    format_views: dict = {}
    for r in scored:
        fmt = r.get("format")
        if fmt:
            format_views.setdefault(fmt, []).append(r["views"])
    format_avg = sorted(
        ((fmt, sum(v) / len(v)) for fmt, v in format_views.items()),
        key=lambda x: x[1], reverse=True,
    )

    # Topics of above-median videos
    winning_topics = []
    for r in winners:
        topic = (r.get("topic") or "").strip()
        if topic and topic.lower() not in (t.lower() for t in winning_topics):
            winning_topics.append(topic)

    top_titles = [
        {"title": (r.get("title") or r.get("topic") or "").strip(), "views": r["views"]}
        for r in scored[:3] if (r.get("title") or r.get("topic"))
    ]

    engagement = [
        (r["likes"] + r["comments"]) / r["views"]
        for r in scored if r.get("likes") is not None and r["views"] > 100
    ]

    return {
        "video_count": len(scored),
        "median_views": med,
        "top_titles": top_titles,
        "winning_topics": winning_topics[:5],
        "format_avg_views": format_avg,
        "avg_engagement_rate": round(sum(engagement) / len(engagement), 4) if engagement else None,
    }


def insights_prompt(user_id: int) -> str:
    """Compact instruction block injected into script generation. Empty string
    when there isn't enough signal yet."""
    ins = compute_insights(user_id)
    if not ins:
        return ""
    parts = [
        "AUDIENCE INSIGHTS — learned from this channel's actual published performance "
        f"({ins['video_count']} videos, median {int(ins['median_views'])} views):"
    ]
    if ins["top_titles"]:
        best = "; ".join(f"\"{t['title']}\" ({t['views']:,} views)" for t in ins["top_titles"])
        parts.append(f"Best performers: {best}.")
    if ins["winning_topics"]:
        parts.append(f"Topics that outperform for this audience: {', '.join(ins['winning_topics'])}.")
    if ins["format_avg_views"]:
        fmt_line = ", ".join(f"{fmt} avg {int(avg):,} views" for fmt, avg in ins["format_avg_views"][:3])
        parts.append(f"Format performance: {fmt_line}.")
    parts.append(
        "Lean into the hooks, angles, and phrasing style of the best performers above "
        "where they fit the requested topic. Do not copy titles verbatim."
    )
    return "\n".join(parts)[:900]
