"""
Storage Archiver Agent — background thread that uploads completed jobs'
video/audio to S3-compatible object storage (AWS S3, Cloudflare R2,
Backblaze B2, Supabase Storage's S3-compatible endpoint, ...) so there's a
durable off-disk copy of every video, and optionally reclaims the local
disk copy once that's confirmed.

Two independent stages, each with its own safety gate:

1. Archive — does nothing at all if S3_BUCKET isn't configured. Purely
   additive: uploads a copy, never touches the local file.
2. Reclaim (local disk cleanup) — OFF by default even when archiving is
   configured. Requires explicitly setting STORAGE_RECLAIM_LOCAL=1, only
   considers jobs archived more than STORAGE_RECLAIM_GRACE_DAYS ago
   (default 14), and re-verifies the remote copy exists AND matches the
   local file's size immediately before deleting anything -- the DB flag
   being set only proves the upload succeeded at the time it ran.

Runs every STORAGE_ARCHIVER_INTERVAL seconds (default: 10 minutes),
processing a bounded batch per pass so a large backlog doesn't try to
upload/reclaim everything at once.
"""
from __future__ import annotations
import os
import threading

STORAGE_ARCHIVER_INTERVAL = 600  # 10 minutes
BATCH_SIZE = 20


def _archive_batch() -> None:
    import config
    if not (config.S3_BUCKET and config.S3_ACCESS_KEY_ID and config.S3_SECRET_ACCESS_KEY):
        return  # nothing configured to archive to -- stay quiet, don't spam logs every cycle

    import database as db
    import media_host
    from datetime import datetime, timezone

    jobs = db.get_jobs_needing_archive(limit=BATCH_SIZE)
    if not jobs:
        return

    archived = 0
    for job in jobs:
        try:
            video_url = media_host.archive_to_storage(job.get("video_path"))
            if not video_url:
                continue  # upload failed or file missing -- leave it for the next pass
            updates = {"video_storage_url": video_url, "archived_at": datetime.now(timezone.utc)}
            audio_path = job.get("audio_path")
            if audio_path and not job.get("audio_storage_url"):
                audio_url = media_host.archive_to_storage(audio_path)
                if audio_url:
                    updates["audio_storage_url"] = audio_url
            db.update_job(job["id"], **updates)
            archived += 1
        except Exception as e:
            print(f"[storage_archiver] Job #{job.get('id')} archive failed: {e}")

    if archived:
        print(f"[storage_archiver] Archived {archived}/{len(jobs)} job(s) to object storage")


def _truthy(val: str) -> bool:
    return (val or "").strip().lower() in ("1", "true", "yes", "on")


def _reclaim_batch() -> None:
    if not _truthy(os.getenv("STORAGE_RECLAIM_LOCAL", "0")):
        return  # explicit opt-in required, separate from just having S3 configured

    import config
    if not (config.S3_BUCKET and config.S3_ACCESS_KEY_ID and config.S3_SECRET_ACCESS_KEY):
        return

    import database as db
    import media_host
    from pathlib import Path

    grace_days = float(os.getenv("STORAGE_RECLAIM_GRACE_DAYS", "14"))
    jobs = db.get_jobs_ready_for_reclaim(grace_days=grace_days, limit=BATCH_SIZE)
    if not jobs:
        return

    reclaimed_count = 0
    reclaimed_bytes = 0
    for job in jobs:
        for path_field, url_field in (("video_path", "video_storage_url"),
                                       ("audio_path", "audio_storage_url")):
            local, url = job.get(path_field), job.get(url_field)
            if not local or not url:
                continue
            p = Path(local)
            if not p.is_file():
                continue  # already gone -- nothing to reclaim
            try:
                if not media_host.verify_archived(p):
                    print(f"[storage_archiver] Job #{job['id']} {path_field}: "
                          f"remote copy not verified, skipping reclaim this pass")
                    continue
                size = p.stat().st_size
                p.unlink()
                reclaimed_count += 1
                reclaimed_bytes += size
            except Exception as e:
                print(f"[storage_archiver] Job #{job['id']} reclaim failed for {path_field}: {e}")

    if reclaimed_count:
        print(f"[storage_archiver] Reclaimed {reclaimed_count} local file(s), "
              f"{reclaimed_bytes / 1024 / 1024:.1f} MB freed")


_thread: threading.Thread | None = None
_stop_event = threading.Event()


def _loop() -> None:
    print("[storage_archiver] Storage archiver agent started")
    while not _stop_event.wait(timeout=STORAGE_ARCHIVER_INTERVAL):
        try:
            _archive_batch()
        except Exception as e:
            print(f"[storage_archiver] Unexpected error: {e}")
        try:
            _reclaim_batch()
        except Exception as e:
            print(f"[storage_archiver] Unexpected error during reclaim: {e}")
    print("[storage_archiver] Storage archiver agent stopped")


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="storage-archiver")
    _thread.start()


def stop() -> None:
    _stop_event.set()
