"""Upload videos to Threads using the Meta Threads API (threads.net Graph API)."""
import time
import requests
import config

THREADS_API = "https://graph.threads.net/v1.0"


def upload_video(
    video_url: str,
    title: str,
    description: str,
    tags: list,
) -> dict:
    """
    Publish a video to Threads.

    NOTE: The video must be a publicly accessible CDN URL.
    If video_url is a local path or not publicly accessible, this function
    will skip gracefully and return status='skipped'.

    Uses INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_ACCOUNT_ID from config (Threads is
    linked to Instagram and shares the same access credentials).

    Steps:
      1. POST /{user_id}/threads — create media container
      2. Poll until container status is FINISHED
      3. POST /{user_id}/threads_publish — publish the container

    Returns:
        dict with platform, thread_id, and url keys.
    """
    access_token = config.INSTAGRAM_ACCESS_TOKEN
    user_id = config.INSTAGRAM_ACCOUNT_ID

    if not access_token or not user_id:
        return {
            "platform": "threads",
            "status": "skipped",
            "reason": "INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_ACCOUNT_ID are required for Threads.",
        }

    # If video_url looks like a local path, skip gracefully
    if not video_url or not video_url.startswith("http"):
        return {
            "platform": "threads",
            "status": "skipped",
            "reason": "Threads requires a publicly accessible video URL (CDN). Local file not supported.",
            "video_path": str(video_url),
        }

    tag_str = " ".join(f"#{t.replace(' ', '').replace('#', '')}" for t in tags[:20])
    caption = f"{title}\n\n{description}\n\n{tag_str}".strip()[:500]

    try:
        # Step 1: Create media container
        print("[threads] Creating media container...")
        container_resp = requests.post(
            f"{THREADS_API}/{user_id}/threads",
            params={
                "media_type": "VIDEO",
                "video_url": video_url,
                "text": caption,
                "access_token": access_token,
            },
            timeout=30,
        )
        container_resp.raise_for_status()
        creation_id = container_resp.json()["id"]
        print(f"[threads] Container created: {creation_id}")

        # Step 2: Poll status
        print("[threads] Waiting for media processing...")
        for _ in range(30):
            time.sleep(10)
            status_resp = requests.get(
                f"{THREADS_API}/{creation_id}",
                params={"fields": "status,error_message", "access_token": access_token},
                timeout=15,
            )
            if status_resp.ok:
                data = status_resp.json()
                status = data.get("status", "")
                print(f"[threads] Container status: {status}")
                if status == "FINISHED":
                    break
                if status in ("ERROR", "EXPIRED"):
                    return {
                        "platform": "threads",
                        "status": "error",
                        "error": f"Container failed: {data.get('error_message', status)}",
                    }
        else:
            return {"platform": "threads", "status": "error", "error": "Container processing timed out"}

        # Step 3: Publish
        print("[threads] Publishing thread...")
        publish_resp = requests.post(
            f"{THREADS_API}/{user_id}/threads_publish",
            params={"creation_id": creation_id, "access_token": access_token},
            timeout=30,
        )
        publish_resp.raise_for_status()
        thread_id = publish_resp.json().get("id")

        print(f"[threads] Published! Thread ID: {thread_id}")
        return {
            "platform": "threads",
            "thread_id": thread_id,
            "url": "https://threads.net/",
        }

    except requests.HTTPError as e:
        error_detail = ""
        try:
            error_detail = e.response.json()
        except Exception:
            error_detail = str(e)
        print(f"[threads] Upload failed: {error_detail}")
        return {"platform": "threads", "status": "error", "error": str(error_detail)}
    except Exception as e:
        print(f"[threads] Upload failed: {e}")
        return {"platform": "threads", "status": "error", "error": str(e)}
