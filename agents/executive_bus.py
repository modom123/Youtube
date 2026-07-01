"""
Executive Agent State & Action Bus
====================================
Inter-agent communication system for the C-suite AI workforce.
Agents post events, other agents subscribe and react.

Event flow:
  Elena (Enterprise) → Marcus (Growth) → Julian (Retention) → Sterling (Business)
  Each agent can also broadcast alerts that any other agent picks up.
"""
import json
import threading
from datetime import datetime, timezone
from collections import defaultdict

import database as db

_lock = threading.Lock()
_subscribers = defaultdict(list)  # event_type -> [callback]


def _now():
    return datetime.now(timezone.utc).isoformat()


def init_bus_tables():
    with db.get_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS exec_agent_events (
            id          SERIAL PRIMARY KEY,
            agent_name  TEXT NOT NULL,
            event_type  TEXT NOT NULL,
            payload     TEXT DEFAULT '{}',
            processed   INTEGER DEFAULT 0,
            created_at  TIMESTAMP DEFAULT NOW()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS exec_agent_actions (
            id          SERIAL PRIMARY KEY,
            agent_name  TEXT NOT NULL,
            action_type TEXT NOT NULL,
            target_user INTEGER,
            details     TEXT DEFAULT '{}',
            result      TEXT DEFAULT '',
            status      TEXT DEFAULT 'pending',
            created_at  TIMESTAMP DEFAULT NOW(),
            completed_at TIMESTAMP
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS exec_agent_log (
            id          SERIAL PRIMARY KEY,
            agent_name  TEXT NOT NULL,
            severity    TEXT DEFAULT 'info',
            message     TEXT NOT NULL,
            created_at  TIMESTAMP DEFAULT NOW()
        )
        """)


def publish(agent_name: str, event_type: str, payload: dict = None):
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO exec_agent_events (agent_name, event_type, payload) VALUES (%s,%s,%s)",
            (agent_name, event_type, json.dumps(payload or {})))
    with _lock:
        for cb in _subscribers.get(event_type, []):
            try:
                cb(agent_name, payload or {})
            except Exception:
                pass


def subscribe(event_type: str, callback):
    with _lock:
        _subscribers[event_type].append(callback)


def log_action(agent_name: str, action_type: str, target_user: int = None,
               details: dict = None, result: str = "", status: str = "completed"):
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO exec_agent_actions (agent_name, action_type, target_user, details, result, status, completed_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (agent_name, action_type, target_user, json.dumps(details or {}), result, status, _now()))


def log_msg(agent_name: str, message: str, severity: str = "info"):
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO exec_agent_log (agent_name, severity, message) VALUES (%s,%s,%s)",
            (agent_name, severity, message))


def get_recent_events(limit=50):
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM exec_agent_events ORDER BY created_at DESC LIMIT %s", (limit,)).fetchall()
        return [db.row_to_dict(r) for r in rows]


def get_recent_actions(agent_name=None, limit=50):
    with db.get_conn() as conn:
        if agent_name:
            rows = conn.execute(
                "SELECT * FROM exec_agent_actions WHERE agent_name=%s ORDER BY created_at DESC LIMIT %s",
                (agent_name, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM exec_agent_actions ORDER BY created_at DESC LIMIT %s", (limit,)).fetchall()
        return [db.row_to_dict(r) for r in rows]


def get_agent_log(agent_name=None, limit=100):
    with db.get_conn() as conn:
        if agent_name:
            rows = conn.execute(
                "SELECT * FROM exec_agent_log WHERE agent_name=%s ORDER BY created_at DESC LIMIT %s",
                (agent_name, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM exec_agent_log ORDER BY created_at DESC LIMIT %s", (limit,)).fetchall()
        return [db.row_to_dict(r) for r in rows]


_ALL_AGENTS = (
    "marcus_vance", "elena_rostova", "julian_vance", "sterling_croft",
    "vivian_cross", "nova_chen", "rex_dawson", "aria_singh",
    "isabella_cruz", "sterling_pierce",
)


def get_agent_stats():
    with db.get_conn() as conn:
        agents = {}
        for name in _ALL_AGENTS:
            actions = conn.execute(
                "SELECT COUNT(*) AS c FROM exec_agent_actions WHERE agent_name=%s", (name,)).fetchone()["c"]
            today_actions = conn.execute(
                "SELECT COUNT(*) AS c FROM exec_agent_actions WHERE agent_name=%s AND created_at::date = CURRENT_DATE",
                (name,)).fetchone()["c"]
            events = conn.execute(
                "SELECT COUNT(*) AS c FROM exec_agent_events WHERE agent_name=%s", (name,)).fetchone()["c"]
            agents[name] = {"actions_total": actions, "actions_today": today_actions, "events": events}
        return agents


def get_plan_targets():
    """Get current business plan milestone targets for agent guidance."""
    try:
        with db.get_conn() as conn:
            current = conn.execute(
                "SELECT * FROM business_plan_milestones WHERE status != 'completed' ORDER BY week_number LIMIT 3"
            ).fetchall()
            if not current:
                return None
            milestones = [dict(r) for r in current]
            return {
                "current_focus": milestones[0]["focus"],
                "current_deliverables": milestones[0]["deliverables"],
                "target_users": milestones[0]["target_users"],
                "target_mrr": milestones[0]["target_mrr"],
                "phase": milestones[0]["phase_name"],
                "week": milestones[0]["week_number"],
                "upcoming": [{"week": m["week_number"], "focus": m["focus"]} for m in milestones[1:]],
            }
    except Exception:
        return None
