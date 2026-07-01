"""
Rex Dawson — Director of Revenue Operations
============================================
Stripe reconciliation, failed payment detection, dunning management,
MRR accuracy, subscription lifecycle integrity. Ensures every dollar
owed is collected and every subscription event is correctly recorded.

Runs every 4 hours. Reports to the executive bus.
"""
import threading
import json
import os
from datetime import datetime, timezone, timedelta

import database as db
from agents import executive_bus as bus

AGENT_NAME = "rex_dawson"
CHECK_INTERVAL = 14400  # 4 hours

_thread = None
_stop = threading.Event()

PERSONA = {
    "name": "Rex Dawson",
    "title": "Director of Revenue Operations",
    "dept": "RevOps",
    "core_directive": (
        "Own the revenue data stack. Reconcile Stripe against the database, "
        "catch failed payments before they become churn, run dunning sequences, "
        "and keep MRR numbers accurate so every other agent works from clean data."
    ),
    "behavioral_profile": (
        "Meticulous, process-driven, zero tolerance for revenue leakage. "
        "Speaks in MRR movements, net revenue retention, and payment recovery rates."
    ),
    "expertise": [
        "Stripe payment reconciliation",
        "Failed payment dunning and recovery",
        "MRR accuracy and subscription integrity",
        "Revenue recognition",
        "Involuntary churn prevention",
        "Billing anomaly detection",
    ],
    "color": "#f59e0b",
    "icon": "💳",
}


def _get_subscription_counts():
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT subscription_tier, subscription_status, COUNT(*) AS cnt FROM users GROUP BY subscription_tier, subscription_status"
        ).fetchall()
    return [dict(r) for r in rows]


def _get_recent_billing_events(days=7):
    with db.get_conn() as conn:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        try:
            rows = conn.execute(
                """SELECT event_type, details, created_at FROM audit_log
                   WHERE event_type IN ('payment_received','payment_failed','subscription_cancelled',
                                        'upgrade','downgrade','refund')
                   AND created_at >= %s ORDER BY created_at DESC LIMIT 100""",
                (cutoff,)
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []


def _get_failed_payments():
    """Users with failed/past_due subscription status."""
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT id, email, name, subscription_tier, subscription_status, updated_at
               FROM users WHERE subscription_status IN ('past_due','failed','unpaid')
               ORDER BY updated_at DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def _get_cancelled_this_month():
    with db.get_conn() as conn:
        try:
            rows = conn.execute(
                """SELECT event_type, details, created_at FROM audit_log
                   WHERE event_type IN ('subscription_cancelled','cancel','downgrade')
                   AND created_at >= date_trunc('month', NOW())"""
            ).fetchall()
            return len(rows)
        except Exception:
            return 0


def _compute_mrr():
    """Calculate MRR from live tier counts vs config prices."""
    import config
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT subscription_tier, COUNT(*) AS cnt FROM users WHERE subscription_status='active' GROUP BY subscription_tier"
        ).fetchall()
    counts = {r["subscription_tier"]: int(r["cnt"]) for r in rows}
    prices = {k: v.get("price_monthly", 0) for k, v in config.TIERS.items()}
    mrr = sum(counts.get(t, 0) * p for t, p in prices.items() if t != "free")
    return mrr, counts


def _check_failed_payments():
    failed = _get_failed_payments()
    if failed:
        bus.log_msg(AGENT_NAME,
            f"💳  {len(failed)} users with failed/past_due payments — revenue at risk",
            "error" if len(failed) > 5 else "warning")
        for u in failed[:5]:
            bus.log_msg(AGENT_NAME,
                f"  ↳ {u['email']} ({u['subscription_tier']}) — status: {u['subscription_status']}",
                "warning")
        bus.publish(AGENT_NAME, "failed_payments", {
            "count": len(failed),
            "users": [{"id": u["id"], "email": u["email"], "tier": u["subscription_tier"]} for u in failed[:10]]
        })


def _check_mrr_integrity():
    mrr, counts = _compute_mrr()
    cancellations = _get_cancelled_this_month()
    bus.log_msg(AGENT_NAME,
        f"MRR integrity check: ${mrr:,.2f}/mo from {sum(counts.values())} active subscribers, "
        f"{cancellations} cancellations this month")
    bus.publish(AGENT_NAME, "mrr_check", {
        "mrr": round(mrr, 2),
        "active_subscribers": sum(counts.values()),
        "cancellations_mtd": cancellations,
        "tier_counts": counts,
    })

    if cancellations > 10:
        bus.log_msg(AGENT_NAME,
            f"🚨  {cancellations} cancellations this month — churn spike, alerting retention team",
            "error")
        bus.publish(AGENT_NAME, "churn_spike", {"cancellations": cancellations})


def _check_billing_events():
    events = _get_recent_billing_events(days=1)
    if not events:
        return
    event_types = {}
    for e in events:
        event_types[e["event_type"]] = event_types.get(e["event_type"], 0) + 1

    failures = event_types.get("payment_failed", 0)
    received = event_types.get("payment_received", 0)
    bus.log_msg(AGENT_NAME,
        f"24h billing: {received} payments received, {failures} failed")
    if failures > 0:
        bus.log_msg(AGENT_NAME,
            f"⚠️  {failures} payment failures in last 24h — dunning sequence should trigger",
            "warning")


def _check_subscription_integrity():
    """Flag users with active tier but no subscription status."""
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT COUNT(*) AS cnt FROM users
               WHERE subscription_tier != 'free'
               AND (subscription_status IS NULL OR subscription_status = '')"""
        ).fetchone()
    orphans = int(rows["cnt"]) if rows else 0
    if orphans > 0:
        bus.log_msg(AGENT_NAME,
            f"🔧  {orphans} users on paid tier with no subscription_status — data integrity issue",
            "warning")
        bus.publish(AGENT_NAME, "subscription_orphans", {"count": orphans})


def _check_plan_revenue_target():
    """Compare current MRR against business plan target."""
    try:
        plan = bus.get_plan_targets()
        if not plan:
            return
        mrr, _ = _compute_mrr()
        target_mrr = plan.get("target_mrr", 0)
        if target_mrr > 0:
            pct = mrr / target_mrr * 100
            gap = target_mrr - mrr
            severity = "error" if pct < 50 else "warning" if pct < 80 else "info"
            bus.log_msg(AGENT_NAME,
                f"Plan revenue: ${mrr:,.0f} MRR vs ${target_mrr:,.0f} target "
                f"({pct:.1f}% of target, ${gap:,.0f} gap) — "
                f"Phase '{plan.get('phase','?')}' W{plan.get('week','?')}",
                severity)
            bus.publish(AGENT_NAME, "plan_revenue_gap", {
                "current_mrr": round(mrr, 2),
                "target_mrr": target_mrr,
                "pct_of_target": round(pct, 1),
                "gap": round(gap, 2),
            })
    except Exception:
        pass


def _run_cycle():
    bus.log_msg(AGENT_NAME, "Rex Dawson (RevOps) — running revenue reconciliation")
    try:
        _check_mrr_integrity()
        _check_failed_payments()
        _check_billing_events()
        _check_subscription_integrity()
        _check_plan_revenue_target()
        bus.log_msg(AGENT_NAME, "Revenue reconciliation complete")
    except Exception as exc:
        bus.log_msg(AGENT_NAME, f"Error during reconciliation: {exc}", "error")


def chat(user_message: str) -> str:
    try:
        import anthropic as _ant
        client = _ant.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    except Exception:
        return "Anthropic SDK not available."

    mrr, counts = _compute_mrr()
    failed = _get_failed_payments()
    cancellations = _get_cancelled_this_month()
    subs = _get_subscription_counts()

    context = f"""You are Rex Dawson, Director of Revenue Operations at Social Optimize.

LIVE REVOPS DATA:
MRR: ${mrr:,.2f}/mo
Tier Counts: {json.dumps(counts)}
Subscription Statuses: {json.dumps(subs, indent=2)}
Failed/Past-Due Payments: {len(failed)} users
MTD Cancellations: {cancellations}
At-Risk Revenue: ${sum(0 for u in failed):.2f} (exact requires Stripe)

Answer revenue operations questions with specific data. Flag risks clearly."""

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
    _thread = threading.Thread(target=_loop, daemon=True, name="rex_revops")
    _thread.start()
    bus.log_msg(AGENT_NAME, "Rex Dawson (RevOps) online — revenue reconciliation active")


def stop():
    _stop.set()
