"""Upload videos to TikTok using the TikTok Content Posting API."""
import time
from pathlib import Path
import requests
import config


TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.TIKTOK_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def _init_upload(video_size: int) -> dict:
    """Initialize a direct post upload on TikTok."""
    resp = requests.post(
        f"{TIKTOK_API_BASE}/post/publish/video/init/",
        headers=_headers(),
        json={
            "post_info": {
                "title": "",  # filled later
                "privacy_level": "SELF_ONLY",  # safe default
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
                "video_cover_timestamp_ms": 1000,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": video_size,
                "chunk_size": video_size,
                "total_chunk_count": 1,
            },
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("data", {})


def _upload_chunk(upload_url: str, video_path: Path, video_size: int) -> None:
    """Upload a video chunk to TikTok's upload endpoint."""
    with open(video_path, "rb") as f:
        video_data = f.read()

    resp = requests.put(
        upload_url,
        data=video_data,
        headers={
            "Content-Type": "video/mp4",
            "Content-Length": str(video_size),
            "Content-Range": f"bytes 0-{video_size - 1}/{video_size}",
        },
        timeout=120,
    )
    resp.raise_for_status()


def _publish_post(publish_id: str, title: str, tags: list[str]) -> dict:
    """Finalize TikTok post with title and hashtags."""
    caption = title[:150]
    if tags:
        tag_str = " ".join(f"#{t.replace(' ', '')}" for t in tags[:5])
        caption = f"{caption} {tag_str}"

    resp = requests.post(
        f"{TIKTOK_API_BASE}/post/publish/",
        headers=_headers(),
        json={
            "publish_id": publish_id,
            "post_info": {
                "title": caption[:150],
            },
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("data", {})


def _wait_for_processing(publish_id: str, max_wait: int = 120) -> dict:
    """Poll TikTok until the video finishes processing."""
    for _ in range(max_wait // 5):
        resp = requests.post(
            f"{TIKTOK_API_BASE}/post/publish/status/fetch/",
            headers=_headers(),
            json={"publish_id": publish_id},
            timeout=15,
        )
        if resp.ok:
            data = resp.json().get("data", {})
            status = data.get("status")
            if status == "PUBLISH_COMPLETE":
                return data
            if status in ("FAILED", "CANCELLED"):
                raise RuntimeError(f"TikTok processing failed: {data}")
        time.sleep(5)
    return {}


def upload_video(
    video_path: Path,
    title: str,
    description: str,
    tags: list[str],
    privacy: str = "SELF_ONLY",
) -> dict:
    """Upload a video to TikTok. Returns result metadata."""
    video_path = Path(video_path)
    video_size = video_path.stat().st_size

    print(f"[tiktok] Initializing upload ({video_size / 1024 / 1024:.1f} MB)...")
    init_data = _init_upload(video_size)
    publish_id = init_data.get("publish_id")
    upload_url = init_data.get("upload_url")

    if not publish_id or not upload_url:
        raise RuntimeError(f"TikTok init failed: {init_data}")

    print("[tiktok] Uploading video chunk...")
    _upload_chunk(upload_url, video_path, video_size)

    print("[tiktok] Publishing post...")
    _publish_post(publish_id, title, tags)

    print("[tiktok] Waiting for processing...")
    result = _wait_for_processing(publish_id)

    print(f"[tiktok] Published! Publish ID: {publish_id}")
    return {
        "platform": "tiktok",
        "publish_id": publish_id,
        "status": result.get("status", "SUBMITTED"),
    }
