"""
Asset Tracker Agent — background worker that monitors completed jobs and
auto-creates agency assets with tracking numbers when jobs are linked
to clients or projects.

Runs every ASSET_CHECK_INTERVAL seconds (default: 2 minutes).
"""
from __future__ import annotations
import threading

ASSET_CHECK_INTERVAL = 120

_thread: threading.Thread | None = None
_stop = threading.Event()


def _check_completed_jobs() -> None:
    import database as db

    with db.get_conn() as conn:
        rows = conn.execute("""
            SELECT j.* FROM jobs j
            WHERE j.status = 'done'
              AND j.client_id IS NOT NULL
              AND j.id NOT IN (SELECT COALESCE(job_id,0) FROM agency_assets)
        """).fetchall()
        jobs = [db.row_to_dict(r) for r in rows]

    for job in jobs:
        asset_type = "video"
        if job.get("format") in ("podcast", "audio", "music"):
            asset_type = "audio"
        elif job.get("format") in ("image", "thumbnail"):
            asset_type = "image"

        result = db.create_agency_asset(job["user_id"], {
            "client_id": job["client_id"],
            "project_id": job.get("project_id"),
            "job_id": job["id"],
            "asset_type": asset_type,
            "title": job.get("title") or job.get("topic", "Untitled"),
            "file_path": job.get("video_path") or job.get("audio_path") or "",
            "thumbnail": job.get("thumbnail_path") or "",
            "status": "ready",
        })

        db.update_job(job["id"], asset_number=result["asset_number"])

        if job.get("project_id"):
            db.update_agency_project(job["user_id"], job["project_id"], {
                "videos_used": _get_project_video_count(job["user_id"], job["project_id"])
            })

        print(f"[AssetTracker] Created asset {result['asset_number']} for job {job['id']} → client {job['client_id']}")


def _get_project_video_count(user_id, project_id):
    import database as db
    with db.get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM agency_assets WHERE user_id=? AND project_id=?",
            (user_id, project_id)).fetchone()[0]


def _run():
    while not _stop.wait(ASSET_CHECK_INTERVAL):
        try:
            _check_completed_jobs()
        except Exception as e:
            print(f"[AssetTracker] Error: {e}")


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_run, daemon=True, name="asset-tracker")
    _thread.start()
    print("[AssetTracker] Started — checking every 2 min")
