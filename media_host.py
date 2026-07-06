"""Public media hosting — give local render files a publicly reachable URL.

Instagram Reels and Threads can only ingest videos from a public URL; the
Meta Graph API has no direct file upload. Two strategies, tried in order:

1. S3-compatible object storage (AWS S3, Cloudflare R2, Backblaze B2) when
   S3_BUCKET + credentials are configured. The file is uploaded once and a
   public/CDN URL is returned.
2. Self-serve fallback: the app serves the file itself at an HMAC-signed
   public URL under MEDIA_PUBLIC_BASE_URL (defaults to APP_BASE_URL). Works
   with zero extra config anywhere the app is internet-reachable (Render).
"""
import hashlib
import hmac
from pathlib import Path
from urllib.parse import quote

import config
from utils import logger


# ── Signed self-serve URLs ────────────────────────────────────────────────────

def sign_media_path(relpath: str) -> str:
    """HMAC signature for a path relative to OUTPUT_DIR."""
    return hmac.new(
        config.SECRET_KEY.encode(), relpath.encode(), hashlib.sha256
    ).hexdigest()[:32]


def verify_media_sig(relpath: str, sig: str) -> bool:
    return hmac.compare_digest(sign_media_path(relpath), sig)


def _self_serve_url(video_path: Path) -> str:
    """Public URL served by the app itself for files under OUTPUT_DIR."""
    try:
        relpath = video_path.resolve().relative_to(Path(config.OUTPUT_DIR).resolve()).as_posix()
    except ValueError:
        return ""
    base = (config.MEDIA_PUBLIC_BASE_URL or config.APP_BASE_URL).rstrip("/")
    if not base.startswith("http"):
        return ""
    return f"{base}/public/media/{sign_media_path(relpath)}/{quote(relpath)}"


# ── S3-compatible upload ──────────────────────────────────────────────────────

def _s3_configured() -> bool:
    return bool(config.S3_BUCKET and config.S3_ACCESS_KEY_ID and config.S3_SECRET_ACCESS_KEY)


def _s3_client():
    import boto3
    kwargs = {
        "aws_access_key_id": config.S3_ACCESS_KEY_ID,
        "aws_secret_access_key": config.S3_SECRET_ACCESS_KEY,
        "region_name": config.S3_REGION or "auto",
    }
    if config.S3_ENDPOINT_URL:
        kwargs["endpoint_url"] = config.S3_ENDPOINT_URL
    return boto3.client("s3", **kwargs)


def _s3_key(video_path: Path) -> str:
    """Deterministic key from file identity so re-publishing reuses the upload."""
    stat = video_path.stat()
    digest = hashlib.sha1(
        f"{video_path.name}:{stat.st_size}:{int(stat.st_mtime)}".encode()
    ).hexdigest()[:16]
    return f"public/{digest}/{video_path.name}"


def _s3_url(key: str) -> str:
    if config.S3_PUBLIC_BASE_URL:
        return f"{config.S3_PUBLIC_BASE_URL.rstrip('/')}/{quote(key)}"
    if config.S3_ENDPOINT_URL:
        return f"{config.S3_ENDPOINT_URL.rstrip('/')}/{config.S3_BUCKET}/{quote(key)}"
    region = config.S3_REGION or "us-east-1"
    return f"https://{config.S3_BUCKET}.s3.{region}.amazonaws.com/{quote(key)}"


def _upload_s3(video_path: Path) -> str:
    client = _s3_client()
    key = _s3_key(video_path)
    try:
        client.head_object(Bucket=config.S3_BUCKET, Key=key)
    except Exception:
        content_type = "video/mp4" if video_path.suffix.lower() in (".mp4", ".m4v") else "application/octet-stream"
        client.upload_file(
            str(video_path), config.S3_BUCKET, key,
            ExtraArgs={"ContentType": content_type, "ACL": "public-read"}
            if not config.S3_ENDPOINT_URL else {"ContentType": content_type},
        )
    return _s3_url(key)


# ── Entry point ───────────────────────────────────────────────────────────────

def verify_archived(local_path) -> bool:
    """Re-check, right before deleting a local file, that the object storage
    copy genuinely exists and matches the local file's size. The DB's
    video_storage_url being set only means the upload succeeded at the time
    it ran -- this is the actual safety check that has to pass immediately
    before any local deletion, not a cached assumption from days ago."""
    if not _s3_configured():
        return False
    try:
        local_path = Path(local_path)
        if not local_path.is_file():
            return False
        client = _s3_client()
        key = _s3_key(local_path)
        head = client.head_object(Bucket=config.S3_BUCKET, Key=key)
        return head.get("ContentLength", -1) == local_path.stat().st_size
    except Exception as e:
        logger.warn(f"media_host.verify_archived failed for {local_path}: {e}")
        return False


def get_public_url(video_path) -> str:
    """Return a publicly reachable URL for a local media file, or "" if none
    can be produced. Never raises."""
    try:
        path = Path(video_path)
        if not path.is_file():
            return ""
        if _s3_configured():
            try:
                return _upload_s3(path)
            except Exception as e:
                logger.warn(f"S3 upload failed, falling back to self-serve: {e}")
        return _self_serve_url(path)
    except Exception as e:
        logger.warn(f"media_host.get_public_url failed: {e}")
        return ""


def resolve_or_download(job: dict, path_field: str, url_field: str) -> "Path | None":
    """Return a usable LOCAL path for a job's media, for callers (ffmpeg
    remux, re-voice, editing) that need real bytes on disk, not a redirect.

    If the local file still exists, returns it as-is -- zero extra cost, the
    common case. If it's been reclaimed after being archived, downloads the
    durable copy into a local cache directory and returns that path instead,
    so editing operations keep working transparently after local cleanup.
    Returns None if neither a local file nor an archived URL is available.
    """
    local = job.get(path_field)
    if local and Path(local).is_file():
        return Path(local)

    url = job.get(url_field)
    if not url:
        return None

    try:
        import requests
        cache_dir = Path(config.OUTPUT_DIR) / "_storage_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        dest = cache_dir / f"{job.get('id', 'x')}_{Path(url).name.split('?')[0] or 'media'}"
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        resp = requests.get(url, stream=True, timeout=120)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)
        return dest if dest.exists() and dest.stat().st_size > 0 else None
    except Exception as e:
        logger.warn(f"media_host.resolve_or_download failed for job {job.get('id')}: {e}")
        return None


def archive_to_storage(path) -> str:
    """Upload a local file to S3-compatible object storage and return its
    durable URL, or "" if S3 isn't configured or the upload fails. Unlike
    get_public_url(), this never falls back to a self-serve signed URL --
    that URL only works while the local file still exists, which defeats the
    point of archiving it. Never raises; never deletes the local file itself
    (that's the caller's decision once it has confirmed the archive)."""
    if not _s3_configured():
        return ""
    try:
        path = Path(path)
        if not path.is_file():
            return ""
        return _upload_s3(path)
    except Exception as e:
        logger.warn(f"media_host.archive_to_storage failed for {path}: {e}")
        return ""
