"""
Aria Singh — Director of Customer Success
==========================================
Owns the post-signup experience. Monitors activation (did the user
create their first piece of content?), onboarding completion, first-video
milestones, and health scores. Fires welcome sequences, celebrates wins,
and flags users who signed up but never did anything.

Directly tied to business plan weekly targets — tracks activated users
vs plan cohort goals and fires escalations when behind.

Runs every 6 hours. Reports to the executive bus.
"""
import threading
import json
import os
from datetime import datetime, timezone, timedelta

import database as db
from agents import executive_bus as bus

AGENT_NAME = "aria_singh"
CHECK_INTERVAL = 21600  # 6 hours

_thread = None
_stop = threading.Event()

PERSONA = {
    "name": "Aria Singh",
    "title": "Director of Customer Success",
    "dept": "Customer Success",
    "core_directive": (
        "Ensure every user who signs up creates their first piece of content within 48 hours. "
        "Track activation, onboarding completion, and first-milestone achievement. "
        "Flag users who ghost and re-engage them before they churn. "
        "Keep activation rate above 60% — that's the number that feeds every downstream metric."
    ),
    "behavioral_profile": (
        "Warm but analytically sharp. Empathetic to user friction. "
        "Speaks in activation rates, time-to-first-value, health scores, and NPS proxies."
    ),
    "expertise": [
        "User activation and onboarding optimization",
        "Time-to-first-value (TTFV) reduction",
        "Customer health scoring",
        "First-milestone tracking (first video, first publish)",
        "Re-engagement sequences for dormant users",
        "Business plan cohort tracking",
    ],
    "color": "#ec4899",
    "icon": "🌟",
}

# Health score weights
HEALTH_WEIGHTS = {
    "has_social_account": 20,
    "created_first_job":  30,
    "published_content":  25,
    "active_last_7d":     15,
    "on_paid_tier":       10,
}


def _get_new_users(hours=48):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, email, name, subscription_tier, created_at FROM users WHERE created_at >= %s ORDER BY created_at DESC",
            (cutoff,)
        ).fetchall()
    return [dict(r) for r in rows]


def _get_unactivated_users(signup_window_hours=48, check_window_hours=72):
    """Users who signed up 48-72h ago but have never created a job."""
    lower = (datetime.now(timezone.utc) - timedelta(hours=check_window_hours)).isoformat()
    upper = (datetime.now(timezone.utc) - timedelta(hours=signup_window_hours)).isoformat()
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT u.id, u.email, u.name, u.subscription_tier, u.created_at
               FROM users u
               WHERE u.created_at BETWEEN %s AND %s
               AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.user_id = u.id)
               ORDER BY u.created_at DESC""",
            (lower, upper)
        ).fetchall()
    return [dict(r) for r in rows]


def _get_first_job_time(user_id):
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT MIN(created_at) AS first FROM jobs WHERE user_id=%s", (user_id,)
        ).fetchone()
    return row["first"] if row else None


def _has_published(user_id):
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM scheduled_posts WHERE user_id=%s AND status='published'",
            (user_id,)
        ).fetchone()
    return int(row["c"]) > 0 if row else False


def _active_last_7d(user_id):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM jobs WHERE user_id=%s AND created_at >= %s", (user_id, cutoff)
        ).fetchone()
    return int(row["c"]) > 0 if row else False


def _health_score(user: dict) -> int:
    score = 0
    uid = user["id"]
    if _get_first_job_time(uid):
        score += HEALTH_WEIGHTS["created_first_job"]
    if _has_published(uid):
        score += HEALTH_WEIGHTS["published_content"]
    if _active_last_7d(uid):
        score += HEALTH_WEIGHTS["active_last_7d"]
    if user.get("subscription_tier") not in ("free", None, ""):
        score += HEALTH_WEIGHTS["on_paid_tier"]
    # Social account check
    try:
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM social_accounts WHERE user_id=%s", (uid,)
            ).fetchone()
        if row and int(row["c"]) > 0:
            score += HEALTH_WEIGHTS["has_social_account"]
    except Exception:
        pass
    return score


def _cohort_vs_plan():
    """Compare new signups this week against business plan target."""
    try:
        plan = bus.get_plan_targets()
        if not plan:
            return
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM users WHERE created_at >= %s", (cutoff,)
            ).fetchone()
        new_users = int(row["c"]) if row else 0
        target_users = plan.get("target_users", 0)

        # Estimate weekly signup needed to hit target
        # Simple: if target total users = X and we have Y, need (X-Y) more
        with db.get_conn() as conn:
            total_row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        total_users = int(total_row["c"]) if total_row else 0
        users_needed = max(0, target_users - total_users)

        severity = "error" if new_users < 1 else "warning" if users_needed > new_users * 10 else "info"
        bus.log_msg(AGENT_NAME,
            f"Plan cohort: {new_users} new signups this week | "
            f"Total: {total_users} users | Plan target: {target_users} | "
            f"Need {users_needed} more to hit phase goal — "
            f"Phase '{plan.get('phase','?')}' W{plan.get('week','?')}",
            severity)
        bus.publish(AGENT_NAME, "cohort_vs_plan", {
            "new_this_week": new_users,
            "total_users": total_users,
            "plan_target": target_users,
            "users_needed": users_needed,
        })
    except Exception:
        pass


def _check_new_signups():
    new = _get_new_users(hours=48)
    if not new:
        bus.log_msg(AGENT_NAME, "No new signups in last 48 hours")
        return
    bus.log_msg(AGENT_NAME, f"🌟  {len(new)} new signups in last 48h — monitoring for activation")
    bus.publish(AGENT_NAME, "new_signups", {"count": len(new), "users": [u["email"] for u in new[:10]]})


def _check_unactivated():
    ghosts = _get_unactivated_users()
    if not ghosts:
        bus.log_msg(AGENT_NAME, "✅  All users from 48-72h window have activated")
        return
    bus.log_msg(AGENT_NAME,
        f"👻  {len(ghosts)} users signed up 48-72h ago and never created content — re-engagement needed",
        "warning")
    for u in ghosts[:5]:
        bus.log_msg(AGENT_NAME,
            f"  ↳ {u['email']} ({u['subscription_tier'] or 'free'}) — signed up {str(u['created_at'])[:10]}, no jobs",
            "warning")
    bus.publish(AGENT_NAME, "unactivated_users", {
        "count": len(ghosts),
        "users": [{"id": u["id"], "email": u["email"], "tier": u["subscription_tier"]} for u in ghosts[:10]]
    })


def _check_at_risk_paying():
    """Paying users who haven't been active in 14+ days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT u.id, u.email, u.subscription_tier,
                      MAX(j.created_at) AS last_job
               FROM users u LEFT JOIN jobs j ON j.user_id = u.id
               WHERE u.subscription_tier != 'free'
               AND u.subscription_status = 'active'
               GROUP BY u.id, u.email, u.subscription_tier
               HAVING MAX(j.created_at) < %s OR MAX(j.created_at) IS NULL
               ORDER BY last_job ASC NULLS FIRST LIMIT 20""",
            (cutoff,)
        ).fetchall()
    at_risk = [dict(r) for r in rows]
    if at_risk:
        bus.log_msg(AGENT_NAME,
            f"⚠️  {len(at_risk)} paying users inactive 14+ days — churn risk, flagging for retention",
            "warning")
        bus.publish(AGENT_NAME, "paying_at_risk", {
            "count": len(at_risk),
            "users": [{"id": u["id"], "email": u["email"], "tier": u["subscription_tier"]} for u in at_risk]
        })
        # Tell Julian (retention agent) about each at-risk user
        for u in at_risk[:5]:
            bus.publish(AGENT_NAME, "churn_risk_referral", {"user_id": u["id"], "email": u["email"], "source": "aria_cs"})
    else:
        bus.log_msg(AGENT_NAME, "✅  All paying users active within 14 days")


def _check_first_milestone():
    """Celebrate users who created their first video today."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0).isoformat()
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT DISTINCT j.user_id, u.email, u.name, MIN(j.created_at) AS first_job
               FROM jobs j JOIN users u ON u.id = j.user_id
               WHERE j.created_at >= %s
               GROUP BY j.user_id, u.email, u.name
               HAVING MIN(j.created_at) >= %s""",
            (today_start, today_start)
        ).fetchall()
    first_timers = [dict(r) for r in rows]
    if first_timers:
        bus.log_msg(AGENT_NAME,
            f"🎉  {len(first_timers)} users created their FIRST piece of content today!")
        bus.publish(AGENT_NAME, "first_milestone", {
            "count": len(first_timers),
            "users": [u["email"] for u in first_timers[:10]]
        })


def _run_cycle():
    bus.log_msg(AGENT_NAME, "Aria Singh (CS) — running customer success audit")
    try:
        _check_new_signups()
        _check_unactivated()
        _check_at_risk_paying()
        _check_first_milestone()
        _cohort_vs_plan()
        bus.log_msg(AGENT_NAME, "Customer success audit complete")
    except Exception as exc:
        bus.log_msg(AGENT_NAME, f"Error during CS audit: {exc}", "error")


def chat(user_message: str) -> str:
    try:
        import anthropic as _ant
        client = _ant.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    except Exception:
        return "Anthropic SDK not available."

    ghosts = _get_unactivated_users()
    new = _get_new_users(hours=48)

    context = f"""You are Aria Singh, Director of Customer Success at Social Optimize.

LIVE CS DATA:
New signups (48h): {len(new)}
Unactivated users (signed up 48-72h ago, no content): {len(ghosts)}
Ghost emails: {[u['email'] for u in ghosts[:5]]}

Health Score Weights: {json.dumps(HEALTH_WEIGHTS)}

Answer customer success questions. Focus on activation, onboarding, and retention."""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=context,
            messages=[{"role": "user", "content": user_message}],
        )
        return resp.content[0].text
    except Exception as exc:
        return f"Error: {exc}"


def _loop():
    while not _stop.is_set():
        _run_cycle()
        _stop.wait(CHECK_INTERVAL)


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="aria_success")
    _thread.start()
    bus.log_msg(AGENT_NAME, "Aria Singh (CS) online — customer success monitoring active")


def stop():
    _stop.set()
