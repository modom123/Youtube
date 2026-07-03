"""Upload Reels and videos to Instagram using the Meta Graph API."""
import time
from typing import Optional
import requests
import config


GRAPH_URL = "https://graph.facebook.com/v19.0"


def _create_reel_container(
    video_url: str,
    caption: str,
    thumbnail_url: Optional[str] = None,
) -> str:
    """Create an Instagram Reel media container. Returns container_id."""
    params = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption[:2200],
        "share_to_feed": "true",
        "access_token": config.INSTAGRAM_ACCESS_TOKEN,
    }
    if thumbnail_url:
        params["thumb_offset"] = "0"

    resp = requests.post(
        f"{GRAPH_URL}/{config.INSTAGRAM_ACCOUNT_ID}/media",
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def _wait_for_container(container_id: str, max_wait: int = 300) -> bool:
    """Poll until the media container is ready to publish."""
    for _ in range(max_wait // 10):
        resp = requests.get(
            f"{GRAPH_URL}/{container_id}",
            params={
                "fields": "status_code,status",
                "access_token": config.INSTAGRAM_ACCESS_TOKEN,
            },
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            status = data.get("status_code")
            if status == "FINISHED":
                return True
            if status in ("ERROR", "EXPIRED"):
                raise RuntimeError(f"Container failed: {data.get('status')}")
        time.sleep(10)
    return False


def _publish_container(container_id: str) -> str:
    """Publish a ready media container. Returns the media ID."""
    resp = requests.post(
        f"{GRAPH_URL}/{config.INSTAGRAM_ACCOUNT_ID}/media_publish",
        params={
            "creation_id": container_id,
            "access_token": config.INSTAGRAM_ACCESS_TOKEN,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def upload_reel(
    video_url: str,
    title: str,
    description: str,
    tags: list[str],
    thumbnail_url: Optional[str] = None,
) -> dict:
    """
    Upload a Reel to Instagram.

    NOTE: The video must be publicly accessible via URL (CDN/hosting required).
    Instagram Graph API does not accept local file uploads directly.
    """
    if not config.INSTAGRAM_ACCESS_TOKEN or not config.INSTAGRAM_ACCOUNT_ID:
        return {
            "platform": "instagram",
            "status": "skipped",
            "reason": "INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_ACCOUNT_ID are required for Instagram.",
        }
    tag_str = " ".join(f"#{t.replace(' ', '').replace('#', '')}" for t in tags[:30])
    caption = f"{title}\n\n{description}\n\n{tag_str}"

    print("[instagram] Creating media container...")
    container_id = _create_reel_container(video_url, caption, thumbnail_url)

    print(f"[instagram] Container {container_id} — waiting for processing...")
    ready = _wait_for_container(container_id)

    if not ready:
        raise RuntimeError("[instagram] Container timed out waiting for FINISHED status")

    print("[instagram] Publishing reel...")
    media_id = _publish_container(container_id)

    print(f"[instagram] Published! Media ID: {media_id}")
    return {
        "platform": "instagram",
        "media_id": media_id,
        "container_id": container_id,
        "url": f"https://www.instagram.com/p/{media_id}/",
    }


def get_account_info() -> dict:
    """Verify Instagram account credentials."""
    resp = requests.get(
        f"{GRAPH_URL}/{config.INSTAGRAM_ACCOUNT_ID}",
        params={
            "fields": "id,name,username,followers_count",
            "access_token": config.INSTAGRAM_ACCESS_TOKEN,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()
