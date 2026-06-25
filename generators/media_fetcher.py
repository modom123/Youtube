"""Fetch stock video clips and images — Pixabay primary, Pexels fallback."""
import random
from pathlib import Path
from typing import Optional
import requests
import config


# ── Pixabay ──────────────────────────────────────────────────────────────────

PIXABAY_VIDEOS_URL = "https://pixabay.com/api/videos/"
PIXABAY_PHOTOS_URL = "https://pixabay.com/api/"


def _pixabay_search_videos(query: str, count: int = 8, orientation: str = "horizontal") -> list[dict]:
    params = {
        "key": config.PIXABAY_API_KEY,
        "q": query,
        "per_page": min(count * 2, 20),
        "video_type": "film",
        "safesearch": "true",
    }
    resp = requests.get(PIXABAY_VIDEOS_URL, params=params, timeout=15)
    resp.raise_for_status()
    hits = resp.json().get("hits", [])
    random.shuffle(hits)
    return hits[:count]


def _pixabay_search_images(query: str, count: int = 10, orientation: str = "horizontal") -> list[dict]:
    params = {
        "key": config.PIXABAY_API_KEY,
        "q": query,
        "per_page": min(count * 2, 30),
        "image_type": "photo",
        "orientation": orientation,
        "safesearch": "true",
    }
    resp = requests.get(PIXABAY_PHOTOS_URL, params=params, timeout=15)
    resp.raise_for_status()
    hits = resp.json().get("hits", [])
    random.shuffle(hits)
    return hits[:count]


def _pixabay_download_video(video: dict, output_dir: Path) -> Optional[Path]:
    videos = video.get("videos", {})
    # Prefer medium quality, then small, then large
    for quality in ["medium", "small", "large"]:
        v = videos.get(quality, {})
        url = v.get("url")
        if url:
            break
    else:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    filename = output_dir / f"pixabay_{video.get('id', 0)}.mp4"
    if filename.exists():
        return filename

    resp = requests.get(url, stream=True, timeout=60)
    resp.raise_for_status()
    with open(filename, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    if filename.stat().st_size < 1000:
        filename.unlink(missing_ok=True)
        return None
    return filename


def _pixabay_download_image(photo: dict, output_dir: Path) -> Optional[Path]:
    url = photo.get("largeImageURL") or photo.get("webformatURL")
    if not url:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    filename = output_dir / f"pixabay_{photo.get('id', 0)}.jpg"
    if filename.exists():
        return filename

    resp = requests.get(url, stream=True, timeout=30)
    resp.raise_for_status()
    with open(filename, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    if filename.stat().st_size < 1000:
        filename.unlink(missing_ok=True)
        return None
    return filename


# ── Pexels ───────────────────────────────────────────────────────────────────

PEXELS_VIDEOS_URL = "https://api.pexels.com/videos/search"
PEXELS_PHOTOS_URL = "https://api.pexels.com/v1/search"


def _pexels_headers() -> dict:
    return {"Authorization": config.PEXELS_API_KEY}


def _pexels_search_videos(query: str, count: int = 5, orientation: str = "landscape") -> list[dict]:
    params = {
        "query": query,
        "per_page": min(count * 2, 20),
        "orientation": orientation,
        "size": "medium",
    }
    resp = requests.get(PEXELS_VIDEOS_URL, headers=_pexels_headers(), params=params, timeout=15)
    resp.raise_for_status()
    videos = resp.json().get("videos", [])
    random.shuffle(videos)
    return videos[:count]


def _pexels_search_images(query: str, count: int = 10, orientation: str = "landscape") -> list[dict]:
    params = {
        "query": query,
        "per_page": min(count * 2, 30),
        "orientation": orientation,
    }
    resp = requests.get(PEXELS_PHOTOS_URL, headers=_pexels_headers(), params=params, timeout=15)
    resp.raise_for_status()
    photos = resp.json().get("photos", [])
    random.shuffle(photos)
    return photos[:count]


def _pexels_download_video(video: dict, output_dir: Path, quality: str = "sd") -> Optional[Path]:
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
    filename = output_dir / f"pexels_{video['id']}.mp4"
    if filename.exists():
        return filename

    resp = requests.get(target["link"], stream=True, timeout=60)
    resp.raise_for_status()
    with open(filename, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return filename


def _pexels_download_image(photo: dict, output_dir: Path, size: str = "large") -> Optional[Path]:
    src = photo.get("src", {})
    url = src.get(size) or src.get("large") or src.get("original")
    if not url:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    filename = output_dir / f"pexels_{photo['id']}.jpg"
    if filename.exists():
        return filename

    resp = requests.get(url, stream=True, timeout=30)
    resp.raise_for_status()
    with open(filename, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return filename


# ── Public API ───────────────────────────────────────────────────────────────

def _build_queries(keywords: list[str]) -> list[str]:
    """Build multiple search queries from keywords for better hit rate."""
    queries = []
    if keywords:
        queries.append(" ".join(keywords[:3]))
        for kw in keywords[:3]:
            if kw not in queries:
                queries.append(kw)
    return queries


def fetch_media_for_topic(
    keywords: list[str],
    output_dir: Path,
    video_count: int = 5,
    is_portrait: bool = False,
) -> tuple[list[Path], list[Path]]:
    """Fetch a mix of videos and images. Tries Pixabay first, then Pexels."""
    orientation_pixabay = "vertical" if is_portrait else "horizontal"
    orientation_pexels = "portrait" if is_portrait else "landscape"
    queries = _build_queries(keywords)

    video_paths = []
    image_paths = []

    # ── Try Pixabay first ──
    if config.PIXABAY_API_KEY:
        print(f"[media] Trying Pixabay with queries: {queries}")
        for query in queries:
            if len(video_paths) >= video_count and len(image_paths) >= 6:
                break
            try:
                videos = _pixabay_search_videos(query, count=video_count, orientation=orientation_pixabay)
                print(f"[media] Pixabay videos for '{query}': {len(videos)} results")
                for v in videos:
                    if len(video_paths) >= video_count:
                        break
                    try:
                        path = _pixabay_download_video(v, output_dir / "stock_videos")
                        if path:
                            video_paths.append(path)
                    except Exception as e:
                        print(f"[media] Pixabay video download failed: {e}")
            except Exception as e:
                print(f"[media] Pixabay video search failed for '{query}': {e}")

            try:
                photos = _pixabay_search_images(query, count=8, orientation=orientation_pixabay)
                print(f"[media] Pixabay images for '{query}': {len(photos)} results")
                for p in photos:
                    if len(image_paths) >= 10:
                        break
                    try:
                        path = _pixabay_download_image(p, output_dir / "stock_images")
                        if path:
                            image_paths.append(path)
                    except Exception as e:
                        print(f"[media] Pixabay image download failed: {e}")
            except Exception as e:
                print(f"[media] Pixabay image search failed for '{query}': {e}")

    # ── Pexels — always try if we don't have enough media ──
    if config.PEXELS_API_KEY and (len(video_paths) < video_count or len(image_paths) < 4):
        print(f"[media] Trying Pexels fallback (have {len(video_paths)} videos, {len(image_paths)} images)")
        for query in queries:
            if len(video_paths) >= video_count and len(image_paths) >= 6:
                break
            try:
                videos = _pexels_search_videos(query, count=video_count, orientation=orientation_pexels)
                for v in videos:
                    if len(video_paths) >= video_count:
                        break
                    try:
                        path = _pexels_download_video(v, output_dir / "stock_videos")
                        if path:
                            video_paths.append(path)
                    except Exception as e:
                        print(f"[media] Pexels video download failed: {e}")
            except Exception as e:
                print(f"[media] Pexels video search failed for '{query}': {e}")

            try:
                photos = _pexels_search_images(query, count=8, orientation=orientation_pexels)
                for p in photos:
                    if len(image_paths) >= 10:
                        break
                    try:
                        path = _pexels_download_image(p, output_dir / "stock_images")
                        if path:
                            image_paths.append(path)
                    except Exception as e:
                        print(f"[media] Pexels image download failed: {e}")
            except Exception as e:
                print(f"[media] Pexels image search failed for '{query}': {e}")

    if not config.PIXABAY_API_KEY and not config.PEXELS_API_KEY:
        print("[media] WARNING: No PIXABAY_API_KEY or PEXELS_API_KEY set — no stock media available")

    print(f"[media] Final: {len(video_paths)} videos, {len(image_paths)} images downloaded")
    return video_paths, image_paths


# Legacy aliases
search_videos = _pexels_search_videos
search_images = _pexels_search_images
download_video = _pexels_download_video
download_image = _pexels_download_image
