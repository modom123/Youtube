"""
Storage Archiver Agent — background thread that uploads completed jobs'
video/audio to S3-compatible object storage (AWS S3, Cloudflare R2,
Backblaze B2, Supabase Storage's S3-compatible endpoint, ...) so there's a
durable off-disk copy of every video.

Purely additive: it never deletes or modifies the local file, and does
nothing at all if S3_BUCKET isn't configured (config.py's existing
media_host.py fallback already serves media straight off local disk in that
case, so there is nothing to archive to). This is a prerequisite for ever
safely reclaiming local disk space -- you cannot decide a local video is safe
to delete until you've confirmed it has a durable copy elsewhere.

Runs every STORAGE_ARCHIVER_INTERVAL seconds (default: 10 minutes),
archiving a bounded batch per pass so a large backlog of already-completed
jobs doesn't try to upload everything at once.
"""
from __future__ import annotations
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


_thread: threading.Thread | None = None
_stop_event = threading.Event()


def _loop() -> None:
    print("[storage_archiver] Storage archiver agent started")
    while not _stop_event.wait(timeout=STORAGE_ARCHIVER_INTERVAL):
        try:
            _archive_batch()
        except Exception as e:
            print(f"[storage_archiver] Unexpected error: {e}")
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
