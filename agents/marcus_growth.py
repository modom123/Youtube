"""
Marcus "Metrics" Vance — Chief Growth Officer & PLG Architect
=============================================================
Ex-Head of Growth at Slack and Airtable. Engineers friction-free onboarding,
viral loops, and product-led acquisition funnels to hit $10M ARR.

Runs every 10 minutes. Analyzes user behavior, triggers upgrade nudges,
designs referral mechanics, optimizes conversion funnels.
"""
import threading
import json
from datetime import datetime, timezone, timedelta

import database as db
import config
from agents import executive_bus as bus

AGENT_NAME = "marcus_vance"
CHECK_INTERVAL = 50400  # 14 hours

_thread = None
_stop = threading.Event()

PERSONA = {
    "name": "Marcus Vance",
    "title": "Chief Growth Officer",
    "core_directive": "Engineer friction-free onboarding, viral loops, and product-led acquisition funnels to hit a $10M ARR run rate.",
    "behavioral_profile": "Hyper-analytical, growth-obsessed, and ruthlessly conversion-focused. Speaks in cohort retention, activation velocity, and K-factors.",
    "expertise": [
        "Product-Led Growth (PLG) architecture",
        "Viral coefficient (K-factor) optimization",
        "Dynamic pricing and paywall triggers",
        "A/B testing and behavior-driven user flows"
    ],
}


def _get_all_users():
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, email, name, subscription_tier, subscription_status, created_at FROM users"
        ).fetchall()
        return [db.row_to_dict(r) for r in rows]


def _get_user_video_count(user_id, days=7):
    with db.get_conn() as conn:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE user_id=? AND created_at>=?",
            (user_id, cutoff)).fetchone()[0]


def _get_user_total_videos(user_id):
    with db.get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE user_id=? AND status='done'",
            (user_id,)).fetchone()[0]


def _check_upgrade_triggers():
    """If a free user creates 3+ videos but hasn't upgraded, flag for nudge."""
    users = _get_all_users()
    for user in users:
        if user.get("subscription_tier") not in (None, "", "free"):
            continue
        total = _get_user_total_videos(user["id"])
        if total >= 3:
            already = db.get_setting(f"growth:upgrade_nudge:{user['id']}")
            if already:
                continue
            bus.log_action(AGENT_NAME, "upgrade_nudge_triggered", user["id"],
                           {"total_videos": total, "tier": "free"},
                           f"User {user['email']} hit {total} videos on free tier — upgrade nudge queued")
            bus.publish(AGENT_NAME, "upgrade_nudge", {"user_id": user["id"], "email": user.get("email"), "videos": total})
            db.set_setting(f"growth:upgrade_nudge:{user['id']}", datetime.now(timezone.utc).isoformat())
            _send_upgrade_nudge(user, total)


def _send_upgrade_nudge(user, video_count):
    """Send contextual upgrade email."""
    email = user.get("email")
    if not email:
        return
    subject = f"You've created {video_count} videos — unlock unlimited with Starter"
    body = f"""Hi {(user.get('name') or 'Creator').split()[0]},

You've been on fire — {video_count} videos created! You're getting close to the free tier limit.

Upgrade to Starter ($29.99/mo) and unlock:
- 15 AI videos/month (vs 3 on free)
- Publish to 8 platforms (vs 3 on free)
- The Forge, Ad Lab & Hit Factory
- 150 Social Optimize Credits
- 14-day free trial — no charge today

Start your free trial: {config.APP_BASE_URL}/pricing

Keep creating,
The Social Optimize Team"""

    _queue_email(user["id"], email, subject, body)


def _check_referral_opportunities():
    """Identify power users who could drive referrals."""
    users = _get_all_users()
    for user in users:
        total = _get_user_total_videos(user["id"])
        if total >= 10:
            already = db.get_setting(f"growth:referral_ask:{user['id']}")
            if already:
                continue
            bus.log_action(AGENT_NAME, "referral_opportunity", user["id"],
                           {"total_videos": total},
                           f"Power user {user.get('email')} — {total} videos, referral candidate")
            db.set_setting(f"growth:referral_ask:{user['id']}", datetime.now(timezone.utc).isoformat())


def _compute_growth_metrics():
    """Compute and publish growth KPIs."""
    with db.get_conn() as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        new_this_week = conn.execute("SELECT COUNT(*) FROM users WHERE created_at>=?", (week_ago,)).fetchone()[0]
        paying = conn.execute("SELECT COUNT(*) FROM users WHERE subscription_tier NOT IN ('free','') AND subscription_tier IS NOT NULL").fetchone()[0]
        free = total_users - paying
        conversion_rate = (paying / total_users * 100) if total_users > 0 else 0
        videos_this_week = conn.execute("SELECT COUNT(*) FROM jobs WHERE created_at>=? AND status='done'", (week_ago,)).fetchone()[0]

    metrics = {
        "total_users": total_users, "new_this_week": new_this_week,
        "paying": paying, "free": free,
        "conversion_rate": round(conversion_rate, 2),
        "videos_this_week": videos_this_week,
        "date": today
    }
    bus.publish(AGENT_NAME, "growth_metrics", metrics)
    bus.log_msg(AGENT_NAME, f"Growth: {total_users} users ({paying} paying, {conversion_rate:.1f}% conv), {new_this_week} new this week, {videos_this_week} videos")
    return metrics


def _queue_email(user_id, email, subject, body):
    """Queue a follow-up email via the agency followup system."""
    try:
        db.create_agency_followup(user_id, {
            "client_id": None, "type": "email",
            "subject": subject, "body": body,
            "scheduled_at": datetime.now(timezone.utc).isoformat(),
            "template": "growth_nudge"
        })
    except Exception:
        pass


def _handle_retention_alert(sender, payload):
    """Julian flagged a churn risk — Marcus adjusts engagement."""
    user_id = payload.get("user_id")
    if not user_id:
        return
    bus.log_action(AGENT_NAME, "retention_re_engage", user_id,
                   payload, "Received churn alert from Julian, queuing re-engagement")
    bus.log_msg(AGENT_NAME, f"Re-engaging user {user_id} after retention alert")


def _run():
    bus.subscribe("churn_risk", _handle_retention_alert)
    bus.subscribe("free_tier_surge", lambda s, p: bus.log_msg(AGENT_NAME, f"Free tier surge detected — {p.get('count')} new free users"))

    while not _stop.wait(CHECK_INTERVAL):
        try:
            plan = bus.get_plan_targets()
            if plan:
                bus.log_msg(AGENT_NAME,
                    f"Plan target: {plan['target_users']} users by W{plan['week']} — "
                    f"Focus: {plan['current_focus']}")
            _compute_growth_metrics()
            _check_upgrade_triggers()
            _check_referral_opportunities()
        except Exception as e:
            bus.log_msg(AGENT_NAME, f"Error: {e}", "error")


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_run, daemon=True, name="marcus-growth")
    _thread.start()
    bus.log_msg(AGENT_NAME, "Marcus Vance (CGO) online — growth engine active")
    print("[Marcus Vance] CGO online — PLG engine running every 10 min")
