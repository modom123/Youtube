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
            videos_used_this_month  INTEGER DEFAULT 0,
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

        CREATE TABLE IF NOT EXISTS engagement_campaigns (
            id          TEXT PRIMARY KEY,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name        TEXT NOT NULL,
            platforms   TEXT DEFAULT '[]',
            status      TEXT DEFAULT 'active',
            is_active   INTEGER DEFAULT 1,
            config_json TEXT DEFAULT '{}',
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS engagement_targets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id TEXT REFERENCES engagement_campaigns(id) ON DELETE CASCADE,
            platform    TEXT NOT NULL,
            username    TEXT NOT NULL,
            profile_url TEXT,
            engaged_at  TEXT,
            added_at    TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS engagement_actions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id     TEXT REFERENCES engagement_campaigns(id) ON DELETE CASCADE,
            user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
            platform        TEXT NOT NULL,
            action_type     TEXT NOT NULL,
            target_username TEXT,
            target_content_id TEXT,
            target_url      TEXT,
            comment_text    TEXT,
            scheduled_at    TEXT,
            status          TEXT DEFAULT 'pending',
            result_json     TEXT DEFAULT '{}',
            created_at      TEXT DEFAULT (datetime('now')),
            executed_at     TEXT
        );

        CREATE TABLE IF NOT EXISTS follow_tracking (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
            platform        TEXT NOT NULL,
            target_username TEXT NOT NULL,
            followed_at     TEXT DEFAULT (datetime('now')),
            followed_back   INTEGER DEFAULT 0,
            unfollowed_at   TEXT,
            status          TEXT DEFAULT 'following'
        );

        CREATE TABLE IF NOT EXISTS dm_templates (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id           INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name              TEXT NOT NULL,
            message_template  TEXT NOT NULL,
            platform          TEXT,
            trigger_on        TEXT,
            uses_spintax      INTEGER DEFAULT 0,
            created_at        TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS auto_reply_rules (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
            platform        TEXT NOT NULL,
            trigger_type    TEXT NOT NULL,
            trigger_value   TEXT NOT NULL,
            reply_template  TEXT NOT NULL,
            uses_spintax    INTEGER DEFAULT 0,
            is_active       INTEGER DEFAULT 1,
            created_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS rss_feeds (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            url         TEXT NOT NULL,
            name        TEXT,
            category    TEXT,
            last_fetched TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS growth_snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
            account_id      INTEGER,
            platform        TEXT,
            followers       INTEGER DEFAULT 0,
            following       INTEGER DEFAULT 0,
            posts           INTEGER DEFAULT 0,
            engagement_rate REAL DEFAULT 0,
            views_total     INTEGER DEFAULT 0,
            likes_total     INTEGER DEFAULT 0,
            recorded_at     TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS media_library (
            id              TEXT PRIMARY KEY,
            user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
            filename        TEXT NOT NULL,
            original_name   TEXT NOT NULL,
            media_type      TEXT NOT NULL,
            mime_type       TEXT,
            file_size       INTEGER DEFAULT 0,
            category        TEXT DEFAULT 'uncategorized',
            tags            TEXT DEFAULT '[]',
            description     TEXT DEFAULT '',
            width           INTEGER,
            height          INTEGER,
            duration_seconds REAL,
            thumbnail_path  TEXT,
            file_path       TEXT NOT NULL,
            created_at      TEXT DEFAULT (datetime('now'))
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
        if "videos_used_this_month" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN videos_used_this_month INTEGER DEFAULT 0")


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


# ── Users ───────────────────────────────────────────────────────────────────────────

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


def increment_videos_used(user_id: int) -> int:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET videos_used_this_month = videos_used_this_month + 1 WHERE id=?",
            (user_id,),
        )
        row = conn.execute("SELECT videos_used_this_month FROM users WHERE id=?", (user_id,)).fetchone()
    return row["videos_used_this_month"]


def reset_monthly_usage(user_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET videos_used_this_month=0 WHERE id=?", (user_id,),
        )


TIER_LIMITS = {"free": 2, "starter": 15, "creator": 50, "agency": 9999}


def check_usage_allowed(user_id: int) -> dict:
    user = get_user_by_id(user_id)
    if not user:
        return {"allowed": False, "reason": "user not found"}
    if user.get("is_admin"):
        return {"allowed": True, "reason": "admin", "remaining": 9999}
    tier = user.get("subscription_tier", "free")
    limit = TIER_LIMITS.get(tier, 5)
    used = user.get("videos_used_this_month", 0)
    return {"allowed": used < limit, "remaining": max(0, limit - used), "tier": tier, "limit": limit}


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


# ── Social Accounts ────────────────────────────────────────────────────────────

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


# ── Contacts ─────────────────────────────────────────────────────────────────────

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


# ── Jobs ───────────────────────────────────────────────────────────────────────────

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


# ── Settings ──────────────────────────────────────────────────────────────────────

def get_setting(key, default=None):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, str(value)))


# ── Feature 1: Analytics ────────────────────────────────────────────────────────────

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


# ── Feature 2: Content Calendar / Scheduler ─────────────────────────────────────────

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


# ── Feature 3: Batch Mode ────────────────────────────────────────────────────────────

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


# ── Feature 4: Template Library ────────────────────────────────────────────────────────

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


# ── Feature 5: Dub Jobs ──────────────────────────────────────────────────────────────

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


# ── Feature 6: Notifications ─────────────────────────────────────────────────────────

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


# ── Feature 7: Team Workspaces ──────────────────────────────────────────────────────────

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


# ── Feature 8: Competitor Tracker ──────────────────────────────────────────────────────

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


# ── Engagement Campaigns ───────────────────────────────────────────────────────

def create_engagement_campaign(user_id: int, name: str, platforms, config_json=None) -> str:
    campaign_id = str(uuid.uuid4())
    if config_json is None:
        config_json = {}
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO engagement_campaigns (id, user_id, name, platforms, config_json)
            VALUES (?,?,?,?,?)
        """, (campaign_id, user_id, name, json.dumps(platforms), json.dumps(config_json)))
    return campaign_id


def get_engagement_campaign(campaign_id: str, user_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM engagement_campaigns WHERE id=? AND user_id=?",
            (campaign_id, user_id)
        ).fetchone()
    return row_to_dict(row)


def get_engagement_campaigns(user_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM engagement_campaigns WHERE user_id=? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def update_engagement_campaign(campaign_id: str, user_id: int = None, **kwargs):
    if not kwargs:
        return
    for k in ("platforms", "config_json"):
        if k in kwargs and isinstance(kwargs[k], (list, dict)):
            kwargs[k] = json.dumps(kwargs[k])
    cols = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [campaign_id]
    query = f"UPDATE engagement_campaigns SET {cols} WHERE id=?"
    if user_id is not None:
        query += " AND user_id=?"
        vals.append(user_id)
    with get_conn() as conn:
        conn.execute(query, vals)


def delete_engagement_campaign(campaign_id: str, user_id: int):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM engagement_campaigns WHERE id=? AND user_id=?",
            (campaign_id, user_id)
        )


# ── Engagement Targets ─────────────────────────────────────────────────────────

def add_engagement_targets(campaign_id: str, targets: list) -> int:
    with get_conn() as conn:
        for t in targets:
            conn.execute("""
                INSERT INTO engagement_targets (campaign_id, platform, username, profile_url)
                VALUES (?,?,?,?)
            """, (campaign_id, t.get("platform", ""), t.get("username", ""), t.get("profile_url", "")))
    return len(targets)


def add_engagement_target(user_id: int, campaign_id: str, platform: str, username: str, profile_url: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO engagement_targets (campaign_id, platform, username, profile_url)
            VALUES (?,?,?,?)
        """, (campaign_id, platform, username, profile_url))
        return cur.lastrowid


def get_engagement_targets(user_id: int = None, campaign_id: str = None, engaged: bool = None):
    query = "SELECT * FROM engagement_targets WHERE 1=1"
    params = []
    if campaign_id:
        query += " AND campaign_id=?"
        params.append(campaign_id)
    if engaged is True:
        query += " AND engaged_at IS NOT NULL"
    elif engaged is False:
        query += " AND engaged_at IS NULL"
    query += " ORDER BY added_at DESC"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [row_to_dict(r) for r in rows]


def mark_target_engaged(target_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE engagement_targets SET engaged_at=datetime('now') WHERE id=?",
            (target_id,)
        )


# ── Engagement Actions ─────────────────────────────────────────────────────────

def create_engagement_action(user_id: int, platform: str, action_type: str,
                             target_username: str = "", target_content_id: str = "",
                             target_url: str = "", comment_text: str = "",
                             campaign_id: str = None, scheduled_at: str = None) -> int:
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO engagement_actions
            (campaign_id, user_id, platform, action_type, target_username, target_content_id,
             target_url, comment_text, scheduled_at)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (campaign_id, user_id, platform, action_type, target_username,
              target_content_id, target_url, comment_text or "", scheduled_at))
        return cur.lastrowid


def get_engagement_actions(user_id: int = None, campaign_id=None, status=None):
    query = "SELECT * FROM engagement_actions WHERE 1=1"
    params = []
    if user_id:
        query += " AND user_id=?"
        params.append(user_id)
    if campaign_id:
        query += " AND campaign_id=?"
        params.append(campaign_id)
    if status:
        query += " AND status=?"
        params.append(status)
    query += " ORDER BY created_at DESC"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [row_to_dict(r) for r in rows]


def update_engagement_action(action_id: int, **kwargs):
    if not kwargs:
        return
    cols = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [action_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE engagement_actions SET {cols} WHERE id=?", vals)


def get_engagement_stats(user_id: int):
    today = datetime.now().strftime("%Y-%m-%d")
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) as n FROM engagement_actions WHERE user_id=?", (user_id,)
        ).fetchone()["n"]
        by_status = conn.execute(
            "SELECT status, COUNT(*) as count FROM engagement_actions WHERE user_id=? GROUP BY status",
            (user_id,)
        ).fetchall()
        by_action = conn.execute(
            "SELECT action_type, COUNT(*) as count FROM engagement_actions WHERE user_id=? GROUP BY action_type",
            (user_id,)
        ).fetchall()
        daily_count = conn.execute(
            "SELECT COUNT(*) as n FROM engagement_actions WHERE user_id=? AND created_at >= ?",
            (user_id, today)
        ).fetchone()["n"]
    return {
        "total": total,
        "by_status": {r["status"]: r["count"] for r in by_status},
        "by_action": {r["action_type"]: r["count"] for r in by_action},
        "daily_count": daily_count,
    }


def get_daily_action_count(user_id: int, platform: str = None) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    with get_conn() as conn:
        if platform:
            row = conn.execute(
                "SELECT COUNT(*) as n FROM engagement_actions WHERE user_id=? AND platform=? AND created_at >= ?",
                (user_id, platform, today)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) as n FROM engagement_actions WHERE user_id=? AND created_at >= ?",
                (user_id, today)
            ).fetchone()
    return row["n"]


# ── Follow Tracking ────────────────────────────────────────────────────────────

def track_follow(user_id: int, platform: str, target_username: str) -> int:
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO follow_tracking (user_id, platform, target_username)
            VALUES (?,?,?)
        """, (user_id, platform, target_username))
        return cur.lastrowid


def get_follows(user_id: int, platform=None, status=None):
    query = "SELECT * FROM follow_tracking WHERE user_id=?"
    params = [user_id]
    if platform:
        query += " AND platform=?"
        params.append(platform)
    if status:
        query += " AND status=?"
        params.append(status)
    query += " ORDER BY followed_at DESC"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [row_to_dict(r) for r in rows]


def mark_follow_back(user_id: int, platform: str, target_username: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE follow_tracking SET followed_back=1 WHERE user_id=? AND platform=? AND target_username=?",
            (user_id, platform, target_username)
        )


def mark_unfollowed(follow_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE follow_tracking SET status='unfollowed', unfollowed_at=datetime('now') WHERE id=?",
            (follow_id,)
        )


def get_stale_follows(user_id: int, platform=None, days_threshold: int = 3):
    query = """
        SELECT * FROM follow_tracking
        WHERE user_id=? AND status='following' AND followed_back=0
        AND followed_at <= datetime('now', ?)
    """
    params = [user_id, f"-{days_threshold} days"]
    if platform:
        query += " AND platform=?"
        params.append(platform)
    query += " ORDER BY followed_at ASC"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [row_to_dict(r) for r in rows]


# ── DM Templates ───────────────────────────────────────────────────────────────

def create_dm_template(user_id: int, name: str, message_template: str,
                       platform=None, trigger_on=None, uses_spintax=False) -> int:
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO dm_templates (user_id, name, message_template, platform, trigger_on, uses_spintax)
            VALUES (?,?,?,?,?,?)
        """, (user_id, name, message_template, platform, trigger_on, int(uses_spintax)))
        return cur.lastrowid


def get_dm_templates(user_id: int, platform=None):
    query = "SELECT * FROM dm_templates WHERE user_id=?"
    params = [user_id]
    if platform:
        query += " AND platform=?"
        params.append(platform)
    query += " ORDER BY created_at DESC"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [row_to_dict(r) for r in rows]


def delete_dm_template(tmpl_id: int, user_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM dm_templates WHERE id=? AND user_id=?", (tmpl_id, user_id))


# ── Auto-Reply Rules ──────────────────────────────────────────────────────────

def create_auto_reply_rule(user_id: int, platform: str, trigger_type: str,
                           trigger_value: str, reply_template: str,
                           uses_spintax=False) -> int:
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO auto_reply_rules
            (user_id, platform, trigger_type, trigger_value, reply_template, uses_spintax)
            VALUES (?,?,?,?,?,?)
        """, (user_id, platform, trigger_type, trigger_value, reply_template, int(uses_spintax)))
        return cur.lastrowid


def get_auto_reply_rules(user_id: int, platform=None):
    query = "SELECT * FROM auto_reply_rules WHERE user_id=?"
    params = [user_id]
    if platform:
        query += " AND platform=?"
        params.append(platform)
    query += " ORDER BY created_at DESC"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [row_to_dict(r) for r in rows]


def delete_auto_reply_rule(rule_id: int, user_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM auto_reply_rules WHERE id=? AND user_id=?", (rule_id, user_id))


# ── RSS Feeds ──────────────────────────────────────────────────────────────────

def add_rss_feed(user_id: int, url: str, name=None, category=None) -> int:
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO rss_feeds (user_id, url, name, category)
            VALUES (?,?,?,?)
        """, (user_id, url, name, category))
        return cur.lastrowid


def get_rss_feeds(user_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM rss_feeds WHERE user_id=? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def delete_rss_feed(feed_id: int, user_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM rss_feeds WHERE id=? AND user_id=?", (feed_id, user_id))


# ── Growth Snapshots ───────────────────────────────────────────────────────────

def add_growth_snapshot(user_id: int, account_id, platform: str,
                        followers=0, following=0, posts=0,
                        engagement_rate=0, views_total=0, likes_total=0) -> int:
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO growth_snapshots
            (user_id, account_id, platform, followers, following, posts,
             engagement_rate, views_total, likes_total)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (user_id, account_id, platform, followers, following, posts,
              engagement_rate, views_total, likes_total))
        return cur.lastrowid


def get_growth_history(user_id: int, account_id=None, platform=None):
    query = "SELECT * FROM growth_snapshots WHERE user_id=?"
    params = [user_id]
    if account_id is not None:
        query += " AND account_id=?"
        params.append(account_id)
    if platform:
        query += " AND platform=?"
        params.append(platform)
    query += " ORDER BY recorded_at DESC"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [row_to_dict(r) for r in rows]


def get_growth_summary(user_id: int):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT platform, followers, recorded_at, id
            FROM growth_snapshots WHERE user_id=?
            ORDER BY recorded_at DESC, id DESC
        """, (user_id,)).fetchall()
    snapshots = [row_to_dict(r) for r in rows]
    summary = {}
    for s in snapshots:
        plat = s.get("platform", "unknown")
        if plat not in summary:
            summary[plat] = {"latest_followers": s["followers"], "earliest_followers": s["followers"]}
        else:
            summary[plat]["earliest_followers"] = s["followers"]
    for plat in summary:
        summary[plat]["growth"] = summary[plat]["latest_followers"] - summary[plat]["earliest_followers"]
    return summary


# ── Media Library ─────────────────────────────────────────────────────────────

ALLOWED_MEDIA_TYPES = {
    "image": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".tiff"},
    "video": {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".wmv"},
    "audio": {".mp3", ".wav", ".aac", ".ogg", ".flac", ".m4a", ".wma"},
    "document": {".pdf", ".doc", ".docx", ".txt", ".rtf", ".csv", ".xls", ".xlsx"},
}

MAX_FILE_SIZE = 500 * 1024 * 1024  # 500 MB


def _classify_media_type(extension: str) -> str:
    ext = extension.lower()
    for media_type, extensions in ALLOWED_MEDIA_TYPES.items():
        if ext in extensions:
            return media_type
    return "other"


def _all_allowed_extensions() -> set:
    result = set()
    for exts in ALLOWED_MEDIA_TYPES.values():
        result |= exts
    return result


def add_media(user_id: int, filename: str, original_name: str,
              file_path: str, file_size: int = 0, mime_type: str = "",
              category: str = "uncategorized", tags: list = None,
              description: str = "", width: int = None, height: int = None,
              duration_seconds: float = None) -> dict:
    media_id = str(uuid.uuid4())
    ext = Path(original_name).suffix.lower()
    media_type = _classify_media_type(ext)
    tags_json = json.dumps(tags or [])
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO media_library
            (id, user_id, filename, original_name, media_type, mime_type,
             file_size, category, tags, description, width, height,
             duration_seconds, file_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (media_id, user_id, filename, original_name, media_type,
              mime_type, file_size, category, tags_json, description,
              width, height, duration_seconds, file_path))
    return {"id": media_id, "media_type": media_type, "filename": filename}


def get_media(media_id: str, user_id: int = None) -> dict | None:
    query = "SELECT * FROM media_library WHERE id=?"
    params = [media_id]
    if user_id is not None:
        query += " AND user_id=?"
        params.append(user_id)
    with get_conn() as conn:
        row = conn.execute(query, params).fetchone()
    if not row:
        return None
    item = row_to_dict(row)
    item["tags"] = json.loads(item.get("tags", "[]"))
    return item


def get_media_library(user_id: int, media_type: str = None,
                      category: str = None, search: str = None,
                      limit: int = 50, offset: int = 0) -> list:
    query = "SELECT * FROM media_library WHERE user_id=?"
    params: list = [user_id]
    if media_type:
        query += " AND media_type=?"
        params.append(media_type)
    if category:
        query += " AND category=?"
        params.append(category)
    if search:
        query += " AND (original_name LIKE ? OR description LIKE ? OR tags LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like])
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    items = []
    for r in rows:
        item = row_to_dict(r)
        item["tags"] = json.loads(item.get("tags", "[]"))
        items.append(item)
    return items


def get_media_stats(user_id: int) -> dict:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT media_type, COUNT(*) as count, SUM(file_size) as total_size
            FROM media_library WHERE user_id=? GROUP BY media_type
        """, (user_id,)).fetchall()
    stats = {"total_files": 0, "total_size": 0, "by_type": {}}
    for r in rows:
        d = row_to_dict(r)
        stats["by_type"][d["media_type"]] = {
            "count": d["count"], "size": d["total_size"] or 0
        }
        stats["total_files"] += d["count"]
        stats["total_size"] += d["total_size"] or 0
    return stats


def update_media(media_id: str, user_id: int, **kwargs):
    if not kwargs:
        return
    if "tags" in kwargs and isinstance(kwargs["tags"], list):
        kwargs["tags"] = json.dumps(kwargs["tags"])
    cols = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [media_id, user_id]
    with get_conn() as conn:
        conn.execute(
            f"UPDATE media_library SET {cols} WHERE id=? AND user_id=?", vals
        )


def delete_media(media_id: str, user_id: int) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT file_path FROM media_library WHERE id=? AND user_id=?",
            (media_id, user_id)
        ).fetchone()
        if not row:
            return None
        file_path = row[0]
        conn.execute(
            "DELETE FROM media_library WHERE id=? AND user_id=?",
            (media_id, user_id)
        )
    return file_path


# ── Admin / Business Intelligence ─────────────────────────────────────────────

def admin_get_overview() -> dict:
    with get_conn() as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        users_by_tier = {}
        for row in conn.execute(
            "SELECT COALESCE(tier,'free') as t, COUNT(*) as c FROM users GROUP BY t"
        ).fetchall():
            users_by_tier[row[0]] = row[1]

        total_jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        completed_jobs = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE status='completed'"
        ).fetchone()[0]
        failed_jobs = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE status='failed'"
        ).fetchone()[0]

        today = datetime.now().strftime("%Y-%m-%d")
        jobs_today = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE created_at LIKE ?", (f"{today}%",)
        ).fetchone()[0]
        new_users_today = conn.execute(
            "SELECT COUNT(*) FROM users WHERE created_at LIKE ?", (f"{today}%",)
        ).fetchone()[0]

        total_media = conn.execute("SELECT COUNT(*) FROM media_library").fetchone()[0]
        media_size = conn.execute(
            "SELECT COALESCE(SUM(file_size),0) FROM media_library"
        ).fetchone()[0]

        total_campaigns = conn.execute(
            "SELECT COUNT(*) FROM engagement_campaigns"
        ).fetchone()[0]
        total_actions = conn.execute(
            "SELECT COUNT(*) FROM engagement_actions"
        ).fetchone()[0]

    return {
        "total_users": total_users,
        "users_by_tier": users_by_tier,
        "total_jobs": total_jobs,
        "completed_jobs": completed_jobs,
        "failed_jobs": failed_jobs,
        "jobs_today": jobs_today,
        "new_users_today": new_users_today,
        "total_media": total_media,
        "media_size_bytes": media_size,
        "total_campaigns": total_campaigns,
        "total_actions": total_actions,
    }


def admin_get_revenue_estimate() -> dict:
    from config import TIERS
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT COALESCE(tier,'free') as t, COUNT(*) as c FROM users GROUP BY t"
        ).fetchall()
    mrr = 0
    breakdown = {}
    for row in rows:
        tier_key = row[0]
        count = row[1]
        price = TIERS.get(tier_key, {}).get("price_monthly", 0)
        rev = price * count
        mrr += rev
        breakdown[tier_key] = {"users": count, "price": price, "revenue": rev}
    return {
        "mrr": mrr,
        "arr": mrr * 12,
        "breakdown": breakdown,
    }


def admin_list_users(limit: int = 50, offset: int = 0, search: str = None,
                     tier: str = None) -> list:
    query = "SELECT id, email, name, tier, is_admin, videos_used_this_month, created_at FROM users WHERE 1=1"
    params: list = []
    if search:
        query += " AND (email LIKE ? OR name LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like])
    if tier:
        query += " AND COALESCE(tier,'free')=?"
        params.append(tier)
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [row_to_dict(r) for r in rows]


def admin_get_user_count() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def admin_update_user(user_id: int, **kwargs):
    if not kwargs:
        return
    cols = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [user_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE users SET {cols} WHERE id=?", vals)


def admin_get_job_stats() -> dict:
    with get_conn() as conn:
        by_status = {}
        for row in conn.execute(
            "SELECT status, COUNT(*) FROM jobs GROUP BY status"
        ).fetchall():
            by_status[row[0]] = row[1]

        by_niche = {}
        for row in conn.execute(
            "SELECT niche, COUNT(*) as c FROM jobs GROUP BY niche ORDER BY c DESC LIMIT 10"
        ).fetchall():
            by_niche[row[0]] = row[1]

        recent_7d = conn.execute("""
            SELECT DATE(created_at) as day, COUNT(*) as c
            FROM jobs WHERE created_at >= datetime('now', '-7 days')
            GROUP BY day ORDER BY day
        """).fetchall()
        daily = [{"date": r[0], "count": r[1]} for r in recent_7d]

    return {"by_status": by_status, "top_niches": by_niche, "daily_7d": daily}


def admin_get_growth_metrics() -> dict:
    with get_conn() as conn:
        signups_7d = []
        for row in conn.execute("""
            SELECT DATE(created_at) as day, COUNT(*) as c
            FROM users WHERE created_at >= datetime('now', '-7 days')
            GROUP BY day ORDER BY day
        """).fetchall():
            signups_7d.append({"date": row[0], "count": row[1]})

        signups_30d = []
        for row in conn.execute("""
            SELECT DATE(created_at) as day, COUNT(*) as c
            FROM users WHERE created_at >= datetime('now', '-30 days')
            GROUP BY day ORDER BY day
        """).fetchall():
            signups_30d.append({"date": row[0], "count": row[1]})

        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        paid_users = conn.execute(
            "SELECT COUNT(*) FROM users WHERE tier IS NOT NULL AND tier != 'free'"
        ).fetchone()[0]

    return {
        "signups_7d": signups_7d,
        "signups_30d": signups_30d,
        "total_users": total_users,
        "paid_users": paid_users,
        "conversion_rate": round(paid_users / max(total_users, 1) * 100, 1),
    }


def admin_get_system_health() -> dict:
    import shutil
    db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    upload_dir = Path(_os.getenv("DATA_DIR", Path(__file__).parent)) / "uploads"
    upload_size = sum(f.stat().st_size for f in upload_dir.rglob("*") if f.is_file()) if upload_dir.exists() else 0
    disk = shutil.disk_usage(str(DB_PATH.parent))
    return {
        "db_size_bytes": db_size,
        "upload_size_bytes": upload_size,
        "disk_total_bytes": disk.total,
        "disk_used_bytes": disk.used,
        "disk_free_bytes": disk.free,
        "disk_pct_used": round(disk.used / disk.total * 100, 1),
    }
