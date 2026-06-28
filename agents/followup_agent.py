"""
Follow-up Agent — background worker that sends scheduled follow-up emails
to agency clients and updates lead statuses.

Runs every FOLLOWUP_CHECK_INTERVAL seconds (default: 5 minutes).
"""
from __future__ import annotations
import threading
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone

FOLLOWUP_CHECK_INTERVAL = 300

_thread: threading.Thread | None = None
_stop = threading.Event()


def _send_followup_email(followup: dict) -> bool:
    import config
    host = config.SMTP_HOST
    port = int(config.SMTP_PORT or 587)
    user = config.SMTP_USER
    password = config.SMTP_PASS
    if not host or not user:
        return False

    recipient = followup.get("client_email", "")
    if not recipient:
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = followup.get("subject", "Following up")
        msg["From"] = user
        msg["To"] = recipient

        body_html = followup.get("body", "")
        if not body_html.strip().startswith("<"):
            body_html = f"<p>{body_html}</p>"

        html = f"""<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">
        <div style="border-bottom:2px solid #7c3aed;padding-bottom:12px;margin-bottom:20px;">
            <strong style="color:#7c3aed;font-size:14px;">Social Optimize</strong>
        </div>
        {body_html}
        <div style="margin-top:30px;padding-top:12px;border-top:1px solid #e5e7eb;font-size:11px;color:#9ca3af;">
            Sent via Social Optimize Agency
        </div>
        </body></html>"""

        msg.attach(MIMEText(followup.get("body", ""), "plain"))
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(host, port) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(user, [recipient], msg.as_string())
        return True
    except Exception as e:
        print(f"[FollowupAgent] Email failed: {e}")
        return False


def _process_followups() -> None:
    import database as db

    due = db.get_due_followups()
    for fu in due:
        if fu.get("type") == "email":
            ok = _send_followup_email(fu)
            now = datetime.now(timezone.utc).isoformat()
            if ok:
                db.update_agency_followup(fu["id"], {"status": "sent", "sent_at": now})
                if fu.get("client_id"):
                    db.update_agency_client(fu["user_id"], fu["client_id"], {"last_contact": now})
            else:
                db.update_agency_followup(fu["id"], {"status": "failed"})
        else:
            db.update_agency_followup(fu["id"], {"status": "sent", "sent_at": datetime.now(timezone.utc).isoformat()})


def _auto_schedule_lead_followups() -> None:
    """Auto-create follow-up sequences for new leads that don't have any scheduled."""
    import database as db
    from datetime import timedelta

    try:
        all_users_leads = []
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT c.* FROM agency_clients c WHERE c.status='lead' AND c.id NOT IN (SELECT DISTINCT client_id FROM agency_followups WHERE client_id IS NOT NULL)"
            ).fetchall()
            all_users_leads = [db.row_to_dict(r) for r in rows]

        now = datetime.now(timezone.utc)
        for lead in all_users_leads:
            if not lead.get("email"):
                continue
            sequences = [
                (1, "Introduction — Let's Create Amazing Content Together",
                 f"Hi {lead['name'].split()[0] if lead.get('name') else 'there'},\n\nI noticed your brand and I think we could create some incredible content together using AI-powered video production.\n\nWould you be open to a quick 15-minute call this week to explore how we can help grow your audience?\n\nBest regards"),
                (3, "Quick Follow-up — Content Ideas for Your Brand",
                 f"Hi {lead['name'].split()[0] if lead.get('name') else 'there'},\n\nJust following up on my previous message. I put together a few content ideas specifically for your industry that I'd love to share.\n\nOur AI platform can produce professional-quality videos at a fraction of the traditional cost.\n\nWould love to show you a demo."),
                (7, "Last Check-in — Special Offer",
                 f"Hi {lead['name'].split()[0] if lead.get('name') else 'there'},\n\nI wanted to reach out one more time. We're currently offering new clients a complimentary content strategy session plus 3 free AI-generated videos.\n\nIf the timing isn't right, no worries at all. Just reply and let me know.\n\nBest regards"),
            ]
            for days_offset, subject, body in sequences:
                scheduled = (now + timedelta(days=days_offset)).isoformat()
                db.create_agency_followup(lead["user_id"], {
                    "client_id": lead["id"],
                    "type": "email",
                    "subject": subject,
                    "body": body,
                    "scheduled_at": scheduled,
                    "template": "lead_sequence",
                })
    except Exception as e:
        print(f"[FollowupAgent] Auto-schedule error: {e}")


def _run():
    while not _stop.wait(FOLLOWUP_CHECK_INTERVAL):
        try:
            _process_followups()
            _auto_schedule_lead_followups()
        except Exception as e:
            print(f"[FollowupAgent] Error: {e}")


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_run, daemon=True, name="followup-agent")
    _thread.start()
    print("[FollowupAgent] Started — checking every 5 min")
