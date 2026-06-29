"""
Studio Intelligence — The learning layer that makes each studio smarter.
========================================================================
After every job, records what worked and what didn't. Before every job,
consults past learnings to optimize parameters within the blueprint's
constraints.

Schema: studio_learnings table stores per-job outcomes.
The system answers: "Given this studio + genre/topic, what settings
produced the best results historically?"
"""
import json
from datetime import datetime, timezone
from typing import Optional

import database as db


def init_intelligence_tables():
    """Create the learning tables. Call from init_db or app startup."""
    with db.get_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS studio_learnings (
            id              SERIAL PRIMARY KEY,
            studio          TEXT NOT NULL,
            job_id          INTEGER,
            user_id         INTEGER,
            topic           TEXT DEFAULT '',
            genre           TEXT DEFAULT '',
            format          TEXT DEFAULT '',

            -- What was used
            asset_sources   TEXT DEFAULT '{}',
            clip_count      INTEGER DEFAULT 0,
            duration_seconds REAL DEFAULT 0,
            voice_used      TEXT DEFAULT '',
            music_style     TEXT DEFAULT '',
            ai_provider     TEXT DEFAULT '',
            model_used      TEXT DEFAULT '',
            settings_json   TEXT DEFAULT '{}',

            -- How it turned out
            completed       INTEGER DEFAULT 0,
            error_message   TEXT DEFAULT '',
            generation_time_seconds REAL DEFAULT 0,
            file_size_bytes INTEGER DEFAULT 0,

            -- Quality signals (populated post-hoc or by user feedback)
            quality_score   REAL DEFAULT 0,
            user_rating     INTEGER DEFAULT 0,
            gates_passed    INTEGER DEFAULT 0,
            gates_total     INTEGER DEFAULT 0,

            -- Engagement signals (populated when analytics come in)
            views           INTEGER DEFAULT 0,
            likes           INTEGER DEFAULT 0,
            comments        INTEGER DEFAULT 0,
            retention_pct   REAL DEFAULT 0,
            ctr             REAL DEFAULT 0,

            created_at      TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_studio_learnings_studio
        ON studio_learnings (studio, completed)
        """)
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_studio_learnings_genre
        ON studio_learnings (studio, genre)
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS studio_preferences (
            id          SERIAL PRIMARY KEY,
            studio      TEXT NOT NULL,
            category    TEXT NOT NULL,
            preference  TEXT NOT NULL,
            score       REAL DEFAULT 0,
            sample_size INTEGER DEFAULT 0,
            updated_at  TIMESTAMP DEFAULT NOW(),
            UNIQUE(studio, category, preference)
        )
        """)


def record_job(studio: str, job_id: int, user_id: int, **kwargs):
    """Record a completed (or failed) job for learning."""
    fields = {
        "studio": studio,
        "job_id": job_id,
        "user_id": user_id,
    }
    allowed = {
        "topic", "genre", "format", "clip_count", "duration_seconds",
        "voice_used", "music_style", "ai_provider", "model_used",
        "completed", "error_message", "generation_time_seconds",
        "file_size_bytes", "quality_score", "gates_passed", "gates_total",
    }
    for k, v in kwargs.items():
        if k in allowed:
            fields[k] = v

    if "asset_sources" in kwargs:
        fields["asset_sources"] = json.dumps(kwargs["asset_sources"])
    if "settings_json" in kwargs:
        fields["settings_json"] = json.dumps(kwargs["settings_json"])

    cols = ", ".join(fields.keys())
    placeholders = ", ".join(["%s"] * len(fields))
    try:
        with db.get_conn() as conn:
            conn.execute(
                f"INSERT INTO studio_learnings ({cols}) VALUES ({placeholders})",
                tuple(fields.values()),
            )
    except Exception:
        pass

    if kwargs.get("completed"):
        _update_preferences(studio, kwargs)


def _update_preferences(studio: str, job_data: dict):
    """Update aggregated preference scores from a successful job."""
    updates = []
    if job_data.get("voice_used"):
        updates.append(("voice", job_data["voice_used"]))
    if job_data.get("ai_provider"):
        updates.append(("ai_provider", job_data["ai_provider"]))
    if job_data.get("music_style"):
        updates.append(("music_style", job_data["music_style"]))
    if job_data.get("model_used"):
        updates.append(("model", job_data["model_used"]))
    if job_data.get("genre"):
        updates.append(("genre", job_data["genre"]))

    quality = job_data.get("quality_score", 0.5)

    for category, preference in updates:
        try:
            with db.get_conn() as conn:
                conn.execute("""
                    INSERT INTO studio_preferences (studio, category, preference, score, sample_size)
                    VALUES (%s, %s, %s, %s, 1)
                    ON CONFLICT (studio, category, preference) DO UPDATE SET
                        score = (studio_preferences.score * studio_preferences.sample_size + EXCLUDED.score)
                                / (studio_preferences.sample_size + 1),
                        sample_size = studio_preferences.sample_size + 1,
                        updated_at = NOW()
                """, (studio, category, preference, quality))
        except Exception:
            pass


def record_engagement(job_id: int, views: int = 0, likes: int = 0,
                      comments: int = 0, retention_pct: float = 0, ctr: float = 0):
    """Update a learning record with engagement data (called when analytics come in)."""
    try:
        with db.get_conn() as conn:
            conn.execute("""
                UPDATE studio_learnings
                SET views = %s, likes = %s, comments = %s,
                    retention_pct = %s, ctr = %s
                WHERE job_id = %s
            """, (views, likes, comments, retention_pct, ctr, job_id))
    except Exception:
        pass


def record_user_rating(job_id: int, rating: int):
    """User rates a job output 1-5. Feeds into preference scoring."""
    try:
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE studio_learnings SET user_rating = %s WHERE job_id = %s",
                (rating, job_id),
            )
            row = conn.execute(
                "SELECT studio, voice_used, ai_provider, music_style, model_used, genre "
                "FROM studio_learnings WHERE job_id = %s",
                (job_id,),
            ).fetchone()
            if row:
                row = dict(row)
                quality = rating / 5.0
                _update_preferences(row["studio"], {
                    "voice_used": row.get("voice_used"),
                    "ai_provider": row.get("ai_provider"),
                    "music_style": row.get("music_style"),
                    "model_used": row.get("model_used"),
                    "genre": row.get("genre"),
                    "quality_score": quality,
                })
    except Exception:
        pass


def get_recommendations(studio: str, genre: str = "", format: str = "") -> dict:
    """Get optimized settings for the next job based on past learnings."""
    recs = {
        "voice": None,
        "ai_provider": None,
        "music_style": None,
        "model": None,
        "avg_duration": None,
        "avg_clip_count": None,
        "success_rate": None,
        "top_settings": {},
        "insights": [],
    }

    try:
        with db.get_conn() as conn:
            # Best preferences per category
            for category in ("voice", "ai_provider", "music_style", "model"):
                row = conn.execute("""
                    SELECT preference, score, sample_size
                    FROM studio_preferences
                    WHERE studio = %s AND category = %s AND sample_size >= 2
                    ORDER BY score DESC LIMIT 1
                """, (studio, category)).fetchone()
                if row:
                    row = dict(row)
                    recs[category] = row["preference"]
                    recs["top_settings"][category] = {
                        "value": row["preference"],
                        "score": round(row["score"], 2),
                        "samples": row["sample_size"],
                    }

            # Average stats from successful jobs
            filters = ["studio = %s", "completed = 1"]
            params = [studio]
            if genre:
                filters.append("genre = %s")
                params.append(genre)
            if format:
                filters.append("format = %s")
                params.append(format)

            where = " AND ".join(filters)
            stats = conn.execute(f"""
                SELECT COUNT(*) as total,
                       AVG(duration_seconds) as avg_dur,
                       AVG(clip_count) as avg_clips,
                       AVG(generation_time_seconds) as avg_gen_time,
                       AVG(quality_score) as avg_quality
                FROM studio_learnings
                WHERE {where}
            """, params).fetchone()

            if stats:
                stats = dict(stats)
                recs["avg_duration"] = round(stats["avg_dur"] or 0, 1)
                recs["avg_clip_count"] = round(stats["avg_clips"] or 0)
                total = stats["total"] or 0

                # Success rate
                total_all = conn.execute(f"""
                    SELECT COUNT(*) FROM studio_learnings
                    WHERE {where.replace("completed = 1", "1=1")}
                """, params).fetchone()[0]
                recs["success_rate"] = round(total / total_all, 2) if total_all > 0 else None

            # Generate insights
            if recs["success_rate"] and recs["success_rate"] < 0.7:
                recs["insights"].append(
                    f"Success rate is {recs['success_rate']*100:.0f}% — consider reviewing error patterns")

            # Check if certain providers fail often
            failures = conn.execute("""
                SELECT ai_provider, COUNT(*) as fails
                FROM studio_learnings
                WHERE studio = %s AND completed = 0 AND ai_provider != ''
                GROUP BY ai_provider ORDER BY fails DESC LIMIT 3
            """, (studio,)).fetchall()
            for f in failures:
                f = dict(f)
                if f["fails"] >= 3:
                    recs["insights"].append(
                        f"Provider '{f['ai_provider']}' has {f['fails']} failures — consider deprioritizing")

    except Exception:
        pass

    return recs


def get_studio_stats(studio: str) -> dict:
    """Get overall stats for a studio's learning history."""
    try:
        with db.get_conn() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total_jobs,
                    SUM(CASE WHEN completed = 1 THEN 1 ELSE 0 END) as successes,
                    AVG(CASE WHEN completed = 1 THEN generation_time_seconds END) as avg_time,
                    AVG(CASE WHEN user_rating > 0 THEN user_rating END) as avg_rating,
                    AVG(CASE WHEN completed = 1 THEN quality_score END) as avg_quality,
                    SUM(CASE WHEN views > 0 THEN views ELSE 0 END) as total_views
                FROM studio_learnings WHERE studio = %s
            """, (studio,)).fetchone()
            if row:
                row = dict(row)
                return {
                    "total_jobs": row["total_jobs"] or 0,
                    "successes": row["successes"] or 0,
                    "success_rate": round((row["successes"] or 0) / row["total_jobs"], 2) if row["total_jobs"] else 0,
                    "avg_generation_time": round(row["avg_time"] or 0, 1),
                    "avg_user_rating": round(row["avg_rating"] or 0, 1),
                    "avg_quality": round(row["avg_quality"] or 0, 2),
                    "total_views": row["total_views"] or 0,
                }
    except Exception:
        pass
    return {"total_jobs": 0, "successes": 0, "success_rate": 0}
