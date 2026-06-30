"""Upload videos to YouTube using the YouTube Data API v3."""
import json
from pathlib import Path
from typing import Optional
import google.oauth2.credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.http
import config


def _get_authenticated_service():
    """Authenticate and return a YouTube API service object."""
    credentials = None

    if config.YOUTUBE_TOKEN_FILE.exists():
        with open(config.YOUTUBE_TOKEN_FILE) as f:
            token_data = json.load(f)
        credentials = google.oauth2.credentials.Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=config.YOUTUBE_CLIENT_ID,
            client_secret=config.YOUTUBE_CLIENT_SECRET,
        )

    if not credentials or not credentials.valid:
        flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_config(
            {
                "installed": {
                    "client_id": config.YOUTUBE_CLIENT_ID,
                    "client_secret": config.YOUTUBE_CLIENT_SECRET,
                    "redirect_uris": [config.YOUTUBE_REDIRECT_URI],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=config.YOUTUBE_SCOPES,
        )
        credentials = flow.run_local_server(port=8080)
        with open(config.YOUTUBE_TOKEN_FILE, "w") as f:
            json.dump(
                {
                    "token": credentials.token,
                    "refresh_token": credentials.refresh_token,
                    "token_uri": credentials.token_uri,
                    "client_id": credentials.client_id,
                    "client_secret": credentials.client_secret,
                    "scopes": list(credentials.scopes) if credentials.scopes else [],
                },
                f,
            )

    return googleapiclient.discovery.build("youtube", "v3", credentials=credentials)


def get_channel_info() -> dict:
    """Return info about the authenticated channel."""
    youtube = _get_authenticated_service()
    resp = youtube.channels().list(part="snippet,statistics", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        return {}
    ch = items[0]
    channel_id = ch["id"]
    return {
        "channel_id": channel_id,
        "title": ch["snippet"]["title"],
        "description": ch["snippet"].get("description", ""),
        "thumbnail": ch["snippet"].get("thumbnails", {}).get("default", {}).get("url", ""),
        "url": f"https://www.youtube.com/channel/{channel_id}",
        "subscribers": ch.get("statistics", {}).get("subscriberCount", "0"),
        "video_count": ch.get("statistics", {}).get("videoCount", "0"),
        "verified": channel_id == config.YOUTUBE_CHANNEL_ID if config.YOUTUBE_CHANNEL_ID else True,
    }


def upload_video(
    video_path: Path,
    title: str,
    description: str,
    tags: list[str],
    thumbnail_path: Optional[Path] = None,
    privacy: str = "private",
    is_short: bool = False,
    category_id: str = "22",  # People & Blogs
    notify_subscribers: bool = False,
) -> dict:
    """Upload a video to YouTube. Returns the video metadata dict."""
    youtube = _get_authenticated_service()

    body = {
        "snippet": {
            "title": title[:100],
            "description": description + ("\n\n#Shorts" if is_short else ""),
            "tags": tags[:500],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            "notifySubscribers": notify_subscribers,
        },
    }

    media = googleapiclient.http.MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=5 * 1024 * 1024,
    )

    request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"[youtube] Upload {int(status.progress() * 100)}%")

    video_id = response["id"]
    channel_id = config.YOUTUBE_CHANNEL_ID or "your-channel"
    print(f"[youtube] Uploaded: https://youtube.com/watch?v={video_id}")

    if thumbnail_path and Path(thumbnail_path).exists():
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=googleapiclient.http.MediaFileUpload(str(thumbnail_path)),
            ).execute()
            print(f"[youtube] Thumbnail set for {video_id}")
        except Exception as e:
            print(f"[youtube] Thumbnail upload failed: {e}")

    return {
        "platform": "youtube",
        "video_id": video_id,
        "url": f"https://youtube.com/watch?v={video_id}",
        "channel_url": f"https://www.youtube.com/channel/{channel_id}",
        "short_url": f"https://youtube.com/shorts/{video_id}" if is_short else None,
        "privacy": privacy,
    }
