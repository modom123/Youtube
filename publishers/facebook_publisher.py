"""Upload videos to Facebook using the Meta Graph API v19.0."""
from pathlib import Path
from typing import Optional
import requests
import config

GRAPH_URL = "https://graph.facebook.com/v19.0"


def upload_video(
    video_path: str,
    title: str,
    description: str,
    tags: list,
    page_id: str = "",
    access_token: str = "",
    thumbnail_path: Optional[str] = None,
) -> dict:
    """
    Upload a video to a Facebook Page using multipart upload.

    Args:
        video_path: Local path to the video file.
        title: Video title.
        description: Video description.
        tags: List of hashtag strings.
        page_id: Facebook Page ID (defaults to config.FACEBOOK_PAGE_ID).
        access_token: Long-lived page access token (defaults to config.FACEBOOK_ACCESS_TOKEN).
        thumbnail_path: Optional local path to thumbnail image.

    Returns:
        dict with platform, video_id, and url keys.
    """
    page_id = page_id or config.FACEBOOK_PAGE_ID
    access_token = access_token or config.FACEBOOK_ACCESS_TOKEN

    if not page_id or not access_token:
        return {
            "platform": "facebook",
            "status": "skipped",
            "reason": "FACEBOOK_PAGE_ID and FACEBOOK_ACCESS_TOKEN are required.",
        }

    video_path = Path(video_path)
    if not video_path.exists():
        return {
            "platform": "facebook",
            "status": "error",
            "error": f"Video file not found: {video_path}",
        }

    tag_str = " ".join(f"#{t.replace(' ', '').replace('#', '')}" for t in tags[:30])
    full_description = f"{description}\n\n{tag_str}".strip()

    try:
        print(f"[facebook] Uploading video to page {page_id}...")
        url = f"{GRAPH_URL}/{page_id}/videos"

        with open(video_path, "rb") as video_file:
            files = {"source": (video_path.name, video_file, "video/mp4")}
            data = {
                "title": title[:254],
                "description": full_description[:9000],
                "access_token": access_token,
            }
            resp = requests.post(url, files=files, data=data, timeout=300)

        resp.raise_for_status()
        result = resp.json()
        video_id = result.get("id")

        print(f"[facebook] Upload complete! Video ID: {video_id}")
        return {
            "platform": "facebook",
            "video_id": video_id,
            "url": f"https://facebook.com/{video_id}",
        }

    except requests.HTTPError as e:
        error_detail = ""
        try:
            error_detail = e.response.json()
        except Exception:
            error_detail = str(e)
        print(f"[facebook] Upload failed: {error_detail}")
        return {"platform": "facebook", "status": "error", "error": str(error_detail)}
    except Exception as e:
        print(f"[facebook] Upload failed: {e}")
        return {"platform": "facebook", "status": "error", "error": str(e)}
