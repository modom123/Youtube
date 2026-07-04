"""
Isabella Cruz — Director of Email Automation & Lifecycle Marketing
==================================================================
Closes the loop that every other agent opens. When Julian flags churn risk,
Aria flags unactivated users, or Sterling Pierce completes a recovery attempt,
Isabella fires the actual transactional email via Resend.

Email types fired:
  - churn_risk (critical/high/medium) → win-back sequence
  - unactivated_users → 'you signed up but never started' nudge
  - paying_at_risk → 'we notice you've gone quiet' + personal offer
  - recovery_success → 'payment recovered, you're all set'
  - recovery_failed → 'action needed on your account'
  - first_milestone → celebration email

Throttle: max one email per user per 3 days per category.
Requires env var: RESEND_API_KEY (gracefully degrades to log-only if absent).

Runs every 2 hours to drain the event queue. Also subscribes to the live bus.
"""
import threading
import json
import os
import time
from datetime import datetime, timezone, timedelta

import database as db
import config
from agents import executive_bus as bus

AGENT_NAME = "isabella_cruz"
CHECK_INTERVAL = 7200  # 2 hours

_thread = None
_stop = threading.Event()

PERSONA = {
    "name": "Isabella Cruz",
    "title": "Director of Email Automation",
    "dept": "Growth & Lifecycle",
    "core_directive": (
        "Convert signals from every other agent into real emails that move users to action. "
        "When Julian detects churn, send the win-back. When Aria flags a ghost, send the nudge. "
        "When Sterling recovers a payment, confirm it. Close every loop."
    ),
    "behavioral_profile": (
        "Warm, human-sounding copy. Never spammy. Every email has one call to action. "
        "Obsessed with open rates and click-throughs. Respects the 3-day throttle."
    ),
    "expertise": [
        "Lifecycle email automation",
        "Transactional email via Resend",
        "Win-back and re-engagement sequences",
        "Payment recovery dunning emails",
        "First-milestone celebration emails",
        "Email throttle and suppression management",
    ],
    "color": "#f43f5e",
    "icon": "✉️",
}

THROTTLE_DAYS = 3  # don't email same user+category more than once per N days

_RESEND_API = "https://api.resend.com/emails"
_FROM_EMAIL = os.getenv("FROM_EMAIL", "hello@socialoptimize.online")
_FROM_NAME = os.getenv("FROM_NAME", "Social Optimize")


def _resend_key():
    return os.getenv("RESEND_API_KEY", "")


def _throttle_key(user_id: int, category: str) -> str:
    return f"isabella:throttle:{user_id}:{category}"


def _is_throttled(user_id: int, category: str) -> bool:
    val = db.get_setting(_throttle_key(user_id, category))
    if not val:
        return False
    try:
        sent_at = datetime.fromisoformat(val.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - sent_at).days < THROTTLE_DAYS
    except Exception:
        return False


def _mark_sent(user_id: int, category: str):
    db.set_setting(_throttle_key(user_id, category), datetime.now(timezone.utc).isoformat())


def _send_email(to_email: str, to_name: str, subject: str, html_body: str) -> bool:
    """Send via Resend API. Returns True on success."""
    api_key = _resend_key()
    if not api_key:
        bus.log_msg(AGENT_NAME,
            f"[DRY RUN] Would send '{subject}' to {to_email} (set RESEND_API_KEY to enable)",
            "warning")
        return False

    try:
        import urllib.request
        payload = json.dumps({
            "from": f"{_FROM_NAME} <{_FROM_EMAIL}>",
            "to": [to_email],
            "subject": subject,
            "html": html_body,
        }).encode()
        req = urllib.request.Request(
            _RESEND_API,
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 201)
    except Exception as exc:
        bus.log_msg(AGENT_NAME, f"Email send error to {to_email}: {exc}", "error")
        return False


def _first_name(full_name: str) -> str:
    if not full_name:
        return "Creator"
    return full_name.strip().split()[0]


# ── Email templates ──────────────────────────────────────────────────────────

def _email_churn_critical(user: dict) -> tuple[str, str]:
    name = _first_name(user.get("name", ""))
    subject = f"We miss you, {name} — 50 bonus credits inside"
    html = f"""
<p>Hi {name},</p>
<p>We noticed you haven't created any content recently and wanted to check in.</p>
<p>As a valued {(user.get('subscription_tier') or 'Pro').title()} member, your account is still active and ready to go.
We've added <strong>50 bonus credits</strong> to your wallet as a welcome-back gift.</p>
<p>Here's what's new since you were last in:</p>
<ul>
  <li>🎬 Cinema House — cinematic video in one click</li>
  <li>🎵 Hit Factory — AI beats for your content</li>
  <li>📢 Ad Lab — brand-ready ad creatives</li>
</ul>
<p><a href="{config.APP_BASE_URL}/create" style="background:#7c3aed;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;display:inline-block;">Jump Back In →</a></p>
<p>If something isn't working, just reply — we'll fix it personally.</p>
<p>— The Social Optimize Team</p>
"""
    return subject, html


def _email_churn_high(user: dict) -> tuple[str, str]:
    name = _first_name(user.get("name", ""))
    subject = "Your competitors are posting daily — here's how to catch up"
    html = f"""
<p>Hi {name},</p>
<p>Quick heads up — content creators in your space are publishing 3–5 videos per week right now.</p>
<p>Popular formats worth trying:</p>
<ol>
  <li>"Day in the Life" series</li>
  <li>"Behind the Scenes" reels</li>
  <li>"Quick Tips" shorts</li>
</ol>
<p>You can create any of these in under 2 minutes with Social Optimize.</p>
<p><a href="{config.APP_BASE_URL}/create" style="background:#7c3aed;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;display:inline-block;">Create Now →</a></p>
<p>— Social Optimize Team</p>
"""
    return subject, html


def _email_churn_medium(user: dict) -> tuple[str, str]:
    name = _first_name(user.get("name", ""))
    subject = "Pro tip: how our top creators batch content in 30 minutes"
    html = f"""
<p>Hi {name},</p>
<p>Our most successful creators use one habit that changed everything: <strong>batch creation</strong>.</p>
<p>Instead of creating one video at a time, they spend 30 minutes creating 5–10 at once using our Batch Mode,
then schedule them across the week.</p>
<p><a href="{config.APP_BASE_URL}/batch" style="background:#7c3aed;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;display:inline-block;">Try Batch Mode →</a></p>
<p>Keep growing,<br>Social Optimize Team</p>
"""
    return subject, html


def _email_unactivated(user: dict) -> tuple[str, str]:
    name = _first_name(user.get("name", ""))
    subject = f"{name}, you're one video away from your first win"
    html = f"""
<p>Hi {name},</p>
<p>You signed up for Social Optimize a couple of days ago — and we want to make sure you actually get value from it.</p>
<p>Your first video takes <strong>under 90 seconds</strong> to create. Here's the fastest path:</p>
<ol>
  <li>Go to <a href="{config.APP_BASE_URL}/create">Create</a></li>
  <li>Pick any studio (Viral Shorts is a great start)</li>
  <li>Type your topic and hit Generate</li>
</ol>
<p>That's it. Your first piece of content will be ready to post.</p>
<p><a href="{config.APP_BASE_URL}/create" style="background:#7c3aed;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;display:inline-block;">Create Your First Video →</a></p>
<p>Questions? Just reply to this email.</p>
<p>— Isabella Cruz<br>Customer Success, Social Optimize</p>
"""
    return subject, html


def _email_recovery_success(user: dict) -> tuple[str, str]:
    name = _first_name(user.get("name", ""))
    subject = "Payment confirmed — you're all set ✓"
    html = f"""
<p>Hi {name},</p>
<p>Good news — we've successfully processed your payment and your {(user.get('subscription_tier') or '').title()} subscription is fully active.</p>
<p>No action needed on your end. Keep creating!</p>
<p><a href="{config.APP_BASE_URL}/create" style="background:#10b981;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;display:inline-block;">Go to Dashboard →</a></p>
<p>— Social Optimize Team</p>
"""
    return subject, html


def _email_recovery_failed(user: dict, attempts: int = 1) -> tuple[str, str]:
    name = _first_name(user.get("name", ""))
    subject = "Action needed: update your payment method"
    html = f"""
<p>Hi {name},</p>
<p>We weren't able to process your recent payment after {attempts} attempt{'s' if attempts > 1 else ''}.
Your account is currently paused.</p>
<p>To keep your subscription active and avoid losing your content, please update your payment method:</p>
<p><a href="{config.APP_BASE_URL}/billing" style="background:#ef4444;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;display:inline-block;">Update Payment Method →</a></p>
<p>If you have any questions or need help, reply to this email and we'll sort it out immediately.</p>
<p>— Social Optimize Team</p>
"""
    return subject, html


# ── Bus event handlers ───────────────────────────────────────────────────────

def _handle_churn_risk(sender: str, payload: dict):
    user_id = payload.get("user_id")
    email = payload.get("email")
    risk = payload.get("risk_level", "medium")
    if not email or not user_id:
        return
    cat = f"churn_{risk}"
    if _is_throttled(user_id, cat):
        return
    user = {"id": user_id, "email": email, "name": payload.get("name", ""), "subscription_tier": payload.get("tier", "")}
    if risk == "critical":
        try:
            db.add_credits(user_id, 50, "retention_bonus", "Win-back bonus credits")
        except Exception:
            pass
        subject, html = _email_churn_critical(user)
    elif risk == "high":
        subject, html = _email_churn_high(user)
    else:
        subject, html = _email_churn_medium(user)
    sent = _send_email(email, user.get("name", ""), subject, html)
    _mark_sent(user_id, cat)
    status = "sent" if sent else "logged"
    bus.log_msg(AGENT_NAME, f"✉️  {status.upper()} churn-{risk} email → {email}")
    bus.log_action(AGENT_NAME, "email_churn_winback", user_id,
                   {"risk": risk, "email": email, "status": status}, subject)


def _handle_churn_referral(sender: str, payload: dict):
    """Aria refers a churn risk — same handler as Julian's churn_risk."""
    payload.setdefault("risk_level", "high")
    _handle_churn_risk(sender, payload)


def _handle_unactivated(sender: str, payload: dict):
    users = payload.get("users", [])
    for u in users[:20]:
        user_id = u.get("id")
        email = u.get("email")
        if not email or not user_id:
            continue
        if _is_throttled(user_id, "unactivated"):
            continue
        full_user = {**u, "name": u.get("name", "")}
        subject, html = _email_unactivated(full_user)
        sent = _send_email(email, full_user.get("name", ""), subject, html)
        _mark_sent(user_id, "unactivated")
        status = "sent" if sent else "logged"
        bus.log_msg(AGENT_NAME, f"✉️  {status.upper()} activation nudge → {email}")
        bus.log_action(AGENT_NAME, "email_activation_nudge", user_id,
                       {"email": email, "status": status}, subject)


def _handle_recovery_result(sender: str, payload: dict):
    user_id = payload.get("user_id")
    email = payload.get("email")
    success = payload.get("success", False)
    attempts = payload.get("attempts", 1)
    if not email or not user_id:
        return
    cat = "recovery_success" if success else "recovery_failed"
    if _is_throttled(user_id, cat):
        return
    user = {"id": user_id, "email": email, "name": payload.get("name", ""), "subscription_tier": payload.get("tier", "")}
    if success:
        subject, html = _email_recovery_success(user)
    else:
        subject, html = _email_recovery_failed(user, attempts)
    sent = _send_email(email, user.get("name", ""), subject, html)
    _mark_sent(user_id, cat)
    status = "sent" if sent else "logged"
    bus.log_msg(AGENT_NAME, f"✉️  {status.upper()} recovery-{'ok' if success else 'fail'} email → {email}")
    bus.log_action(AGENT_NAME, f"email_recovery_{'success' if success else 'failed'}", user_id,
                   {"email": email, "attempts": attempts, "status": status}, subject)


def _handle_first_milestone(sender: str, payload: dict):
    """Celebrate users who created their first piece of content."""
    users = payload.get("users", [])
    for email in users[:20]:
        if not email:
            continue
        # Look up user_id for throttle
        try:
            with db.get_conn() as conn:
                row = conn.execute(
                    "SELECT id, name FROM users WHERE email=%s", (email,)
                ).fetchone()
            if not row:
                continue
            user_id = row["id"]
            name = row.get("name", "")
        except Exception:
            continue
        if _is_throttled(user_id, "first_milestone"):
            continue
        fname = _first_name(name)
        subject = f"🎉 {fname}, your first piece of content is live!"
        html = f"""
<p>Hi {fname},</p>
<p>You just created your <strong>first piece of content</strong> on Social Optimize. That's the hardest step — and you just did it.</p>
<p>Here's what top creators do next:</p>
<ul>
  <li>Create 3 more variations of the same idea (takes 5 min)</li>
  <li>Schedule them across the week using the Content Calendar</li>
  <li>Check your analytics after 48h to see what's resonating</li>
</ul>
<p><a href="{config.APP_BASE_URL}/create" style="background:#7c3aed;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;display:inline-block;">Keep Creating →</a></p>
<p>You're just getting started. 🚀<br>— Social Optimize Team</p>
"""
        sent = _send_email(email, name, subject, html)
        _mark_sent(user_id, "first_milestone")
        status = "sent" if sent else "logged"
        bus.log_msg(AGENT_NAME, f"✉️  {status.upper()} first-milestone celebration → {email}")


# ── Cycle: drain any unprocessed events ─────────────────────────────────────

def _run_cycle():
    bus.log_msg(AGENT_NAME, "Isabella Cruz (Email) — scanning for pending email triggers")
    # The live bus.subscribe() handles real-time; the cycle is a catch-up safety net
    # Re-check for any unactivated users Aria may have logged
    try:
        with db.get_conn() as conn:
            # Users signed up 48-96h ago, never created a job, not throttled
            lower = (datetime.now(timezone.utc) - timedelta(hours=96)).isoformat()
            upper = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
            rows = conn.execute(
                """SELECT u.id, u.email, u.name FROM users u
                   WHERE u.created_at BETWEEN %s AND %s
                   AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.user_id = u.id)
                   LIMIT 50""",
                (lower, upper)
            ).fetchall()
        ghosts = [dict(r) for r in rows]
        sent_count = 0
        for u in ghosts:
            if not _is_throttled(u["id"], "unactivated"):
                subject, html = _email_unactivated(u)
                sent = _send_email(u["email"], u.get("name", ""), subject, html)
                _mark_sent(u["id"], "unactivated")
                sent_count += 1
        if sent_count:
            bus.log_msg(AGENT_NAME, f"✉️  Queued {sent_count} activation nudge emails (catch-up cycle)")
    except Exception as exc:
        bus.log_msg(AGENT_NAME, f"Cycle error: {exc}", "error")


def chat(user_message: str) -> str:
    try:
        import anthropic as _ant
        client = _ant.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    except Exception:
        return "Anthropic SDK not available."

    has_key = bool(_resend_key())
    context = f"""You are Isabella Cruz, Director of Email Automation at Social Optimize.

LIVE STATUS:
Resend API key configured: {has_key}
From email: {_FROM_EMAIL}
Email throttle: {THROTTLE_DAYS} days per user per category

Email sequences active:
- Churn risk (critical/high/medium) win-backs from Julian Vance
- Activation nudges for unactivated users from Aria Singh
- Payment recovery confirmations from Sterling Pierce
- First-milestone celebrations

Answer questions about email automation, deliverability, and lifecycle sequences."""

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
    # Subscribe to live bus events
    bus.subscribe("churn_risk", _handle_churn_risk)
    bus.subscribe("churn_risk_referral", _handle_churn_referral)
    bus.subscribe("unactivated_users", _handle_unactivated)
    bus.subscribe("recovery_attempted", _handle_recovery_result)
    bus.subscribe("first_milestone", _handle_first_milestone)

    while not _stop.is_set():
        _run_cycle()
        _stop.wait(CHECK_INTERVAL)


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="isabella_email")
    _thread.start()
    bus.log_msg(AGENT_NAME, "Isabella Cruz (Email) online — lifecycle email automation active")
