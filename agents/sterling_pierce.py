"""
Sterling Pierce — Chief Revenue Recovery Officer
=================================================
Owns the money that's already been earned but not collected.
Monitors failed payments, retries Stripe charges, applies dunning logic,
and signals Isabella Cruz to fire the right email for each outcome.

Recovery pipeline:
  Rex Dawson detects failed payments →
  Sterling Pierce retries via Stripe API →
  Publishes recovery_attempted (success/fail) →
  Isabella Cruz fires confirmation or dunning email

Also runs its own sweep every 8 hours independently of Rex's events.

Requires env var: STRIPE_SECRET_KEY
Falls back to graceful logging if Stripe SDK not available.
"""
import threading
import json
import os
import time
from datetime import datetime, timezone, timedelta

import database as db
import config
from agents import executive_bus as bus

AGENT_NAME = "sterling_pierce"
CHECK_INTERVAL = 28800  # 8 hours

_thread = None
_stop = threading.Event()

PERSONA = {
    "name": "Sterling Pierce",
    "title": "Chief Revenue Recovery Officer",
    "dept": "Revenue Operations",
    "core_directive": (
        "Recover every dollar of revenue that's already been earned but not collected. "
        "Retry failed payments, apply smart dunning, prevent involuntary churn. "
        "Every recovered payment is pure margin — no CAC, no effort."
    ),
    "behavioral_profile": (
        "Relentless but tactful. Knows the difference between a card expiry and a dispute. "
        "Escalates the right way at the right time. Works the Stripe dunning ladder."
    ),
    "expertise": [
        "Stripe payment retry and dunning automation",
        "Failed payment root cause analysis",
        "Involuntary churn prevention",
        "Revenue recovery waterfall (retry → email → discount → pause)",
        "Subscription grace period management",
    ],
    "color": "#0ea5e9",
    "icon": "💳",
}

RETRY_COOLDOWN_HOURS = 24   # don't retry same invoice more than once per day
MAX_AUTO_RETRIES = 3        # after 3 failures, escalate to email-only


def _stripe_client():
    key = os.getenv("STRIPE_SECRET_KEY", "")
    if not key:
        return None
    try:
        import stripe
        stripe.api_key = key
        return stripe
    except ImportError:
        return None


def _get_failed_users():
    """Users with active subscriptions in a failed/past_due payment state."""
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT u.id, u.email, u.name, u.subscription_tier,
                      u.subscription_status, u.stripe_customer_id
               FROM users u
               WHERE u.subscription_status IN ('past_due', 'failed', 'unpaid')
               AND u.subscription_tier NOT IN ('free', '')
               AND u.subscription_tier IS NOT NULL
               ORDER BY u.id""",
        ).fetchall()
    return [dict(r) for r in rows]


def _retry_cooldown_key(user_id: int) -> str:
    return f"sterling_pierce:retry:{user_id}"


def _retry_count_key(user_id: int) -> str:
    return f"sterling_pierce:retry_count:{user_id}"


def _is_on_cooldown(user_id: int) -> bool:
    val = db.get_setting(_retry_cooldown_key(user_id))
    if not val:
        return False
    try:
        last = datetime.fromisoformat(val.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - last).total_seconds() < RETRY_COOLDOWN_HOURS * 3600
    except Exception:
        return False


def _get_retry_count(user_id: int) -> int:
    val = db.get_setting(_retry_count_key(user_id))
    try:
        return int(val or 0)
    except Exception:
        return 0


def _increment_retry_count(user_id: int) -> int:
    count = _get_retry_count(user_id) + 1
    db.set_setting(_retry_count_key(user_id), str(count))
    db.set_setting(_retry_cooldown_key(user_id), datetime.now(timezone.utc).isoformat())
    return count


def _reset_retry_count(user_id: int):
    db.set_setting(_retry_count_key(user_id), "0")


def _attempt_stripe_retry(user: dict) -> dict:
    """
    Attempt to retry the latest unpaid/open invoice for a Stripe customer.
    Returns dict: {success, invoice_id, amount, attempts, error}
    """
    stripe = _stripe_client()
    customer_id = user.get("stripe_customer_id")

    if not stripe:
        return {"success": False, "error": "Stripe SDK not available — set STRIPE_SECRET_KEY", "attempts": 0}

    if not customer_id:
        return {"success": False, "error": "No Stripe customer ID on record", "attempts": 0}

    try:
        # Find the latest open invoice
        invoices = stripe.Invoice.list(
            customer=customer_id,
            status="open",
            limit=1,
        )
        if not invoices.data:
            return {"success": False, "error": "No open invoices found", "attempts": 0}

        invoice = invoices.data[0]
        attempts = invoice.get("attempt_count", 0)

        if attempts >= MAX_AUTO_RETRIES:
            return {
                "success": False,
                "error": f"Max retries ({MAX_AUTO_RETRIES}) reached — escalating to email",
                "attempts": attempts,
                "invoice_id": invoice.id,
            }

        # Retry the payment
        retried = stripe.Invoice.pay(invoice.id)
        success = retried.get("status") == "paid"
        return {
            "success": success,
            "invoice_id": invoice.id,
            "amount": invoice.get("amount_due", 0) / 100,
            "attempts": attempts + 1,
            "currency": invoice.get("currency", "usd"),
        }

    except Exception as exc:
        err = str(exc)
        # Stripe card errors are expected — extract the message cleanly
        if hasattr(exc, "user_message"):
            err = exc.user_message
        return {"success": False, "error": err, "attempts": 0}


def _process_failed_user(user: dict):
    uid = user["id"]
    email = user.get("email", "")
    tier = user.get("subscription_tier", "")

    if _is_on_cooldown(uid):
        return

    retry_count = _get_retry_count(uid)
    result = _attempt_stripe_retry(user)
    new_count = _increment_retry_count(uid)

    success = result.get("success", False)
    amount = result.get("amount", 0)
    error = result.get("error", "")
    invoice_id = result.get("invoice_id", "")

    if success:
        _reset_retry_count(uid)
        bus.log_msg(AGENT_NAME,
            f"💳 RECOVERED ${amount:.2f} from {email} (invoice {invoice_id})")
        bus.log_action(AGENT_NAME, "payment_recovered", uid,
                       {"email": email, "amount": amount, "invoice_id": invoice_id, "tier": tier},
                       f"Recovered ${amount:.2f}")
        # Signal Isabella to send confirmation email
        bus.publish(AGENT_NAME, "recovery_attempted", {
            "user_id": uid, "email": email, "name": user.get("name", ""),
            "tier": tier, "success": True, "amount": amount, "attempts": new_count,
        })
    else:
        level = "error" if new_count >= MAX_AUTO_RETRIES else "warning"
        bus.log_msg(AGENT_NAME,
            f"💳 FAILED retry #{new_count} for {email}: {error}", level)
        bus.log_action(AGENT_NAME, "payment_retry_failed", uid,
                       {"email": email, "error": error, "attempt": new_count, "tier": tier},
                       f"Retry #{new_count} failed: {error}")
        # Signal Isabella to send dunning email
        bus.publish(AGENT_NAME, "recovery_attempted", {
            "user_id": uid, "email": email, "name": user.get("name", ""),
            "tier": tier, "success": False, "attempts": new_count, "error": error,
        })


def _handle_failed_payments_event(sender: str, payload: dict):
    """Rex published a failed_payments event — act immediately."""
    users_data = payload.get("users", [])
    if not users_data:
        return
    bus.log_msg(AGENT_NAME,
        f"💳 Rex flagged {len(users_data)} failed payments — initiating recovery")
    for u in users_data:
        try:
            # Fetch full user record for stripe_customer_id
            with db.get_conn() as conn:
                row = conn.execute(
                    "SELECT id, email, name, subscription_tier, subscription_status, stripe_customer_id FROM users WHERE id=%s",
                    (u.get("id") or u.get("user_id"),)
                ).fetchone()
            if row:
                _process_failed_user(dict(row))
        except Exception as exc:
            bus.log_msg(AGENT_NAME, f"Error processing {u}: {exc}", "error")


def _run_cycle():
    bus.log_msg(AGENT_NAME, "Sterling Pierce (Revenue Recovery) — running payment sweep")
    try:
        failed = _get_failed_users()
        if not failed:
            bus.log_msg(AGENT_NAME, "✅ No failed payments — all subscriptions current")
            return

        stripe = _stripe_client()
        mode = "LIVE (Stripe)" if stripe else "DRY RUN (no Stripe key)"
        bus.log_msg(AGENT_NAME,
            f"💳 {len(failed)} failed payments found — attempting recovery [{mode}]",
            "warning")

        recovered = 0
        for user in failed:
            try:
                uid = user["id"]
                if _is_on_cooldown(uid):
                    continue
                _process_failed_user(user)
                recovered += 1
                time.sleep(0.5)  # gentle rate limiting
            except Exception as exc:
                bus.log_msg(AGENT_NAME, f"Error on user {user.get('email')}: {exc}", "error")

        bus.log_msg(AGENT_NAME, f"💳 Recovery sweep complete — processed {recovered}/{len(failed)} accounts")
        bus.publish(AGENT_NAME, "recovery_sweep_complete", {
            "total_failed": len(failed),
            "processed": recovered,
        })

    except Exception as exc:
        bus.log_msg(AGENT_NAME, f"Sweep error: {exc}", "error")


def chat(user_message: str) -> str:
    try:
        import anthropic as _ant
        client = _ant.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    except Exception:
        return "Anthropic SDK not available."

    stripe_ok = bool(os.getenv("STRIPE_SECRET_KEY"))
    failed = []
    try:
        failed = _get_failed_users()
    except Exception:
        pass

    context = f"""You are Sterling Pierce, Chief Revenue Recovery Officer at Social Optimize.

LIVE STATUS:
Stripe connected: {stripe_ok}
Failed payment accounts: {len(failed)}
Max auto-retries before email escalation: {MAX_AUTO_RETRIES}
Retry cooldown: {RETRY_COOLDOWN_HOURS} hours

Recovery pipeline:
  Rex Dawson (RevOps) detects → Sterling Pierce retries Stripe → Isabella Cruz emails

Answer questions about payment recovery, dunning strategy, and involuntary churn prevention."""

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
    bus.subscribe("failed_payments", _handle_failed_payments_event)

    # Run immediately on start, then every 8 hours
    _run_cycle()
    while not _stop.is_set():
        _stop.wait(CHECK_INTERVAL)
        if not _stop.is_set():
            _run_cycle()


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="sterling_pierce")
    _thread.start()
    bus.log_msg(AGENT_NAME, "Sterling Pierce (Revenue Recovery) online — payment recovery active")
