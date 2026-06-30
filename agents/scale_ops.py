"""
Scale-Ops Agent — daemon thread that monitors business metrics and
recommends infrastructure upgrades based on growth phase.

Runs every SCALE_OPS_INTERVAL seconds (default: 30 minutes).
"""
from __future__ import annotations
import os
import shutil
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCALE_OPS_INTERVAL = 1800  # 30 minutes

# ── Infrastructure Phases ─────────────────────────────────────────────────────

PHASES = {
    0: {"max_users": 100, "label": "Bootstrap",
        "stack": "SQLite, local disk, threading"},
    1: {"max_users": 500, "label": "Foundation",
        "stack": "PostgreSQL, Redis, S3"},
    2: {"max_users": 2000, "label": "Growth",
        "stack": "Dedicated workers (RQ/Celery), CDN, monitoring"},
    3: {"max_users": 10_000, "label": "Scale",
        "stack": "AWS ECS, RDS Multi-AZ, auto-scaling"},
    4: {"max_users": 50_000, "label": "Platform",
        "stack": "Service-oriented arch, React frontend, FastAPI"},
    5: {"max_users": 200_000, "label": "Enterprise",
        "stack": "Multi-region, Kubernetes, read replicas"},
    6: {"max_users": float("inf"), "label": "Hyperscale",
        "stack": "Microservices, data lake, ML infrastructure"},
}

PHASE_RECOMMENDATIONS: dict[int, list[dict]] = {
    1: [
        {"category": "database", "title": "Migrate to PostgreSQL",
         "description": "SQLite will hit write-lock contention above ~100 concurrent users.",
         "priority": "critical", "estimated_cost": "$50-200/mo", "estimated_effort": "1-2 weeks"},
        {"category": "cache", "title": "Add Redis for sessions & caching",
         "description": "Offload session storage and job queues from SQLite.",
         "priority": "high", "estimated_cost": "$15-50/mo", "estimated_effort": "3-5 days"},
        {"category": "storage", "title": "Migrate file storage to S3",
         "description": "Local disk won't survive server replacements or horizontal scaling.",
         "priority": "high", "estimated_cost": "$5-50/mo", "estimated_effort": "1 week"},
    ],
    2: [
        {"category": "workers", "title": "Replace threading with Celery/RQ",
         "description": "Python threads hit GIL limits; dedicated workers enable horizontal job scaling.",
         "priority": "critical", "estimated_cost": "$100-300/mo", "estimated_effort": "2-3 weeks"},
        {"category": "cdn", "title": "Add CDN for static assets & outputs",
         "description": "Reduce server load and improve global delivery speed.",
         "priority": "high", "estimated_cost": "$20-100/mo", "estimated_effort": "3-5 days"},
        {"category": "monitoring", "title": "Add APM & structured logging",
         "description": "Datadog/New Relic for visibility into performance bottlenecks.",
         "priority": "medium", "estimated_cost": "$50-200/mo", "estimated_effort": "1 week"},
    ],
    3: [
        {"category": "compute", "title": "Migrate to AWS ECS / container orchestration",
         "description": "Enable auto-scaling and zero-downtime deploys.",
         "priority": "critical", "estimated_cost": "$500-2000/mo", "estimated_effort": "3-4 weeks"},
        {"category": "database", "title": "RDS Multi-AZ with read replicas",
         "description": "Eliminate single point of failure for the database.",
         "priority": "critical", "estimated_cost": "$200-800/mo", "estimated_effort": "1-2 weeks"},
        {"category": "scaling", "title": "Auto-scaling policies",
         "description": "CPU/memory-based scaling for web and worker tiers.",
         "priority": "high", "estimated_cost": "Variable", "estimated_effort": "1 week"},
    ],
    4: [
        {"category": "architecture", "title": "Service-oriented architecture",
         "description": "Split monolith into auth, billing, jobs, and media services.",
         "priority": "critical", "estimated_cost": "$2000-5000/mo", "estimated_effort": "2-3 months"},
        {"category": "frontend", "title": "Migrate frontend to React/Next.js",
         "description": "Enable richer UX, better caching, and independent deploys.",
         "priority": "high", "estimated_cost": "$1000-3000/mo", "estimated_effort": "2-3 months"},
        {"category": "api", "title": "Migrate API to FastAPI",
         "description": "Async support and better performance for high-concurrency workloads.",
         "priority": "high", "estimated_cost": "Minimal", "estimated_effort": "1-2 months"},
    ],
    5: [
        {"category": "infrastructure", "title": "Multi-region deployment",
         "description": "Serve users from nearest region for latency and redundancy.",
         "priority": "critical", "estimated_cost": "$5000-15000/mo", "estimated_effort": "2-3 months"},
        {"category": "orchestration", "title": "Kubernetes migration",
         "description": "Fine-grained scaling, service mesh, and self-healing infrastructure.",
         "priority": "high", "estimated_cost": "$3000-10000/mo", "estimated_effort": "2-4 months"},
        {"category": "database", "title": "Database read replicas per region",
         "description": "Reduce read latency and distribute query load globally.",
         "priority": "high", "estimated_cost": "$1000-5000/mo", "estimated_effort": "2-4 weeks"},
    ],
    6: [
        {"category": "architecture", "title": "Full microservices decomposition",
         "description": "Independent deployment, scaling, and technology choice per service.",
         "priority": "critical", "estimated_cost": "$10000+/mo", "estimated_effort": "6+ months"},
        {"category": "data", "title": "Data lake & analytics pipeline",
         "description": "Centralized data warehouse for business intelligence and reporting.",
         "priority": "high", "estimated_cost": "$3000-10000/mo", "estimated_effort": "2-3 months"},
        {"category": "ml", "title": "ML infrastructure",
         "description": "Model training pipelines, feature stores, and inference serving.",
         "priority": "medium", "estimated_cost": "$5000-20000/mo", "estimated_effort": "3-6 months"},
    ],
}

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS scale_ops_recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phase INTEGER NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    priority TEXT DEFAULT 'medium',
    status TEXT DEFAULT 'pending',
    estimated_cost TEXT,
    estimated_effort TEXT,
    trigger_metric TEXT,
    trigger_value REAL,
    threshold REAL,
    created_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT
);
"""


def _ensure_table():
    import database as db
    conn = db.get_conn()
    conn.execute(_TABLE_SQL)
    conn.commit()


def _collect_metrics() -> dict:
    """Gather all business and infrastructure health metrics."""
    import database as db
    conn = db.get_conn()
    conn.row_factory = sqlite3.Row

    m: dict = {}

    # User counts
    row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
    m["total_users"] = row["c"] if row else 0

    row = conn.execute(
        "SELECT COUNT(*) AS c FROM users WHERE subscription_status = 'active'"
    ).fetchone()
    m["paying_users"] = row["c"] if row else 0

    # MRR / ARR — sum monthly_amount from active subscribers
    row = conn.execute("""
        SELECT COALESCE(SUM(
            CASE WHEN billing_cycle = 'yearly' THEN price / 12.0 ELSE price END
        ), 0) AS mrr
        FROM users
        WHERE subscription_status = 'active' AND price IS NOT NULL
    """).fetchone()
    m["mrr"] = round(row["mrr"], 2) if row else 0
    m["arr"] = round(m["mrr"] * 12, 2)

    # Database size
    db_path = Path(os.environ.get("DB_PATH", "database.db"))
    m["db_size_mb"] = round(db_path.stat().st_size / (1024 * 1024), 2) if db_path.exists() else 0

    # Disk usage
    disk = shutil.disk_usage("/")
    m["disk_usage_pct"] = round((disk.used / disk.total) * 100, 1)

    # Job error rate (last 24h)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM jobs WHERE created_at >= ?", (cutoff,)
    ).fetchone()
    total_jobs_24h = row["c"] if row else 0

    row = conn.execute(
        "SELECT COUNT(*) AS c FROM jobs WHERE status = 'error' AND created_at >= ?", (cutoff,)
    ).fetchone()
    error_jobs_24h = row["c"] if row else 0

    m["jobs_24h"] = total_jobs_24h
    m["error_rate_24h"] = round((error_jobs_24h / total_jobs_24h * 100), 1) if total_jobs_24h else 0

    # Stuck jobs
    row = conn.execute("""
        SELECT COUNT(*) AS c FROM jobs
        WHERE status = 'running'
        AND updated_at < datetime('now', '-20 minutes')
    """).fetchone()
    m["stuck_jobs"] = row["c"] if row else 0

    # Jobs per hour (throughput proxy)
    row = conn.execute("""
        SELECT COUNT(*) AS c FROM jobs
        WHERE status = 'completed' AND created_at >= datetime('now', '-1 hour')
    """).fetchone()
    m["jobs_per_hour"] = row["c"] if row else 0

    return m


def _determine_phase(total_users: int) -> int:
    for phase, info in sorted(PHASES.items()):
        if total_users < info["max_users"]:
            return phase
    return 6


def _sync_recommendations(conn, phase: int, metrics: dict) -> list[dict]:
    """Insert recommendations for the given phase if not already present."""
    recs = PHASE_RECOMMENDATIONS.get(phase, [])
    new_recs = []
    for rec in recs:
        existing = conn.execute(
            "SELECT id FROM scale_ops_recommendations WHERE phase = ? AND title = ?",
            (phase, rec["title"]),
        ).fetchone()
        if existing:
            continue
        conn.execute("""
            INSERT INTO scale_ops_recommendations
                (phase, category, title, description, priority,
                 estimated_cost, estimated_effort, trigger_metric, trigger_value, threshold)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            phase, rec["category"], rec["title"], rec["description"], rec["priority"],
            rec.get("estimated_cost"), rec.get("estimated_effort"),
            "total_users", metrics["total_users"], PHASES[phase - 1]["max_users"] if phase > 0 else 0,
        ))
        new_recs.append(rec)
    if new_recs:
        conn.commit()
    return new_recs


def _check_alerts(metrics: dict, phase: int) -> None:
    """Create monetizer alerts when key thresholds are crossed."""
    from monetizer import create_alert

    if metrics["error_rate_24h"] > 15:
        create_alert(
            "scale_ops_error_rate",
            f"Job error rate is {metrics['error_rate_24h']}% (last 24h) — investigate failures.",
            severity="critical",
            metric_name="error_rate_24h",
            metric_value=metrics["error_rate_24h"],
            threshold=15,
        )

    if metrics["disk_usage_pct"] > 85:
        create_alert(
            "scale_ops_disk",
            f"Disk usage at {metrics['disk_usage_pct']}% — consider cleanup or storage upgrade.",
            severity="critical" if metrics["disk_usage_pct"] > 95 else "warning",
            metric_name="disk_usage_pct",
            metric_value=metrics["disk_usage_pct"],
            threshold=85,
        )

    if metrics["db_size_mb"] > 500:
        create_alert(
            "scale_ops_db_size",
            f"Database is {metrics['db_size_mb']} MB — SQLite performance degrades at scale.",
            severity="warning",
            metric_name="db_size_mb",
            metric_value=metrics["db_size_mb"],
            threshold=500,
        )

    if metrics["stuck_jobs"] > 5:
        create_alert(
            "scale_ops_stuck_jobs",
            f"{metrics['stuck_jobs']} stuck jobs detected — worker capacity may be saturated.",
            severity="warning",
            metric_name="stuck_jobs",
            metric_value=metrics["stuck_jobs"],
            threshold=5,
        )

    # Phase transition alert
    if phase > 0:
        prev_threshold = PHASES[phase - 1]["max_users"]
        if metrics["total_users"] >= prev_threshold:
            info = PHASES[phase]
            create_alert(
                "scale_ops_phase_transition",
                f"Reached Phase {phase} ({info['label']}): {metrics['total_users']} users. "
                f"Recommended stack: {info['stack']}.",
                severity="critical",
                metric_name="total_users",
                metric_value=metrics["total_users"],
                threshold=prev_threshold,
            )


def _run_check() -> None:
    """Single pass: collect metrics, determine phase, sync recommendations, check alerts."""
    import database as db

    _ensure_table()
    metrics = _collect_metrics()
    phase = _determine_phase(metrics["total_users"])

    print(f"[scale-ops] Phase {phase} ({PHASES[phase]['label']}) — "
          f"{metrics['total_users']} users, MRR ${metrics['mrr']}, "
          f"DB {metrics['db_size_mb']}MB, disk {metrics['disk_usage_pct']}%")

    conn = db.get_conn()
    conn.row_factory = sqlite3.Row
    new_recs = _sync_recommendations(conn, phase, metrics)
    if new_recs:
        print(f"[scale-ops] Created {len(new_recs)} new recommendation(s) for phase {phase}")

    try:
        _check_alerts(metrics, phase)
    except Exception as e:
        print(f"[scale-ops] Alert check error: {e}")


def _loop(stop_event: threading.Event) -> None:
    print("[scale-ops] Scale-ops agent started")
    while not stop_event.wait(timeout=SCALE_OPS_INTERVAL):
        try:
            _run_check()
        except Exception as e:
            print(f"[scale-ops] Unexpected error: {e}")
    print("[scale-ops] Scale-ops agent stopped")


_thread: threading.Thread | None = None
_stop = threading.Event()


def start_scale_ops_agent(stop_event: threading.Event | None = None) -> None:
    """Start the scale-ops daemon thread (idempotent)."""
    global _thread, _stop
    if _thread and _thread.is_alive():
        return
    if stop_event is not None:
        _stop = stop_event
    else:
        _stop.clear()
    _thread = threading.Thread(target=_loop, args=(_stop,), daemon=True, name="scale-ops")
    _thread.start()


def stop() -> None:
    """Signal the agent to stop."""
    _stop.set()
