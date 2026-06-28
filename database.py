"""SQLite database layer for the Social Optimize dashboard."""
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

        CREATE TABLE IF NOT EXISTS outreach_campaigns (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name        TEXT NOT NULL,
            type        TEXT NOT NULL DEFAULT 'email',
            subject     TEXT,
            body        TEXT NOT NULL,
            status      TEXT DEFAULT 'draft',
            sent_count  INTEGER DEFAULT 0,
            open_count  INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now')),
            sent_at     TEXT
        );

        CREATE TABLE IF NOT EXISTS outreach_sends (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id     INTEGER REFERENCES outreach_campaigns(id) ON DELETE CASCADE,
            contact_id      INTEGER REFERENCES contacts(id) ON DELETE CASCADE,
            user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
            status          TEXT DEFAULT 'pending',
            sent_at         TEXT,
            error_msg       TEXT,
            message_sid     TEXT,
            UNIQUE(campaign_id, contact_id)
        );

        CREATE TABLE IF NOT EXISTS inbound_sms (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            message_sid     TEXT UNIQUE,
            from_number     TEXT NOT NULL,
            to_number       TEXT,
            body            TEXT,
            received_at     TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS inbound_calls (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            call_sid        TEXT UNIQUE,
            from_number     TEXT NOT NULL,
            to_number       TEXT,
            call_status     TEXT DEFAULT 'ringing',
            duration        INTEGER DEFAULT 0,
            recording_sid   TEXT,
            recording_url   TEXT,
            recording_duration INTEGER DEFAULT 0,
            caller_city     TEXT,
            caller_state    TEXT,
            caller_country  TEXT,
            transcription   TEXT,
            received_at     TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
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

        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,
            token      TEXT UNIQUE NOT NULL,
            expires_at TEXT NOT NULL,
            used       INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
            action        TEXT NOT NULL,
            target_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            details       TEXT DEFAULT '{}',
            created_at    TEXT DEFAULT (datetime('now'))
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

        -- Feature: Follow Tracking
        CREATE TABLE IF NOT EXISTS follow_tracking (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
            platform        TEXT,
            target_username TEXT,
            status          TEXT DEFAULT 'following',
            followed_back   INTEGER DEFAULT 0,
            followed_at     TEXT DEFAULT (datetime('now')),
            unfollowed_at   TEXT
        );

        -- Feature: DM Templates
        CREATE TABLE IF NOT EXISTS dm_templates (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id          INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name             TEXT,
            message_template TEXT,
            platform         TEXT,
            trigger_on       TEXT,
            created_at       TEXT DEFAULT (datetime('now'))
        );

        -- Feature: Auto-Reply Rules
        CREATE TABLE IF NOT EXISTS auto_reply_rules (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
            platform        TEXT,
            trigger_type    TEXT,
            trigger_value   TEXT,
            reply_template  TEXT,
            uses_spintax    INTEGER DEFAULT 0,
            enabled         INTEGER DEFAULT 1,
            created_at      TEXT DEFAULT (datetime('now'))
        );

        -- Feature: RSS Feeds
        CREATE TABLE IF NOT EXISTS rss_feeds (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
            url          TEXT,
            name         TEXT,
            category     TEXT,
            enabled      INTEGER DEFAULT 1,
            last_checked TEXT,
            created_at   TEXT DEFAULT (datetime('now'))
        );

        -- Feature: Growth Snapshots
        CREATE TABLE IF NOT EXISTS growth_snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
            account_id      TEXT,
            platform        TEXT,
            followers       INTEGER DEFAULT 0,
            following       INTEGER DEFAULT 0,
            posts           INTEGER DEFAULT 0,
            engagement_rate REAL DEFAULT 0,
            views_total     INTEGER DEFAULT 0,
            likes_total     INTEGER DEFAULT 0,
            created_at      TEXT DEFAULT (datetime('now'))
        );

        -- Feature: Engagement Targets
        CREATE TABLE IF NOT EXISTS engagement_targets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            campaign_id INTEGER,
            platform    TEXT,
            username    TEXT,
            followers   INTEGER DEFAULT 0,
            engaged     INTEGER DEFAULT 0,
            engaged_at  TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        -- Feature: Engagement Actions
        CREATE TABLE IF NOT EXISTS engagement_actions (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id           INTEGER REFERENCES users(id) ON DELETE CASCADE,
            platform          TEXT,
            action_type       TEXT,
            target_url        TEXT DEFAULT '',
            target_username   TEXT DEFAULT '',
            target_content_id TEXT DEFAULT '',
            comment_text      TEXT DEFAULT '',
            campaign_id       INTEGER,
            status            TEXT DEFAULT 'queued',
            scheduled_at      TEXT,
            executed_at       TEXT,
            error_msg         TEXT DEFAULT '',
            created_at        TEXT DEFAULT (datetime('now'))
        );

        -- Feature: Engagement Campaigns
        CREATE TABLE IF NOT EXISTS engagement_campaigns (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name         TEXT,
            platforms    TEXT DEFAULT '[]',
            target_niche TEXT DEFAULT '',
            strategy     TEXT DEFAULT 'growth',
            daily_limit  INTEGER DEFAULT 50,
            is_active    INTEGER DEFAULT 1,
            created_at   TEXT DEFAULT (datetime('now'))
        );
        """)

        # ── Agency / BizDev tables ────────────────────────────────
        conn.execute("""
        CREATE TABLE IF NOT EXISTS agency_clients (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name         TEXT NOT NULL,
            company      TEXT DEFAULT '',
            email        TEXT DEFAULT '',
            phone        TEXT DEFAULT '',
            industry     TEXT DEFAULT '',
            website      TEXT DEFAULT '',
            status       TEXT DEFAULT 'lead',
            monthly_value REAL DEFAULT 0,
            notes        TEXT DEFAULT '',
            created_at   TEXT DEFAULT (datetime('now')),
            updated_at   TEXT DEFAULT (datetime('now'))
        );
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS agency_deals (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
            client_id    INTEGER REFERENCES agency_clients(id) ON DELETE CASCADE,
            title        TEXT NOT NULL,
            value        REAL DEFAULT 0,
            stage        TEXT DEFAULT 'discovery',
            service_type TEXT DEFAULT 'content',
            description  TEXT DEFAULT '',
            close_date   TEXT DEFAULT '',
            created_at   TEXT DEFAULT (datetime('now')),
            updated_at   TEXT DEFAULT (datetime('now'))
        );
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS agency_proposals (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
            deal_id      INTEGER REFERENCES agency_deals(id) ON DELETE CASCADE,
            client_id    INTEGER REFERENCES agency_clients(id) ON DELETE CASCADE,
            title        TEXT NOT NULL,
            content      TEXT DEFAULT '',
            pricing      TEXT DEFAULT '{}',
            status       TEXT DEFAULT 'draft',
            sent_at      TEXT,
            created_at   TEXT DEFAULT (datetime('now'))
        );
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS agency_projects (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
            client_id    INTEGER REFERENCES agency_clients(id) ON DELETE CASCADE,
            deal_id      INTEGER REFERENCES agency_deals(id),
            name         TEXT NOT NULL,
            status       TEXT DEFAULT 'active',
            service_type TEXT DEFAULT 'content',
            deliverables TEXT DEFAULT '[]',
            start_date   TEXT DEFAULT (date('now')),
            end_date     TEXT DEFAULT '',
            monthly_fee  REAL DEFAULT 0,
            videos_quota INTEGER DEFAULT 10,
            videos_used  INTEGER DEFAULT 0,
            created_at   TEXT DEFAULT (datetime('now'))
        );
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS agency_revenue (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
            client_id    INTEGER REFERENCES agency_clients(id),
            project_id   INTEGER REFERENCES agency_projects(id),
            amount       REAL NOT NULL,
            type         TEXT DEFAULT 'recurring',
            description  TEXT DEFAULT '',
            period       TEXT DEFAULT '',
            created_at   TEXT DEFAULT (datetime('now'))
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

        # Migrate: add build_log column for diagnostic logging
        job_cols = [r["name"] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()]
        if "build_log" not in job_cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN build_log TEXT DEFAULT ''")


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
        return row_to_dict(conn.execute("SELECT *, videos_used AS videos_used_this_month FROM users WHERE id=?", (user_id,)).fetchone())


def get_user_by_email(email: str):
    with get_conn() as conn:
        return row_to_dict(conn.execute("SELECT * FROM users WHERE email=?", (email.lower().strip(),)).fetchone())


def count_users() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
        return row[0] if row else 0


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
        conn.execute("UPDATE users SET videos_used = videos_used + 1 WHERE id=?", (user_id,))
        row = conn.execute("SELECT videos_used FROM users WHERE id=?", (user_id,)).fetchone()
        return row["videos_used"] if row else 0


def reset_monthly_usage(user_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE users SET videos_used = 0, credits_used = 0 WHERE id=?", (user_id,))


def check_usage_allowed(user_id: int) -> dict:
    user = get_user_by_id(user_id)
    if not user:
        return {"allowed": False, "reason": "User not found"}
    if user.get("is_admin"):
        return {"allowed": True, "reason": "admin"}
    tier = user.get("subscription_tier", "free")
    limits = {"free": 2, "starter": 30, "creator": 100, "agency": 999999}
    limit = limits.get(tier, 2)
    used = user.get("videos_used", 0)
    if used >= limit:
        return {"allowed": False, "reason": f"Limit of {limit} reached for {tier} tier"}
    return {"allowed": True, "reason": "ok"}


def reset_usage_if_new_period(user_id: int):
    """Reset usage counters when a new billing period has started."""
    user = get_user_by_id(user_id)
    if not user:
        return
    period_start = user.get("period_start") or ""
    current_month_start = datetime.now().strftime("%Y-%m-01")
    if period_start < current_month_start:
        update_user(user_id, videos_used=0, credits_used=0, period_start=current_month_start)


def count_completed_jobs_since(user_id: int, since_date: str) -> int:
    """Count jobs with status='done' for user since the given date (YYYY-MM-DD)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM jobs WHERE user_id=? AND status='done' AND created_at >= ?",
            (user_id, since_date),
        ).fetchone()
        return (row["cnt"] if row else 0) or 0


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
                   user_id=None, platform_user_id=None):
    if platform_user_id and not account_id:
        account_id = platform_user_id
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


def delete_job(job_id, user_id=None):
    with get_conn() as conn:
        if user_id:
            conn.execute("DELETE FROM jobs WHERE id=? AND user_id=?", (job_id, user_id))
        else:
            conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))


def get_jobs(limit=50, user_id=None, team_id=None, status=None):
    with get_conn() as conn:
        if team_id:
            q = """SELECT j.* FROM jobs j
                JOIN team_members tm ON tm.user_id = j.user_id
                WHERE tm.team_id = ? AND tm.status = 'active'"""
            params = [team_id]
            if status:
                q += " AND j.status = ?"
                params.append(status)
            q += " ORDER BY j.created_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(q, params).fetchall()
        elif user_id:
            q = "SELECT * FROM jobs WHERE user_id=?"
            params = [user_id]
            if status:
                q += " AND status=?"
                params.append(status)
            q += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(q, params).fetchall()
        else:
            q = "SELECT * FROM jobs"
            params = []
            if status:
                q += " WHERE status=?"
                params.append(status)
            q += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(q, params).fetchall()
    return [row_to_dict(r) for r in rows]


def get_all_running_jobs():
    """Return all jobs currently in 'running' or 'pending' status (for monitor agent)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status IN ('running','pending') ORDER BY created_at ASC"
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


# ── Feature 9: Outreach Campaigns ────────────────────────────────────────────

def create_campaign(user_id, name, type_, subject, body):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO outreach_campaigns (user_id, name, type, subject, body) VALUES (?,?,?,?,?)",
            (user_id, name, type_, subject, body)
        )
        return cur.lastrowid


def get_campaigns(user_id):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM outreach_campaigns WHERE user_id=? ORDER BY created_at DESC", (user_id,)
        ).fetchall()]


def get_campaign(campaign_id, user_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM outreach_campaigns WHERE id=? AND user_id=?", (campaign_id, user_id)
        ).fetchone()
        return dict(row) if row else None


def delete_campaign(campaign_id, user_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM outreach_campaigns WHERE id=? AND user_id=?", (campaign_id, user_id))


def log_send(campaign_id, contact_id, user_id, status, error_msg=None, message_sid=None):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO outreach_sends
               (campaign_id, contact_id, user_id, status, sent_at, error_msg, message_sid)
               VALUES (?,?,?,?,datetime('now'),?,?)""",
            (campaign_id, contact_id, user_id, status, error_msg, message_sid)
        )


def increment_campaign_sent(campaign_id, count=1):
    with get_conn() as conn:
        conn.execute(
            "UPDATE outreach_campaigns SET sent_count=sent_count+?, sent_at=datetime('now'), status='sent' WHERE id=?",
            (count, campaign_id)
        )


def get_campaign_sends(campaign_id):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            """SELECT os.*, c.name, c.email, c.phone FROM outreach_sends os
               JOIN contacts c ON c.id=os.contact_id
               WHERE os.campaign_id=?""", (campaign_id,)
        ).fetchall()]


def update_send_status_by_sid(message_sid: str, status: str):
    """Update outreach_sends delivery status when Twilio posts a status callback."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE outreach_sends SET status=? WHERE message_sid=?",
            (status, message_sid)
        )


def log_inbound_call(call_sid: str, from_: str, to: str,
                     status: str = "ringing",
                     city: str = None, state: str = None, country: str = None):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO inbound_calls
               (call_sid, from_number, to_number, call_status, caller_city, caller_state, caller_country)
               VALUES (?,?,?,?,?,?,?)""",
            (call_sid, from_, to, status, city, state, country)
        )


def update_inbound_call(call_sid: str, **kwargs):
    if not kwargs:
        return
    kwargs["updated_at"] = "datetime('now')"
    # updated_at uses SQL function — handle it separately
    kwargs.pop("updated_at")
    cols = ", ".join(f"{k}=?" for k in kwargs) + ", updated_at=datetime('now')"
    vals = list(kwargs.values()) + [call_sid]
    with get_conn() as conn:
        conn.execute(f"UPDATE inbound_calls SET {cols} WHERE call_sid=?", vals)


def get_inbound_calls(limit: int = 100):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM inbound_calls ORDER BY received_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def get_admin_users():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users WHERE is_admin=1").fetchall()
    return [row_to_dict(r) for r in rows]


def get_all_users(limit: int = 500, tier: str = None):
    with get_conn() as conn:
        if tier:
            rows = conn.execute(
                "SELECT *, videos_used AS videos_used_this_month FROM users WHERE subscription_tier=? ORDER BY created_at DESC LIMIT ?",
                (tier, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT *, videos_used AS videos_used_this_month FROM users ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
    return [row_to_dict(r) for r in rows]


def get_admin_stats():
    """Return MRR, tier counts, and status counts for the admin dashboard."""
    tier_prices = {"starter": 29, "creator": 79, "agency": 199}
    with get_conn() as conn:
        rows = conn.execute("SELECT subscription_tier, subscription_status FROM users").fetchall()
    total = len(rows)
    tier_counts = {"free": 0, "starter": 0, "creator": 0, "agency": 0}
    status_counts = {"active": 0, "canceled": 0, "past_due": 0, "suspended": 0}
    mrr = 0
    for r in rows:
        tier = r["subscription_tier"] or "free"
        status = r["subscription_status"] or "active"
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        status_counts[status] = status_counts.get(status, 0) + 1
        if status == "active" and tier in tier_prices:
            mrr += tier_prices[tier]
    return {
        "total_users": total,
        "tier_counts": tier_counts,
        "status_counts": status_counts,
        "mrr": mrr,
    }


def get_user_jobs_summary(user_id: int):
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM jobs WHERE user_id=?", (user_id,)).fetchone()[0]
        done = conn.execute("SELECT COUNT(*) FROM jobs WHERE user_id=? AND status='done'", (user_id,)).fetchone()[0]
        recent = conn.execute(
            "SELECT id, topic, format, status, created_at FROM jobs WHERE user_id=? ORDER BY created_at DESC LIMIT 10",
            (user_id,)
        ).fetchall()
    return {"total": total, "done": done, "recent": [row_to_dict(r) for r in recent]}


# ── Password Reset ────────────────────────────────────────────────────────────

def create_password_reset_token(user_id: int, token: str, expires_at: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM password_reset_tokens WHERE user_id=? AND used=0", (user_id,))
        conn.execute(
            "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (?,?,?)",
            (user_id, token, expires_at)
        )


def get_password_reset_token(token: str):
    with get_conn() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM password_reset_tokens WHERE token=? AND used=0", (token,)
        ).fetchone())


def consume_password_reset_token(token: str):
    with get_conn() as conn:
        conn.execute("UPDATE password_reset_tokens SET used=1 WHERE token=?", (token,))


# ── Audit Log ─────────────────────────────────────────────────────────────────

def log_audit(admin_id: int, action: str, target_user_id: int = None, details: dict = None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO audit_log (admin_id, action, target_user_id, details) VALUES (?,?,?,?)",
            (admin_id, action, target_user_id, json.dumps(details or {}))
        )


def get_audit_log(limit: int = 100):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT a.*, u.email AS admin_email, t.email AS target_email
               FROM audit_log a
               LEFT JOIN users u ON u.id = a.admin_id
               LEFT JOIN users t ON t.id = a.target_user_id
               ORDER BY a.created_at DESC LIMIT ?""",
            (limit,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def get_inbound_sms(limit: int = 100):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM inbound_sms ORDER BY received_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def log_inbound_sms(from_: str, to: str, body: str, message_sid: str):
    """Store an inbound SMS reply received via the Twilio webhook."""
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO inbound_sms (message_sid, from_number, to_number, body, received_at)
               VALUES (?,?,?,?,datetime('now'))""",
            (message_sid, from_, to, body)
        )


# ── Follow Tracking ──────────────────────────────────────────────────────────

def track_follow(user_id, platform, target_username):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO follow_tracking (user_id, platform, target_username) VALUES (?,?,?)",
            (user_id, platform, target_username))
        return cur.lastrowid

def get_follows(user_id, status=None):
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM follow_tracking WHERE user_id=? AND status=? ORDER BY followed_at DESC",
                (user_id, status)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM follow_tracking WHERE user_id=? ORDER BY followed_at DESC",
                (user_id,)).fetchall()
        return [dict(r) for r in rows]

def mark_follow_back(user_id, platform, target_username):
    with get_conn() as conn:
        conn.execute(
            "UPDATE follow_tracking SET followed_back=1 WHERE user_id=? AND platform=? AND target_username=?",
            (user_id, platform, target_username))

def mark_unfollowed(follow_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE follow_tracking SET status='unfollowed', unfollowed_at=datetime('now') WHERE id=?",
            (follow_id,))

def get_stale_follows(user_id, days=7, platform=None, days_threshold=None):
    if days_threshold is not None:
        days = days_threshold
    with get_conn() as conn:
        if platform:
            rows = conn.execute(
                "SELECT * FROM follow_tracking WHERE user_id=? AND platform=? AND status='following' AND followed_back=0 AND followed_at < datetime('now', ?)",
                (user_id, platform, f'-{days} days')).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM follow_tracking WHERE user_id=? AND status='following' AND followed_back=0 AND followed_at < datetime('now', ?)",
                (user_id, f'-{days} days')).fetchall()
        return [dict(r) for r in rows]


# ── RSS Feeds ────────────────────────────────────────────────────────────────

def add_rss_feed(user_id, url, name="", category=""):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO rss_feeds (user_id, url, name, category) VALUES (?,?,?,?)",
            (user_id, url, name, category))
        return cur.lastrowid

def get_rss_feeds(user_id):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM rss_feeds WHERE user_id=? ORDER BY created_at DESC", (user_id,)).fetchall()
        return [dict(r) for r in rows]

def delete_rss_feed(feed_id, user_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM rss_feeds WHERE id=? AND user_id=?", (feed_id, user_id))


# ── Auto-Reply Rules ────────────────────────────────────────────────────────

def create_auto_reply_rule(user_id, platform, trigger_type, trigger_value, reply_template, uses_spintax=False):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO auto_reply_rules (user_id, platform, trigger_type, trigger_value, reply_template, uses_spintax) VALUES (?,?,?,?,?,?)",
            (user_id, platform, trigger_type, trigger_value, reply_template, 1 if uses_spintax else 0))
        return cur.lastrowid

def get_auto_reply_rules(user_id, platform=None):
    with get_conn() as conn:
        if platform:
            rows = conn.execute(
                "SELECT * FROM auto_reply_rules WHERE user_id=? AND platform=? ORDER BY created_at DESC",
                (user_id, platform)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM auto_reply_rules WHERE user_id=? ORDER BY created_at DESC",
                (user_id,)).fetchall()
        return [dict(r) for r in rows]

def delete_auto_reply_rule(rule_id, user_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM auto_reply_rules WHERE id=? AND user_id=?", (rule_id, user_id))


# ── DM Templates ────────────────────────────────────────────────────────────

def create_dm_template(user_id, name, message_template, platform="", trigger_on=""):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO dm_templates (user_id, name, message_template, platform, trigger_on) VALUES (?,?,?,?,?)",
            (user_id, name, message_template, platform, trigger_on))
        return cur.lastrowid

def get_dm_templates(user_id):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM dm_templates WHERE user_id=? ORDER BY created_at DESC", (user_id,)).fetchall()
        return [dict(r) for r in rows]

def delete_dm_template(tmpl_id, user_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM dm_templates WHERE id=? AND user_id=?", (tmpl_id, user_id))


# ── Growth Snapshots ─────────────────────────────────────────────────────────

def add_growth_snapshot(user_id, account_id, platform, followers=0, following=0, posts=0, engagement_rate=0, views_total=0, likes_total=0):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO growth_snapshots (user_id, account_id, platform, followers, following, posts, engagement_rate, views_total, likes_total) VALUES (?,?,?,?,?,?,?,?,?)",
            (user_id, account_id, platform, followers, following, posts, engagement_rate, views_total, likes_total))
        return cur.lastrowid

def get_growth_history(user_id, account_id=None):
    with get_conn() as conn:
        if account_id:
            rows = conn.execute(
                "SELECT * FROM growth_snapshots WHERE user_id=? AND account_id=? ORDER BY created_at DESC",
                (user_id, account_id)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM growth_snapshots WHERE user_id=? ORDER BY created_at DESC",
                (user_id,)).fetchall()
        return [dict(r) for r in rows]

def get_growth_summary(user_id):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT platform,
                   MIN(followers) as min_followers,
                   MAX(followers) as max_followers
            FROM growth_snapshots WHERE user_id=?
            GROUP BY platform
        """, (user_id,)).fetchall()
        summary = {}
        for r in rows:
            summary[r["platform"]] = {
                "min_followers": r["min_followers"],
                "max_followers": r["max_followers"],
                "growth": r["max_followers"] - r["min_followers"],
            }
        return summary


# ── Engagement Campaigns ─────────────────────────────────────────────────────

def create_engagement_campaign(user_id, name, platforms=None, target_niche="", strategy="growth", daily_limit=50):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO engagement_campaigns (user_id, name, platforms, target_niche, strategy, daily_limit) VALUES (?,?,?,?,?,?)",
            (user_id, name, json.dumps(platforms or []), target_niche, strategy, daily_limit))
        return cur.lastrowid


def get_engagement_campaigns(user_id):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM engagement_campaigns WHERE user_id=? ORDER BY created_at DESC", (user_id,)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["platforms"] = json.loads(d.get("platforms") or "[]")
            except (json.JSONDecodeError, TypeError):
                d["platforms"] = []
            result.append(d)
        return result


def get_engagement_campaign(campaign_id, user_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM engagement_campaigns WHERE id=? AND user_id=?", (campaign_id, user_id)).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["platforms"] = json.loads(d.get("platforms") or "[]")
        except (json.JSONDecodeError, TypeError):
            d["platforms"] = []
        return d


def update_engagement_campaign(campaign_id, **kwargs):
    if not kwargs:
        return
    if "platforms" in kwargs and isinstance(kwargs["platforms"], list):
        kwargs["platforms"] = json.dumps(kwargs["platforms"])
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [campaign_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE engagement_campaigns SET {sets} WHERE id=?", vals)


def delete_engagement_campaign(campaign_id, user_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM engagement_campaigns WHERE id=? AND user_id=?", (campaign_id, user_id))


# ── Engagement Actions ───────────────────────────────────────────────────────

def create_engagement_action(user_id, platform, action_type, target_url="", comment_text="", campaign_id=None, target_username="", target_content_id="", scheduled_at=None):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO engagement_actions (user_id, platform, action_type, target_url, comment_text, campaign_id, target_username, target_content_id, scheduled_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (user_id, platform, action_type, target_url or "", comment_text or "", campaign_id, target_username or "", target_content_id or "", scheduled_at))
        return cur.lastrowid


def get_engagement_actions(user_id, status=None, campaign_id=None, limit=None):
    with get_conn() as conn:
        q = "SELECT * FROM engagement_actions WHERE user_id=?"
        params = [user_id]
        if status:
            q += " AND status=?"
            params.append(status)
        if campaign_id:
            q += " AND campaign_id=?"
            params.append(campaign_id)
        q += " ORDER BY created_at DESC"
        if limit:
            q += " LIMIT ?"
            params.append(limit)
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]


def update_engagement_action(action_id, **kwargs):
    if not kwargs:
        return
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [action_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE engagement_actions SET {sets} WHERE id=?", vals)


# ── Engagement Targets ───────────────────────────────────────────────────────

def add_engagement_target(user_id, campaign_id, platform, username, followers=0):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO engagement_targets (user_id, campaign_id, platform, username, followers) VALUES (?,?,?,?,?)",
            (user_id, campaign_id, platform, username, followers))
        return cur.lastrowid


def get_engagement_targets(user_id, campaign_id, engaged=None, limit=None):
    with get_conn() as conn:
        q = "SELECT * FROM engagement_targets WHERE user_id=? AND campaign_id=?"
        params = [user_id, campaign_id]
        if engaged is not None:
            q += " AND engaged=?"
            params.append(1 if engaged else 0)
        q += " ORDER BY created_at DESC"
        if limit:
            q += " LIMIT ?"
            params.append(limit)
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]


def mark_target_engaged(target_id):
    with get_conn() as conn:
        conn.execute("UPDATE engagement_targets SET engaged=1, engaged_at=datetime('now') WHERE id=?", (target_id,))


# ── Engagement Stats ─────────────────────────────────────────────────────────

def get_engagement_stats(user_id):
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM engagement_actions WHERE user_id=?", (user_id,)).fetchone()[0]
        rows = conn.execute("SELECT action_type, COUNT(*) as cnt FROM engagement_actions WHERE user_id=? GROUP BY action_type", (user_id,)).fetchall()
        by_action = {r["action_type"]: r["cnt"] for r in rows}
        daily = conn.execute(
            "SELECT COUNT(*) FROM engagement_actions WHERE user_id=? AND date(created_at)=date('now')",
            (user_id,)).fetchone()[0]
        status_rows = conn.execute("SELECT status, COUNT(*) as cnt FROM engagement_actions WHERE user_id=? GROUP BY status", (user_id,)).fetchall()
        by_status = {r["status"]: r["cnt"] for r in status_rows}
        return {"total": total, "by_action": by_action, "daily_count": daily, "by_status": by_status}


def get_daily_action_count(user_id, platform=None):
    with get_conn() as conn:
        if platform:
            return conn.execute(
                "SELECT COUNT(*) FROM engagement_actions WHERE user_id=? AND platform=? AND date(created_at)=date('now')",
                (user_id, platform)).fetchone()[0]
        return conn.execute(
            "SELECT COUNT(*) FROM engagement_actions WHERE user_id=? AND date(created_at)=date('now')",
            (user_id,)).fetchone()[0]


# ── Agency / BizDev ──────────────────────────────────────────────────────────

def get_agency_clients(user_id, status=None):
    with get_conn() as conn:
        if status:
            rows = conn.execute("SELECT * FROM agency_clients WHERE user_id=? AND status=? ORDER BY updated_at DESC", (user_id, status)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM agency_clients WHERE user_id=? ORDER BY updated_at DESC", (user_id,)).fetchall()
        return [row_to_dict(r) for r in rows]

def create_agency_client(user_id, data):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO agency_clients (user_id, name, company, email, phone, industry, website, status, monthly_value, notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (user_id, data.get("name",""), data.get("company",""), data.get("email",""), data.get("phone",""),
             data.get("industry",""), data.get("website",""), data.get("status","lead"), data.get("monthly_value",0), data.get("notes","")))
        return cur.lastrowid

def update_agency_client(user_id, client_id, data):
    with get_conn() as conn:
        fields = []
        vals = []
        for k in ("name","company","email","phone","industry","website","status","monthly_value","notes"):
            if k in data:
                fields.append(f"{k}=?")
                vals.append(data[k])
        if not fields:
            return
        fields.append("updated_at=datetime('now')")
        vals.extend([user_id, client_id])
        conn.execute(f"UPDATE agency_clients SET {','.join(fields)} WHERE user_id=? AND id=?", vals)

def delete_agency_client(user_id, client_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM agency_clients WHERE user_id=? AND id=?", (user_id, client_id))

def get_agency_deals(user_id, client_id=None, stage=None):
    with get_conn() as conn:
        q = "SELECT d.*, c.name as client_name, c.company as client_company FROM agency_deals d LEFT JOIN agency_clients c ON d.client_id=c.id WHERE d.user_id=?"
        params = [user_id]
        if client_id:
            q += " AND d.client_id=?"
            params.append(client_id)
        if stage:
            q += " AND d.stage=?"
            params.append(stage)
        q += " ORDER BY d.updated_at DESC"
        return [row_to_dict(r) for r in conn.execute(q, params).fetchall()]

def create_agency_deal(user_id, data):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO agency_deals (user_id, client_id, title, value, stage, service_type, description, close_date) VALUES (?,?,?,?,?,?,?,?)",
            (user_id, data.get("client_id"), data.get("title",""), data.get("value",0), data.get("stage","discovery"),
             data.get("service_type","content"), data.get("description",""), data.get("close_date","")))
        return cur.lastrowid

def update_agency_deal(user_id, deal_id, data):
    with get_conn() as conn:
        fields = []
        vals = []
        for k in ("client_id","title","value","stage","service_type","description","close_date"):
            if k in data:
                fields.append(f"{k}=?")
                vals.append(data[k])
        if not fields:
            return
        fields.append("updated_at=datetime('now')")
        vals.extend([user_id, deal_id])
        conn.execute(f"UPDATE agency_deals SET {','.join(fields)} WHERE user_id=? AND id=?", vals)

def delete_agency_deal(user_id, deal_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM agency_deals WHERE user_id=? AND id=?", (user_id, deal_id))

def get_agency_projects(user_id, client_id=None, status=None):
    with get_conn() as conn:
        q = "SELECT p.*, c.name as client_name FROM agency_projects p LEFT JOIN agency_clients c ON p.client_id=c.id WHERE p.user_id=?"
        params = [user_id]
        if client_id:
            q += " AND p.client_id=?"
            params.append(client_id)
        if status:
            q += " AND p.status=?"
            params.append(status)
        q += " ORDER BY p.created_at DESC"
        return [row_to_dict(r) for r in conn.execute(q, params).fetchall()]

def create_agency_project(user_id, data):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO agency_projects (user_id, client_id, deal_id, name, status, service_type, deliverables, start_date, end_date, monthly_fee, videos_quota) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, data.get("client_id"), data.get("deal_id"), data.get("name",""), data.get("status","active"),
             data.get("service_type","content"), json.dumps(data.get("deliverables",[])), data.get("start_date",""),
             data.get("end_date",""), data.get("monthly_fee",0), data.get("videos_quota",10)))
        return cur.lastrowid

def update_agency_project(user_id, project_id, data):
    with get_conn() as conn:
        fields = []
        vals = []
        for k in ("client_id","name","status","service_type","start_date","end_date","monthly_fee","videos_quota","videos_used"):
            if k in data:
                fields.append(f"{k}=?")
                vals.append(data[k])
        if "deliverables" in data:
            fields.append("deliverables=?")
            vals.append(json.dumps(data["deliverables"]))
        if not fields:
            return
        vals.extend([user_id, project_id])
        conn.execute(f"UPDATE agency_projects SET {','.join(fields)} WHERE user_id=? AND id=?", vals)

def get_agency_revenue(user_id, client_id=None, period=None):
    with get_conn() as conn:
        q = "SELECT r.*, c.name as client_name FROM agency_revenue r LEFT JOIN agency_clients c ON r.client_id=c.id WHERE r.user_id=?"
        params = [user_id]
        if client_id:
            q += " AND r.client_id=?"
            params.append(client_id)
        if period:
            q += " AND r.period=?"
            params.append(period)
        q += " ORDER BY r.created_at DESC"
        return [row_to_dict(r) for r in conn.execute(q, params).fetchall()]

def create_agency_revenue(user_id, data):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO agency_revenue (user_id, client_id, project_id, amount, type, description, period) VALUES (?,?,?,?,?,?,?)",
            (user_id, data.get("client_id"), data.get("project_id"), data.get("amount",0),
             data.get("type","recurring"), data.get("description",""), data.get("period","")))

def get_agency_stats(user_id):
    with get_conn() as conn:
        clients_total = conn.execute("SELECT COUNT(*) FROM agency_clients WHERE user_id=?", (user_id,)).fetchone()[0]
        clients_active = conn.execute("SELECT COUNT(*) FROM agency_clients WHERE user_id=? AND status='active'", (user_id,)).fetchone()[0]
        leads = conn.execute("SELECT COUNT(*) FROM agency_clients WHERE user_id=? AND status='lead'", (user_id,)).fetchone()[0]
        deals_open = conn.execute("SELECT COUNT(*) FROM agency_deals WHERE user_id=? AND stage NOT IN ('won','lost')", (user_id,)).fetchone()[0]
        pipeline_value = conn.execute("SELECT COALESCE(SUM(value),0) FROM agency_deals WHERE user_id=? AND stage NOT IN ('won','lost')", (user_id,)).fetchone()[0]
        deals_won = conn.execute("SELECT COALESCE(SUM(value),0) FROM agency_deals WHERE user_id=? AND stage='won'", (user_id,)).fetchone()[0]
        mrr = conn.execute("SELECT COALESCE(SUM(monthly_fee),0) FROM agency_projects WHERE user_id=? AND status='active'", (user_id,)).fetchone()[0]
        total_revenue = conn.execute("SELECT COALESCE(SUM(amount),0) FROM agency_revenue WHERE user_id=?", (user_id,)).fetchone()[0]
        projects_active = conn.execute("SELECT COUNT(*) FROM agency_projects WHERE user_id=? AND status='active'", (user_id,)).fetchone()[0]
        return {
            "clients_total": clients_total, "clients_active": clients_active, "leads": leads,
            "deals_open": deals_open, "pipeline_value": pipeline_value, "deals_won": deals_won,
            "mrr": mrr, "total_revenue": total_revenue, "projects_active": projects_active
        }
