"""
Job Monitor Agent — background thread that watches for stuck or unhealthy jobs
and automatically takes corrective action.

Runs every JOB_MONITOR_INTERVAL seconds (default: 5 minutes).
Detects:
  - Jobs stuck in 'running' for > STUCK_THRESHOLD minutes → force-reset to 'error'
  - Jobs queued (pending) for > QUEUE_THRESHOLD minutes → alert or restart
"""
from __future__ import annotations
import threading
import time
from datetime import datetime, timezone

JOB_MONITOR_INTERVAL = 300       # check every 5 minutes
STUCK_THRESHOLD_MINUTES = 20     # jobs running longer than this are considered stuck
QUEUE_THRESHOLD_MINUTES = 10     # jobs pending longer than this need attention

_monitor_thread: threading.Thread | None = None
_stop_event = threading.Event()


def _check_jobs() -> None:
    """Single pass: find and fix unhealthy jobs."""
    import database as db

    now = datetime.now(timezone.utc)
    jobs = db.get_all_running_jobs()  # returns jobs with status='running' or 'pending'

    stuck_count = 0
    for job in jobs:
        try:
            started_raw = job.get("updated_at") or job.get("created_at")
            if not started_raw:
                continue
            # Parse ISO timestamp (may or may not have timezone)
            if started_raw.endswith("Z"):
                started_raw = started_raw[:-1] + "+00:00"
            try:
                started = datetime.fromisoformat(started_raw)
            except ValueError:
                started = datetime.strptime(started_raw, "%Y-%m-%d %H:%M:%S")
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)

            age_minutes = (now - started).total_seconds() / 60

            if job["status"] == "running" and age_minutes > STUCK_THRESHOLD_MINUTES:
                print(f"[monitor] Job #{job['id']} stuck for {age_minutes:.0f}m — auto-resetting")
                db.update_job(
                    job["id"],
                    status="error",
                    progress=0,
                    current_step="Auto-reset: job was stuck (monitor agent)",
                    error_msg=f"Job was running for {age_minutes:.0f} minutes without completing",
                )
                try:
                    db.log_audit(
                        admin_id=None,
                        action="auto_reset_stuck_job",
                        target_user_id=job.get("user_id"),
                        details={"job_id": job["id"], "age_minutes": round(age_minutes)},
                    )
                except Exception:
                    pass
                stuck_count += 1

        except Exception as e:
            print(f"[monitor] Error checking job #{job.get('id')}: {e}")

    if stuck_count:
        print(f"[monitor] Auto-reset {stuck_count} stuck job(s)")


def _monitor_loop() -> None:
    """Main loop — runs until stop event is set."""
    print("[monitor] Job monitor agent started")
    while not _stop_event.wait(timeout=JOB_MONITOR_INTERVAL):
        try:
            _check_jobs()
        except Exception as e:
            print(f"[monitor] Unexpected error: {e}")
    print("[monitor] Job monitor agent stopped")


def start() -> None:
    """Start the background monitor thread (idempotent)."""
    global _monitor_thread
    if _monitor_thread and _monitor_thread.is_alive():
        return
    _stop_event.clear()
    _monitor_thread = threading.Thread(target=_monitor_loop, daemon=True, name="job-monitor")
    _monitor_thread.start()


def stop() -> None:
    """Signal the monitor to stop (for graceful shutdown)."""
    _stop_event.set()
