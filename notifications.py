"""
Notification module — email, webhook, and in-app notifications.
"""
import json
import smtplib
import threading
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import config
import database as db


def send_notification(user_id: int, event_type: str, data: dict):
    """
    Main entry point — call this from job completion handlers.
    Fires email + webhook + in-app notifications based on user settings.
    All channels run in background threads (fire-and-forget).
    """
    user = db.get_user_by_id(user_id)
    if not user:
        return

    # Create in-app notification
    title, body, link = _build_notification_content(event_type, data)
    notif_id = db.create_in_app_notification(
        user_id=user_id, title=title, body=body, link=link
    )

    # Email notification (if enabled)
    if user.get("notify_email", 1):
        t = threading.Thread(
            target=_send_email_notification,
            args=(user, event_type, title, body, notif_id),
            daemon=True,
        )
        t.start()

    # Webhook notification (if configured)
    webhook_url = user.get("webhook_url", "")
    if webhook_url:
        payload = {
            "event": event_type,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": data,
        }
        t = threading.Thread(
            target=_send_webhook_notification,
            args=(user_id, webhook_url, payload),
            daemon=True,
        )
        t.start()


def _build_notification_content(event_type: str, data: dict):
    """Build human-readable notification content."""
    if event_type == "job_complete":
        title = data.get("title") or "Video Ready"
        body = f'Your video "{title}" has finished processing.'
        link = f"/jobs/{data.get('job_id', '')}"
    elif event_type == "job_error":
        title = "Job Failed"
        body = f"A video job failed: {data.get('error', 'Unknown error')}"
        link = f"/jobs/{data.get('job_id', '')}"
    elif event_type == "schedule_posted":
        title = "Scheduled Post Published"
        body = f'Your scheduled video has been posted to {data.get("platform", "social media")}.'
        link = "/calendar"
    elif event_type == "schedule_error":
        title = "Scheduled Post Failed"
        body = f'Could not post to {data.get("platform", "social media")}: {data.get("error", "")}'
        link = "/calendar"
    elif event_type == "batch_complete":
        title = "Batch Complete"
        body = f'Batch of {data.get("total", 0)} videos finished. {data.get("completed", 0)} succeeded.'
        link = "/batch"
    elif event_type == "team_invite":
        title = "Team Invitation"
        body = f'You have been invited to join the team "{data.get("team_name", "")}".'
        link = "/team"
    elif event_type == "dub_complete":
        title = "Dubbing Complete"
        body = f'Your video has been dubbed in {data.get("language", "")}.'
        link = f"/jobs/{data.get('job_id', '')}"
    else:
        title = event_type.replace("_", " ").title()
        body = json.dumps(data)
        link = "/dashboard"
    return title, body, link


def _send_email_notification(user: dict, event_type: str, title: str, body: str, notif_id: str):
    """Send email via SMTP. Silently skips if SMTP not configured."""
    import os
    host = os.getenv("SMTP_HOST", "")
    port = int(os.getenv("SMTP_PORT", "587"))
    user_smtp = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASS", "")
    from_addr = os.getenv("SMTP_FROM", user_smtp)

    if not host or not user_smtp:
        db.log_notification(notif_id, user["id"], event_type, "email", "skipped_no_config")
        return

    recipient = user.get("email", "")
    if not recipient:
        return

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Social Optimize: {title}"
        msg["From"] = from_addr
        msg["To"] = recipient

        text_part = MIMEText(f"{title}\n\n{body}\n\nLog in: {config.APP_BASE_URL}", "plain")
        html_part = MIMEText(
            f"""<html><body style="font-family:sans-serif;background:#111;color:#eee;padding:24px;">
            <div style="max-width:560px;margin:0 auto;">
              <h2 style="color:#ff3b30;">{title}</h2>
              <p style="color:#ccc;">{body}</p>
              <a href="{config.APP_BASE_URL}" style="display:inline-block;margin-top:16px;padding:10px 20px;background:#ff3b30;color:#fff;text-decoration:none;border-radius:6px;">
                Open Social Optimize
              </a>
            </div></body></html>""",
            "html",
        )
        msg.attach(text_part)
        msg.attach(html_part)

        with smtplib.SMTP(host, port) as server:
            server.ehlo()
            server.starttls()
            server.login(user_smtp, password)
            server.sendmail(from_addr, recipient, msg.as_string())

        db.log_notification(notif_id, user["id"], event_type, "email", "sent")
    except Exception as e:
        db.log_notification(notif_id, user["id"], event_type, "email", f"error: {e}")


def _send_webhook_notification(user_id: int, webhook_url: str, payload: dict):
    """POST JSON to webhook URL. Fire-and-forget."""
    try:
        import requests as req
        resp = req.post(
            webhook_url,
            json=payload,
            timeout=10,
            headers={"Content-Type": "application/json", "User-Agent": "SocialOptimizeMachine/1.0"},
        )
        status = "sent" if resp.status_code < 400 else f"http_{resp.status_code}"
    except Exception as e:
        status = f"error: {str(e)[:100]}"

    db.log_notification(None, user_id, payload.get("event", ""), "webhook", status)
