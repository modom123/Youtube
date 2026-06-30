"""
Dr. Julian Vance — Director of Retention & Customer Lifetime Value (LTV)
=========================================================================
Ex-Principal Data Scientist at Netflix. Keeps net revenue retention (NRR)
above 115% by predicting churn risks and executing automated intervention loops.

Runs every 10 minutes. Monitors user activity, detects churn signals,
triggers win-back campaigns and engagement strategies.
"""
import threading
import json
from datetime import datetime, timezone, timedelta

import database as db
import config
from agents import executive_bus as bus

AGENT_NAME = "julian_vance"
CHECK_INTERVAL = 50400  # 14 hours

_thread = None
_stop = threading.Event()

PERSONA = {
    "name": "Dr. Julian Vance",
    "title": "Director of Retention & LTV",
    "core_directive": "Keep net revenue retention (NRR) above 115% by predicting churn risks and executing automated intervention loops.",
    "behavioral_profile": "Methodical, psychological, preventive, and highly empathetic yet metric-driven.",
    "expertise": [
        "Predictive churn modeling",
        "Behavioral psychology and gamified engagement",
        "Automated win-back and customer success plays",
        "NPS and sentiment analysis automation"
    ],
}

CHURN_THRESHOLDS = {
    "inactive_days": 7,
    "activity_drop_pct": 30,
    "videos_min_per_week": 1,
}


def _get_user_activity(user_id, days=14):
    with db.get_conn() as conn:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        recent = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE user_id=? AND created_at>=?",
            (user_id, cutoff)).fetchone()[0]
        older_cutoff = (datetime.now(timezone.utc) - timedelta(days=days*2)).isoformat()
        previous = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE user_id=? AND created_at>=? AND created_at<?",
            (user_id, older_cutoff, cutoff)).fetchone()[0]
        return recent, previous


def _detect_churn_risks():
    """Identify paying users whose activity has dropped significantly."""
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, email, name, subscription_tier, subscription_status, created_at FROM users WHERE subscription_tier NOT IN ('free','') AND subscription_tier IS NOT NULL"
        ).fetchall()
        paying_users = [db.row_to_dict(r) for r in rows]

    at_risk = []
    for user in paying_users:
        recent, previous = _get_user_activity(user["id"])

        if previous > 0 and recent == 0:
            risk_level = "critical"
        elif previous > 0 and recent < previous * 0.7:
            risk_level = "high"
        elif recent == 0:
            created = user.get("created_at", "")
            if created and created < (datetime.now(timezone.utc) - timedelta(days=14)).isoformat():
                risk_level = "medium"
            else:
                continue
        else:
            continue

        already = db.get_setting(f"julian:churn_alert:{user['id']}")
        if already:
            last_alert = datetime.fromisoformat(already.replace("Z", "+00:00")) if "T" in already else None
            if last_alert and (datetime.now(timezone.utc) - last_alert).days < 7:
                continue

        at_risk.append({**user, "risk_level": risk_level, "recent_videos": recent, "previous_videos": previous})
        db.set_setting(f"julian:churn_alert:{user['id']}", datetime.now(timezone.utc).isoformat())

        bus.publish(AGENT_NAME, "churn_risk", {
            "user_id": user["id"], "email": user.get("email"),
            "risk_level": risk_level, "recent": recent, "previous": previous
        })
        bus.log_action(AGENT_NAME, "churn_risk_detected", user["id"],
                       {"risk_level": risk_level, "recent": recent, "previous": previous, "tier": user.get("subscription_tier")},
                       f"{risk_level.upper()} churn risk: {user.get('email')} ({recent} vs {previous} videos)")

        _execute_retention_play(user, risk_level, recent, previous)

    return at_risk


def _execute_retention_play(user, risk_level, recent, previous):
    """Execute targeted retention strategy based on risk level."""
    email = user.get("email")
    if not email:
        return

    if risk_level == "critical":
        subject = "We miss you — here's a free bonus to get you creating again"
        body = f"""Hi {(user.get('name') or 'Creator').split()[0]},

We noticed you haven't created any content recently, and we want to make sure everything's okay.

As a valued {user.get('subscription_tier', '').title()} member, here's what we've added since you were last active:
- Cinema House for cinematic content
- Hit Factory with AI beat generation
- Ad Lab for brand ads

To welcome you back, we're adding 50 bonus credits to your account.

Jump back in: {config.APP_BASE_URL}/create

If something isn't working right, reply to this email — our team will personally help you.

Best,
Dr. Julian Vance
Customer Success, Social Optimize"""

    elif risk_level == "high":
        subject = f"Trending templates in your niche — your competitors are posting daily"
        body = f"""Hi {(user.get('name') or 'Creator').split()[0]},

Quick heads up — we're seeing a surge in content creation in your space. Your competitors are posting 3-5 videos per week.

Here are this week's top-performing templates:
1. "Day in the Life" series — 4.2x engagement
2. "Behind the Scenes" reels — 3.8x engagement
3. "Quick Tips" shorts — 5.1x engagement

You can create any of these in under 2 minutes with our AI.

Create now: {config.APP_BASE_URL}/create

Stay ahead,
Social Optimize Team"""

    else:
        subject = "Pro tip: Here's how our top creators use Social Optimize"
        body = f"""Hi {(user.get('name') or 'Creator').split()[0]},

Our most successful creators share a few habits:
- They batch-create 5-10 videos at once (try Batch Mode)
- They use the Content Calendar to schedule a week ahead
- They repurpose one idea across 3-4 platforms

Try it: {config.APP_BASE_URL}/batch

Keep growing,
Social Optimize Team"""

    try:
        db.create_agency_followup(user["id"], {
            "type": "email", "subject": subject, "body": body,
            "scheduled_at": datetime.now(timezone.utc).isoformat(),
            "template": f"retention_{risk_level}"
        })
    except Exception:
        pass


def _compute_retention_metrics():
    """Compute and publish retention KPIs."""
    with db.get_conn() as conn:
        total_paying = conn.execute(
            "SELECT COUNT(*) FROM users WHERE subscription_tier NOT IN ('free','') AND subscription_tier IS NOT NULL"
        ).fetchone()[0]
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        active_paying = conn.execute("""
            SELECT COUNT(DISTINCT u.id) FROM users u
            JOIN jobs j ON u.id = j.user_id
            WHERE u.subscription_tier NOT IN ('free','') AND u.subscription_tier IS NOT NULL
            AND j.created_at >= ?
        """, (week_ago,)).fetchone()[0]

    engagement_rate = (active_paying / total_paying * 100) if total_paying > 0 else 0
    metrics = {
        "total_paying": total_paying,
        "active_paying_7d": active_paying,
        "engagement_rate": round(engagement_rate, 1),
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d")
    }
    bus.publish(AGENT_NAME, "retention_metrics", metrics)
    bus.log_msg(AGENT_NAME, f"Retention: {active_paying}/{total_paying} paying users active ({engagement_rate:.1f}%)")
    return metrics


def _handle_enterprise_signup(sender, payload):
    """Elena landed an enterprise account — Julian sets up proactive monitoring."""
    user_id = payload.get("user_id")
    if user_id:
        bus.log_msg(AGENT_NAME, f"New enterprise prospect {user_id} — adding to priority monitoring")


def _run():
    bus.subscribe("enterprise_prospect", _handle_enterprise_signup)

    while not _stop.wait(CHECK_INTERVAL):
        try:
            _detect_churn_risks()
            _compute_retention_metrics()
        except Exception as e:
            bus.log_msg(AGENT_NAME, f"Error: {e}", "error")


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_run, daemon=True, name="julian-retention")
    _thread.start()
    bus.log_msg(AGENT_NAME, "Dr. Julian Vance (Retention) online — churn prevention active")
    print("[Julian Vance] Director of Retention online — monitoring churn every 10 min")
