"""Fetch stock video clips and images — Pexels primary, Mixkit fallback.

Note: Pixabay's API terms prohibit use in automated/AI content-generation
pipelines (per their licensing team, 2026-06-29). Pexels' API terms permit
this kind of automated, programmatic use, so it replaces Pixabay here.
"""
import random
from pathlib import Path
from typing import Optional
import requests
import config


# ── Pexels ───────────────────────────────────────────────────────────────────

PEXELS_VIDEOS_URL = "https://api.pexels.com/videos/search"
PEXELS_PHOTOS_URL = "https://api.pexels.com/v1/search"


def _pexels_headers() -> dict:
    return {"Authorization": config.PEXELS_API_KEY}


def _pexels_search_videos(query: str, count: int = 8, orientation: str = "landscape") -> list[dict]:
    params = {
        "query": query,
        "per_page": min(count * 2, 20),
        "orientation": orientation,
    }
    resp = requests.get(PEXELS_VIDEOS_URL, params=params, headers=_pexels_headers(), timeout=15)
    resp.raise_for_status()
    hits = resp.json().get("videos", [])
    random.shuffle(hits)
    return hits[:count]


def _pexels_search_images(query: str, count: int = 10, orientation: str = "landscape") -> list[dict]:
    params = {
        "query": query,
        "per_page": min(count * 2, 30),
        "orientation": orientation,
    }
    resp = requests.get(PEXELS_PHOTOS_URL, params=params, headers=_pexels_headers(), timeout=15)
    resp.raise_for_status()
    hits = resp.json().get("photos", [])
    random.shuffle(hits)
    return hits[:count]


def _pexels_download_video(video: dict, output_dir: Path) -> Optional[Path]:
    files = sorted(video.get("video_files", []), key=lambda f: f.get("width") or 0)
    url = None
    for f in files:
        w = f.get("width") or 0
        if 480 <= w <= 1280:
            url = f.get("link")
            break
    if not url and files:
        url = files[0].get("link")
    if not url:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    filename = output_dir / f"pexels_{video.get('id', 0)}.mp4"
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


def _pexels_download_image(photo: dict, output_dir: Path) -> Optional[Path]:
    src = photo.get("src", {})
    url = src.get("large") or src.get("medium") or src.get("original")
    if not url:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    filename = output_dir / f"pexels_{photo.get('id', 0)}.jpg"
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
    "sports":      ["https://assets.mixkit.co/videos/preview/mixkit-football-player-kicking-the-ball-in-a-stadium-40390-large.mp4",
                    "https://assets.mixkit.co/videos/preview/mixkit-soccer-stadium-with-a-full-crowd-40394-large.mp4",
                    "https://assets.mixkit.co/videos/preview/mixkit-crowd-cheering-in-a-soccer-stadium-40396-large.mp4",
                    "https://assets.mixkit.co/videos/preview/mixkit-aerial-view-of-a-soccer-field-42954-large.mp4"],
    "default":     ["https://assets.mixkit.co/videos/preview/mixkit-white-sand-beach-and-palm-trees-1564-large.mp4",
                    "https://assets.mixkit.co/videos/preview/mixkit-clouds-and-blue-sky-2408-large.mp4",
                    "https://assets.mixkit.co/videos/preview/mixkit-forest-stream-in-the-sunlight-529-large.mp4"],
}

_SPORTS_KEYWORDS = {
    "soccer", "football", "basketball", "tennis", "baseball", "stadium", "arena", "sport",
    "athlete", "game", "match", "team", "player", "league", "championship", "olympic",
    "fifa", "nfl", "nba", "mlb", "nhl", "cricket", "rugby", "golf", "swimming",
}

def _mixkit_category(keywords: list[str]) -> str:
    kw_str = " ".join(keywords).lower()
    kw_words = set(kw_str.split())
    if kw_words & _SPORTS_KEYWORDS or any(w in kw_str for w in _SPORTS_KEYWORDS):
        return "sports"
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


# ── Wikimedia Commons (real, named people — free, no API key, no licensing risk) ──

WIKIMEDIA_API_URL = "https://commons.wikimedia.org/w/api.php"


def _wikimedia_search_person_images(name: str, count: int = 6) -> list[dict]:
    """Search Wikimedia Commons for real photos of a named public figure.

    Commons hosts only public-domain / CC-licensed media, so anything returned
    here is legally safe to use — unlike pulling broadcast (ESPN/TNT/CBS) footage,
    which is copyrighted and NOT available through this or any consumer API.
    """
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f'{name} filetype:bitmap',
        "gsrnamespace": 6,  # File: namespace
        "gsrlimit": count * 2,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|size",
        "iiurlwidth": 1280,
    }
    resp = requests.get(WIKIMEDIA_API_URL, params=params, timeout=15,
                         headers={"User-Agent": "SocialOptimizeBot/1.0 (video production asset search)"})
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", {})
    hits = []
    for page in pages.values():
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        url = info.get("thumburl") or info.get("url")
        width = info.get("thumbwidth") or info.get("width") or 0
        if not url or width < 400:
            continue
        hits.append({"title": page.get("title", ""), "url": url})
    random.shuffle(hits)
    return hits[:count]


def _wikimedia_download_image(hit: dict, output_dir: Path) -> Optional[Path]:
    url = hit.get("url")
    if not url:
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c if c.isalnum() else "_" for c in hit.get("title", "wikimedia"))[:80]
    filename = output_dir / f"wikimedia_{safe_name}.jpg"
    if filename.exists():
        return filename
    resp = requests.get(url, stream=True, timeout=30,
                         headers={"User-Agent": "SocialOptimizeBot/1.0"})
    resp.raise_for_status()
    with open(filename, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    if filename.stat().st_size < 1000:
        filename.unlink(missing_ok=True)
        return None
    return filename


def fetch_person_images(name: str, output_dir: Path, count: int = 4) -> list[Path]:
    """Fetch real, legally-clean photos of a named real person from Wikimedia Commons.

    Returns an empty list if no usable photos are found (caller should fall back
    to generic stock — there is no API for licensed broadcast/ESPN/TNT/CBS footage).
    """
    name = (name or "").strip()
    if not name:
        return []
    paths: list[Path] = []
    try:
        hits = _wikimedia_search_person_images(name, count=count)
        print(f"[media] Wikimedia Commons for '{name}': {len(hits)} results")
        for hit in hits:
            try:
                path = _wikimedia_download_image(hit, output_dir / "person_photos")
                if path:
                    paths.append(path)
            except Exception as e:
                print(f"[media] Wikimedia download failed for '{name}': {e}")
    except Exception as e:
        print(f"[media] Wikimedia search failed for '{name}': {e}")
    return paths


# ── Public API ───────────────────────────────────────────────────────────────

# Sports/slang acronyms and abbreviations that collide with literal English words
# or are meaningless to a stock-footage search engine — these get matched literally
# (e.g. "GOAT" → real farm goats) and have produced wrong/embarrassing footage.
# This is a hard backstop independent of the LLM curator, since per-section script
# text doesn't always restate a player's name (e.g. "Who is the GOAT of the NBA?",
# "Who has the most Finals MVPs?") for the curator to extract.
_AMBIGUOUS_TERMS = {
    "goat", "goats", "mvp", "mvps", "ring", "rings", "champ", "champs",
}


def _sanitize_keywords(keywords: list[str]) -> list[str]:
    """Strip ambiguous slang/acronym tokens from a keyword list before searching."""
    cleaned = []
    for kw in keywords:
        words = [w for w in kw.split() if w.lower().strip(".,!?") not in _AMBIGUOUS_TERMS]
        if words:
            cleaned.append(" ".join(words))
    return cleaned


def _build_queries(keywords: list[str]) -> list[str]:
    keywords = _sanitize_keywords(keywords)
    if not keywords:
        keywords = ["sports arena crowd"]
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
    """Fetch a mix of videos and images. Pexels primary, Mixkit fallback (no API key needed)."""
    orientation = "portrait" if is_portrait else "landscape"
    queries = _build_queries(keywords)

    video_paths: list[Path] = []
    image_paths: list[Path] = []

    # ── Pexels (primary) ──
    if config.PEXELS_API_KEY:
        print(f"[media] Trying Pexels with queries: {queries}")
        for query in queries:
            if len(video_paths) >= video_count and len(image_paths) >= 6:
                break
            try:
                videos = _pexels_search_videos(query, count=video_count, orientation=orientation)
                print(f"[media] Pexels videos for '{query}': {len(videos)} results")
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
                photos = _pexels_search_images(query, count=8, orientation=orientation)
                print(f"[media] Pexels images for '{query}': {len(photos)} results")
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

    # ── Mixkit fallback (no API key required) ──
    if len(video_paths) < video_count:
        needed = video_count - len(video_paths)
        print(f"[media] Mixkit fallback — fetching {needed} clips")
        try:
            mk_paths = _mixkit_fetch_videos(keywords, needed, output_dir / "stock_videos")
            video_paths.extend(mk_paths)
        except Exception as e:
            print(f"[media] Mixkit fallback failed: {e}")

    if not config.PEXELS_API_KEY:
        print("[media] No PEXELS_API_KEY set — using Mixkit fallback only")

    print(f"[media] Final: {len(video_paths)} videos, {len(image_paths)} images")
    return video_paths, image_paths


# Aliases for any code that imports these directly
search_videos = _pexels_search_videos
search_images = _pexels_search_images
download_video = _pexels_download_video
download_image = _pexels_download_image
