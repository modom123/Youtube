"""
Nova Chen — Chief Product Officer
==================================
Tracks studio usage patterns, feature adoption, content output health,
and what's actually working in the product. Flags underused features,
surfaces power-user behaviors to replicate, and keeps the product
roadmap aligned with what drives retention and revenue.

Runs every 12 hours. Reports to the executive bus.
"""
import threading
import json
import os
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import database as db
from agents import executive_bus as bus

AGENT_NAME = "nova_chen"
CHECK_INTERVAL = 43200  # 12 hours

_thread = None
_stop = threading.Event()

PERSONA = {
    "name": "Nova Chen",
    "title": "Chief Product Officer",
    "dept": "Product",
    "core_directive": (
        "Monitor studio usage, feature adoption, and content output quality. "
        "Identify what's working, what's dead weight, and what the product needs "
        "to hit the next growth milestone on the business plan."
    ),
    "behavioral_profile": (
        "Data-driven, user-empathetic, and ruthlessly focused on activation and "
        "retention loops. Speaks in DAU/MAU ratios, feature adoption curves, and "
        "jobs-to-be-done frameworks."
    ),
    "expertise": [
        "Feature adoption and engagement analytics",
        "Studio usage pattern analysis",
        "Product-market fit signals",
        "Content output quality monitoring",
        "Roadmap prioritization against business plan",
        "Power-user behavior identification",
    ],
    "color": "#8b5cf6",
    "icon": "🧠",
}

# Studios / features to track by job format
STUDIO_MAP = {
    "youtube":    "The Forge",
    "commercial": "Ad Lab",
    "hollywood":  "Cinema House",
    "music":      "Hit Factory",
    "podcast":    "Podcast Studio",
    "batch":      "Forge Batch",
    "quickpost":  "Quick Post",
    "clip":       "The Scalpel",
}


def _studio_usage(days=7):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT format, COUNT(*) AS cnt, COUNT(DISTINCT user_id) AS unique_users
               FROM jobs WHERE created_at >= %s GROUP BY format ORDER BY cnt DESC""",
            (cutoff,)
        ).fetchall()
    return [dict(r) for r in rows]


def _activation_rate():
    """% of users who created at least 1 job within 7 days of signup."""
    with db.get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        activated = conn.execute("""
            SELECT COUNT(DISTINCT u.id) AS c FROM users u
            WHERE EXISTS (
                SELECT 1 FROM jobs j WHERE j.user_id = u.id
                AND j.created_at <= u.created_at + INTERVAL '7 days'
            )
        """).fetchone()["c"]
    return (activated / total * 100) if total > 0 else 0, activated, total


def _power_users(days=30, threshold=10):
    """Users who created 10+ jobs in the last 30 days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT u.id, u.email, u.subscription_tier, COUNT(j.id) AS job_count
               FROM users u JOIN jobs j ON j.user_id = u.id
               WHERE j.created_at >= %s
               GROUP BY u.id, u.email, u.subscription_tier
               HAVING COUNT(j.id) >= %s
               ORDER BY job_count DESC LIMIT 20""",
            (cutoff, threshold)
        ).fetchall()
    return [dict(r) for r in rows]


def _dead_studios(days=14):
    """Studios with zero usage in the last 14 days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with db.get_conn() as conn:
        active = {r["format"] for r in conn.execute(
            "SELECT DISTINCT format FROM jobs WHERE created_at >= %s", (cutoff,)
        ).fetchall()}
    return [s for fmt, s in STUDIO_MAP.items() if fmt not in active]


def _output_quality():
    """Check job failure rate over last 7 days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT status, COUNT(*) AS cnt FROM jobs
               WHERE created_at >= %s GROUP BY status""",
            (cutoff,)
        ).fetchall()
    counts = {r["status"]: int(r["cnt"]) for r in rows}
    total = sum(counts.values())
    failed = counts.get("failed", 0) + counts.get("error", 0)
    success = counts.get("done", 0) + counts.get("completed", 0)
    fail_rate = (failed / total * 100) if total > 0 else 0
    return fail_rate, failed, total, success


def _check_adoption():
    usage = _studio_usage(days=7)
    if not usage:
        bus.log_msg(AGENT_NAME, "No studio usage in last 7 days — product engagement is zero", "error")
        return

    total_jobs = sum(u["cnt"] for u in usage)
    top = usage[0]
    bus.log_msg(AGENT_NAME,
        f"Studio usage (7d): {total_jobs} total jobs — top: {STUDIO_MAP.get(top['format'], top['format'])} "
        f"({top['cnt']} jobs, {top['unique_users']} users)")

    # Flag dominant studio — single studio >70% of all usage
    if top["cnt"] / total_jobs > 0.70:
        bus.log_msg(AGENT_NAME,
            f"⚠️  {STUDIO_MAP.get(top['format'], top['format'])} accounts for "
            f"{top['cnt']/total_jobs*100:.0f}% of all usage — other studios need activation push",
            "warning")

    bus.publish(AGENT_NAME, "studio_usage", {
        "total_jobs": total_jobs,
        "breakdown": [{**u, "studio": STUDIO_MAP.get(u["format"], u["format"])} for u in usage],
    })


def _check_activation():
    rate, activated, total = _activation_rate()
    severity = "error" if rate < 30 else "warning" if rate < 50 else "info"
    bus.log_msg(AGENT_NAME,
        f"Activation rate: {rate:.1f}% ({activated}/{total} users created content within 7 days of signup)",
        severity)
    if rate < 40:
        bus.log_msg(AGENT_NAME,
            "🚨  Activation below 40% — onboarding funnel needs immediate attention. "
            "Recommend: in-app first-video prompt, email sequence, credit incentive.",
            "warning")
    bus.publish(AGENT_NAME, "activation_rate", {"rate": round(rate, 1), "activated": activated, "total": total})


def _check_power_users():
    powers = _power_users()
    if powers:
        free_powers = [u for u in powers if u["subscription_tier"] == "free"]
        bus.log_msg(AGENT_NAME,
            f"Power users (30d, 10+ jobs): {len(powers)} found — {len(free_powers)} still on free tier")
        for u in free_powers[:3]:
            bus.log_msg(AGENT_NAME,
                f"💎  Power user on free: {u['email']} ({u['job_count']} jobs) — prime upgrade candidate",
                "warning")
            bus.publish(AGENT_NAME, "power_user_free", {"user_id": u["id"], "email": u["email"], "job_count": u["job_count"]})


def _check_dead_studios():
    dead = _dead_studios(days=14)
    if dead:
        bus.log_msg(AGENT_NAME,
            f"🪦  Dead studios (0 usage in 14d): {', '.join(dead)} — consider onboarding campaigns or feature spotlight",
            "warning")


def _check_quality():
    fail_rate, failed, total, success = _output_quality()
    severity = "error" if fail_rate > 20 else "warning" if fail_rate > 10 else "info"
    bus.log_msg(AGENT_NAME,
        f"Job quality (7d): {total} jobs — {success} succeeded, {failed} failed ({fail_rate:.1f}% fail rate)",
        severity)
    if fail_rate > 15:
        bus.log_msg(AGENT_NAME,
            f"🔴  High failure rate {fail_rate:.1f}% — users are hitting errors. Investigate job processor.",
            "error")
    bus.publish(AGENT_NAME, "output_quality", {"fail_rate": round(fail_rate, 1), "total": total, "failed": failed})


def _check_plan_alignment():
    """Compare product output velocity against business plan targets."""
    try:
        plan = bus.get_plan_targets()
        if not plan:
            return
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM jobs WHERE created_at >= NOW() - INTERVAL '7 days'"
            ).fetchone()
        weekly_jobs = int(row["c"]) if row else 0
        bus.log_msg(AGENT_NAME,
            f"Plan alignment: Phase '{plan.get('phase','?')}' W{plan.get('week','?')} — "
            f"{weekly_jobs} content jobs created this week. "
            f"Target: {plan.get('target_users','?')} users @ ${plan.get('target_mrr',0):,.0f} MRR")
    except Exception:
        pass


def _run_cycle():
    bus.log_msg(AGENT_NAME, "Nova Chen (CPO) — running product health audit")
    try:
        _check_adoption()
        _check_activation()
        _check_power_users()
        _check_dead_studios()
        _check_quality()
        _check_plan_alignment()
        bus.log_msg(AGENT_NAME, "Product audit complete")
    except Exception as exc:
        bus.log_msg(AGENT_NAME, f"Error during product audit: {exc}", "error")


def chat(user_message: str) -> str:
    try:
        import anthropic as _ant
        client = _ant.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    except Exception:
        return "Anthropic SDK not available."

    usage = _studio_usage(days=30)
    fail_rate, failed, total, success = _output_quality()
    act_rate, activated, user_total = _activation_rate()

    context = f"""You are Nova Chen, Chief Product Officer at Social Optimize.

LIVE PRODUCT DATA (last 30 days):
Studio Usage: {json.dumps([{**u, 'studio': STUDIO_MAP.get(u['format'], u['format'])} for u in usage], indent=2)}
Job Quality: {total} total jobs, {success} succeeded, {failed} failed ({fail_rate:.1f}% fail rate)
Activation Rate: {act_rate:.1f}% of users created content within 7 days of signup
Dead Studios (14d): {', '.join(_dead_studios()) or 'None'}
Power Users (30d, 10+ jobs): {len(_power_users())} identified

Answer product questions with specific data. Be direct and actionable."""

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
    _thread = threading.Thread(target=_loop, daemon=True, name="nova_product")
    _thread.start()
    bus.log_msg(AGENT_NAME, "Nova Chen (CPO) online — product health monitoring active")


def stop():
    _stop.set()
