"""SQLite database layer for the Social Optimize Machine dashboard."""
import sqlite3
import json
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "som_data.db"


def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS social_accounts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
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
            topic       TEXT NOT NULL,
            format      TEXT NOT NULL,
            platforms   TEXT DEFAULT '[]',
            audience    TEXT DEFAULT 'general public',
            voice       TEXT,
            style       TEXT DEFAULT 'fire',
            privacy     TEXT DEFAULT 'private',
            status      TEXT DEFAULT 'pending',
            progress    INTEGER DEFAULT 0,
            current_step TEXT DEFAULT '',
            title       TEXT,
            duration    REAL DEFAULT 0,
            video_path  TEXT,
            audio_path  TEXT,
            thumbnail_path TEXT,
            script_path TEXT,
            manifest_path TEXT,
            publish_results TEXT DEFAULT '{}',
            error_msg   TEXT,
            created_at  TEXT DEFAULT (datetime('now')),
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        """)


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


# ── Social Accounts ──────────────────────────────────────────────────────────

def get_accounts():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM social_accounts ORDER BY platform").fetchall()
    return [row_to_dict(r) for r in rows]


def upsert_account(platform, username, display_name=None, avatar_url=None,
                   access_token=None, refresh_token=None, account_id=None, followers=0):
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM social_accounts WHERE platform=? AND username=?",
            (platform, username)
        ).fetchone()
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
                 account_id, followers)
                VALUES (?,?,?,?,?,?,?,?)
            """, (platform, username, display_name, avatar_url, access_token,
                  refresh_token, account_id, followers))
            return cur.lastrowid


def delete_account(account_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM social_accounts WHERE id=?", (account_id,))


# ── Contacts ─────────────────────────────────────────────────────────────────

def get_contacts(platform=None, search=None, limit=100, offset=0):
    query = "SELECT * FROM contacts WHERE 1=1"
    params = []
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


def count_contacts(platform=None):
    query = "SELECT COUNT(*) as n FROM contacts"
    params = []
    if platform:
        query += " WHERE platform=?"
        params.append(platform)
    with get_conn() as conn:
        return conn.execute(query, params).fetchone()["n"]


def insert_contacts_bulk(contacts: list[dict]):
    with get_conn() as conn:
        conn.executemany("""
            INSERT OR IGNORE INTO contacts (name, handle, email, phone, platform, avatar_url, followers, tags)
            VALUES (:name, :handle, :email, :phone, :platform, :avatar_url, :followers, :tags)
        """, contacts)
    return len(contacts)


def delete_contacts(platform=None):
    with get_conn() as conn:
        if platform:
            conn.execute("DELETE FROM contacts WHERE platform=?", (platform,))
        else:
            conn.execute("DELETE FROM contacts")


# ── Jobs ─────────────────────────────────────────────────────────────────────

def create_job(topic, format, platforms, audience, voice, style, privacy):
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO jobs (topic, format, platforms, audience, voice, style, privacy)
            VALUES (?,?,?,?,?,?,?)
        """, (topic, format, json.dumps(platforms), audience, voice, style, privacy))
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


def get_job(job_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return row_to_dict(row)


def get_jobs(limit=50):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def get_stats():
    with get_conn() as conn:
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
