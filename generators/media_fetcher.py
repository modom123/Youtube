"""Fetch stock video clips and images — Pixabay primary, Mixkit fallback."""
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


# ── Mixkit (no API key required) ─────────────────────────────────────────────

MIXKIT_SEARCH_URL = "https://mixkit.co/free-stock-video/"

# Curated Mixkit CDN clips by category — no API key needed, direct download
MIXKIT_CLIPS = {
    "nature":      ["https://assets.mixkit.co/videos/preview/mixkit-forest-stream-in-the-sunlight-529-large.mp4",
                    "https://assets.mixkit.co/videos/preview/mixkit-tree-with-yellow-flowers-1173-large.mp4",
                    "https://assets.mixkit.co/videos/preview/mixkit-waves-in-the-open-sea-1164-large.mp4"],
    "city":        ["https://assets.mixkit.co/videos/preview/mixkit-timelapse-of-a-city-from-the-top-of-a-building-4-large.mp4",
                    "https://assets.mixkit.co/videos/preview/mixkit-aerial-view-of-city-traffic-at-night-11-large.mp4"],
    "technology":  ["https://assets.mixkit.co/videos/preview/mixkit-hands-typing-on-laptop-keyboard-2568-large.mp4",
                    "https://assets.mixkit.co/videos/preview/mixkit-digital-animation-of-futuristic-devices-99786-large.mp4"],
    "business":    ["https://assets.mixkit.co/videos/preview/mixkit-business-woman-working-in-the-office-4045-large.mp4",
                    "https://assets.mixkit.co/videos/preview/mixkit-colleagues-working-in-an-office-4037-large.mp4"],
    "abstract":    ["https://assets.mixkit.co/videos/preview/mixkit-abstract-technology-blur-background-2588-large.mp4",
                    "https://assets.mixkit.co/videos/preview/mixkit-particle-explosion-1-large.mp4"],
    "default":     ["https://assets.mixkit.co/videos/preview/mixkit-white-sand-beach-and-palm-trees-1564-large.mp4",
                    "https://assets.mixkit.co/videos/preview/mixkit-clouds-and-blue-sky-2408-large.mp4",
                    "https://assets.mixkit.co/videos/preview/mixkit-forest-stream-in-the-sunlight-529-large.mp4"],
}


def _mixkit_category(keywords: list[str]) -> str:
    kw_str = " ".join(keywords).lower()
    for cat in ["nature", "city", "technology", "business", "abstract"]:
        if cat in kw_str or any(w in kw_str for w in {"tech", "digital", "ai", "code", "software"} if cat == "technology") or \
           any(w in kw_str for w in {"urban", "street", "downtown"} if cat == "city"):
            return cat
    return "default"


def _mixkit_fetch_videos(keywords: list[str], count: int, output_dir: Path) -> list[Path]:
    cat = _mixkit_category(keywords)
    urls = MIXKIT_CLIPS.get(cat, MIXKIT_CLIPS["default"])
    random.shuffle(urls)
    paths = []
    for url in urls[:count]:
        try:
            fname = output_dir / f"mixkit_{url.split('/')[-1]}"
            if fname.exists():
                paths.append(fname)
                continue
            output_dir.mkdir(parents=True, exist_ok=True)
            resp = requests.get(url, stream=True, timeout=30,
                                headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                with open(fname, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                if fname.stat().st_size > 10000:
                    paths.append(fname)
                else:
                    fname.unlink(missing_ok=True)
        except Exception as e:
            print(f"[media] Mixkit download failed: {e}")
    return paths


# ── Public API ───────────────────────────────────────────────────────────────

def _build_queries(keywords: list[str]) -> list[str]:
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
    """Fetch a mix of videos and images. Pixabay primary, Mixkit fallback (no API key needed)."""
    orientation = "vertical" if is_portrait else "horizontal"
    queries = _build_queries(keywords)

    video_paths: list[Path] = []
    image_paths: list[Path] = []

    # ── Pixabay (primary) ──
    if config.PIXABAY_API_KEY:
        print(f"[media] Trying Pixabay with queries: {queries}")
        for query in queries:
            if len(video_paths) >= video_count and len(image_paths) >= 6:
                break
            try:
                videos = _pixabay_search_videos(query, count=video_count, orientation=orientation)
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
                photos = _pixabay_search_images(query, count=8, orientation=orientation)
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

    # ── Mixkit fallback (no API key required) ──
    if len(video_paths) < video_count:
        needed = video_count - len(video_paths)
        print(f"[media] Mixkit fallback — fetching {needed} clips")
        try:
            mk_paths = _mixkit_fetch_videos(keywords, needed, output_dir / "stock_videos")
            video_paths.extend(mk_paths)
        except Exception as e:
            print(f"[media] Mixkit fallback failed: {e}")

    if not config.PIXABAY_API_KEY:
        print("[media] No PIXABAY_API_KEY set — using Mixkit fallback only")

    print(f"[media] Final: {len(video_paths)} videos, {len(image_paths)} images")
    return video_paths, image_paths


# Aliases for any code that imports these directly
search_videos = _pixabay_search_videos
search_images = _pixabay_search_images
download_video = _pixabay_download_video
download_image = _pixabay_download_image
