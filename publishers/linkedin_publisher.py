"""Upload videos to LinkedIn using the REST API."""
from pathlib import Path
import requests
import config

REGISTER_URL = "https://api.linkedin.com/v2/assets?action=registerUpload"
UGC_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"


def upload_video(
    video_path: str,
    title: str,
    description: str,
    tags: list,
    access_token: str = "",
    person_id: str = "",
) -> dict:
    """
    Upload a video to LinkedIn and create a UGC post.

    Steps:
      1. Register upload — get asset URN and upload URL
      2. PUT video bytes to the upload URL
      3. POST ugcPost with the asset URN

    Args:
        video_path: Local path to the video file.
        title: Post title / headline.
        description: Post body text.
        tags: List of hashtag strings.
        access_token: LinkedIn access token (defaults to config.LINKEDIN_ACCESS_TOKEN).
        person_id: LinkedIn person URN ID (defaults to config.LINKEDIN_PERSON_ID).

    Returns:
        dict with platform, post_id, and url keys.
    """
    access_token = access_token or config.LINKEDIN_ACCESS_TOKEN
    person_id = person_id or config.LINKEDIN_PERSON_ID

    if not access_token or not person_id:
        return {
            "platform": "linkedin",
            "status": "skipped",
            "reason": "LINKEDIN_ACCESS_TOKEN and LINKEDIN_PERSON_ID are required.",
        }

    video_path = Path(video_path)
    if not video_path.exists():
        return {"platform": "linkedin", "status": "error", "error": f"File not found: {video_path}"}

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    try:
        # Step 1: Register upload
        print("[linkedin] Registering upload...")
        owner_urn = f"urn:li:person:{person_id}"
        register_body = {
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-video"],
                "owner": owner_urn,
                "serviceRelationships": [
                    {
                        "relationshipType": "OWNER",
                        "identifier": "urn:li:userGeneratedContent",
                    }
                ],
            }
        }
        reg_resp = requests.post(REGISTER_URL, json=register_body, headers=headers, timeout=30)
        reg_resp.raise_for_status()
        reg_data = reg_resp.json()

        asset_urn = reg_data["value"]["asset"]
        upload_url = reg_data["value"]["uploadMechanism"][
            "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
        ]["uploadUrl"]

        # Step 2: Upload video bytes
        print(f"[linkedin] Uploading video to {upload_url[:60]}...")
        with open(video_path, "rb") as fh:
            upload_resp = requests.put(
                upload_url,
                data=fh,
                headers={"Content-Type": "video/mp4"},
                timeout=300,
            )
        upload_resp.raise_for_status()
        print("[linkedin] Video bytes uploaded.")

        # Step 3: Create UGC post
        tag_str = " ".join(f"#{t.replace(' ', '').replace('#', '')}" for t in tags[:20])
        post_text = f"{title}\n\n{description}\n\n{tag_str}".strip()[:3000]

        post_body = {
            "author": owner_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": post_text},
                    "shareMediaCategory": "VIDEO",
                    "media": [
                        {
                            "status": "READY",
                            "description": {"text": description[:200]},
                            "media": asset_urn,
                            "title": {"text": title[:200]},
                        }
                    ],
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }

        post_resp = requests.post(UGC_POSTS_URL, json=post_body, headers=headers, timeout=30)
        post_resp.raise_for_status()
        post_id = post_resp.headers.get("x-restli-id") or post_resp.json().get("id", "")

        print(f"[linkedin] Post created! ID: {post_id}")
        return {
            "platform": "linkedin",
            "post_id": post_id,
            "url": "https://linkedin.com/feed/",
        }

    except requests.HTTPError as e:
        error_detail = ""
        try:
            error_detail = e.response.json()
        except Exception:
            error_detail = str(e)
        print(f"[linkedin] Upload failed: {error_detail}")
        return {"platform": "linkedin", "status": "error", "error": str(error_detail)}
    except Exception as e:
        print(f"[linkedin] Upload failed: {e}")
        return {"platform": "linkedin", "status": "error", "error": str(e)}
