"""Upload videos and post tweets to Twitter/X using API v2 with chunked media upload."""
import time
import math
from pathlib import Path
import requests
from requests_oauthlib import OAuth1
import config

UPLOAD_URL = "https://upload.twitter.com/1.1/media/upload.json"
TWEET_URL = "https://api.twitter.com/2/tweets"
CHUNK_SIZE = 5 * 1024 * 1024  # 5 MB


def _get_auth() -> OAuth1:
    return OAuth1(
        config.TWITTER_API_KEY,
        config.TWITTER_API_SECRET,
        config.TWITTER_ACCESS_TOKEN,
        config.TWITTER_ACCESS_TOKEN_SECRET,
    )


def _media_upload_init(auth: OAuth1, total_bytes: int) -> str:
    """INIT phase — returns media_id_string."""
    resp = requests.post(
        UPLOAD_URL,
        data={
            "command": "INIT",
            "media_type": "video/mp4",
            "media_category": "tweet_video",
            "total_bytes": total_bytes,
        },
        auth=auth,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["media_id_string"]


def _media_upload_append(auth: OAuth1, media_id: str, chunk: bytes, segment_index: int) -> None:
    """APPEND phase — uploads one chunk."""
    resp = requests.post(
        UPLOAD_URL,
        data={"command": "APPEND", "media_id": media_id, "segment_index": segment_index},
        files={"media": chunk},
        auth=auth,
        timeout=60,
    )
    resp.raise_for_status()


def _media_upload_finalize(auth: OAuth1, media_id: str) -> dict:
    """FINALIZE phase — returns the API response."""
    resp = requests.post(
        UPLOAD_URL,
        data={"command": "FINALIZE", "media_id": media_id},
        auth=auth,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _poll_processing(auth: OAuth1, media_id: str, max_wait: int = 300) -> bool:
    """Poll until processing_info.state == 'succeeded'. Returns True on success."""
    waited = 0
    check_after = 5
    while waited < max_wait:
        time.sleep(check_after)
        waited += check_after
        resp = requests.get(
            UPLOAD_URL,
            params={"command": "STATUS", "media_id": media_id},
            auth=auth,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        processing = data.get("processing_info", {})
        state = processing.get("state", "succeeded")
        print(f"[twitter] Media processing state: {state} (waited {waited}s)")
        if state == "succeeded":
            return True
        if state == "failed":
            return False
        check_after = processing.get("check_after_secs", 5)
    return False


def upload_video(
    video_path: str,
    title: str,
    description: str,
    tags: list,
) -> dict:
    """
    Upload a video to Twitter/X.

    Steps:
      1. Chunked media upload (INIT → APPEND × N → FINALIZE)
      2. Poll until processing succeeds
      3. Post tweet with media attachment

    Returns:
        dict with platform, tweet_id, and url keys.
    """
    missing = [
        k for k in ("TWITTER_API_KEY", "TWITTER_API_SECRET",
                    "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_TOKEN_SECRET")
        if not getattr(config, k, "")
    ]
    if missing:
        return {
            "platform": "twitter",
            "status": "skipped",
            "reason": f"Missing config vars: {', '.join(missing)}",
        }

    video_path = Path(video_path)
    if not video_path.exists():
        return {"platform": "twitter", "status": "error", "error": f"File not found: {video_path}"}

    try:
        auth = _get_auth()
        total_bytes = video_path.stat().st_size
        num_chunks = math.ceil(total_bytes / CHUNK_SIZE)

        print(f"[twitter] INIT upload — {total_bytes} bytes, {num_chunks} chunks")
        media_id = _media_upload_init(auth, total_bytes)

        with open(video_path, "rb") as fh:
            for idx in range(num_chunks):
                chunk = fh.read(CHUNK_SIZE)
                print(f"[twitter] APPEND chunk {idx + 1}/{num_chunks}")
                _media_upload_append(auth, media_id, chunk, idx)

        print("[twitter] FINALIZE upload")
        finalize_data = _media_upload_finalize(auth, media_id)

        if finalize_data.get("processing_info", {}).get("state") == "pending":
            print("[twitter] Polling media processing...")
            ok = _poll_processing(auth, media_id)
            if not ok:
                return {"platform": "twitter", "status": "error", "error": "Media processing failed"}

        # Build tweet text (max 280 chars)
        hashtags = " ".join(f"#{t.replace(' ', '').replace('#', '')}" for t in tags[:5])
        tweet_text = f"{title} {hashtags}"[:280]

        print("[twitter] Posting tweet...")
        tweet_resp = requests.post(
            TWEET_URL,
            json={"text": tweet_text, "media": {"media_ids": [media_id]}},
            auth=auth,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        tweet_resp.raise_for_status()
        tweet_data = tweet_resp.json()
        tweet_id = tweet_data.get("data", {}).get("id")

        print(f"[twitter] Tweet posted! ID: {tweet_id}")
        return {
            "platform": "twitter",
            "tweet_id": tweet_id,
            "url": f"https://twitter.com/i/web/status/{tweet_id}",
        }

    except requests.HTTPError as e:
        error_detail = ""
        try:
            error_detail = e.response.json()
        except Exception:
            error_detail = str(e)
        print(f"[twitter] Upload failed: {error_detail}")
        return {"platform": "twitter", "status": "error", "error": str(error_detail)}
    except Exception as e:
        print(f"[twitter] Upload failed: {e}")
        return {"platform": "twitter", "status": "error", "error": str(e)}
