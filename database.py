"""SQLite database layer for the Social Optimize Machine dashboard."""
import sqlite3
import json
import uuid
from pathlib import Path
from datetime import datetime

import os as _os
_DATA_DIR = Path(_os.getenv("DATA_DIR", Path(__file__).parent))
DB_PATH = _DATA_DIR / "som_data.db"


def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            email                   TEXT UNIQUE NOT NULL,
            password_hash           TEXT NOT NULL,
            name                    TEXT,
            stripe_customer_id      TEXT,
            stripe_subscription_id  TEXT,
            subscription_tier       TEXT DEFAULT 'free',
            subscription_status     TEXT DEFAULT 'active',
            videos_used             INTEGER DEFAULT 0,
            credits_used            INTEGER DEFAULT 0,
            period_start            TEXT DEFAULT (date('now', 'start of month')),
            is_admin                INTEGER DEFAULT 0,
            notify_email            INTEGER DEFAULT 1,
            webhook_url             TEXT,
            created_at              TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS social_accounts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            platform    TEXT NOT NULL,
            username    TEXT NOT NULL,
            display_name TEXT,
            avatar_url  TEXT,
            access_token TEXT,
            refresh_token TEXT,
            account_id  TEXT,
            followers   INTEGER DEFAULT 0,
            connected_at TEXT DEFAULT (datetime('now')),
            is_active   INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS contacts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name        TEXT NOT NULL,
            handle      TEXT,
            email       TEXT,
            phone       TEXT,
            platform    TEXT,
            avatar_url  TEXT,
            followers   INTEGER DEFAULT 0,
            notes       TEXT,
            tags        TEXT DEFAULT '[]',
            imported_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            topic       TEXT NOT NULL,
            format      TEXT NOT NULL,
            platforms   TEXT DEFAULT '[]',
            audience    TEXT DEFAULT 'general public',
            voice       TEXT,
            style       TEXT DEFAULT 'fire',
            privacy     TEXT DEFAULT 'private',
            skip_research INTEGER DEFAULT 0,
            status      TEXT DEFAULT 'pending',
            progress    INTEGER DEFAULT 0,
            current_step TEXT DEFAULT '',
            title       TEXT,
            duration    REAL DEFAULT 0,
            video_path  TEXT,
            audio_path  TEXT,
            thumbnail_path TEXT,
            script_path TEXT,
            research_path TEXT,
            manifest_path TEXT,
            publish_results TEXT DEFAULT '{}',
            research_summary TEXT DEFAULT '{}',
            error_msg   TEXT,
            created_at  TEXT DEFAULT (datetime('now')),
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        -- Feature 1: Analytics
        CREATE TABLE IF NOT EXISTS analytics_cache (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
            video_id        TEXT NOT NULL,
            platform        TEXT DEFAULT 'youtube',
            title           TEXT,
            views           INTEGER DEFAULT 0,
            likes           INTEGER DEFAULT 0,
            comments        INTEGER DEFAULT 0,
            ctr             REAL DEFAULT 0,
            avg_retention_pct REAL DEFAULT 0,
            revenue_estimate REAL DEFAULT 0,
            fetched_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS published_videos (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            job_id      INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
            platform    TEXT NOT NULL,
            video_id    TEXT,
            video_url   TEXT,
            title       TEXT,
            published_at TEXT DEFAULT (datetime('now'))
        );

        -- Feature 2: Content Calendar / Scheduler
        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            job_id      INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
            platform    TEXT NOT NULL,
            scheduled_at TEXT NOT NULL,
            status      TEXT DEFAULT 'pending',
            posted_at   TEXT,
            error_msg   TEXT
        );

        -- Feature 3: Batch Mode
        CREATE TABLE IF NOT EXISTS batch_jobs (
            id              TEXT PRIMARY KEY,
            user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
            total_count     INTEGER DEFAULT 0,
            completed_count INTEGER DEFAULT 0,
            failed_count    INTEGER DEFAULT 0,
            status          TEXT DEFAULT 'running',
            created_at      TEXT DEFAULT (datetime('now')),
            topics_json     TEXT DEFAULT '[]'
        );

        -- Feature 4: Template Library
        CREATE TABLE IF NOT EXISTS content_templates (
            id          TEXT PRIMARY KEY,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name        TEXT NOT NULL,
            description TEXT,
            config_json TEXT DEFAULT '{}',
            use_count   INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        -- Feature 5: Multi-language Dub Jobs
        CREATE TABLE IF NOT EXISTS dub_jobs (
            id              TEXT PRIMARY KEY,
            user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
            source_job_id   INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
            target_language TEXT NOT NULL,
            status          TEXT DEFAULT 'pending',
            output_path     TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        );

        -- Feature 6: Notifications
        CREATE TABLE IF NOT EXISTS notification_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            notif_id    TEXT,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            event_type  TEXT,
            channel     TEXT,
            status      TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS in_app_notifications (
            id          TEXT PRIMARY KEY,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            title       TEXT NOT NULL,
            body        TEXT,
            read        INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now')),
            link        TEXT
        );

        -- Feature 7: Team Workspaces
        CREATE TABLE IF NOT EXISTS teams (
            id          TEXT PRIMARY KEY,
            owner_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name        TEXT NOT NULL,
            plan        TEXT DEFAULT 'agency',
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS team_members (
            id              TEXT PRIMARY KEY,
            team_id         TEXT REFERENCES teams(id) ON DELETE CASCADE,
            user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
            role            TEXT DEFAULT 'editor',
            invited_email   TEXT,
            status          TEXT DEFAULT 'pending',
            created_at      TEXT DEFAULT (datetime('now'))
        );

        -- Feature 10: A/B Testing
        CREATE TABLE IF NOT EXISTS ab_tests (
            id          TEXT PRIMARY KEY,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            job_id      INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
            test_type   TEXT NOT NULL,
            status      TEXT DEFAULT 'running',
            winner_id   TEXT,
            created_at  TEXT DEFAULT (datetime('now')),
            ended_at    TEXT
        );

        CREATE TABLE IF NOT EXISTS ab_variants (
            id          TEXT PRIMARY KEY,
            test_id     TEXT REFERENCES ab_tests(id) ON DELETE CASCADE,
            label       TEXT NOT NULL,
            content     TEXT NOT NULL,
            impressions INTEGER DEFAULT 0,
            clicks      INTEGER DEFAULT 0,
            conversions INTEGER DEFAULT 0,
            ctr         REAL DEFAULT 0,
            confidence  REAL DEFAULT 0
        );

        -- Feature 11: AI Avatars & Personas
        CREATE TABLE IF NOT EXISTS ai_personas (
            id              TEXT PRIMARY KEY,
            user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name            TEXT NOT NULL,
            avatar_style    TEXT DEFAULT 'professional',
            gender          TEXT DEFAULT 'neutral',
            age_range       TEXT DEFAULT '25-35',
            ethnicity       TEXT DEFAULT 'diverse',
            appearance_desc TEXT DEFAULT '',
            voice_id        TEXT DEFAULT 'en-US-AriaNeural',
            personality     TEXT DEFAULT 'friendly and authoritative',
            speaking_style  TEXT DEFAULT 'conversational',
            niche           TEXT DEFAULT 'general',
            reference_image TEXT,
            model_preference TEXT DEFAULT 'seedance_2_0',
            is_preset       INTEGER DEFAULT 0,
            use_count       INTEGER DEFAULT 0,
            created_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS persona_generations (
            id          TEXT PRIMARY KEY,
            persona_id  TEXT REFERENCES ai_personas(id) ON DELETE CASCADE,
            job_id      INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            video_path  TEXT,
            status      TEXT DEFAULT 'pending',
            created_at  TEXT DEFAULT (datetime('now'))
        );

        -- Feature 9: Lifecycle / Checkout Tracking
        CREATE TABLE IF NOT EXISTS checkout_events (
            id          TEXT PRIMARY KEY,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            tier        TEXT NOT NULL,
            stripe_session_id TEXT,
            status      TEXT DEFAULT 'started',
            created_at  TEXT DEFAULT (datetime('now')),
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS lifecycle_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            event_key   TEXT NOT NULL,
            sent_at     TEXT DEFAULT (datetime('now'))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_lifecycle_user_event
            ON lifecycle_events(user_id, event_key);

        CREATE TABLE IF NOT EXISTS onboarding_checklist (
            user_id             INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            welcome_seen        INTEGER DEFAULT 0,
            first_video_created INTEGER DEFAULT 0,
            platform_connected  INTEGER DEFAULT 0,
            first_publish       INTEGER DEFAULT 0,
            upgraded            INTEGER DEFAULT 0,
            updated_at          TEXT DEFAULT (datetime('now'))
        );

        -- Feature 8: Competitor Tracker
        CREATE TABLE IF NOT EXISTS competitor_channels (
            id          TEXT PRIMARY KEY,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            platform    TEXT DEFAULT 'youtube',
            channel_id  TEXT,
            channel_name TEXT,
            channel_url TEXT,
            added_at    TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS competitor_videos (
            id              TEXT PRIMARY KEY,
            competitor_id   TEXT REFERENCES competitor_channels(id) ON DELETE CASCADE,
            video_id        TEXT,
            title           TEXT,
            views           INTEGER DEFAULT 0,
            likes           INTEGER DEFAULT 0,
            published_at    TEXT,
            thumbnail_url   TEXT,
            video_url       TEXT,
            fetched_at      TEXT DEFAULT (datetime('now'))
        );
        """)

        # Migrate: add user_id columns if upgrading from an older schema
        for table in ("jobs", "contacts", "social_accounts"):
            cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if "user_id" not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE")

        # Migrate: add notify_email / webhook_url to users if upgrading
        user_cols = [r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "notify_email" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN notify_email INTEGER DEFAULT 1")
        if "webhook_url" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN webhook_url TEXT")
        if "trial_ends_at" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN trial_ends_at TEXT")
        if "last_active_at" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN last_active_at TEXT")


def row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, str) and v.startswith(('[', '{')):
            try:
                d[k] = json.loads(v)
            except Exception:
                pass
    return d


# ── Users ─────────────────────────────────────────────────────────────────────

def create_user(email: str, password_hash: str, name: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, name) VALUES (?,?,?)",
            (email.lower().strip(), password_hash, name),
        )
        return cur.lastrowid


def get_user_by_id(user_id: int):
    with get_conn() as conn:
        return row_to_dict(conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())


def get_user_by_email(email: str):
    with get_conn() as conn:
        return row_to_dict(conn.execute("SELECT * FROM users WHERE email=?", (email.lower().strip(),)).fetchone())


def update_user(user_id: int, **kwargs):
    if not kwargs:
        return
    cols = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [user_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE users SET {cols} WHERE id=?", vals)


def increment_user_usage(user_id: int, videos: int = 0, credits: int = 0):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET videos_used = videos_used + ?, credits_used = credits_used + ? WHERE id=?",
            (videos, credits, user_id),
        )


def reset_usage_if_new_period(user_id: int):
    """Reset usage counters when a new billing period has started."""
    user = get_user_by_id(user_id)
    if not user:
        return
    period_start = user.get("period_start") or ""
    current_month_start = datetime.now().strftime("%Y-%m-01")
    if period_start < current_month_start:
        update_user(user_id, videos_used=0, credits_used=0, period_start=current_month_start)


def get_user_by_stripe_customer(stripe_customer_id: str):
    with get_conn() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM users WHERE stripe_customer_id=?", (stripe_customer_id,)
        ).fetchone())


def get_user_by_stripe_subscription(stripe_subscription_id: str):
    with get_conn() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM users WHERE stripe_subscription_id=?", (stripe_subscription_id,)
        ).fetchone())


def list_users(limit=200):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [row_to_dict(r) for r in rows]


# ── Social Accounts ──────────────────────────────────────────────────────────

def get_accounts(user_id: int = None):
    with get_conn() as conn:
        if user_id:
            rows = conn.execute("SELECT * FROM social_accounts WHERE user_id=? ORDER BY platform", (user_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM social_accounts ORDER BY platform").fetchall()
    return [row_to_dict(r) for r in rows]


def upsert_account(platform, username, display_name=None, avatar_url=None,
                   access_token=None, refresh_token=None, account_id=None, followers=0,
                   user_id=None):
    with get_conn() as conn:
        q = "SELECT id FROM social_accounts WHERE platform=? AND username=?"
        params = [platform, username]
        if user_id:
            q += " AND user_id=?"
            params.append(user_id)
        existing = conn.execute(q, params).fetchone()
        if existing:
            conn.execute("""
                UPDATE social_accounts SET display_name=?, avatar_url=?, access_token=?,
                refresh_token=?, account_id=?, followers=?, is_active=1
                WHERE id=?
            """, (display_name, avatar_url, access_token, refresh_token, account_id,
                  followers, existing["id"]))
            return existing["id"]
        else:
            cur = conn.execute("""
                INSERT INTO social_accounts
                (platform, username, display_name, avatar_url, access_token, refresh_token,
                 account_id, followers, user_id)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (platform, username, display_name, avatar_url, access_token,
                  refresh_token, account_id, followers, user_id))
            return cur.lastrowid


def delete_account(account_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM social_accounts WHERE id=?", (account_id,))


# ── Contacts ─────────────────────────────────────────────────────────────────

def get_contacts(platform=None, search=None, limit=100, offset=0, user_id=None):
    query = "SELECT * FROM contacts WHERE 1=1"
    params = []
    if user_id:
        query += " AND user_id=?"
        params.append(user_id)
    if platform:
        query += " AND platform=?"
        params.append(platform)
    if search:
        query += " AND (name LIKE ? OR handle LIKE ? OR email LIKE ?)"
        s = f"%{search}%"
        params.extend([s, s, s])
    query += f" ORDER BY name LIMIT {limit} OFFSET {offset}"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [row_to_dict(r) for r in rows]


def count_contacts(platform=None, user_id=None):
    query = "SELECT COUNT(*) as n FROM contacts WHERE 1=1"
    params = []
    if user_id:
        query += " AND user_id=?"
        params.append(user_id)
    if platform:
        query += " AND platform=?"
        params.append(platform)
    with get_conn() as conn:
        return conn.execute(query, params).fetchone()["n"]


def insert_contacts_bulk(contacts: list, user_id=None):
    if user_id:
        for c in contacts:
            c["user_id"] = user_id
    with get_conn() as conn:
        conn.executemany("""
            INSERT OR IGNORE INTO contacts (name, handle, email, phone, platform, avatar_url, followers, tags, user_id)
            VALUES (:name, :handle, :email, :phone, :platform, :avatar_url, :followers, :tags, :user_id)
        """, contacts)
    return len(contacts)


def delete_contacts(platform=None, user_id=None):
    with get_conn() as conn:
        if user_id and platform:
            conn.execute("DELETE FROM contacts WHERE platform=? AND user_id=?", (platform, user_id))
        elif user_id:
            conn.execute("DELETE FROM contacts WHERE user_id=?", (user_id,))
        elif platform:
            conn.execute("DELETE FROM contacts WHERE platform=?", (platform,))
        else:
            conn.execute("DELETE FROM contacts")


# ── Jobs ─────────────────────────────────────────────────────────────────────

def create_job(topic, format, platforms, audience, voice, style, privacy,
               skip_research=False, user_id=None):
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO jobs (topic, format, platforms, audience, voice, style, privacy, skip_research, user_id)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (topic, format, json.dumps(platforms), audience, voice, style, privacy,
              int(skip_research), user_id))
        return cur.lastrowid


def update_job(job_id, **kwargs):
    if not kwargs:
        return
    for k in ["platforms", "publish_results", "tags"]:
        if k in kwargs and isinstance(kwargs[k], (list, dict)):
            kwargs[k] = json.dumps(kwargs[k])
    cols = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [job_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE jobs SET {cols} WHERE id=?", vals)


def get_job(job_id, user_id=None):
    with get_conn() as conn:
        if user_id:
            row = conn.execute("SELECT * FROM jobs WHERE id=? AND user_id=?", (job_id, user_id)).fetchone()
        else:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return row_to_dict(row)


def get_jobs(limit=50, user_id=None, team_id=None):
    with get_conn() as conn:
        if team_id:
            # Return jobs for all members of the team
            rows = conn.execute("""
                SELECT j.* FROM jobs j
                JOIN team_members tm ON tm.user_id = j.user_id
                WHERE tm.team_id = ? AND tm.status = 'active'
                ORDER BY j.created_at DESC LIMIT ?
            """, (team_id, limit)).fetchall()
        elif user_id:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
    return [row_to_dict(r) for r in rows]


def get_stats(user_id=None):
    with get_conn() as conn:
        if user_id:
            total = conn.execute("SELECT COUNT(*) as n FROM jobs WHERE user_id=?", (user_id,)).fetchone()["n"]
            done = conn.execute("SELECT COUNT(*) as n FROM jobs WHERE status='done' AND user_id=?", (user_id,)).fetchone()["n"]
            contacts = conn.execute("SELECT COUNT(*) as n FROM contacts WHERE user_id=?", (user_id,)).fetchone()["n"]
            accounts = conn.execute("SELECT COUNT(*) as n FROM social_accounts WHERE is_active=1 AND user_id=?", (user_id,)).fetchone()["n"]
        else:
            total = conn.execute("SELECT COUNT(*) as n FROM jobs").fetchone()["n"]
            done = conn.execute("SELECT COUNT(*) as n FROM jobs WHERE status='done'").fetchone()["n"]
            contacts = conn.execute("SELECT COUNT(*) as n FROM contacts").fetchone()["n"]
            accounts = conn.execute("SELECT COUNT(*) as n FROM social_accounts WHERE is_active=1").fetchone()["n"]
    return {"total_jobs": total, "completed_jobs": done, "contacts": contacts, "accounts": accounts}


# ── Settings ─────────────────────────────────────────────────────────────────

def get_setting(key, default=None):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, str(value)))


# ── Feature 1: Analytics ─────────────────────────────────────────────────────

def upsert_analytics(user_id: int, video_id: str, platform: str = "youtube", **kwargs):
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM analytics_cache WHERE user_id=? AND video_id=? AND platform=?",
            (user_id, video_id, platform)
        ).fetchone()
        if existing:
            sets = ", ".join(f"{k}=?" for k in kwargs)
            sets += ", fetched_at=datetime('now')"
            vals = list(kwargs.values()) + [existing["id"]]
            conn.execute(f"UPDATE analytics_cache SET {sets} WHERE id=?", vals)
            return existing["id"]
        else:
            fields = ["user_id", "video_id", "platform"] + list(kwargs.keys())
            placeholders = ",".join(["?"] * len(fields))
            vals = [user_id, video_id, platform] + list(kwargs.values())
            cur = conn.execute(
                f"INSERT INTO analytics_cache ({','.join(fields)}) VALUES ({placeholders})", vals
            )
            return cur.lastrowid


def get_analytics(user_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM analytics_cache WHERE user_id=? ORDER BY views DESC",
            (user_id,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def add_published_video(user_id: int, job_id, platform: str, video_id: str,
                        video_url: str, title: str):
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO published_videos (user_id, job_id, platform, video_id, video_url, title)
            VALUES (?,?,?,?,?,?)
        """, (user_id, job_id, platform, video_id, video_url, title))
        return cur.lastrowid


def get_published_videos(user_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM published_videos WHERE user_id=? ORDER BY published_at DESC",
            (user_id,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


# ── Feature 2: Content Calendar / Scheduler ───────────────────────────────────

def create_scheduled_post(user_id: int, job_id: int, platform: str, scheduled_at: str) -> int:
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO scheduled_posts (user_id, job_id, platform, scheduled_at)
            VALUES (?,?,?,?)
        """, (user_id, job_id, platform, scheduled_at))
        return cur.lastrowid


def get_scheduled_posts(user_id: int, status: str = None):
    query = "SELECT sp.*, j.title as job_title, j.video_path, j.thumbnail_path FROM scheduled_posts sp LEFT JOIN jobs j ON j.id = sp.job_id WHERE sp.user_id=?"
    params = [user_id]
    if status:
        query += " AND sp.status=?"
        params.append(status)
    query += " ORDER BY sp.scheduled_at ASC"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [row_to_dict(r) for r in rows]


def get_scheduled_post(post_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT sp.*, j.video_path, j.thumbnail_path FROM scheduled_posts sp LEFT JOIN jobs j ON j.id=sp.job_id WHERE sp.id=?",
            (post_id,)
        ).fetchone()
    return row_to_dict(row)


def update_scheduled_post(post_id: int, **kwargs):
    if not kwargs:
        return
    cols = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [post_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE scheduled_posts SET {cols} WHERE id=?", vals)


def delete_scheduled_post(post_id: int, user_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM scheduled_posts WHERE id=? AND user_id=?", (post_id, user_id))


def get_due_scheduled_posts():
    """Get all pending scheduled posts that are due now."""
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT sp.*, j.video_path, j.thumbnail_path, j.title as job_title
            FROM scheduled_posts sp
            LEFT JOIN jobs j ON j.id = sp.job_id
            WHERE sp.status = 'pending' AND sp.scheduled_at <= ?
        """, (now,)).fetchall()
    return [row_to_dict(r) for r in rows]


# ── Feature 3: Batch Mode ────────────────────────────────────────────────────

def create_batch_job(user_id: int, topics: list) -> str:
    batch_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO batch_jobs (id, user_id, total_count, topics_json)
            VALUES (?,?,?,?)
        """, (batch_id, user_id, len(topics), json.dumps(topics)))
    return batch_id


def get_batch_job(batch_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM batch_jobs WHERE id=?", (batch_id,)).fetchone()
    return row_to_dict(row)


def update_batch_job(batch_id: str, **kwargs):
    if not kwargs:
        return
    cols = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [batch_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE batch_jobs SET {cols} WHERE id=?", vals)


def get_batch_jobs(user_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM batch_jobs WHERE user_id=? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


# ── Feature 4: Template Library ──────────────────────────────────────────────

def create_template(user_id: int, name: str, description: str, config_json: dict) -> str:
    tmpl_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO content_templates (id, user_id, name, description, config_json)
            VALUES (?,?,?,?,?)
        """, (tmpl_id, user_id, name, description, json.dumps(config_json)))
    return tmpl_id


def get_templates(user_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM content_templates WHERE user_id=? ORDER BY use_count DESC, created_at DESC",
            (user_id,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def get_template(tmpl_id: str, user_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM content_templates WHERE id=? AND user_id=?", (tmpl_id, user_id)
        ).fetchone()
    return row_to_dict(row)


def increment_template_use(tmpl_id: str):
    with get_conn() as conn:
        conn.execute("UPDATE content_templates SET use_count=use_count+1 WHERE id=?", (tmpl_id,))


def delete_template(tmpl_id: str, user_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM content_templates WHERE id=? AND user_id=?", (tmpl_id, user_id))


# ── Feature 5: Dub Jobs ──────────────────────────────────────────────────────

def create_dub_job(user_id: int, source_job_id: int, target_language: str) -> str:
    dub_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO dub_jobs (id, user_id, source_job_id, target_language)
            VALUES (?,?,?,?)
        """, (dub_id, user_id, source_job_id, target_language))
    return dub_id


def get_dub_job(dub_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM dub_jobs WHERE id=?", (dub_id,)).fetchone()
    return row_to_dict(row)


def update_dub_job(dub_id: str, **kwargs):
    if not kwargs:
        return
    cols = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [dub_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE dub_jobs SET {cols} WHERE id=?", vals)


def get_dub_jobs_for_source(user_id: int, source_job_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM dub_jobs WHERE user_id=? AND source_job_id=? ORDER BY created_at DESC",
            (user_id, source_job_id)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


# ── Feature 6: Notifications ─────────────────────────────────────────────────

def create_in_app_notification(user_id: int, title: str, body: str, link: str = "") -> str:
    notif_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO in_app_notifications (id, user_id, title, body, link)
            VALUES (?,?,?,?,?)
        """, (notif_id, user_id, title, body, link))
    return notif_id


def get_in_app_notifications(user_id: int, limit: int = 10):
    with get_conn() as conn:
        unread_count = conn.execute(
            "SELECT COUNT(*) as n FROM in_app_notifications WHERE user_id=? AND read=0",
            (user_id,)
        ).fetchone()["n"]
        rows = conn.execute(
            "SELECT * FROM in_app_notifications WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
    return {"unread_count": unread_count, "notifications": [row_to_dict(r) for r in rows]}


def mark_notification_read(notif_id: str, user_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE in_app_notifications SET read=1 WHERE id=? AND user_id=?",
            (notif_id, user_id)
        )


def log_notification(notif_id, user_id: int, event_type: str, channel: str, status: str):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO notification_log (notif_id, user_id, event_type, channel, status)
            VALUES (?,?,?,?,?)
        """, (notif_id, user_id, event_type, channel, status))


# ── Feature 7: Team Workspaces ────────────────────────────────────────────────

def create_team(owner_id: int, name: str) -> str:
    team_id = str(uuid.uuid4())
    member_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO teams (id, owner_id, name) VALUES (?,?,?)",
            (team_id, owner_id, name)
        )
        conn.execute("""
            INSERT INTO team_members (id, team_id, user_id, role, status)
            VALUES (?,?,?,?,?)
        """, (member_id, team_id, owner_id, "owner", "active"))
    return team_id


def get_team_for_user(user_id: int):
    """Get the team where this user is an active member."""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT t.*, tm.role as user_role FROM teams t
            JOIN team_members tm ON tm.team_id = t.id
            WHERE tm.user_id = ? AND tm.status = 'active'
            LIMIT 1
        """, (user_id,)).fetchone()
    return row_to_dict(row)


def get_team_by_id(team_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
    return row_to_dict(row)


def get_team_members(team_id: str):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT tm.*, u.name as user_name, u.email as user_email
            FROM team_members tm
            LEFT JOIN users u ON u.id = tm.user_id
            WHERE tm.team_id=?
            ORDER BY tm.created_at ASC
        """, (team_id,)).fetchall()
    return [row_to_dict(r) for r in rows]


def add_team_member(team_id: str, invited_email: str, role: str = "editor") -> str:
    member_id = str(uuid.uuid4())
    # Check if user exists
    with get_conn() as conn:
        user = conn.execute("SELECT id FROM users WHERE email=?", (invited_email.lower(),)).fetchone()
        user_id = user["id"] if user else None
        conn.execute("""
            INSERT INTO team_members (id, team_id, user_id, role, invited_email, status)
            VALUES (?,?,?,?,?,?)
        """, (member_id, team_id, user_id, role, invited_email.lower(), "pending" if not user_id else "active"))
    return member_id


def update_team_member(member_id: str, **kwargs):
    if not kwargs:
        return
    cols = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [member_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE team_members SET {cols} WHERE id=?", vals)


def remove_team_member(member_id: str, team_id: str):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM team_members WHERE id=? AND team_id=?",
            (member_id, team_id)
        )


# ── Feature 8: Competitor Tracker ────────────────────────────────────────────

def add_competitor_channel(user_id: int, platform: str, channel_id: str,
                           channel_name: str, channel_url: str) -> str:
    comp_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO competitor_channels (id, user_id, platform, channel_id, channel_name, channel_url)
            VALUES (?,?,?,?,?,?)
        """, (comp_id, user_id, platform, channel_id, channel_name, channel_url))
    return comp_id


def get_competitor_channels(user_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM competitor_channels WHERE user_id=? ORDER BY added_at DESC",
            (user_id,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def get_competitor_channel(comp_id: str, user_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM competitor_channels WHERE id=? AND user_id=?", (comp_id, user_id)
        ).fetchone()
    return row_to_dict(row)


def delete_competitor_channel(comp_id: str, user_id: int):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM competitor_channels WHERE id=? AND user_id=?", (comp_id, user_id)
        )


def upsert_competitor_video(competitor_id: str, video_id: str, title: str,
                            views: int, likes: int, published_at: str,
                            thumbnail_url: str, video_url: str):
    vid_pk = str(uuid.uuid4())
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM competitor_videos WHERE competitor_id=? AND video_id=?",
            (competitor_id, video_id)
        ).fetchone()
        if existing:
            conn.execute("""
                UPDATE competitor_videos SET title=?, views=?, likes=?, published_at=?,
                thumbnail_url=?, video_url=?, fetched_at=datetime('now')
                WHERE id=?
            """, (title, views, likes, published_at, thumbnail_url, video_url, existing["id"]))
        else:
            conn.execute("""
                INSERT INTO competitor_videos
                (id, competitor_id, video_id, title, views, likes, published_at, thumbnail_url, video_url)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (vid_pk, competitor_id, video_id, title, views, likes, published_at, thumbnail_url, video_url))


def get_competitor_videos(competitor_id: str, limit: int = 10):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM competitor_videos WHERE competitor_id=?
            ORDER BY views DESC, fetched_at DESC LIMIT ?
        """, (competitor_id, limit)).fetchall()
    return [row_to_dict(r) for r in rows]


def get_all_competitor_channels_for_refresh():
    """Used by background thread to fetch all competitors needing refresh."""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM competitor_channels").fetchall()
    return [row_to_dict(r) for r in rows]


# ── Feature 11: AI Avatars & Personas ───────────────────────────────────────

def create_persona(user_id: int, name: str, **kwargs) -> str:
    persona_id = str(uuid.uuid4())
    with get_conn() as conn:
        fields = ["id", "user_id", "name"] + list(kwargs.keys())
        placeholders = ",".join(["?"] * len(fields))
        values = [persona_id, user_id, name] + list(kwargs.values())
        conn.execute(
            f"INSERT INTO ai_personas ({','.join(fields)}) VALUES ({placeholders})",
            values
        )
    return persona_id


def get_persona(persona_id: str, user_id: int = None):
    with get_conn() as conn:
        if user_id:
            row = conn.execute(
                "SELECT * FROM ai_personas WHERE id=? AND (user_id=? OR is_preset=1)",
                (persona_id, user_id)
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM ai_personas WHERE id=?", (persona_id,)).fetchone()
    return row_to_dict(row)


def get_personas(user_id: int):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM ai_personas
            WHERE user_id=? OR is_preset=1
            ORDER BY is_preset DESC, use_count DESC, created_at DESC
        """, (user_id,)).fetchall()
    return [row_to_dict(r) for r in rows]


def update_persona(persona_id: str, user_id: int, **kwargs):
    if not kwargs:
        return
    cols = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [persona_id, user_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE ai_personas SET {cols} WHERE id=? AND user_id=?", vals)


def delete_persona(persona_id: str, user_id: int):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM ai_personas WHERE id=? AND user_id=? AND is_preset=0",
            (persona_id, user_id)
        )


def increment_persona_use(persona_id: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE ai_personas SET use_count=use_count+1 WHERE id=?",
            (persona_id,)
        )


def create_persona_generation(persona_id: str, user_id: int, job_id: int = None) -> str:
    gen_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO persona_generations (id, persona_id, user_id, job_id)
            VALUES (?,?,?,?)
        """, (gen_id, persona_id, user_id, job_id))
    return gen_id


def update_persona_generation(gen_id: str, **kwargs):
    if not kwargs:
        return
    cols = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [gen_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE persona_generations SET {cols} WHERE id=?", vals)


# ── Feature 10: A/B Testing ────────────────────────────────────────────────

def create_ab_test(user_id: int, test_type: str, job_id: int = None) -> str:
    test_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO ab_tests (id, user_id, job_id, test_type)
            VALUES (?,?,?,?)
        """, (test_id, user_id, job_id, test_type))
    return test_id


def add_ab_variant(test_id: str, label: str, content: str) -> str:
    variant_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO ab_variants (id, test_id, label, content)
            VALUES (?,?,?,?)
        """, (variant_id, test_id, label, content))
    return variant_id


def record_ab_impression(variant_id: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE ab_variants SET impressions=impressions+1 WHERE id=?",
            (variant_id,)
        )


def record_ab_click(variant_id: str):
    with get_conn() as conn:
        conn.execute("""
            UPDATE ab_variants SET clicks=clicks+1,
            ctr=CAST(clicks+1 AS REAL)/CASE WHEN impressions=0 THEN 1 ELSE impressions END
            WHERE id=?
        """, (variant_id,))


def record_ab_conversion(variant_id: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE ab_variants SET conversions=conversions+1 WHERE id=?",
            (variant_id,)
        )


def get_ab_test(test_id: str):
    with get_conn() as conn:
        test = row_to_dict(conn.execute("SELECT * FROM ab_tests WHERE id=?", (test_id,)).fetchone())
        if test:
            variants = conn.execute(
                "SELECT * FROM ab_variants WHERE test_id=? ORDER BY ctr DESC",
                (test_id,)
            ).fetchall()
            test["variants"] = [row_to_dict(v) for v in variants]
    return test


def get_ab_tests(user_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM ab_tests WHERE user_id=? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
    tests = []
    for row in rows:
        t = row_to_dict(row)
        with get_conn() as conn:
            variants = conn.execute(
                "SELECT * FROM ab_variants WHERE test_id=? ORDER BY ctr DESC",
                (t["id"],)
            ).fetchall()
            t["variants"] = [row_to_dict(v) for v in variants]
        tests.append(t)
    return tests


def end_ab_test(test_id: str, winner_id: str = None):
    with get_conn() as conn:
        if not winner_id:
            top = conn.execute(
                "SELECT id FROM ab_variants WHERE test_id=? ORDER BY ctr DESC LIMIT 1",
                (test_id,)
            ).fetchone()
            winner_id = top["id"] if top else None
        conn.execute(
            "UPDATE ab_tests SET status='completed', winner_id=?, ended_at=datetime('now') WHERE id=?",
            (winner_id, test_id)
        )


# ── Feature 9: Checkout & Lifecycle Tracking ────────────────────────────────

def create_checkout_event(user_id: int, tier: str, stripe_session_id: str = None) -> str:
    event_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO checkout_events (id, user_id, tier, stripe_session_id, status)
            VALUES (?,?,?,?,?)
        """, (event_id, user_id, tier, stripe_session_id, "started"))
    return event_id


def complete_checkout_event(user_id: int, tier: str):
    with get_conn() as conn:
        conn.execute("""
            UPDATE checkout_events SET status='completed', completed_at=datetime('now')
            WHERE user_id=? AND tier=? AND status='started'
        """, (user_id, tier))


def get_abandoned_checkouts(minutes_ago: int = 30):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT ce.*, u.email, u.name FROM checkout_events ce
            JOIN users u ON u.id = ce.user_id
            WHERE ce.status = 'started'
              AND ce.created_at <= datetime('now', ? || ' minutes')
        """, (f"-{minutes_ago}",)).fetchall()
    return [row_to_dict(r) for r in rows]


def mark_checkout_abandoned(event_id: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE checkout_events SET status='abandoned' WHERE id=?", (event_id,)
        )


def has_lifecycle_event(user_id: int, event_key: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM lifecycle_events WHERE user_id=? AND event_key=?",
            (user_id, event_key)
        ).fetchone()
    return row is not None


def record_lifecycle_event(user_id: int, event_key: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO lifecycle_events (user_id, event_key) VALUES (?,?)",
            (user_id, event_key)
        )


def get_onboarding(user_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM onboarding_checklist WHERE user_id=?", (user_id,)
        ).fetchone()
    return row_to_dict(row)


def upsert_onboarding(user_id: int, **kwargs):
    kwargs["updated_at"] = datetime.now().isoformat()
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT user_id FROM onboarding_checklist WHERE user_id=?", (user_id,)
        ).fetchone()
        if existing:
            cols = ", ".join(f"{k}=?" for k in kwargs)
            vals = list(kwargs.values()) + [user_id]
            conn.execute(f"UPDATE onboarding_checklist SET {cols} WHERE user_id=?", vals)
        else:
            kwargs["user_id"] = user_id
            fields = ", ".join(kwargs.keys())
            placeholders = ", ".join(["?"] * len(kwargs))
            conn.execute(
                f"INSERT INTO onboarding_checklist ({fields}) VALUES ({placeholders})",
                list(kwargs.values())
            )


def touch_user_activity(user_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET last_active_at=datetime('now') WHERE id=?", (user_id,)
        )


def get_users_for_lifecycle():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT u.*,
                   (SELECT COUNT(*) FROM jobs j WHERE j.user_id=u.id) as total_jobs,
                   (SELECT COUNT(*) FROM jobs j WHERE j.user_id=u.id AND j.status='done') as completed_jobs,
                   (SELECT COUNT(*) FROM social_accounts sa WHERE sa.user_id=u.id AND sa.is_active=1) as connected_platforms
            FROM users u
            ORDER BY u.created_at DESC
        """).fetchall()
    return [row_to_dict(r) for r in rows]
