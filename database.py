"""PostgreSQL (Supabase) database layer for the Social Optimize dashboard."""
import json
import uuid
import os as _os
import re
from datetime import datetime
from contextlib import contextmanager

import psycopg2
import psycopg2.pool
import psycopg2.extras

_DATABASE_URL = _os.getenv("DATABASE_URL", "")

# Supabase requires SSL — append sslmode=require if not already present
def _ensure_ssl(url: str) -> str:
    if url and "sslmode" not in url:
        sep = "&" if "?" in url else "?"
        return url + sep + "sslmode=require"
    return url

_pool = None

def _get_pool():
    global _pool
    if _pool is None:
        if not _DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not set. Set it to: postgresql://postgres:PASSWORD@db.PROJECT.supabase.co:5432/postgres")
        if _DATABASE_URL.startswith("https://") or _DATABASE_URL.startswith("http://"):
            raise RuntimeError(
                f"DATABASE_URL looks like a project URL, not a Postgres connection string. "
                f"Got: {_DATABASE_URL!r}. "
                f"It must start with postgresql:// — e.g. postgresql://postgres:PASSWORD@db.PROJECT.supabase.co:5432/postgres"
            )
        _pool = psycopg2.pool.ThreadedConnectionPool(2, 20, _ensure_ssl(_DATABASE_URL))
    return _pool


def _checkout_live_conn(pool):
    """Get a connection from the pool, discarding any the pooler has
    silently killed server-side (psycopg2's .closed flag only reflects
    local close() calls, not a dropped remote socket — so a cheap ping
    is the only reliable way to detect those)."""
    for _ in range(3):
        conn = pool.getconn()
        if conn.closed:
            pool.putconn(conn, close=True)
            continue
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            conn.commit()
            return conn
        except Exception:
            pool.putconn(conn, close=True)
    # Last resort: let the caller hit the real error.
    return pool.getconn()


@contextmanager
def get_conn():
    pool = _get_pool()
    conn = _checkout_live_conn(pool)
    try:
        conn.autocommit = False
        yield _PgConn(conn)
        conn.commit()
    except Exception:
        if not conn.closed:
            conn.rollback()
        raise
    finally:
        pool.putconn(conn, close=conn.closed)


class _PgConn:
    """Thin wrapper that mimics the sqlite3 connection interface used everywhere."""

    def __init__(self, raw):
        self._conn = raw

    def execute(self, sql, params=None):
        sql = _translate_sql(sql)
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params or ())
        return _CursorWrapper(cur)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()


class _CursorWrapper:
    """Wraps psycopg2 cursor to provide .lastrowid and sqlite3.Row-like fetchone/fetchall."""

    def __init__(self, cur):
        self._cur = cur
        self.lastrowid = None
        self.description = cur.description

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None:
            return None
        return _DictRow(row)

    def fetchall(self):
        return [_DictRow(r) for r in self._cur.fetchall()]


class _DictRow(dict):
    """Dict subclass that also supports index access like sqlite3.Row."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


def _translate_sql(sql):
    sql = sql.replace("?", "%s")
    sql = sql.replace("datetime('now')", "NOW()")
    sql = sql.replace("date('now')", "CURRENT_DATE")
    return sql


# ── Schema ───────────────────────────────────────────────────────────────────

def init_db():
    with get_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id                      SERIAL PRIMARY KEY,
            email                   TEXT UNIQUE NOT NULL,
            password_hash           TEXT NOT NULL,
            name                    TEXT,
            stripe_customer_id      TEXT,
            stripe_subscription_id  TEXT,
            subscription_tier       TEXT DEFAULT 'free',
            subscription_status     TEXT DEFAULT 'active',
            videos_used             INTEGER DEFAULT 0,
            credits_used            INTEGER DEFAULT 0,
            period_start            DATE DEFAULT date_trunc('month', NOW()),
            is_admin                INTEGER DEFAULT 0,
            notify_email            INTEGER DEFAULT 1,
            webhook_url             TEXT,
            subscription_channel    TEXT DEFAULT 'stripe',
            subscription_external_id TEXT DEFAULT '',
            referred_by             TEXT DEFAULT '',
            assistant_enabled       INTEGER DEFAULT 1,
            default_voice           TEXT DEFAULT 'en-US-Studio-O',
            created_at              TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS assistant_enabled INTEGER DEFAULT 1")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS default_voice TEXT DEFAULT 'en-US-Studio-O'")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS social_accounts (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            platform    TEXT NOT NULL,
            username    TEXT NOT NULL,
            display_name TEXT,
            avatar_url  TEXT,
            access_token TEXT,
            refresh_token TEXT,
            account_id  TEXT,
            followers   INTEGER DEFAULT 0,
            connected_at TIMESTAMP DEFAULT NOW(),
            is_active   INTEGER DEFAULT 1
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id          SERIAL PRIMARY KEY,
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
            imported_at TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS outreach_campaigns (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name        TEXT NOT NULL,
            type        TEXT NOT NULL DEFAULT 'email',
            subject     TEXT,
            body        TEXT NOT NULL,
            status      TEXT DEFAULT 'draft',
            sent_count  INTEGER DEFAULT 0,
            open_count  INTEGER DEFAULT 0,
            created_at  TIMESTAMP DEFAULT NOW(),
            sent_at     TIMESTAMP
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS outreach_sends (
            id              SERIAL PRIMARY KEY,
            campaign_id     INTEGER REFERENCES outreach_campaigns(id) ON DELETE CASCADE,
            contact_id      INTEGER REFERENCES contacts(id) ON DELETE CASCADE,
            user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
            status          TEXT DEFAULT 'pending',
            sent_at         TIMESTAMP,
            error_msg       TEXT,
            message_sid     TEXT,
            UNIQUE(campaign_id, contact_id)
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS sequences (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name        TEXT NOT NULL,
            trigger     TEXT NOT NULL DEFAULT 'new_contact',
            active      BOOLEAN DEFAULT FALSE,
            created_at  TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS sequence_steps (
            id           SERIAL PRIMARY KEY,
            sequence_id  INTEGER REFERENCES sequences(id) ON DELETE CASCADE,
            step_order   INTEGER NOT NULL,
            delay_hours  INTEGER NOT NULL DEFAULT 0,
            channel      TEXT NOT NULL DEFAULT 'email',
            subject      TEXT,
            body         TEXT NOT NULL
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS sequence_enrollments (
            id              SERIAL PRIMARY KEY,
            sequence_id     INTEGER REFERENCES sequences(id) ON DELETE CASCADE,
            contact_id      INTEGER REFERENCES contacts(id) ON DELETE CASCADE,
            user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
            current_step    INTEGER NOT NULL DEFAULT 0,
            status          TEXT NOT NULL DEFAULT 'active',
            next_send_at    TIMESTAMP DEFAULT NOW(),
            enrolled_at     TIMESTAMP DEFAULT NOW(),
            UNIQUE(sequence_id, contact_id)
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS inbound_sms (
            id              SERIAL PRIMARY KEY,
            message_sid     TEXT UNIQUE,
            from_number     TEXT NOT NULL,
            to_number       TEXT,
            body            TEXT,
            received_at     TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS inbound_calls (
            id              SERIAL PRIMARY KEY,
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
            received_at     TIMESTAMP DEFAULT NOW(),
            updated_at      TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id          SERIAL PRIMARY KEY,
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
            build_log   TEXT DEFAULT '',
            client_id   INTEGER,
            project_id  INTEGER,
            asset_number TEXT DEFAULT '',
            created_at  TIMESTAMP DEFAULT NOW(),
            completed_at TIMESTAMP
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id         SERIAL PRIMARY KEY,
            user_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,
            token      TEXT UNIQUE NOT NULL,
            expires_at TEXT NOT NULL,
            used       INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id            SERIAL PRIMARY KEY,
            admin_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
            action        TEXT NOT NULL,
            target_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            details       TEXT DEFAULT '{}',
            created_at    TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS analytics_cache (
            id              SERIAL PRIMARY KEY,
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
            fetched_at      TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS published_videos (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            job_id      INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
            platform    TEXT NOT NULL,
            video_id    TEXT,
            video_url   TEXT,
            title       TEXT,
            published_at TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            job_id      INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
            platform    TEXT NOT NULL,
            scheduled_at TEXT NOT NULL,
            status      TEXT DEFAULT 'pending',
            posted_at   TIMESTAMP,
            error_msg   TEXT
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS autopilot_channels (
            id             SERIAL PRIMARY KEY,
            user_id        INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name           TEXT NOT NULL,
            niche          TEXT NOT NULL,
            format         TEXT DEFAULT 'short',
            platforms      TEXT DEFAULT '["youtube"]',
            voice          TEXT,
            style          TEXT DEFAULT 'fire',
            audience       TEXT DEFAULT 'general public',
            cadence_hours  INTEGER DEFAULT 24,
            topic_source   TEXT DEFAULT 'auto',
            rss_url        TEXT,
            privacy        TEXT DEFAULT 'public',
            enabled        INTEGER DEFAULT 1,
            last_run_at    TIMESTAMP,
            next_run_at    TIMESTAMP DEFAULT NOW(),
            last_job_id    INTEGER,
            last_error     TEXT,
            created_at     TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS batch_jobs (
            id              TEXT PRIMARY KEY,
            user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
            total_count     INTEGER DEFAULT 0,
            completed_count INTEGER DEFAULT 0,
            failed_count    INTEGER DEFAULT 0,
            status          TEXT DEFAULT 'running',
            created_at      TIMESTAMP DEFAULT NOW(),
            topics_json     TEXT DEFAULT '[]'
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS content_templates (
            id          TEXT PRIMARY KEY,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name        TEXT NOT NULL,
            description TEXT,
            config_json TEXT DEFAULT '{}',
            use_count   INTEGER DEFAULT 0,
            created_at  TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS dub_jobs (
            id              TEXT PRIMARY KEY,
            user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
            source_job_id   INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
            target_language TEXT NOT NULL,
            status          TEXT DEFAULT 'pending',
            output_path     TEXT,
            created_at      TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS notification_log (
            id          SERIAL PRIMARY KEY,
            notif_id    TEXT,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            event_type  TEXT,
            channel     TEXT,
            status      TEXT,
            created_at  TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS in_app_notifications (
            id          TEXT PRIMARY KEY,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            title       TEXT NOT NULL,
            body        TEXT,
            read        INTEGER DEFAULT 0,
            created_at  TIMESTAMP DEFAULT NOW(),
            link        TEXT
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS teams (
            id          TEXT PRIMARY KEY,
            owner_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name        TEXT NOT NULL,
            plan        TEXT DEFAULT 'agency',
            created_at  TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS team_members (
            id              TEXT PRIMARY KEY,
            team_id         TEXT REFERENCES teams(id) ON DELETE CASCADE,
            user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
            role            TEXT DEFAULT 'editor',
            invited_email   TEXT,
            status          TEXT DEFAULT 'pending',
            created_at      TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS competitor_channels (
            id          TEXT PRIMARY KEY,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            platform    TEXT DEFAULT 'youtube',
            channel_id  TEXT,
            channel_name TEXT,
            channel_url TEXT,
            added_at    TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
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
            fetched_at      TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS follow_tracking (
            id              SERIAL PRIMARY KEY,
            user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
            platform        TEXT,
            target_username TEXT,
            status          TEXT DEFAULT 'following',
            followed_back   INTEGER DEFAULT 0,
            followed_at     TIMESTAMP DEFAULT NOW(),
            unfollowed_at   TIMESTAMP
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS dm_templates (
            id               SERIAL PRIMARY KEY,
            user_id          INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name             TEXT,
            message_template TEXT,
            platform         TEXT,
            trigger_on       TEXT,
            created_at       TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS auto_reply_rules (
            id              SERIAL PRIMARY KEY,
            user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
            platform        TEXT,
            trigger_type    TEXT,
            trigger_value   TEXT,
            reply_template  TEXT,
            uses_spintax    INTEGER DEFAULT 0,
            enabled         INTEGER DEFAULT 1,
            created_at      TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS rss_feeds (
            id           SERIAL PRIMARY KEY,
            user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
            url          TEXT,
            name         TEXT,
            category     TEXT,
            enabled      INTEGER DEFAULT 1,
            last_checked TIMESTAMP,
            created_at   TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS growth_snapshots (
            id              SERIAL PRIMARY KEY,
            user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
            account_id      TEXT,
            platform        TEXT,
            followers       INTEGER DEFAULT 0,
            following       INTEGER DEFAULT 0,
            posts           INTEGER DEFAULT 0,
            engagement_rate REAL DEFAULT 0,
            views_total     INTEGER DEFAULT 0,
            likes_total     INTEGER DEFAULT 0,
            created_at      TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS engagement_targets (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            campaign_id INTEGER,
            platform    TEXT,
            username    TEXT,
            followers   INTEGER DEFAULT 0,
            engaged     INTEGER DEFAULT 0,
            engaged_at  TIMESTAMP,
            created_at  TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS engagement_actions (
            id                SERIAL PRIMARY KEY,
            user_id           INTEGER REFERENCES users(id) ON DELETE CASCADE,
            platform          TEXT,
            action_type       TEXT,
            target_url        TEXT DEFAULT '',
            target_username   TEXT DEFAULT '',
            target_content_id TEXT DEFAULT '',
            comment_text      TEXT DEFAULT '',
            campaign_id       INTEGER,
            status            TEXT DEFAULT 'queued',
            scheduled_at      TIMESTAMP,
            executed_at       TIMESTAMP,
            error_msg         TEXT DEFAULT '',
            created_at        TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS engagement_campaigns (
            id           SERIAL PRIMARY KEY,
            user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name         TEXT,
            platforms    TEXT DEFAULT '[]',
            target_niche TEXT DEFAULT '',
            strategy     TEXT DEFAULT 'growth',
            daily_limit  INTEGER DEFAULT 50,
            is_active    INTEGER DEFAULT 1,
            created_at   TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS automation_settings (
            id                   SERIAL PRIMARY KEY,
            platform             TEXT UNIQUE NOT NULL,
            auto_reply_comments  INTEGER DEFAULT 0,
            auto_reply_dms       INTEGER DEFAULT 0,
            follow_back          INTEGER DEFAULT 0,
            reply_template       TEXT DEFAULT 'Thanks for watching! 🙌',
            known_follower_ids   TEXT DEFAULT '[]',
            last_comment_check   TIMESTAMP,
            last_dm_check        TIMESTAMP,
            last_follower_check  TIMESTAMP,
            updated_at           TIMESTAMP DEFAULT NOW()
        )
        """)

        # Agency / BizDev tables
        conn.execute("""
        CREATE TABLE IF NOT EXISTS agency_clients (
            id           SERIAL PRIMARY KEY,
            user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
            client_number TEXT DEFAULT '',
            name         TEXT NOT NULL,
            company      TEXT DEFAULT '',
            email        TEXT DEFAULT '',
            phone        TEXT DEFAULT '',
            industry     TEXT DEFAULT '',
            website      TEXT DEFAULT '',
            status       TEXT DEFAULT 'lead',
            monthly_value REAL DEFAULT 0,
            notes        TEXT DEFAULT '',
            source       TEXT DEFAULT 'manual',
            last_contact TEXT DEFAULT '',
            next_followup TEXT DEFAULT '',
            created_at   TIMESTAMP DEFAULT NOW(),
            updated_at   TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS agency_deals (
            id           SERIAL PRIMARY KEY,
            user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
            client_id    INTEGER REFERENCES agency_clients(id) ON DELETE CASCADE,
            title        TEXT NOT NULL,
            value        REAL DEFAULT 0,
            stage        TEXT DEFAULT 'discovery',
            service_type TEXT DEFAULT 'content',
            description  TEXT DEFAULT '',
            close_date   TEXT DEFAULT '',
            created_at   TIMESTAMP DEFAULT NOW(),
            updated_at   TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS agency_proposals (
            id           SERIAL PRIMARY KEY,
            user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
            deal_id      INTEGER REFERENCES agency_deals(id) ON DELETE CASCADE,
            client_id    INTEGER REFERENCES agency_clients(id) ON DELETE CASCADE,
            title        TEXT NOT NULL,
            content      TEXT DEFAULT '',
            pricing      TEXT DEFAULT '{}',
            status       TEXT DEFAULT 'draft',
            sent_at      TIMESTAMP,
            created_at   TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS agency_projects (
            id           SERIAL PRIMARY KEY,
            user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
            client_id    INTEGER REFERENCES agency_clients(id) ON DELETE CASCADE,
            deal_id      INTEGER REFERENCES agency_deals(id),
            name         TEXT NOT NULL,
            status       TEXT DEFAULT 'active',
            service_type TEXT DEFAULT 'content',
            deliverables TEXT DEFAULT '[]',
            start_date   DATE DEFAULT CURRENT_DATE,
            end_date     TEXT DEFAULT '',
            monthly_fee  REAL DEFAULT 0,
            videos_quota INTEGER DEFAULT 10,
            videos_used  INTEGER DEFAULT 0,
            created_at   TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS agency_assets (
            id           SERIAL PRIMARY KEY,
            user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
            asset_number TEXT NOT NULL,
            client_id    INTEGER REFERENCES agency_clients(id),
            project_id   INTEGER REFERENCES agency_projects(id),
            job_id       INTEGER REFERENCES jobs(id),
            asset_type   TEXT DEFAULT 'video',
            title        TEXT DEFAULT '',
            file_path    TEXT DEFAULT '',
            thumbnail    TEXT DEFAULT '',
            status       TEXT DEFAULT 'draft',
            delivered_at TIMESTAMP,
            feedback     TEXT DEFAULT '',
            created_at   TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS agency_followups (
            id           SERIAL PRIMARY KEY,
            user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
            client_id    INTEGER REFERENCES agency_clients(id) ON DELETE CASCADE,
            deal_id      INTEGER REFERENCES agency_deals(id),
            type         TEXT DEFAULT 'email',
            subject      TEXT DEFAULT '',
            body         TEXT DEFAULT '',
            status       TEXT DEFAULT 'scheduled',
            scheduled_at TEXT NOT NULL,
            sent_at      TIMESTAMP,
            opened_at    TIMESTAMP,
            template     TEXT DEFAULT '',
            created_at   TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS agency_revenue (
            id           SERIAL PRIMARY KEY,
            user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
            client_id    INTEGER REFERENCES agency_clients(id),
            project_id   INTEGER REFERENCES agency_projects(id),
            amount       REAL NOT NULL,
            type         TEXT DEFAULT 'recurring',
            description  TEXT DEFAULT '',
            period       TEXT DEFAULT '',
            created_at   TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS affiliates (
            id              SERIAL PRIMARY KEY,
            user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
            code            TEXT UNIQUE NOT NULL,
            commission_pct  REAL DEFAULT 20,
            active          INTEGER DEFAULT 1,
            created_at      TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS affiliate_earnings (
            id              SERIAL PRIMARY KEY,
            affiliate_id    INTEGER REFERENCES affiliates(id),
            user_id         INTEGER,
            tier            TEXT,
            amount          REAL DEFAULT 0,
            paid            INTEGER DEFAULT 0,
            created_at      TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            id               TEXT PRIMARY KEY,
            codename         TEXT NOT NULL,
            title            TEXT DEFAULT '',
            team             TEXT DEFAULT 'command_center',
            role_description TEXT DEFAULT '',
            expertise        TEXT DEFAULT '',
            status           TEXT DEFAULT 'online',
            config           TEXT DEFAULT '{}',
            tasks_completed  INTEGER DEFAULT 0,
            tasks_failed     INTEGER DEFAULT 0,
            last_active      TIMESTAMP,
            created_at       TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_logs (
            id          SERIAL PRIMARY KEY,
            agent_id    TEXT,
            event_type  TEXT DEFAULT 'info',
            message     TEXT DEFAULT '',
            created_at  TIMESTAMP DEFAULT NOW()
        )
        """)

        # Performance indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON jobs(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_stripe_cust ON users(stripe_customer_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_stripe_sub ON users(stripe_subscription_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_social_accounts_user ON social_accounts(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_contacts_user ON contacts(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_analytics_user ON analytics_cache(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user ON in_app_notifications(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_follow_tracking_user ON follow_tracking(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_engagement_actions_user ON engagement_actions(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agency_clients_user ON agency_clients(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agency_deals_user ON agency_deals(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_logs_agent ON agent_logs(agent_id)")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS personas (
            id               SERIAL PRIMARY KEY,
            user_id          INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name             TEXT NOT NULL,
            gender           TEXT DEFAULT '',
            age_range        TEXT DEFAULT '',
            appearance_desc  TEXT DEFAULT '',
            niche            TEXT DEFAULT '',
            avatar_style     TEXT DEFAULT '',
            voice_id         TEXT DEFAULT '',
            personality      TEXT DEFAULT '',
            speaking_style   TEXT DEFAULT '',
            model_preference TEXT DEFAULT '',
            created_at       TIMESTAMP DEFAULT NOW()
        )
        """)

        # ── CRM tables ───────────────────────────────────────────────────
        conn.execute("""
        CREATE TABLE IF NOT EXISTS crm_companies (
            id             SERIAL PRIMARY KEY,
            user_id        INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name           TEXT NOT NULL,
            industry       TEXT DEFAULT '',
            website        TEXT DEFAULT '',
            phone          TEXT DEFAULT '',
            annual_revenue NUMERIC(14,2),
            employees      INTEGER,
            notes          TEXT DEFAULT '',
            created_at     TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS crm_contacts (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            company_id  INTEGER REFERENCES crm_companies(id) ON DELETE SET NULL,
            name        TEXT NOT NULL,
            email       TEXT DEFAULT '',
            phone       TEXT DEFAULT '',
            title       TEXT DEFAULT '',
            stage       TEXT DEFAULT 'lead',
            source      TEXT DEFAULT '',
            tags        TEXT DEFAULT '[]',
            notes       TEXT DEFAULT '',
            last_activity TIMESTAMP,
            created_at  TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS crm_deals (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            contact_id  INTEGER REFERENCES crm_contacts(id) ON DELETE SET NULL,
            company_id  INTEGER REFERENCES crm_companies(id) ON DELETE SET NULL,
            name        TEXT NOT NULL,
            value       NUMERIC(14,2) DEFAULT 0,
            stage       TEXT DEFAULT 'lead',
            close_date  DATE,
            notes       TEXT DEFAULT '',
            created_at  TIMESTAMP DEFAULT NOW(),
            updated_at  TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS crm_activities (
            id            SERIAL PRIMARY KEY,
            user_id       INTEGER REFERENCES users(id) ON DELETE CASCADE,
            contact_id    INTEGER REFERENCES crm_contacts(id) ON DELETE SET NULL,
            activity_type TEXT DEFAULT 'note',
            summary       TEXT NOT NULL,
            notes         TEXT DEFAULT '',
            created_at    TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS crm_tasks (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
            contact_id  INTEGER REFERENCES crm_contacts(id) ON DELETE SET NULL,
            title       TEXT NOT NULL,
            notes       TEXT DEFAULT '',
            priority    TEXT DEFAULT 'normal',
            status      TEXT DEFAULT 'open',
            due_date    DATE,
            created_at  TIMESTAMP DEFAULT NOW()
        )""")

        # ── Finance / IEBC tables ────────────────────────────────────────
        conn.execute("""
        CREATE TABLE IF NOT EXISTS finance_clients (
            id             SERIAL PRIMARY KEY,
            name           TEXT NOT NULL,
            contact_name   TEXT DEFAULT '',
            contact_email  TEXT DEFAULT '',
            contact_phone  TEXT DEFAULT '',
            monthly_value  NUMERIC(14,2) DEFAULT 0,
            billing_cycle  TEXT DEFAULT 'monthly',
            status         TEXT DEFAULT 'active',
            platform       TEXT DEFAULT '',
            start_date     DATE,
            notes          TEXT DEFAULT '',
            created_at     TIMESTAMP DEFAULT NOW(),
            updated_at     TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS finance_subscriptions (
            id             SERIAL PRIMARY KEY,
            name           TEXT NOT NULL,
            category       TEXT DEFAULT 'other',
            vendor         TEXT DEFAULT '',
            monthly_cost   NUMERIC(12,2) DEFAULT 0,
            annual_cost    NUMERIC(12,2) DEFAULT 0,
            billing_cycle  TEXT DEFAULT 'monthly',
            status         TEXT DEFAULT 'active',
            renewal_date   DATE,
            last_used_at   TIMESTAMP,
            url            TEXT DEFAULT '',
            notes          TEXT DEFAULT '',
            created_at     TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS finance_platforms (
            id             SERIAL PRIMARY KEY,
            name           TEXT NOT NULL,
            platform_type  TEXT DEFAULT 'social',
            monthly_cost   NUMERIC(12,2) DEFAULT 0,
            status         TEXT DEFAULT 'active',
            account_id     TEXT DEFAULT '',
            notes          TEXT DEFAULT '',
            created_at     TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS finance_provider_credits (
            id             SERIAL PRIMARY KEY,
            provider       TEXT NOT NULL UNIQUE,
            balance        NUMERIC(16,4) DEFAULT 0,
            credit_cap     NUMERIC(16,4) DEFAULT 0,
            monthly_spend  NUMERIC(12,4) DEFAULT 0,
            unit           TEXT DEFAULT 'USD',
            last_refill_at TIMESTAMP,
            last_updated   TIMESTAMP DEFAULT NOW(),
            notes          TEXT DEFAULT ''
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS finance_credit_txns (
            id          SERIAL PRIMARY KEY,
            provider    TEXT NOT NULL,
            amount      NUMERIC(16,4) NOT NULL,
            direction   TEXT DEFAULT 'debit',
            description TEXT DEFAULT '',
            created_at  TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS finance_invoices (
            id           SERIAL PRIMARY KEY,
            client_id    INTEGER REFERENCES finance_clients(id) ON DELETE SET NULL,
            amount       NUMERIC(14,2) NOT NULL,
            status       TEXT DEFAULT 'draft',
            due_date     DATE,
            paid_at      TIMESTAMP,
            notes        TEXT DEFAULT '',
            created_at   TIMESTAMP DEFAULT NOW()
        )""")

        # ── Monetizer tables ─────────────────────────────────────────────
        conn.execute("""
        CREATE TABLE IF NOT EXISTS monetizer_expenses (
            id          SERIAL PRIMARY KEY,
            category    TEXT NOT NULL,
            vendor      TEXT DEFAULT '',
            description TEXT DEFAULT '',
            amount      NUMERIC(12,2) NOT NULL DEFAULT 0,
            recurring   BOOLEAN DEFAULT FALSE,
            created_at  TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS monetizer_cost_centers (
            id             SERIAL PRIMARY KEY,
            name           TEXT NOT NULL,
            category       TEXT DEFAULT '',
            monthly_budget NUMERIC(12,2) DEFAULT 0,
            actual_spend   NUMERIC(12,2) DEFAULT 0,
            created_at     TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS monetizer_campaigns (
            id          SERIAL PRIMARY KEY,
            name        TEXT NOT NULL,
            channel     TEXT DEFAULT '',
            budget      NUMERIC(12,2) DEFAULT 0,
            spent       NUMERIC(12,2) DEFAULT 0,
            signups     INTEGER DEFAULT 0,
            conversions INTEGER DEFAULT 0,
            status      TEXT DEFAULT 'active',
            created_at  TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS monetizer_features (
            id          SERIAL PRIMARY KEY,
            name        TEXT NOT NULL,
            description TEXT DEFAULT '',
            tier_min    TEXT DEFAULT 'free',
            rollout_pct INTEGER DEFAULT 100,
            enabled     BOOLEAN DEFAULT TRUE,
            created_at  TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS monetizer_tickets (
            id          SERIAL PRIMARY KEY,
            subject     TEXT NOT NULL,
            body        TEXT DEFAULT '',
            priority    TEXT DEFAULT 'normal',
            status      TEXT DEFAULT 'open',
            user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at  TIMESTAMP DEFAULT NOW(),
            resolved_at TIMESTAMP
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS monetizer_goals (
            id            SERIAL PRIMARY KEY,
            metric        TEXT NOT NULL,
            target_value  NUMERIC(20,2) DEFAULT 0,
            current_value NUMERIC(20,2) DEFAULT 0,
            deadline      DATE,
            created_at    TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS monetizer_changelog (
            id         SERIAL PRIMARY KEY,
            version    TEXT DEFAULT '',
            title      TEXT NOT NULL,
            body       TEXT DEFAULT '',
            category   TEXT DEFAULT 'feature',
            published  BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS monetizer_alerts (
            id           SERIAL PRIMARY KEY,
            alert_type   TEXT NOT NULL,
            message      TEXT NOT NULL,
            severity     TEXT DEFAULT 'info',
            acknowledged BOOLEAN DEFAULT FALSE,
            created_at   TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS monetizer_kpi_snapshots (
            id              SERIAL PRIMARY KEY,
            snapshot_date   DATE DEFAULT CURRENT_DATE,
            mrr             NUMERIC(12,2) DEFAULT 0,
            arr             NUMERIC(12,2) DEFAULT 0,
            total_users     INTEGER DEFAULT 0,
            paying_users    INTEGER DEFAULT 0,
            free_users      INTEGER DEFAULT 0,
            arpu            NUMERIC(12,2) DEFAULT 0,
            conversion_rate NUMERIC(6,2)  DEFAULT 0,
            total_videos    INTEGER DEFAULT 0,
            created_at      TIMESTAMP DEFAULT NOW()
        )""")

        # ── Social Optimize Credits ──────────────────────────────────────
        conn.execute("""
        CREATE TABLE IF NOT EXISTS so_credits (
            id                  SERIAL PRIMARY KEY,
            user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE UNIQUE,
            balance             NUMERIC(14,2) DEFAULT 0,
            rollover_balance    NUMERIC(14,2) DEFAULT 0,
            monthly_allocation  NUMERIC(14,2) DEFAULT 0,
            lifetime_earned     NUMERIC(14,2) DEFAULT 0,
            lifetime_spent      NUMERIC(14,2) DEFAULT 0,
            last_rollover_at    TIMESTAMP,
            updated_at          TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS so_credit_txns (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            amount      NUMERIC(14,2) NOT NULL,
            direction   TEXT NOT NULL DEFAULT 'debit',
            action_type TEXT DEFAULT '',
            description TEXT DEFAULT '',
            ref_id      TEXT DEFAULT '',
            balance_after NUMERIC(14,2),
            created_at  TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS so_credit_packages (
            id          SERIAL PRIMARY KEY,
            name        TEXT NOT NULL,
            credits     NUMERIC(14,2) NOT NULL,
            price_usd   NUMERIC(10,2) NOT NULL,
            bonus_pct   NUMERIC(5,2) DEFAULT 0,
            active      BOOLEAN DEFAULT TRUE,
            created_at  TIMESTAMP DEFAULT NOW()
        )""")
        # Seed default packages
        conn.execute("""
        INSERT INTO so_credit_packages (name, credits, price_usd, bonus_pct)
        VALUES
            ('Starter Pack',  500,   4.99, 0),
            ('Growth Pack',  2000,  14.99, 0),
            ('Pro Pack',     5000,  29.99, 10),
            ('Agency Pack', 15000,  79.99, 20)
        ON CONFLICT DO NOTHING
        """)

        _seed_agents(conn)


def _seed_agents(conn):
    agents = [
        ("showrunner", "The Showrunner", "Chief Orchestrator", "command_center", "Orchestrates all content pipelines end-to-end", "pipeline orchestration, scheduling, resource allocation", '{"icon":"crown"}'),
        ("ledger", "Cost Engineer", "Financial Optimizer", "command_center", "Routes tasks to cheapest viable AI provider", "cost optimization, provider routing, budget tracking", '{"icon":"calculator"}'),
        ("ghost", "The Ghost", "Spintax & Variation Engine", "command_center", "Generates unique content variations at scale", "spintax processing, content variation, deduplication", '{"icon":"ghost"}'),
        ("scout", "The Scout", "Trend Intelligence", "command_center", "Monitors trends, competitors, and viral content", "trend analysis, competitor monitoring, content intelligence", '{"icon":"radar"}'),
        ("guardian", "The Guardian", "QA & Compliance", "command_center", "Reviews all output for quality and brand safety", "quality assurance, compliance checking, content review", '{"icon":"shield-check"}'),
        ("architect", "The Architect", "UI/UX Engine", "website", "Manages dashboard rendering and real-time updates", "frontend rendering, real-time updates, UI optimization", '{"icon":"layout"}'),
        ("conduit", "The Conduit", "API Bridge", "website", "Handles all API communication and data flow", "API routing, data transformation, rate limiting", '{"icon":"plug-zap"}'),
        ("native", "The Native", "Mobile Bridge", "mobile", "Manages mobile app bridge and push notifications", "mobile optimization, push notifications, offline sync", '{"icon":"smartphone"}'),
        ("courier", "The Courier", "Notification Engine", "mobile", "Delivers push notifications and alerts", "push delivery, notification scheduling, engagement tracking", '{"icon":"bell-ring"}'),
        ("growth_engine", "The Growth Engine", "Platform Optimizer", "social_optimize", "Optimizes content for each social platform", "platform optimization, hashtag strategy, posting schedule", '{"icon":"trending-up"}'),
        ("editor", "The Editor", "Post-Production", "client_pipeline", "Handles video editing, transitions, and effects", "video editing, audio mixing, subtitle generation", '{"icon":"film"}'),
        # IEBC C-Suite live agents
        ("marcus_vance", "Marcus Vance", "Chief Growth Officer", "iebc_csuite", "Engineers PLG funnels, upgrade nudges, and referral loops toward $10M ARR", "PLG, viral coefficients, conversion optimization, referral mechanics", '{"icon":"trending-up","color":"#3b82f6"}'),
        ("julian_vance", "Dr. Julian Vance", "Director of Retention & LTV", "iebc_csuite", "Detects churn risk, fires re-engagement sequences, protects LTV", "churn prediction, re-engagement, LTV optimization, cohort analysis", '{"icon":"heart","color":"#10b981"}'),
        ("elena_rostova", "Elena Rostova", "VP of Enterprise Development", "iebc_csuite", "Identifies enterprise prospects and manages outbound pipeline", "enterprise sales, outbound prospecting, ACV optimization", '{"icon":"building","color":"#8b5cf6"}'),
        ("sterling_croft", "Sterling Croft", "Chief Business Officer", "iebc_csuite", "Protects gross margin, monitors unit economics, aligns ops to business plan", "unit economics, margin protection, business plan execution", '{"icon":"briefcase","color":"#f59e0b"}'),
        ("vivian_cross", "Vivian Cross", "Chief Financial Officer", "iebc_csuite", "IEBC efficiency accounting — tracks every dollar in and out", "IEBC accounting, subscription costs, credit monitoring, renewal alerts", '{"icon":"dollar-sign","color":"#10b981"}'),
        ("nova_chen", "Nova Chen", "Chief Product Officer", "iebc_csuite", "Monitors studio usage, feature adoption, activation rate, and product health", "product analytics, feature adoption, activation, studio usage", '{"icon":"brain","color":"#8b5cf6"}'),
        ("rex_dawson", "Rex Dawson", "Director of Revenue Operations", "iebc_csuite", "Stripe reconciliation, failed payments, dunning, MRR accuracy", "RevOps, payment reconciliation, dunning, MRR integrity", '{"icon":"credit-card","color":"#f59e0b"}'),
        ("aria_singh", "Aria Singh", "Director of Customer Success", "iebc_csuite", "Activation monitoring, onboarding, first-milestone tracking, plan cohort targets", "customer success, activation, onboarding, cohort tracking", '{"icon":"star","color":"#ec4899"}'),
    ]
    for a in agents:
        conn.execute(
            """INSERT INTO agents (id, codename, title, team, role_description, expertise, config)
               VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""", a
        )


# ── Social Optimize Credits helpers ──────────────────────────────────────────

# How many credits each action costs
SO_CREDIT_COSTS = {
    "video_generate":   10,
    "audio_generate":   3,
    "image_generate":   2,
    "podcast_generate": 8,
    "caption_generate": 1,
    "script_generate":  2,
    "remix_generate":   5,
    "publish":          1,
    "ai_chat":          1,
}


def get_user_credits(user_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM so_credits WHERE user_id=%s", (user_id,)
        ).fetchone()
        if row is None:
            # Lazy init for existing users
            monthly = _TIER_MONTHLY_CREDITS.get("free", 100)
            conn.execute(
                """INSERT INTO so_credits (user_id, balance, rollover_balance, monthly_allocation, lifetime_earned)
                   VALUES (%s,%s,0,%s,%s) ON CONFLICT (user_id) DO NOTHING""",
                (user_id, monthly, monthly, monthly),
            )
            row = conn.execute("SELECT * FROM so_credits WHERE user_id=%s", (user_id,)).fetchone()
        return dict(row) if row else {}


def deduct_credits(user_id: int, action_type: str, description: str = "", ref_id: str = "") -> dict:
    """Deduct credits for an action. Returns {'ok': bool, 'balance': float, 'cost': int}."""
    cost = SO_CREDIT_COSTS.get(action_type, 1)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT balance, rollover_balance FROM so_credits WHERE user_id=%s FOR UPDATE",
            (user_id,)
        ).fetchone()
        if row is None:
            return {"ok": False, "balance": 0, "cost": cost, "error": "No credit wallet"}
        total = float(row["balance"]) + float(row["rollover_balance"])
        if total < cost:
            return {"ok": False, "balance": total, "cost": cost, "error": "Insufficient credits"}
        # Deduct from rollover first, then main balance
        rollover = float(row["rollover_balance"])
        main = float(row["balance"])
        if rollover >= cost:
            rollover -= cost
            main_new, roll_new = main, rollover
        else:
            remainder = cost - rollover
            roll_new = 0
            main_new = main - remainder
        conn.execute(
            """UPDATE so_credits SET balance=%s, rollover_balance=%s,
               lifetime_spent=lifetime_spent+%s, updated_at=NOW()
               WHERE user_id=%s""",
            (main_new, roll_new, cost, user_id),
        )
        balance_after = main_new + roll_new
        conn.execute(
            """INSERT INTO so_credit_txns (user_id, amount, direction, action_type, description, ref_id, balance_after)
               VALUES (%s,%s,'debit',%s,%s,%s,%s)""",
            (user_id, cost, action_type, description or action_type, ref_id, balance_after),
        )
        return {"ok": True, "balance": balance_after, "cost": cost}


def add_credits(user_id: int, amount: float, action_type: str = "topup", description: str = "") -> dict:
    """Add credits to a user's wallet."""
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO so_credits (user_id, balance, rollover_balance, monthly_allocation, lifetime_earned)
               VALUES (%s,%s,0,0,%s)
               ON CONFLICT (user_id) DO UPDATE
               SET balance=so_credits.balance+%s, lifetime_earned=so_credits.lifetime_earned+%s, updated_at=NOW()""",
            (user_id, amount, amount, amount, amount),
        )
        row = conn.execute("SELECT balance+rollover_balance AS total FROM so_credits WHERE user_id=%s", (user_id,)).fetchone()
        balance_after = float(row["total"]) if row else amount
        conn.execute(
            """INSERT INTO so_credit_txns (user_id, amount, direction, action_type, description, balance_after)
               VALUES (%s,%s,'credit',%s,%s,%s)""",
            (user_id, amount, action_type, description or f"Credit top-up: {amount}", balance_after),
        )
        return {"ok": True, "balance": balance_after}


def rollover_credits(user_id: int) -> dict:
    """Carry unused main balance into rollover, then set new monthly allocation."""
    wallet = get_user_credits(user_id)
    if not wallet:
        return {"ok": False}
    # Get user tier for new monthly allocation
    with get_conn() as conn:
        user_row = conn.execute("SELECT subscription_tier FROM users WHERE id=%s", (user_id,)).fetchone()
        tier = (user_row["subscription_tier"] if user_row else "free") or "free"
        monthly = _TIER_MONTHLY_CREDITS.get(tier, 100)
        old_balance = float(wallet.get("balance", 0))
        # Add unused balance into rollover, set new monthly balance
        conn.execute(
            """UPDATE so_credits
               SET rollover_balance=rollover_balance+%s,
                   balance=%s,
                   monthly_allocation=%s,
                   lifetime_earned=lifetime_earned+%s,
                   last_rollover_at=NOW(),
                   updated_at=NOW()
               WHERE user_id=%s""",
            (old_balance, monthly, monthly, monthly, user_id),
        )
        conn.execute(
            """INSERT INTO so_credit_txns (user_id, amount, direction, action_type, description, balance_after)
               VALUES (%s,%s,'credit','monthly_rollover','Monthly credit rollover',%s)""",
            (user_id, monthly, monthly + float(wallet.get("rollover_balance", 0)) + old_balance),
        )
        return {"ok": True, "new_balance": monthly, "rollover": float(wallet.get("rollover_balance", 0)) + old_balance}


def get_credit_txns(user_id: int, limit: int = 50) -> list:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM so_credit_txns WHERE user_id=%s ORDER BY created_at DESC LIMIT %s",
            (user_id, limit),
        ).fetchall()]


def get_credit_packages() -> list:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM so_credit_packages WHERE active=TRUE ORDER BY price_usd"
        ).fetchall()]


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

_TIER_MONTHLY_CREDITS = {
    "free": 100,
    "starter": 500,
    "growth": 2000,
    "pro": 5000,
    "agency": 15000,
}

def create_user(email: str, password_hash: str, name: str = "", tier: str = "free") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, name) VALUES (%s,%s,%s) RETURNING id",
            (email.lower().strip(), password_hash, name),
        )
        user_id = cur.fetchone()["id"]
        monthly = _TIER_MONTHLY_CREDITS.get(tier, 100)
        conn.execute(
            """INSERT INTO so_credits (user_id, balance, rollover_balance, monthly_allocation, lifetime_earned)
               VALUES (%s,%s,0,%s,%s)
               ON CONFLICT (user_id) DO NOTHING""",
            (user_id, monthly, monthly, monthly),
        )
        conn.execute(
            """INSERT INTO so_credit_txns (user_id, amount, direction, action_type, description, balance_after)
               VALUES (%s,%s,'credit','account_creation','Welcome credits on account creation',%s)""",
            (user_id, monthly, monthly),
        )
        return user_id


def get_user_by_id(user_id: int):
    with get_conn() as conn:
        return row_to_dict(conn.execute("SELECT *, videos_used AS videos_used_this_month FROM users WHERE id=%s", (user_id,)).fetchone())


def get_user_by_email(email: str):
    with get_conn() as conn:
        return row_to_dict(conn.execute("SELECT * FROM users WHERE email=%s", (email.lower().strip(),)).fetchone())


def count_users() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()
        return row["cnt"] if row else 0


def update_user(user_id: int, **kwargs):
    if not kwargs:
        return
    cols = ", ".join(f"{k}=%s" for k in kwargs)
    vals = list(kwargs.values()) + [user_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE users SET {cols} WHERE id=%s", vals)


def increment_user_usage(user_id: int, videos: int = 0, credits: int = 0):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET videos_used = videos_used + %s, credits_used = credits_used + %s WHERE id=%s",
            (videos, credits, user_id),
        )


def increment_videos_used(user_id: int) -> int:
    with get_conn() as conn:
        conn.execute("UPDATE users SET videos_used = videos_used + 1 WHERE id=%s", (user_id,))
        row = conn.execute("SELECT videos_used FROM users WHERE id=%s", (user_id,)).fetchone()
        return row["videos_used"] if row else 0


def reset_monthly_usage(user_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE users SET videos_used = 0, credits_used = 0 WHERE id=%s", (user_id,))


def check_usage_allowed(user_id: int) -> dict:
    user = get_user_by_id(user_id)
    if not user:
        return {"allowed": False, "reason": "User not found"}
    if user.get("is_admin"):
        return {"allowed": True, "reason": "admin"}
    tier = user.get("subscription_tier", "free")
    limits = {"free": 3, "starter": 7, "creator": 15, "pro": 50, "agency": 999999}
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
    period_start = str(user.get("period_start") or "")
    current_month_start = datetime.now().strftime("%Y-%m-01")
    if period_start < current_month_start:
        update_user(user_id, videos_used=0, credits_used=0, period_start=current_month_start)


def count_completed_jobs_since(user_id: int, since_date: str) -> int:
    """Count jobs with status='done' for user since the given date (YYYY-MM-DD)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM jobs WHERE user_id=%s AND status='done' AND created_at >= %s",
            (user_id, since_date),
        ).fetchone()
        return (row["cnt"] if row else 0) or 0


def get_user_by_stripe_customer(stripe_customer_id: str):
    with get_conn() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM users WHERE stripe_customer_id=%s", (stripe_customer_id,)
        ).fetchone())


def get_user_by_stripe_subscription(stripe_subscription_id: str):
    with get_conn() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM users WHERE stripe_subscription_id=%s", (stripe_subscription_id,)
        ).fetchone())


def list_users(limit=200):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT %s", (limit,)).fetchall()
    return [row_to_dict(r) for r in rows]


# ── Social Accounts ──────────────────────────────────────────────────────────

def get_accounts(user_id: int = None):
    with get_conn() as conn:
        if user_id:
            rows = conn.execute("SELECT * FROM social_accounts WHERE user_id=%s ORDER BY platform", (user_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM social_accounts ORDER BY platform").fetchall()
    return [row_to_dict(r) for r in rows]


def upsert_account(platform, username, display_name=None, avatar_url=None,
                   access_token=None, refresh_token=None, account_id=None, followers=0,
                   user_id=None, platform_user_id=None):
    if platform_user_id and not account_id:
        account_id = platform_user_id
    with get_conn() as conn:
        q = "SELECT id FROM social_accounts WHERE platform=%s AND username=%s"
        params = [platform, username]
        if user_id:
            q += " AND user_id=%s"
            params.append(user_id)
        existing = conn.execute(q, params).fetchone()
        if existing:
            conn.execute("""
                UPDATE social_accounts SET display_name=%s, avatar_url=%s, access_token=%s,
                refresh_token=%s, account_id=%s, followers=%s, is_active=1
                WHERE id=%s
            """, (display_name, avatar_url, access_token, refresh_token, account_id,
                  followers, existing["id"]))
            return existing["id"]
        else:
            cur = conn.execute("""
                INSERT INTO social_accounts
                (platform, username, display_name, avatar_url, access_token, refresh_token,
                 account_id, followers, user_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
            """, (platform, username, display_name, avatar_url, access_token,
                  refresh_token, account_id, followers, user_id))
            return cur.fetchone()["id"]


def delete_account(account_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM social_accounts WHERE id=%s", (account_id,))


# ── Contacts ─────────────────────────────────────────────────────────────────

def get_contacts(platform=None, search=None, limit=100, offset=0, user_id=None):
    query = "SELECT * FROM contacts WHERE 1=1"
    params = []
    if user_id:
        query += " AND user_id=%s"
        params.append(user_id)
    if platform:
        query += " AND platform=%s"
        params.append(platform)
    if search:
        query += " AND (name LIKE %s OR handle LIKE %s OR email LIKE %s)"
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
        query += " AND user_id=%s"
        params.append(user_id)
    if platform:
        query += " AND platform=%s"
        params.append(platform)
    with get_conn() as conn:
        return conn.execute(query, params).fetchone()["n"]


def insert_contacts_bulk(contacts: list, user_id=None):
    if user_id:
        for c in contacts:
            c["user_id"] = user_id
    new_ids = []
    with get_conn() as conn:
        for c in contacts:
            cur = conn.execute("""
                INSERT INTO contacts (name, handle, email, phone, platform, avatar_url, followers, tags, user_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING id
            """, (c.get("name",""), c.get("handle",""), c.get("email",""), c.get("phone",""),
                  c.get("platform",""), c.get("avatar_url",""), c.get("followers",0),
                  c.get("tags","[]"), c.get("user_id")))
            row = cur.fetchone()
            if row:
                new_ids.append(row["id"])
    if user_id and new_ids:
        enroll_contacts_in_active_sequences(user_id, new_ids)
    return len(contacts)


# ── Sequences (auto-enroll a new contact into an email/SMS drip) ──────────────

def create_sequence(user_id, name, trigger="new_contact", steps=None):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO sequences (user_id, name, trigger) VALUES (%s,%s,%s) RETURNING id",
            (user_id, name, trigger))
        seq_id = cur.fetchone()["id"]
        for i, step in enumerate(steps or []):
            conn.execute("""
                INSERT INTO sequence_steps (sequence_id, step_order, delay_hours, channel, subject, body)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (seq_id, i, step.get("delay_hours", 0), step.get("channel", "email"),
                  step.get("subject", ""), step.get("body", "")))
        return seq_id


def get_sequences(user_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM sequences WHERE user_id=%s ORDER BY created_at DESC", (user_id,)
        ).fetchall()


def get_sequence(sequence_id, user_id):
    with get_conn() as conn:
        seq = conn.execute(
            "SELECT * FROM sequences WHERE id=%s AND user_id=%s", (sequence_id, user_id)
        ).fetchone()
        if not seq:
            return None
        steps = conn.execute(
            "SELECT * FROM sequence_steps WHERE sequence_id=%s ORDER BY step_order", (sequence_id,)
        ).fetchall()
        return {**seq, "steps": steps}


def set_sequence_active(sequence_id, user_id, active: bool):
    with get_conn() as conn:
        conn.execute(
            "UPDATE sequences SET active=%s WHERE id=%s AND user_id=%s",
            (active, sequence_id, user_id))


def delete_sequence(sequence_id, user_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM sequences WHERE id=%s AND user_id=%s", (sequence_id, user_id))


def enroll_contacts_in_active_sequences(user_id, contact_ids):
    """Auto-enroll newly-captured contacts into every active new_contact sequence."""
    if not contact_ids:
        return
    with get_conn() as conn:
        seqs = conn.execute(
            "SELECT id FROM sequences WHERE user_id=%s AND active=TRUE AND trigger='new_contact'",
            (user_id,)
        ).fetchall()
        for seq in seqs:
            for cid in contact_ids:
                conn.execute("""
                    INSERT INTO sequence_enrollments (sequence_id, contact_id, user_id, next_send_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT DO NOTHING
                """, (seq["id"], cid, user_id))


def get_due_sequence_enrollments(limit=50):
    with get_conn() as conn:
        return conn.execute("""
            SELECT e.*, s.name AS sequence_name,
                   c.name AS contact_name, c.email AS contact_email, c.phone AS contact_phone
            FROM sequence_enrollments e
            JOIN sequences s ON s.id = e.sequence_id
            JOIN contacts c ON c.id = e.contact_id
            WHERE e.status='active' AND e.next_send_at <= NOW() AND s.active=TRUE
            ORDER BY e.next_send_at ASC
            LIMIT %s
        """, (limit,)).fetchall()


def get_sequence_step(sequence_id, step_order):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM sequence_steps WHERE sequence_id=%s AND step_order=%s",
            (sequence_id, step_order)
        ).fetchone()


def advance_sequence_enrollment(enrollment_id, next_step, next_send_at=None, status="active"):
    with get_conn() as conn:
        conn.execute("""
            UPDATE sequence_enrollments
            SET current_step=%s, next_send_at=%s, status=%s
            WHERE id=%s
        """, (next_step, next_send_at, status, enrollment_id))


def delete_contacts(platform=None, user_id=None):
    with get_conn() as conn:
        if user_id and platform:
            conn.execute("DELETE FROM contacts WHERE platform=%s AND user_id=%s", (platform, user_id))
        elif user_id:
            conn.execute("DELETE FROM contacts WHERE user_id=%s", (user_id,))
        elif platform:
            conn.execute("DELETE FROM contacts WHERE platform=%s", (platform,))
        else:
            conn.execute("DELETE FROM contacts")


# ── Jobs ─────────────────────────────────────────────────────────────────────

def create_job(topic, format, platforms, audience, voice, style, privacy,
               skip_research=False, user_id=None):
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO jobs (topic, format, platforms, audience, voice, style, privacy, skip_research, user_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """, (topic, format, json.dumps(platforms), audience, voice, style, privacy,
              int(skip_research), user_id))
        return cur.fetchone()["id"]


def _coerce_val(v):
    """Convert numpy scalars → native Python types so psycopg2 can serialize them.
    numpy 2.x repr changed: str(np.float64(x)) == 'np.float64(x)', which breaks SQL."""
    try:
        if hasattr(v, "item") and type(v).__module__.startswith("numpy"):
            return v.item()
    except Exception:
        pass
    return v


def update_job(job_id, **kwargs):
    if not kwargs:
        return
    for k in ["platforms", "publish_results", "tags"]:
        if k in kwargs and isinstance(kwargs[k], (list, dict)):
            kwargs[k] = json.dumps(kwargs[k])
    cols = ", ".join(f"{k}=%s" for k in kwargs)
    vals = [_coerce_val(v) for v in kwargs.values()] + [job_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE jobs SET {cols} WHERE id=%s", vals)


def get_job(job_id, user_id=None):
    with get_conn() as conn:
        if user_id:
            row = conn.execute("SELECT * FROM jobs WHERE id=%s AND user_id=%s", (job_id, user_id)).fetchone()
        else:
            row = conn.execute("SELECT * FROM jobs WHERE id=%s", (job_id,)).fetchone()
    return row_to_dict(row)


def delete_job(job_id, user_id=None):
    with get_conn() as conn:
        if user_id:
            conn.execute("DELETE FROM jobs WHERE id=%s AND user_id=%s", (job_id, user_id))
        else:
            conn.execute("DELETE FROM jobs WHERE id=%s", (job_id,))


def get_jobs(limit=50, user_id=None, team_id=None, status=None):
    with get_conn() as conn:
        if team_id:
            q = """SELECT j.* FROM jobs j
                JOIN team_members tm ON tm.user_id = j.user_id
                WHERE tm.team_id = %s AND tm.status = 'active'"""
            params = [team_id]
            if status:
                q += " AND j.status = %s"
                params.append(status)
            q += " ORDER BY j.created_at DESC LIMIT %s"
            params.append(limit)
            rows = conn.execute(q, params).fetchall()
        elif user_id:
            q = "SELECT * FROM jobs WHERE user_id=%s"
            params = [user_id]
            if status:
                q += " AND status=%s"
                params.append(status)
            q += " ORDER BY created_at DESC LIMIT %s"
            params.append(limit)
            rows = conn.execute(q, params).fetchall()
        else:
            q = "SELECT * FROM jobs"
            params = []
            if status:
                q += " WHERE status=%s"
                params.append(status)
            q += " ORDER BY created_at DESC LIMIT %s"
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
            total = conn.execute("SELECT COUNT(*) as n FROM jobs WHERE user_id=%s", (user_id,)).fetchone()["n"]
            done = conn.execute("SELECT COUNT(*) as n FROM jobs WHERE status='done' AND user_id=%s", (user_id,)).fetchone()["n"]
            contacts = conn.execute("SELECT COUNT(*) as n FROM contacts WHERE user_id=%s", (user_id,)).fetchone()["n"]
            accounts = conn.execute("SELECT COUNT(*) as n FROM social_accounts WHERE is_active=1 AND user_id=%s", (user_id,)).fetchone()["n"]
        else:
            total = conn.execute("SELECT COUNT(*) as n FROM jobs").fetchone()["n"]
            done = conn.execute("SELECT COUNT(*) as n FROM jobs WHERE status='done'").fetchone()["n"]
            contacts = conn.execute("SELECT COUNT(*) as n FROM contacts").fetchone()["n"]
            accounts = conn.execute("SELECT COUNT(*) as n FROM social_accounts WHERE is_active=1").fetchone()["n"]
    return {"total_jobs": total, "completed_jobs": done, "contacts": contacts, "accounts": accounts}


# ── Settings ─────────────────────────────────────────────────────────────────

def get_setting(key, default=None):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=%s", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (key, str(value))
        )


# ── Feature 1: Analytics ─────────────────────────────────────────────────────

def upsert_analytics(user_id: int, video_id: str, platform: str = "youtube", **kwargs):
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM analytics_cache WHERE user_id=%s AND video_id=%s AND platform=%s",
            (user_id, video_id, platform)
        ).fetchone()
        if existing:
            sets = ", ".join(f"{k}=%s" for k in kwargs)
            sets += ", fetched_at=NOW()"
            vals = list(kwargs.values()) + [existing["id"]]
            conn.execute(f"UPDATE analytics_cache SET {sets} WHERE id=%s", vals)
            return existing["id"]
        else:
            fields = ["user_id", "video_id", "platform"] + list(kwargs.keys())
            placeholders = ",".join(["%s"] * len(fields))
            vals = [user_id, video_id, platform] + list(kwargs.values())
            cur = conn.execute(
                f"INSERT INTO analytics_cache ({','.join(fields)}) VALUES ({placeholders}) RETURNING id", vals
            )
            return cur.fetchone()["id"]


def get_analytics(user_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM analytics_cache WHERE user_id=%s ORDER BY views DESC",
            (user_id,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def get_analytics_joined(user_id: int, limit: int = 200):
    """Analytics rows enriched with the originating job's topic/format so the
    feedback loop can learn which content angles perform."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM (
                SELECT DISTINCT ON (a.id) a.*, pv.job_id, j.topic, j.format
                FROM analytics_cache a
                LEFT JOIN published_videos pv
                       ON pv.video_id = a.video_id AND pv.platform = a.platform AND pv.user_id = a.user_id
                LEFT JOIN jobs j ON j.id = pv.job_id
                WHERE a.user_id=%s
                ORDER BY a.id, pv.id DESC
            ) sub
            ORDER BY sub.views DESC
            LIMIT %s
        """, (user_id, limit)).fetchall()
    return [row_to_dict(r) for r in rows]


def get_user_ids_with_platform_account(platform: str = "youtube"):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT user_id FROM social_accounts "
            "WHERE platform=%s AND access_token IS NOT NULL AND user_id IS NOT NULL",
            (platform,)
        ).fetchall()
    return [r["user_id"] for r in rows]


def add_published_video(user_id: int, job_id, platform: str, video_id: str,
                        video_url: str, title: str):
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO published_videos (user_id, job_id, platform, video_id, video_url, title)
            VALUES (%s,%s,%s,%s,%s,%s) RETURNING id
        """, (user_id, job_id, platform, video_id, video_url, title))
        return cur.fetchone()["id"]


def get_published_videos(user_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM published_videos WHERE user_id=%s ORDER BY published_at DESC",
            (user_id,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


# ── Feature 2: Content Calendar / Scheduler ───────────────────────────────────

def create_scheduled_post(user_id: int, job_id: int, platform: str, scheduled_at: str) -> int:
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO scheduled_posts (user_id, job_id, platform, scheduled_at)
            VALUES (%s,%s,%s,%s) RETURNING id
        """, (user_id, job_id, platform, scheduled_at))
        return cur.fetchone()["id"]


def get_scheduled_posts(user_id: int, status: str = None):
    query = "SELECT sp.*, j.title as job_title, j.video_path, j.thumbnail_path FROM scheduled_posts sp LEFT JOIN jobs j ON j.id = sp.job_id WHERE sp.user_id=%s"
    params = [user_id]
    if status:
        query += " AND sp.status=%s"
        params.append(status)
    query += " ORDER BY sp.scheduled_at ASC"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [row_to_dict(r) for r in rows]


def get_scheduled_post(post_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT sp.*, j.video_path, j.thumbnail_path FROM scheduled_posts sp LEFT JOIN jobs j ON j.id=sp.job_id WHERE sp.id=%s",
            (post_id,)
        ).fetchone()
    return row_to_dict(row)


def update_scheduled_post(post_id: int, **kwargs):
    if not kwargs:
        return
    cols = ", ".join(f"{k}=%s" for k in kwargs)
    vals = list(kwargs.values()) + [post_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE scheduled_posts SET {cols} WHERE id=%s", vals)


def delete_scheduled_post(post_id: int, user_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM scheduled_posts WHERE id=%s AND user_id=%s", (post_id, user_id))


def get_due_scheduled_posts():
    """Get all pending scheduled posts that are due now."""
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT sp.*, j.video_path, j.thumbnail_path, j.title as job_title
            FROM scheduled_posts sp
            LEFT JOIN jobs j ON j.id = sp.job_id
            WHERE sp.status = 'pending' AND sp.scheduled_at <= %s
        """, (now,)).fetchall()
    return [row_to_dict(r) for r in rows]


# ── Autopilot Channels ────────────────────────────────────────────────────────

_AUTOPILOT_FIELDS = {
    "name", "niche", "format", "platforms", "voice", "style", "audience",
    "cadence_hours", "topic_source", "rss_url", "privacy", "enabled",
    "last_run_at", "next_run_at", "last_job_id", "last_error",
}


def create_autopilot_channel(user_id: int, name: str, niche: str, **kwargs) -> int:
    fields = {k: v for k, v in kwargs.items() if k in _AUTOPILOT_FIELDS}
    cols = ["user_id", "name", "niche"] + list(fields.keys())
    vals = [user_id, name, niche] + list(fields.values())
    placeholders = ",".join(["%s"] * len(cols))
    with get_conn() as conn:
        cur = conn.execute(
            f"INSERT INTO autopilot_channels ({','.join(cols)}) VALUES ({placeholders}) RETURNING id",
            vals,
        )
        return cur.fetchone()["id"]


def get_autopilot_channels(user_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM autopilot_channels WHERE user_id=%s ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def get_autopilot_channel(channel_id: int, user_id: int = None):
    query = "SELECT * FROM autopilot_channels WHERE id=%s"
    params = [channel_id]
    if user_id is not None:
        query += " AND user_id=%s"
        params.append(user_id)
    with get_conn() as conn:
        row = conn.execute(query, params).fetchone()
    return row_to_dict(row) if row else None


def update_autopilot_channel(channel_id: int, user_id: int = None, **kwargs):
    fields = {k: v for k, v in kwargs.items() if k in _AUTOPILOT_FIELDS}
    if not fields:
        return
    sets = ", ".join(f"{k}=%s" for k in fields)
    query = f"UPDATE autopilot_channels SET {sets} WHERE id=%s"
    params = list(fields.values()) + [channel_id]
    if user_id is not None:
        query += " AND user_id=%s"
        params.append(user_id)
    with get_conn() as conn:
        conn.execute(query, params)


def delete_autopilot_channel(channel_id: int, user_id: int):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM autopilot_channels WHERE id=%s AND user_id=%s",
            (channel_id, user_id)
        )


def get_due_autopilot_channels():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM autopilot_channels WHERE enabled=1 AND next_run_at <= NOW()"
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def get_recent_job_topics(user_id: int, limit: int = 40):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT topic FROM jobs WHERE user_id=%s ORDER BY id DESC LIMIT %s",
            (user_id, limit)
        ).fetchall()
    return [r["topic"] for r in rows]


# ── Feature 3: Batch Mode ────────────────────────────────────────────────────

def create_batch_job(user_id: int, topics: list) -> str:
    batch_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO batch_jobs (id, user_id, total_count, topics_json)
            VALUES (%s,%s,%s,%s)
        """, (batch_id, user_id, len(topics), json.dumps(topics)))
    return batch_id


def get_batch_job(batch_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM batch_jobs WHERE id=%s", (batch_id,)).fetchone()
    return row_to_dict(row)


def update_batch_job(batch_id: str, **kwargs):
    if not kwargs:
        return
    cols = ", ".join(f"{k}=%s" for k in kwargs)
    vals = list(kwargs.values()) + [batch_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE batch_jobs SET {cols} WHERE id=%s", vals)


def get_batch_jobs(user_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM batch_jobs WHERE user_id=%s ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


# ── Feature 4: Template Library ──────────────────────────────────────────────

def create_template(user_id: int, name: str, description: str, config_json: dict) -> str:
    tmpl_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO content_templates (id, user_id, name, description, config_json)
            VALUES (%s,%s,%s,%s,%s)
        """, (tmpl_id, user_id, name, description, json.dumps(config_json)))
    return tmpl_id


def get_templates(user_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM content_templates WHERE user_id=%s ORDER BY use_count DESC, created_at DESC",
            (user_id,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def get_template(tmpl_id: str, user_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM content_templates WHERE id=%s AND user_id=%s", (tmpl_id, user_id)
        ).fetchone()
    return row_to_dict(row)


def increment_template_use(tmpl_id: str):
    with get_conn() as conn:
        conn.execute("UPDATE content_templates SET use_count=use_count+1 WHERE id=%s", (tmpl_id,))


def delete_template(tmpl_id: str, user_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM content_templates WHERE id=%s AND user_id=%s", (tmpl_id, user_id))


# ── Feature 5: Dub Jobs ──────────────────────────────────────────────────────

def create_dub_job(user_id: int, source_job_id: int, target_language: str) -> str:
    dub_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO dub_jobs (id, user_id, source_job_id, target_language)
            VALUES (%s,%s,%s,%s)
        """, (dub_id, user_id, source_job_id, target_language))
    return dub_id


def get_dub_job(dub_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM dub_jobs WHERE id=%s", (dub_id,)).fetchone()
    return row_to_dict(row)


def update_dub_job(dub_id: str, **kwargs):
    if not kwargs:
        return
    cols = ", ".join(f"{k}=%s" for k in kwargs)
    vals = list(kwargs.values()) + [dub_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE dub_jobs SET {cols} WHERE id=%s", vals)


def get_dub_jobs_for_source(user_id: int, source_job_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM dub_jobs WHERE user_id=%s AND source_job_id=%s ORDER BY created_at DESC",
            (user_id, source_job_id)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


# ── Feature 6: Notifications ─────────────────────────────────────────────────

def create_in_app_notification(user_id: int, title: str, body: str, link: str = "") -> str:
    notif_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO in_app_notifications (id, user_id, title, body, link)
            VALUES (%s,%s,%s,%s,%s)
        """, (notif_id, user_id, title, body, link))
    return notif_id


def get_in_app_notifications(user_id: int, limit: int = 10):
    with get_conn() as conn:
        unread_count = conn.execute(
            "SELECT COUNT(*) as n FROM in_app_notifications WHERE user_id=%s AND read=0",
            (user_id,)
        ).fetchone()["n"]
        rows = conn.execute(
            "SELECT * FROM in_app_notifications WHERE user_id=%s ORDER BY created_at DESC LIMIT %s",
            (user_id, limit)
        ).fetchall()
    return {"unread_count": unread_count, "notifications": [row_to_dict(r) for r in rows]}


def mark_notification_read(notif_id: str, user_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE in_app_notifications SET read=1 WHERE id=%s AND user_id=%s",
            (notif_id, user_id)
        )


def log_notification(notif_id, user_id: int, event_type: str, channel: str, status: str):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO notification_log (notif_id, user_id, event_type, channel, status)
            VALUES (%s,%s,%s,%s,%s)
        """, (notif_id, user_id, event_type, channel, status))


# ── Feature 7: Team Workspaces ────────────────────────────────────────────────

def create_team(owner_id: int, name: str) -> str:
    team_id = str(uuid.uuid4())
    member_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO teams (id, owner_id, name) VALUES (%s,%s,%s)",
            (team_id, owner_id, name)
        )
        conn.execute("""
            INSERT INTO team_members (id, team_id, user_id, role, status)
            VALUES (%s,%s,%s,%s,%s)
        """, (member_id, team_id, owner_id, "owner", "active"))
    return team_id


def get_team_for_user(user_id: int):
    """Get the team where this user is an active member."""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT t.*, tm.role as user_role FROM teams t
            JOIN team_members tm ON tm.team_id = t.id
            WHERE tm.user_id = %s AND tm.status = 'active'
            LIMIT 1
        """, (user_id,)).fetchone()
    return row_to_dict(row)


def get_team_by_id(team_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM teams WHERE id=%s", (team_id,)).fetchone()
    return row_to_dict(row)


def get_team_members(team_id: str):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT tm.*, u.name as user_name, u.email as user_email
            FROM team_members tm
            LEFT JOIN users u ON u.id = tm.user_id
            WHERE tm.team_id=%s
            ORDER BY tm.created_at ASC
        """, (team_id,)).fetchall()
    return [row_to_dict(r) for r in rows]


def add_team_member(team_id: str, invited_email: str, role: str = "editor") -> str:
    member_id = str(uuid.uuid4())
    with get_conn() as conn:
        user = conn.execute("SELECT id FROM users WHERE email=%s", (invited_email.lower(),)).fetchone()
        user_id = user["id"] if user else None
        conn.execute("""
            INSERT INTO team_members (id, team_id, user_id, role, invited_email, status)
            VALUES (%s,%s,%s,%s,%s,%s)
        """, (member_id, team_id, user_id, role, invited_email.lower(), "pending" if not user_id else "active"))
    return member_id


def update_team_member(member_id: str, **kwargs):
    if not kwargs:
        return
    cols = ", ".join(f"{k}=%s" for k in kwargs)
    vals = list(kwargs.values()) + [member_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE team_members SET {cols} WHERE id=%s", vals)


def remove_team_member(member_id: str, team_id: str):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM team_members WHERE id=%s AND team_id=%s",
            (member_id, team_id)
        )


# ── Feature 8: Competitor Tracker ────────────────────────────────────────────

def add_competitor_channel(user_id: int, platform: str, channel_id: str,
                           channel_name: str, channel_url: str) -> str:
    comp_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO competitor_channels (id, user_id, platform, channel_id, channel_name, channel_url)
            VALUES (%s,%s,%s,%s,%s,%s)
        """, (comp_id, user_id, platform, channel_id, channel_name, channel_url))
    return comp_id


def get_competitor_channels(user_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM competitor_channels WHERE user_id=%s ORDER BY added_at DESC",
            (user_id,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def get_competitor_channel(comp_id: str, user_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM competitor_channels WHERE id=%s AND user_id=%s", (comp_id, user_id)
        ).fetchone()
    return row_to_dict(row)


def delete_competitor_channel(comp_id: str, user_id: int):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM competitor_channels WHERE id=%s AND user_id=%s", (comp_id, user_id)
        )


def upsert_competitor_video(competitor_id: str, video_id: str, title: str,
                            views: int, likes: int, published_at: str,
                            thumbnail_url: str, video_url: str):
    vid_pk = str(uuid.uuid4())
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM competitor_videos WHERE competitor_id=%s AND video_id=%s",
            (competitor_id, video_id)
        ).fetchone()
        if existing:
            conn.execute("""
                UPDATE competitor_videos SET title=%s, views=%s, likes=%s, published_at=%s,
                thumbnail_url=%s, video_url=%s, fetched_at=NOW()
                WHERE id=%s
            """, (title, views, likes, published_at, thumbnail_url, video_url, existing["id"]))
        else:
            conn.execute("""
                INSERT INTO competitor_videos
                (id, competitor_id, video_id, title, views, likes, published_at, thumbnail_url, video_url)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (vid_pk, competitor_id, video_id, title, views, likes, published_at, thumbnail_url, video_url))


def get_competitor_videos(competitor_id: str, limit: int = 10):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM competitor_videos WHERE competitor_id=%s
            ORDER BY views DESC, fetched_at DESC LIMIT %s
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
            "INSERT INTO outreach_campaigns (user_id, name, type, subject, body) VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (user_id, name, type_, subject, body)
        )
        return cur.fetchone()["id"]


def get_campaigns(user_id):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM outreach_campaigns WHERE user_id=%s ORDER BY created_at DESC", (user_id,)
        ).fetchall()]


def get_campaign(campaign_id, user_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM outreach_campaigns WHERE id=%s AND user_id=%s", (campaign_id, user_id)
        ).fetchone()
        return dict(row) if row else None


def delete_campaign(campaign_id, user_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM outreach_campaigns WHERE id=%s AND user_id=%s", (campaign_id, user_id))


def log_send(campaign_id, contact_id, user_id, status, error_msg=None, message_sid=None):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO outreach_sends
               (campaign_id, contact_id, user_id, status, sent_at, error_msg, message_sid)
               VALUES (%s,%s,%s,%s,NOW(),%s,%s)
               ON CONFLICT (campaign_id, contact_id) DO UPDATE SET
               status = EXCLUDED.status, sent_at = EXCLUDED.sent_at,
               error_msg = EXCLUDED.error_msg, message_sid = EXCLUDED.message_sid""",
            (campaign_id, contact_id, user_id, status, error_msg, message_sid)
        )


def increment_campaign_sent(campaign_id, count=1):
    with get_conn() as conn:
        conn.execute(
            "UPDATE outreach_campaigns SET sent_count=sent_count+%s, sent_at=NOW(), status='sent' WHERE id=%s",
            (count, campaign_id)
        )


def get_campaign_sends(campaign_id):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            """SELECT os.*, c.name, c.email, c.phone FROM outreach_sends os
               JOIN contacts c ON c.id=os.contact_id
               WHERE os.campaign_id=%s""", (campaign_id,)
        ).fetchall()]


def update_send_status_by_sid(message_sid: str, status: str):
    """Update outreach_sends delivery status when Twilio posts a status callback."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE outreach_sends SET status=%s WHERE message_sid=%s",
            (status, message_sid)
        )


def log_inbound_call(call_sid: str, from_: str, to: str,
                     status: str = "ringing",
                     city: str = None, state: str = None, country: str = None):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO inbound_calls
               (call_sid, from_number, to_number, call_status, caller_city, caller_state, caller_country)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (call_sid) DO NOTHING""",
            (call_sid, from_, to, status, city, state, country)
        )


def update_inbound_call(call_sid: str, **kwargs):
    if not kwargs:
        return
    cols = ", ".join(f"{k}=%s" for k in kwargs) + ", updated_at=NOW()"
    vals = list(kwargs.values()) + [call_sid]
    with get_conn() as conn:
        conn.execute(f"UPDATE inbound_calls SET {cols} WHERE call_sid=%s", vals)


def get_inbound_calls(limit: int = 100):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM inbound_calls ORDER BY received_at DESC LIMIT %s", (limit,)
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
                "SELECT *, videos_used AS videos_used_this_month FROM users WHERE subscription_tier=%s ORDER BY created_at DESC LIMIT %s",
                (tier, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT *, videos_used AS videos_used_this_month FROM users ORDER BY created_at DESC LIMIT %s",
                (limit,)
            ).fetchall()
    return [row_to_dict(r) for r in rows]


def get_admin_stats():
    """Return MRR, tier counts, and status counts for the admin dashboard."""
    tier_prices = {"starter": 9.99, "creator": 29.99, "pro": 79.99, "agency": 199.99}
    with get_conn() as conn:
        rows = conn.execute("SELECT subscription_tier, subscription_status FROM users").fetchall()
    total = len(rows)
    tier_counts = {"free": 0, "starter": 0, "creator": 0, "pro": 0, "agency": 0}
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
        total = conn.execute("SELECT COUNT(*) AS cnt FROM jobs WHERE user_id=%s", (user_id,)).fetchone()["cnt"]
        done = conn.execute("SELECT COUNT(*) AS cnt FROM jobs WHERE user_id=%s AND status='done'", (user_id,)).fetchone()["cnt"]
        recent = conn.execute(
            "SELECT id, topic, format, status, created_at FROM jobs WHERE user_id=%s ORDER BY created_at DESC LIMIT 10",
            (user_id,)
        ).fetchall()
    return {"total": total, "done": done, "recent": [row_to_dict(r) for r in recent]}


# ── Password Reset ────────────────────────────────────────────────────────────

def create_password_reset_token(user_id: int, token: str, expires_at: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM password_reset_tokens WHERE user_id=%s AND used=0", (user_id,))
        conn.execute(
            "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (%s,%s,%s)",
            (user_id, token, expires_at)
        )


def get_password_reset_token(token: str):
    with get_conn() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM password_reset_tokens WHERE token=%s AND used=0", (token,)
        ).fetchone())


def consume_password_reset_token(token: str):
    with get_conn() as conn:
        conn.execute("UPDATE password_reset_tokens SET used=1 WHERE token=%s", (token,))


# ── Audit Log ─────────────────────────────────────────────────────────────────

def log_audit(admin_id: int, action: str, target_user_id: int = None, details: dict = None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO audit_log (admin_id, action, target_user_id, details) VALUES (%s,%s,%s,%s)",
            (admin_id, action, target_user_id, json.dumps(details or {}))
        )


def get_audit_log(limit: int = 100):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT a.*, u.email AS admin_email, t.email AS target_email
               FROM audit_log a
               LEFT JOIN users u ON u.id = a.admin_id
               LEFT JOIN users t ON t.id = a.target_user_id
               ORDER BY a.created_at DESC LIMIT %s""",
            (limit,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def get_inbound_sms(limit: int = 100):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM inbound_sms ORDER BY received_at DESC LIMIT %s", (limit,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def log_inbound_sms(from_: str, to: str, body: str, message_sid: str):
    """Store an inbound SMS reply received via the Twilio webhook."""
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO inbound_sms (message_sid, from_number, to_number, body, received_at)
               VALUES (%s,%s,%s,%s,NOW())
               ON CONFLICT (message_sid) DO NOTHING""",
            (message_sid, from_, to, body)
        )


# ── Follow Tracking ──────────────────────────────────────────────────────────

def track_follow(user_id, platform, target_username):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO follow_tracking (user_id, platform, target_username) VALUES (%s,%s,%s) RETURNING id",
            (user_id, platform, target_username))
        return cur.fetchone()["id"]

def get_follows(user_id, status=None):
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM follow_tracking WHERE user_id=%s AND status=%s ORDER BY followed_at DESC",
                (user_id, status)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM follow_tracking WHERE user_id=%s ORDER BY followed_at DESC",
                (user_id,)).fetchall()
        return [dict(r) for r in rows]

def mark_follow_back(user_id, platform, target_username):
    with get_conn() as conn:
        conn.execute(
            "UPDATE follow_tracking SET followed_back=1 WHERE user_id=%s AND platform=%s AND target_username=%s",
            (user_id, platform, target_username))

def mark_unfollowed(follow_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE follow_tracking SET status='unfollowed', unfollowed_at=NOW() WHERE id=%s",
            (follow_id,))

def get_stale_follows(user_id, days=7, platform=None, days_threshold=None):
    if days_threshold is not None:
        days = days_threshold
    with get_conn() as conn:
        if platform:
            rows = conn.execute(
                "SELECT * FROM follow_tracking WHERE user_id=%s AND platform=%s AND status='following' AND followed_back=0 AND followed_at < NOW() - %s * INTERVAL '1 day'",
                (user_id, platform, days)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM follow_tracking WHERE user_id=%s AND status='following' AND followed_back=0 AND followed_at < NOW() - %s * INTERVAL '1 day'",
                (user_id, days)).fetchall()
        return [dict(r) for r in rows]


# ── RSS Feeds ────────────────────────────────────────────────────────────────

def add_rss_feed(user_id, url, name="", category=""):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO rss_feeds (user_id, url, name, category) VALUES (%s,%s,%s,%s) RETURNING id",
            (user_id, url, name, category))
        return cur.fetchone()["id"]

def get_rss_feeds(user_id):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM rss_feeds WHERE user_id=%s ORDER BY created_at DESC", (user_id,)).fetchall()
        return [dict(r) for r in rows]

def delete_rss_feed(feed_id, user_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM rss_feeds WHERE id=%s AND user_id=%s", (feed_id, user_id))


# ── Auto-Reply Rules ────────────────────────────────────────────────────────

def create_auto_reply_rule(user_id, platform, trigger_type, trigger_value, reply_template, uses_spintax=False):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO auto_reply_rules (user_id, platform, trigger_type, trigger_value, reply_template, uses_spintax) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
            (user_id, platform, trigger_type, trigger_value, reply_template, 1 if uses_spintax else 0))
        return cur.fetchone()["id"]

def get_auto_reply_rules(user_id, platform=None):
    with get_conn() as conn:
        if platform:
            rows = conn.execute(
                "SELECT * FROM auto_reply_rules WHERE user_id=%s AND platform=%s ORDER BY created_at DESC",
                (user_id, platform)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM auto_reply_rules WHERE user_id=%s ORDER BY created_at DESC",
                (user_id,)).fetchall()
        return [dict(r) for r in rows]

def delete_auto_reply_rule(rule_id, user_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM auto_reply_rules WHERE id=%s AND user_id=%s", (rule_id, user_id))


# ── DM Templates ────────────────────────────────────────────────────────────

def create_dm_template(user_id, name, message_template, platform="", trigger_on=""):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO dm_templates (user_id, name, message_template, platform, trigger_on) VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (user_id, name, message_template, platform, trigger_on))
        return cur.fetchone()["id"]

def get_dm_templates(user_id):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM dm_templates WHERE user_id=%s ORDER BY created_at DESC", (user_id,)).fetchall()
        return [dict(r) for r in rows]

def delete_dm_template(tmpl_id, user_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM dm_templates WHERE id=%s AND user_id=%s", (tmpl_id, user_id))


# ── Growth Snapshots ─────────────────────────────────────────────────────────

def add_growth_snapshot(user_id, account_id, platform, followers=0, following=0, posts=0, engagement_rate=0, views_total=0, likes_total=0):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO growth_snapshots (user_id, account_id, platform, followers, following, posts, engagement_rate, views_total, likes_total) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (user_id, account_id, platform, followers, following, posts, engagement_rate, views_total, likes_total))
        return cur.fetchone()["id"]

def get_growth_history(user_id, account_id=None):
    with get_conn() as conn:
        if account_id:
            rows = conn.execute(
                "SELECT * FROM growth_snapshots WHERE user_id=%s AND account_id=%s ORDER BY created_at DESC",
                (user_id, account_id)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM growth_snapshots WHERE user_id=%s ORDER BY created_at DESC",
                (user_id,)).fetchall()
        return [dict(r) for r in rows]

def get_growth_summary(user_id):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT platform,
                   MIN(followers) as min_followers,
                   MAX(followers) as max_followers
            FROM growth_snapshots WHERE user_id=%s
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
            "INSERT INTO engagement_campaigns (user_id, name, platforms, target_niche, strategy, daily_limit) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
            (user_id, name, json.dumps(platforms or []), target_niche, strategy, daily_limit))
        return cur.fetchone()["id"]


def get_engagement_campaigns(user_id):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM engagement_campaigns WHERE user_id=%s ORDER BY created_at DESC", (user_id,)).fetchall()
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
        row = conn.execute("SELECT * FROM engagement_campaigns WHERE id=%s AND user_id=%s", (campaign_id, user_id)).fetchone()
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
    sets = ", ".join(f"{k}=%s" for k in kwargs)
    vals = list(kwargs.values()) + [campaign_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE engagement_campaigns SET {sets} WHERE id=%s", vals)


def delete_engagement_campaign(campaign_id, user_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM engagement_campaigns WHERE id=%s AND user_id=%s", (campaign_id, user_id))


# ── Engagement Actions ───────────────────────────────────────────────────────

def create_engagement_action(user_id, platform, action_type, target_url="", comment_text="", campaign_id=None, target_username="", target_content_id="", scheduled_at=None):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO engagement_actions (user_id, platform, action_type, target_url, comment_text, campaign_id, target_username, target_content_id, scheduled_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (user_id, platform, action_type, target_url or "", comment_text or "", campaign_id, target_username or "", target_content_id or "", scheduled_at))
        return cur.fetchone()["id"]


def get_engagement_actions(user_id, status=None, campaign_id=None, limit=None):
    with get_conn() as conn:
        q = "SELECT * FROM engagement_actions WHERE user_id=%s"
        params = [user_id]
        if status:
            q += " AND status=%s"
            params.append(status)
        if campaign_id:
            q += " AND campaign_id=%s"
            params.append(campaign_id)
        q += " ORDER BY created_at DESC"
        if limit:
            q += " LIMIT %s"
            params.append(limit)
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]


def update_engagement_action(action_id, **kwargs):
    if not kwargs:
        return
    sets = ", ".join(f"{k}=%s" for k in kwargs)
    vals = list(kwargs.values()) + [action_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE engagement_actions SET {sets} WHERE id=%s", vals)


# ── Engagement Targets ───────────────────────────────────────────────────────

def add_engagement_target(user_id, campaign_id, platform, username, followers=0):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO engagement_targets (user_id, campaign_id, platform, username, followers) VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (user_id, campaign_id, platform, username, followers))
        return cur.fetchone()["id"]


def get_engagement_targets(user_id, campaign_id, engaged=None, limit=None):
    with get_conn() as conn:
        q = "SELECT * FROM engagement_targets WHERE user_id=%s AND campaign_id=%s"
        params = [user_id, campaign_id]
        if engaged is not None:
            q += " AND engaged=%s"
            params.append(1 if engaged else 0)
        q += " ORDER BY created_at DESC"
        if limit:
            q += " LIMIT %s"
            params.append(limit)
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]


def mark_target_engaged(target_id):
    with get_conn() as conn:
        conn.execute("UPDATE engagement_targets SET engaged=1, engaged_at=NOW() WHERE id=%s", (target_id,))


# ── Automation Settings (official-API auto-reply / follow-back) ─────────────

def get_automation_settings(platform):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM automation_settings WHERE platform=%s", (platform,)).fetchone()
    return dict(row) if row else None


def get_all_automation_settings():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM automation_settings ORDER BY platform").fetchall()
    return [dict(r) for r in rows]


def upsert_automation_settings(platform, **fields):
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM automation_settings WHERE platform=%s", (platform,)).fetchone()
        if existing:
            if fields:
                sets = ", ".join(f"{k}=%s" for k in fields)
                conn.execute(f"UPDATE automation_settings SET {sets}, updated_at=NOW() WHERE platform=%s",
                             list(fields.values()) + [platform])
            return existing["id"]
        cols = ["platform"] + list(fields.keys())
        placeholders = ", ".join(["%s"] * len(cols))
        cur = conn.execute(
            f"INSERT INTO automation_settings ({', '.join(cols)}) VALUES ({placeholders}) RETURNING id",
            [platform] + list(fields.values()))
        return cur.fetchone()["id"]


# ── Engagement Stats ─────────────────────────────────────────────────────────

def get_engagement_stats(user_id):
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS cnt FROM engagement_actions WHERE user_id=%s", (user_id,)).fetchone()["cnt"]
        rows = conn.execute("SELECT action_type, COUNT(*) as cnt FROM engagement_actions WHERE user_id=%s GROUP BY action_type", (user_id,)).fetchall()
        by_action = {r["action_type"]: r["cnt"] for r in rows}
        daily = conn.execute(
            "SELECT COUNT(*) AS cnt FROM engagement_actions WHERE user_id=%s AND created_at::date = CURRENT_DATE",
            (user_id,)).fetchone()["cnt"]
        status_rows = conn.execute("SELECT status, COUNT(*) as cnt FROM engagement_actions WHERE user_id=%s GROUP BY status", (user_id,)).fetchall()
        by_status = {r["status"]: r["cnt"] for r in status_rows}
        return {"total": total, "by_action": by_action, "daily_count": daily, "by_status": by_status}


def get_daily_action_count(user_id, platform=None):
    with get_conn() as conn:
        if platform:
            return conn.execute(
                "SELECT COUNT(*) AS cnt FROM engagement_actions WHERE user_id=%s AND platform=%s AND created_at::date = CURRENT_DATE",
                (user_id, platform)).fetchone()["cnt"]
        return conn.execute(
            "SELECT COUNT(*) AS cnt FROM engagement_actions WHERE user_id=%s AND created_at::date = CURRENT_DATE",
            (user_id,)).fetchone()["cnt"]


# ── Agency / BizDev ──────────────────────────────────────────────────────────

def get_agency_clients(user_id, status=None):
    with get_conn() as conn:
        if status:
            rows = conn.execute("SELECT * FROM agency_clients WHERE user_id=%s AND status=%s ORDER BY updated_at DESC", (user_id, status)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM agency_clients WHERE user_id=%s ORDER BY updated_at DESC", (user_id,)).fetchall()
        return [row_to_dict(r) for r in rows]

def _next_client_number(conn, user_id):
    row = conn.execute("SELECT COUNT(*) AS cnt FROM agency_clients WHERE user_id=%s", (user_id,)).fetchone()
    seq = (row["cnt"] if row else 0) + 1
    return f"SO-{user_id:04d}-{seq:04d}"

def create_agency_client(user_id, data):
    with get_conn() as conn:
        client_num = _next_client_number(conn, user_id)
        cur = conn.execute(
            "INSERT INTO agency_clients (user_id, client_number, name, company, email, phone, industry, website, status, monthly_value, notes, source) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (user_id, client_num, data.get("name",""), data.get("company",""), data.get("email",""), data.get("phone",""),
             data.get("industry",""), data.get("website",""), data.get("status","lead"), data.get("monthly_value",0),
             data.get("notes",""), data.get("source","manual")))
        return cur.fetchone()["id"]

def update_agency_client(user_id, client_id, data):
    with get_conn() as conn:
        fields = []
        vals = []
        for k in ("name","company","email","phone","industry","website","status","monthly_value","notes","source","last_contact","next_followup"):
            if k in data:
                fields.append(f"{k}=%s")
                vals.append(data[k])
        if not fields:
            return
        fields.append("updated_at=NOW()")
        vals.extend([user_id, client_id])
        conn.execute(f"UPDATE agency_clients SET {','.join(fields)} WHERE user_id=%s AND id=%s", vals)

def delete_agency_client(user_id, client_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM agency_clients WHERE user_id=%s AND id=%s", (user_id, client_id))

def get_agency_deals(user_id, client_id=None, stage=None):
    with get_conn() as conn:
        q = "SELECT d.*, c.name as client_name, c.company as client_company FROM agency_deals d LEFT JOIN agency_clients c ON d.client_id=c.id WHERE d.user_id=%s"
        params = [user_id]
        if client_id:
            q += " AND d.client_id=%s"
            params.append(client_id)
        if stage:
            q += " AND d.stage=%s"
            params.append(stage)
        q += " ORDER BY d.updated_at DESC"
        return [row_to_dict(r) for r in conn.execute(q, params).fetchall()]

def create_agency_deal(user_id, data):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO agency_deals (user_id, client_id, title, value, stage, service_type, description, close_date) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (user_id, data.get("client_id"), data.get("title",""), data.get("value",0), data.get("stage","discovery"),
             data.get("service_type","content"), data.get("description",""), data.get("close_date","")))
        return cur.fetchone()["id"]

def update_agency_deal(user_id, deal_id, data):
    with get_conn() as conn:
        fields = []
        vals = []
        for k in ("client_id","title","value","stage","service_type","description","close_date"):
            if k in data:
                fields.append(f"{k}=%s")
                vals.append(data[k])
        if not fields:
            return
        fields.append("updated_at=NOW()")
        vals.extend([user_id, deal_id])
        conn.execute(f"UPDATE agency_deals SET {','.join(fields)} WHERE user_id=%s AND id=%s", vals)

def delete_agency_deal(user_id, deal_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM agency_deals WHERE user_id=%s AND id=%s", (user_id, deal_id))

def get_agency_projects(user_id, client_id=None, status=None):
    with get_conn() as conn:
        q = "SELECT p.*, c.name as client_name FROM agency_projects p LEFT JOIN agency_clients c ON p.client_id=c.id WHERE p.user_id=%s"
        params = [user_id]
        if client_id:
            q += " AND p.client_id=%s"
            params.append(client_id)
        if status:
            q += " AND p.status=%s"
            params.append(status)
        q += " ORDER BY p.created_at DESC"
        return [row_to_dict(r) for r in conn.execute(q, params).fetchall()]

def create_agency_project(user_id, data):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO agency_projects (user_id, client_id, deal_id, name, status, service_type, deliverables, start_date, end_date, monthly_fee, videos_quota) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (user_id, data.get("client_id"), data.get("deal_id"), data.get("name",""), data.get("status","active"),
             data.get("service_type","content"), json.dumps(data.get("deliverables",[])), data.get("start_date",""),
             data.get("end_date",""), data.get("monthly_fee",0), data.get("videos_quota",10)))
        return cur.fetchone()["id"]

def update_agency_project(user_id, project_id, data):
    with get_conn() as conn:
        fields = []
        vals = []
        for k in ("client_id","name","status","service_type","start_date","end_date","monthly_fee","videos_quota","videos_used"):
            if k in data:
                fields.append(f"{k}=%s")
                vals.append(data[k])
        if "deliverables" in data:
            fields.append("deliverables=%s")
            vals.append(json.dumps(data["deliverables"]))
        if not fields:
            return
        vals.extend([user_id, project_id])
        conn.execute(f"UPDATE agency_projects SET {','.join(fields)} WHERE user_id=%s AND id=%s", vals)

def get_agency_revenue(user_id, client_id=None, period=None):
    with get_conn() as conn:
        q = "SELECT r.*, c.name as client_name FROM agency_revenue r LEFT JOIN agency_clients c ON r.client_id=c.id WHERE r.user_id=%s"
        params = [user_id]
        if client_id:
            q += " AND r.client_id=%s"
            params.append(client_id)
        if period:
            q += " AND r.period=%s"
            params.append(period)
        q += " ORDER BY r.created_at DESC"
        return [row_to_dict(r) for r in conn.execute(q, params).fetchall()]

def create_agency_revenue(user_id, data):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO agency_revenue (user_id, client_id, project_id, amount, type, description, period) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (user_id, data.get("client_id"), data.get("project_id"), data.get("amount",0),
             data.get("type","recurring"), data.get("description",""), data.get("period","")))

def get_agency_stats(user_id):
    with get_conn() as conn:
        clients_total = conn.execute("SELECT COUNT(*) AS cnt FROM agency_clients WHERE user_id=%s", (user_id,)).fetchone()["cnt"]
        clients_active = conn.execute("SELECT COUNT(*) AS cnt FROM agency_clients WHERE user_id=%s AND status='active'", (user_id,)).fetchone()["cnt"]
        leads = conn.execute("SELECT COUNT(*) AS cnt FROM agency_clients WHERE user_id=%s AND status='lead'", (user_id,)).fetchone()["cnt"]
        deals_open = conn.execute("SELECT COUNT(*) AS cnt FROM agency_deals WHERE user_id=%s AND stage NOT IN ('won','lost')", (user_id,)).fetchone()["cnt"]
        pipeline_value = conn.execute("SELECT COALESCE(SUM(value),0) AS val FROM agency_deals WHERE user_id=%s AND stage NOT IN ('won','lost')", (user_id,)).fetchone()["val"]
        deals_won = conn.execute("SELECT COALESCE(SUM(value),0) AS val FROM agency_deals WHERE user_id=%s AND stage='won'", (user_id,)).fetchone()["val"]
        mrr = conn.execute("SELECT COALESCE(SUM(monthly_fee),0) AS val FROM agency_projects WHERE user_id=%s AND status='active'", (user_id,)).fetchone()["val"]
        total_revenue = conn.execute("SELECT COALESCE(SUM(amount),0) AS val FROM agency_revenue WHERE user_id=%s", (user_id,)).fetchone()["val"]
        projects_active = conn.execute("SELECT COUNT(*) AS cnt FROM agency_projects WHERE user_id=%s AND status='active'", (user_id,)).fetchone()["cnt"]
        assets_total = conn.execute("SELECT COUNT(*) AS cnt FROM agency_assets WHERE user_id=%s", (user_id,)).fetchone()["cnt"]
        followups_pending = conn.execute("SELECT COUNT(*) AS cnt FROM agency_followups WHERE user_id=%s AND status='scheduled'", (user_id,)).fetchone()["cnt"]
        return {
            "clients_total": clients_total, "clients_active": clients_active, "leads": leads,
            "deals_open": deals_open, "pipeline_value": pipeline_value, "deals_won": deals_won,
            "mrr": mrr, "total_revenue": total_revenue, "projects_active": projects_active,
            "assets_total": assets_total, "followups_pending": followups_pending
        }


# ── Agency Assets ────────────────────────────────────────────────────────────

def _next_asset_number(conn, user_id):
    row = conn.execute("SELECT COUNT(*) AS cnt FROM agency_assets WHERE user_id=%s", (user_id,)).fetchone()
    seq = (row["cnt"] if row else 0) + 1
    return f"AST-{user_id:04d}-{seq:05d}"

def create_agency_asset(user_id, data):
    with get_conn() as conn:
        asset_num = _next_asset_number(conn, user_id)
        cur = conn.execute(
            "INSERT INTO agency_assets (user_id, asset_number, client_id, project_id, job_id, asset_type, title, file_path, thumbnail, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (user_id, asset_num, data.get("client_id"), data.get("project_id"), data.get("job_id"),
             data.get("asset_type","video"), data.get("title",""), data.get("file_path",""),
             data.get("thumbnail",""), data.get("status","draft")))
        return {"id": cur.fetchone()["id"], "asset_number": asset_num}

def get_agency_assets(user_id, client_id=None, project_id=None, status=None):
    with get_conn() as conn:
        q = "SELECT a.*, c.name as client_name, c.client_number, p.name as project_name FROM agency_assets a LEFT JOIN agency_clients c ON a.client_id=c.id LEFT JOIN agency_projects p ON a.project_id=p.id WHERE a.user_id=%s"
        params = [user_id]
        if client_id:
            q += " AND a.client_id=%s"
            params.append(client_id)
        if project_id:
            q += " AND a.project_id=%s"
            params.append(project_id)
        if status:
            q += " AND a.status=%s"
            params.append(status)
        q += " ORDER BY a.created_at DESC"
        return [row_to_dict(r) for r in conn.execute(q, params).fetchall()]

def update_agency_asset(user_id, asset_id, data):
    with get_conn() as conn:
        fields = []
        vals = []
        for k in ("client_id","project_id","status","title","feedback","delivered_at"):
            if k in data:
                fields.append(f"{k}=%s")
                vals.append(data[k])
        if not fields:
            return
        vals.extend([user_id, asset_id])
        conn.execute(f"UPDATE agency_assets SET {','.join(fields)} WHERE user_id=%s AND id=%s", vals)

def link_job_to_client(job_id, client_id, project_id=None):
    with get_conn() as conn:
        conn.execute("UPDATE jobs SET client_id=%s, project_id=%s WHERE id=%s", (client_id, project_id, job_id))


# ── Agency Follow-ups ────────────────────────────────────────────────────────

def create_agency_followup(user_id, data):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO agency_followups (user_id, client_id, deal_id, type, subject, body, status, scheduled_at, template) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (user_id, data.get("client_id"), data.get("deal_id"), data.get("type","email"),
             data.get("subject",""), data.get("body",""), data.get("status","scheduled"),
             data.get("scheduled_at",""), data.get("template","")))
        return cur.fetchone()["id"]

def get_agency_followups(user_id, client_id=None, status=None):
    with get_conn() as conn:
        q = "SELECT f.*, c.name as client_name, c.email as client_email FROM agency_followups f LEFT JOIN agency_clients c ON f.client_id=c.id WHERE f.user_id=%s"
        params = [user_id]
        if client_id:
            q += " AND f.client_id=%s"
            params.append(client_id)
        if status:
            q += " AND f.status=%s"
            params.append(status)
        q += " ORDER BY f.scheduled_at ASC"
        return [row_to_dict(r) for r in conn.execute(q, params).fetchall()]

def get_due_followups():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT f.*, c.name as client_name, c.email as client_email FROM agency_followups f LEFT JOIN agency_clients c ON f.client_id=c.id WHERE f.status='scheduled' AND f.scheduled_at <= NOW()::text"
        ).fetchall()
        return [row_to_dict(r) for r in rows]

def update_agency_followup(followup_id, data):
    with get_conn() as conn:
        fields = []
        vals = []
        for k in ("status","sent_at","opened_at","subject","body","scheduled_at"):
            if k in data:
                fields.append(f"{k}=%s")
                vals.append(data[k])
        if fields:
            vals.append(followup_id)
            conn.execute(f"UPDATE agency_followups SET {','.join(fields)} WHERE id=%s", vals)

def delete_agency_followup(user_id, followup_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM agency_followups WHERE user_id=%s AND id=%s", (user_id, followup_id))


# ── Agent operations ────────────────────────────────────────────────────────

def get_agents():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM agents ORDER BY team, codename").fetchall()
        return [dict(r) for r in rows]

def get_agent(agent_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM agents WHERE id=%s", (agent_id,)).fetchone()
        return dict(row) if row else None

def update_agent(agent_id, **kwargs):
    with get_conn() as conn:
        fields = []
        vals = []
        for k, v in kwargs.items():
            fields.append(f"{k}=%s")
            vals.append(v)
        if fields:
            vals.append(agent_id)
            conn.execute(f"UPDATE agents SET {','.join(fields)} WHERE id=%s", vals)

def add_agent_log(agent_id, event_type, message):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO agent_logs (agent_id, event_type, message) VALUES (%s,%s,%s)",
            (agent_id, event_type, message)
        )
        conn.execute(
            "UPDATE agents SET last_active=NOW() WHERE id=%s", (agent_id,)
        )
        if event_type == "task_completed":
            conn.execute("UPDATE agents SET tasks_completed = tasks_completed + 1 WHERE id=%s", (agent_id,))
        elif event_type == "error":
            conn.execute("UPDATE agents SET tasks_failed = tasks_failed + 1 WHERE id=%s", (agent_id,))

def get_agent_logs(agent_id=None, limit=30):
    with get_conn() as conn:
        if agent_id:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM agent_logs WHERE agent_id=%s ORDER BY created_at DESC LIMIT %s",
                (agent_id, limit)
            ).fetchall()]
        return [dict(r) for r in conn.execute(
            "SELECT * FROM agent_logs ORDER BY created_at DESC LIMIT %s", (limit,)
        ).fetchall()]

def get_agent_stats():
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS cnt FROM agents").fetchone()["cnt"]
        online = conn.execute("SELECT COUNT(*) AS cnt FROM agents WHERE status='online'").fetchone()["cnt"]
        done = conn.execute("SELECT COALESCE(SUM(tasks_completed),0) AS val FROM agents").fetchone()["val"]
        failed = conn.execute("SELECT COALESCE(SUM(tasks_failed),0) AS val FROM agents").fetchone()["val"]
        return {
            "total_agents": total, "online": online, "offline": total - online,
            "tasks_completed": done, "tasks_failed": failed,
        }


# ── Personas ──────────────────────────────────────────────────────────────────

def get_personas(user_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM personas WHERE user_id=%s ORDER BY created_at DESC", (user_id,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def create_persona(user_id: int, name: str, gender: str = "", age_range: str = "",
                   appearance_desc: str = "", niche: str = "", avatar_style: str = "",
                   voice_id: str = "", personality: str = "", speaking_style: str = "",
                   model_preference: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO personas (user_id, name, gender, age_range, appearance_desc, niche,
                                  avatar_style, voice_id, personality, speaking_style, model_preference)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """, (user_id, name, gender, age_range, appearance_desc, niche,
              avatar_style, voice_id, personality, speaking_style, model_preference))
        return cur.fetchone()["id"]


def update_persona(persona_id: int, user_id: int, **kwargs):
    if not kwargs:
        return
    cols = ", ".join(f"{k}=%s" for k in kwargs)
    vals = list(kwargs.values()) + [persona_id, user_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE personas SET {cols} WHERE id=%s AND user_id=%s", vals)


def delete_persona(persona_id: int, user_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM personas WHERE id=%s AND user_id=%s", (persona_id, user_id))
