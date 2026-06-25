"""Fetch stock video clips and images from Pexels."""
import random
from pathlib import Path
from typing import Optional
import requests
import config


PEXELS_VIDEOS_URL = "https://api.pexels.com/videos/search"
PEXELS_PHOTOS_URL = "https://api.pexels.com/v1/search"


def _headers() -> dict:
    return {"Authorization": config.PEXELS_API_KEY}


def search_videos(query: str, count: int = 5, orientation: str = "landscape") -> list[dict]:
    """Search Pexels for stock videos matching query."""
    params = {
        "query": query,
        "per_page": min(count * 2, 20),
        "orientation": orientation,
        "size": "medium",
    }
    resp = requests.get(PEXELS_VIDEOS_URL, headers=_headers(), params=params, timeout=15)
    resp.raise_for_status()
    videos = resp.json().get("videos", [])
    random.shuffle(videos)
    return videos[:count]


def search_images(query: str, count: int = 10, orientation: str = "landscape") -> list[dict]:
    """Search Pexels for stock images."""
    params = {
        "query": query,
        "per_page": min(count * 2, 30),
        "orientation": orientation,
    }
    resp = requests.get(PEXELS_PHOTOS_URL, headers=_headers(), params=params, timeout=15)
    resp.raise_for_status()
    photos = resp.json().get("photos", [])
    random.shuffle(photos)
    return photos[:count]


def download_video(video: dict, output_dir: Path, quality: str = "sd") -> Optional[Path]:
    """Download a Pexels video file."""
    files = video.get("video_files", [])
    quality_map = {"hd": ["hd", "sd"], "sd": ["sd", "hd"]}
    preferred = quality_map.get(quality, ["sd", "hd"])

    target = None
    for q in preferred:
        matches = [f for f in files if f.get("quality") == q and f.get("file_type") == "video/mp4"]
        if matches:
            target = min(matches, key=lambda f: abs(f.get("width", 0) - 1280))
            break

    if not target and files:
        target = files[0]

    if not target:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    filename = output_dir / f"pexels_{video['id']}_{quality}.mp4"

    if filename.exists():
        return filename

    resp = requests.get(target["link"], stream=True, timeout=60)
    resp.raise_for_status()
    with open(filename, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    return filename


def download_image(photo: dict, output_dir: Path, size: str = "large") -> Optional[Path]:
    """Download a Pexels image."""
    src = photo.get("src", {})
    url = src.get(size) or src.get("large") or src.get("original")
    if not url:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    ext = "jpg"
    filename = output_dir / f"pexels_{photo['id']}_{size}.{ext}"

    if filename.exists():
        return filename

    resp = requests.get(url, stream=True, timeout=30)
    resp.raise_for_status()
    with open(filename, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    return filename


def fetch_media_for_topic(
    keywords: list[str],
    output_dir: Path,
    video_count: int = 5,
    is_portrait: bool = False,
) -> tuple[list[Path], list[Path]]:
    """Fetch a mix of videos and images for a topic."""
    orientation = "portrait" if is_portrait else "landscape"
    query = " ".join(keywords[:3])

    video_paths = []
    image_paths = []

    if not config.PEXELS_API_KEY:
        print("[media] PEXELS_API_KEY not set — no stock media will be fetched")
        return video_paths, image_paths

    print(f"[media] Searching Pexels for: '{query}' (orientation={orientation})")

    try:
        videos = search_videos(query, count=video_count, orientation=orientation)
        print(f"[media] Found {len(videos)} videos from Pexels")
        for v in videos:
            try:
                path = download_video(v, output_dir / "stock_videos")
                if path:
                    video_paths.append(path)
            except Exception as e:
                print(f"[media] Video download failed for {v.get('id')}: {e}")
    except Exception as e:
        print(f"[media] Video search failed: {e}")

    try:
        photos = search_images(query, count=10, orientation=orientation)
        print(f"[media] Found {len(photos)} images from Pexels")
        for p in photos:
            try:
                path = download_image(p, output_dir / "stock_images")
                if path:
                    image_paths.append(path)
            except Exception as e:
                print(f"[media] Image download failed for {p.get('id')}: {e}")
    except Exception as e:
        print(f"[media] Image search failed: {e}")

    print(f"[media] Final count: {len(video_paths)} videos, {len(image_paths)} images downloaded")
    return video_paths, image_paths
