"""Upload videos to Pinterest using the Pinterest API v5."""
import time
from pathlib import Path
import requests
import config

PINTEREST_API = "https://api.pinterest.com/v5"


def upload_video(
    video_path: str,
    title: str,
    description: str,
    tags: list,
    board_id: str = "",
    access_token: str = "",
) -> dict:
    """
    Upload a video to Pinterest and create a Pin.

    Steps:
      1. Register media at /v5/media — get media_id and S3 upload URL
      2. Upload video bytes to the S3 URL
      3. Poll until media is ready
      4. Create pin at /v5/pins with media_id

    Args:
        video_path: Local path to the video file.
        title: Pin title.
        description: Pin description.
        tags: List of tag strings (used in description as hashtags).
        board_id: Pinterest board ID (defaults to config.PINTEREST_BOARD_ID).
        access_token: Pinterest access token (defaults to config.PINTEREST_ACCESS_TOKEN).

    Returns:
        dict with platform, pin_id, and url keys.
    """
    board_id = board_id or config.PINTEREST_BOARD_ID
    access_token = access_token or config.PINTEREST_ACCESS_TOKEN

    if not board_id or not access_token:
        return {
            "platform": "pinterest",
            "status": "skipped",
            "reason": "PINTEREST_ACCESS_TOKEN and PINTEREST_BOARD_ID are required.",
        }

    video_path = Path(video_path)
    if not video_path.exists():
        return {"platform": "pinterest", "status": "error", "error": f"File not found: {video_path}"}

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    try:
        # Step 1: Register media
        print("[pinterest] Registering media upload...")
        reg_resp = requests.post(
            f"{PINTEREST_API}/media",
            json={"media_type": "video"},
            headers=headers,
            timeout=30,
        )
        reg_resp.raise_for_status()
        reg_data = reg_resp.json()
        media_id = reg_data["media_id"]
        upload_url = reg_data["upload_url"]
        upload_parameters = reg_data.get("upload_parameters", {})

        # Step 2: Upload video to S3
        print(f"[pinterest] Uploading video to S3 ({upload_url[:60]}...)...")
        with open(video_path, "rb") as fh:
            upload_resp = requests.post(
                upload_url,
                data=upload_parameters,
                files={"file": (video_path.name, fh, "video/mp4")},
                timeout=300,
            )
        # S3 returns 204 No Content on success
        if upload_resp.status_code not in (200, 204):
            upload_resp.raise_for_status()
        print("[pinterest] Video bytes uploaded.")

        # Step 3: Poll until media is ready
        print("[pinterest] Waiting for media processing...")
        for _ in range(30):
            time.sleep(10)
            status_resp = requests.get(
                f"{PINTEREST_API}/media/{media_id}",
                headers=headers,
                timeout=15,
            )
            if status_resp.ok:
                status = status_resp.json().get("status", "")
                print(f"[pinterest] Media status: {status}")
                if status == "succeeded":
                    break
                if status == "failed":
                    return {"platform": "pinterest", "status": "error", "error": "Media processing failed"}
        else:
            return {"platform": "pinterest", "status": "error", "error": "Media processing timed out"}

        # Step 4: Create Pin
        tag_str = " ".join(f"#{t.replace(' ', '').replace('#', '')}" for t in tags[:20])
        pin_description = f"{description}\n\n{tag_str}".strip()[:500]

        print("[pinterest] Creating pin...")
        pin_resp = requests.post(
            f"{PINTEREST_API}/pins",
            json={
                "board_id": board_id,
                "title": title[:100],
                "description": pin_description,
                "media_source": {
                    "source_type": "video_id",
                    "media_id": media_id,
                },
            },
            headers=headers,
            timeout=30,
        )
        pin_resp.raise_for_status()
        pin_data = pin_resp.json()
        pin_id = pin_data.get("id")

        print(f"[pinterest] Pin created! ID: {pin_id}")
        return {
            "platform": "pinterest",
            "pin_id": pin_id,
            "url": f"https://pinterest.com/pin/{pin_id}",
        }

    except requests.HTTPError as e:
        error_detail = ""
        try:
            error_detail = e.response.json()
        except Exception:
            error_detail = str(e)
        print(f"[pinterest] Upload failed: {error_detail}")
        return {"platform": "pinterest", "status": "error", "error": str(error_detail)}
    except Exception as e:
        print(f"[pinterest] Upload failed: {e}")
        return {"platform": "pinterest", "status": "error", "error": str(e)}
