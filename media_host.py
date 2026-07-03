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
