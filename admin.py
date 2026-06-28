"""Admin Blueprint — client management, provisioning, audit log, settings."""
import os
import secrets
import shutil
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import Blueprint, render_template, request, jsonify, abort
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash

import database as db
import config
from agent_dispatch import get_system_status

admin_bp = Blueprint("admin", __name__)


def _require_admin():
    if not current_user.is_authenticated or not current_user.is_admin:
        abort(403)


def _send_email(to: str, subject: str, html: str, text: str):
    host = config.SMTP_HOST
    port = config.SMTP_PORT
    user = config.SMTP_USER
    pw = config.SMTP_PASS
    from_addr = config.SMTP_FROM
    if not host or not user:
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to
        msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP(host, port) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(user, pw)
            srv.sendmail(from_addr, to, msg.as_string())
        return True
    except Exception:
        return False


# ── Dashboard ─────────────────────────────────────────────────────────────────

@admin_bp.route("/admin")
@login_required
def admin_dashboard():
    _require_admin()
    stats = db.get_admin_stats()
    users = db.get_all_users(limit=500)
    return render_template("admin.html", users=users, **stats)


# ── User detail ───────────────────────────────────────────────────────────────

@admin_bp.route("/admin/user/<int:uid>")
@login_required
def admin_user_detail(uid):
    _require_admin()
    user = db.get_user_by_id(uid)
    if not user:
        abort(404)
    jobs = db.get_user_jobs_summary(uid)
    return render_template("admin/user.html", u=user, jobs=jobs)


# ── API: Change tier ──────────────────────────────────────────────────────────

@admin_bp.route("/api/admin/user/<int:uid>/tier", methods=["POST"])
@login_required
def admin_set_tier(uid):
    _require_admin()
    tier = request.json.get("tier", "").strip()
    if tier not in ("free", "starter", "creator", "agency"):
        return jsonify({"ok": False, "error": "Invalid tier"}), 400
    db.update_user(uid, subscription_tier=tier)
    db.log_audit(current_user.id, "set_tier", uid, {"tier": tier})
    return jsonify({"ok": True})


# ── API: Change status ────────────────────────────────────────────────────────

@admin_bp.route("/api/admin/user/<int:uid>/status", methods=["POST"])
@login_required
def admin_set_status(uid):
    _require_admin()
    status = request.json.get("status", "").strip()
    if status not in ("active", "canceled", "past_due", "suspended"):
        return jsonify({"ok": False, "error": "Invalid status"}), 400
    db.update_user(uid, subscription_status=status)
    db.log_audit(current_user.id, "set_status", uid, {"status": status})
    return jsonify({"ok": True})


# ── API: Reset usage ──────────────────────────────────────────────────────────

@admin_bp.route("/api/admin/user/<int:uid>/reset-usage", methods=["POST"])
@login_required
def admin_reset_usage(uid):
    _require_admin()
    db.update_user(uid, videos_used=0, credits_used=0, period_start=datetime.now().strftime("%Y-%m-01"))
    db.log_audit(current_user.id, "reset_usage", uid)
    return jsonify({"ok": True})


# ── API: Toggle admin ─────────────────────────────────────────────────────────

@admin_bp.route("/api/admin/user/<int:uid>/toggle-admin", methods=["POST"])
@login_required
def admin_toggle_admin(uid):
    _require_admin()
    if uid == current_user.id:
        return jsonify({"ok": False, "error": "Cannot change your own admin status"}), 400
    user = db.get_user_by_id(uid)
    if not user:
        return jsonify({"ok": False, "error": "User not found"}), 404
    new_val = 0 if user.get("is_admin") else 1
    db.update_user(uid, is_admin=new_val)
    db.log_audit(current_user.id, "toggle_admin", uid, {"is_admin": new_val})
    return jsonify({"ok": True, "is_admin": bool(new_val)})


# ── API: Provision new client ─────────────────────────────────────────────────

@admin_bp.route("/api/admin/provision", methods=["POST"])
@login_required
def admin_provision():
    _require_admin()
    data = request.json or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    tier = (data.get("tier") or "free").strip()
    send_invite = bool(data.get("send_invite", True))

    if not email:
        return jsonify({"ok": False, "error": "Email is required"}), 400
    if tier not in ("free", "starter", "creator", "agency"):
        return jsonify({"ok": False, "error": "Invalid tier"}), 400
    if db.get_user_by_email(email):
        return jsonify({"ok": False, "error": "An account with that email already exists"}), 409

    temp_pw = secrets.token_urlsafe(12)
    pw_hash = generate_password_hash(temp_pw)
    user_id = db.create_user(email=email, password_hash=pw_hash, name=name or email.split("@")[0])
    if tier != "free":
        db.update_user(user_id, subscription_tier=tier)

    db.log_audit(current_user.id, "provision_user", user_id, {"email": email, "tier": tier})

    email_sent = False
    if send_invite and config.SMTP_HOST and config.SMTP_USER:
        login_url = f"{config.APP_BASE_URL}/auth/login"
        html = f"""
        <html><body style="font-family:sans-serif;background:#111;color:#eee;padding:32px;">
        <div style="max-width:560px;margin:0 auto;">
          <h1 style="color:#d4a017;font-size:28px;margin-bottom:8px;">Social Money</h1>
          <p style="color:#ccc;font-size:16px;">Hi {name or email},</p>
          <p style="color:#ccc;">Your account has been created on the <strong style="color:#fff;">{tier.title()}</strong> plan.</p>
          <table style="background:#1a1a1a;border:1px solid #333;border-radius:12px;padding:20px;margin:20px 0;width:100%;">
            <tr><td style="color:#888;padding:4px 0;">Email</td><td style="color:#fff;">{email}</td></tr>
            <tr><td style="color:#888;padding:4px 0;">Temp Password</td><td style="color:#d4a017;font-family:monospace;font-size:16px;">{temp_pw}</td></tr>
            <tr><td style="color:#888;padding:4px 0;">Plan</td><td style="color:#fff;">{tier.title()}</td></tr>
          </table>
          <p style="color:#aaa;font-size:13px;">Please log in and change your password from the Settings page.</p>
          <a href="{login_url}" style="display:inline-block;margin-top:8px;padding:12px 28px;background:#d4a017;color:#000;font-weight:700;text-decoration:none;border-radius:10px;font-size:15px;">
            Log In Now
          </a>
        </div></body></html>"""
        text = f"Social Money\n\nYour account:\nEmail: {email}\nTemp Password: {temp_pw}\nPlan: {tier.title()}\n\nLog in: {login_url}"
        email_sent = _send_email(email, "Your Social Money account is ready", html, text)

    return jsonify({
        "ok": True,
        "user_id": user_id,
        "temp_password": temp_pw,
        "email_sent": email_sent,
    })


# ── API: Generate invite link ─────────────────────────────────────────────────

@admin_bp.route("/api/admin/invite", methods=["POST"])
@login_required
def admin_create_invite():
    """Generate a one-time invite link the admin can share with a tester."""
    _require_admin()
    from auth import _invite_store
    data = request.json or {}
    tier = (data.get("tier") or "free").strip()
    if tier not in ("free", "starter", "creator", "agency"):
        return jsonify({"ok": False, "error": "Invalid tier"}), 400
    token = secrets.token_urlsafe(24)
    expires = (datetime.utcnow() + timedelta(hours=48)).isoformat()
    _invite_store[token] = {"tier": tier, "expires": expires}
    link = f"{config.APP_BASE_URL}/auth/invite/{token}"
    return jsonify({"ok": True, "link": link, "tier": tier, "expires_hours": 48})


# ── API: Audit log ────────────────────────────────────────────────────────────

@admin_bp.route("/api/admin/audit-log")
@login_required
def admin_audit_log():
    _require_admin()
    limit = int(request.args.get("limit", 100))
    return jsonify(db.get_audit_log(limit=limit))


# ── API: Stats refresh ────────────────────────────────────────────────────────

@admin_bp.route("/api/admin/stats")
@login_required
def admin_stats():
    _require_admin()
    return jsonify(db.get_admin_stats())


# ── Settings / Env Vars ──────────────────────────────────────────────────────

_ENV_VAR_MAP = [
    ("Core AI", [
        ("ANTHROPIC_API_KEY", "All AI agents — scripts, vision, ad copy"),
        ("ELEVENLABS_API_KEY", "AI voiceovers"),
        ("DEEPSEEK_API_KEY", "DeepSeek AI model (optional)"),
        ("GROQ_API_KEY", "Groq AI model (optional)"),
        ("OPENROUTER_API_KEY", "OpenRouter AI models (optional)"),
    ]),
    ("Google / YouTube", [
        ("GOOGLE_API_KEY", "Competitor tracker (YouTube Data API)"),
        ("YOUTUBE_CLIENT_ID", "YouTube OAuth — upload/broadcast"),
        ("YOUTUBE_CLIENT_SECRET", "YouTube OAuth — upload/broadcast"),
    ]),
    ("Higgsfield", [
        ("HIGGSFIELD_MCP_TOKEN", "Higgsfield AI video generation"),
    ]),
    ("Media", [
        ("PIXABAY_API_KEY", "Free stock footage"),
        ("FREESOUND_API_KEY", "Free sound/loop library"),
        ("REPLICATE_API_TOKEN", "Replicate AI models"),
    ]),
    ("Stripe Payments", [
        ("STRIPE_SECRET_KEY", "Subscription billing"),
        ("STRIPE_PUBLISHABLE_KEY", "Checkout UI"),
        ("STRIPE_WEBHOOK_SECRET", "Payment webhooks"),
    ]),
    ("Social Platforms", [
        ("TIKTOK_CLIENT_KEY", "TikTok"),
        ("TIKTOK_CLIENT_SECRET", "TikTok"),
        ("INSTAGRAM_ACCESS_TOKEN", "Instagram"),
        ("FACEBOOK_APP_ID", "Facebook"),
        ("FACEBOOK_APP_SECRET", "Facebook"),
        ("TWITTER_CLIENT_ID", "Twitter / X"),
        ("TWITTER_CLIENT_SECRET", "Twitter / X"),
        ("TWITCH_CLIENT_ID", "Twitch streaming"),
        ("TWITCH_CLIENT_SECRET", "Twitch streaming"),
        ("THREADS_APP_ID", "Threads"),
        ("SNAP_CLIENT_ID", "Snapchat"),
        ("LINKEDIN_CLIENT_ID", "LinkedIn"),
        ("PINTEREST_ACCESS_TOKEN", "Pinterest"),
    ]),
    ("Notifications", [
        ("SMTP_HOST", "Email notifications"),
        ("SMTP_USER", "Email login"),
        ("SMTP_PASS", "Email password"),
        ("TWILIO_ACCOUNT_SID", "SMS notifications"),
        ("TWILIO_AUTH_TOKEN", "SMS notifications"),
    ]),
]


def load_env_from_db():
    """Load saved API keys from DB into os.environ and config on startup."""
    for _, vlist in _ENV_VAR_MAP:
        for var_name, _ in vlist:
            val = db.get_setting(f"env:{var_name}")
            if val and not os.getenv(var_name):
                os.environ[var_name] = val
                if hasattr(config, var_name):
                    setattr(config, var_name, val)


@admin_bp.route("/admin/settings")
@login_required
def admin_settings():
    _require_admin()
    groups = []
    total_set = 0
    total_vars = 0
    for group_name, vars_list in _ENV_VAR_MAP:
        items = []
        for var_name, description in vars_list:
            val = os.getenv(var_name, "") or db.get_setting(f"env:{var_name}") or ""
            is_set = bool(val)
            if is_set:
                total_set += 1
            total_vars += 1
            masked = ""
            if is_set:
                if len(val) <= 8:
                    masked = "••••••"
                else:
                    masked = val[:4] + "••••" + val[-4:]
            items.append({"name": var_name, "description": description,
                          "is_set": is_set, "masked": masked})
        groups.append({"name": group_name, "vars": items})
    return render_template("admin/settings.html", groups=groups,
                           total_set=total_set, total_vars=total_vars)


@admin_bp.route("/api/admin/env", methods=["POST"])
@login_required
def admin_set_env():
    _require_admin()
    data = request.get_json(silent=True) or {}
    var_name = (data.get("name") or "").strip()
    var_value = (data.get("value") or "").strip()
    if not var_name:
        return jsonify({"error": "Variable name required"}), 400
    allowed = {v for _, vlist in _ENV_VAR_MAP for v, _ in vlist}
    if var_name not in allowed:
        return jsonify({"error": "Unknown variable"}), 400
    os.environ[var_name] = var_value
    if hasattr(config, var_name):
        setattr(config, var_name, var_value)
    db.set_setting(f"env:{var_name}", var_value)
    return jsonify({"ok": True, "name": var_name,
                    "masked": var_value[:4] + "••••" + var_value[-4:] if len(var_value) > 8 else "••••••"})


# ── API: Overview ────────────────────────────────────────────────────────────

@admin_bp.route("/api/admin/overview")
@login_required
def admin_overview():
    _require_admin()
    with db.get_conn() as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        today = datetime.utcnow().strftime("%Y-%m-%d")
        new_today = conn.execute("SELECT COUNT(*) FROM users WHERE created_at >= ?", (today,)).fetchone()[0]
        total_jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        jobs_today = conn.execute("SELECT COUNT(*) FROM jobs WHERE created_at >= ?", (today,)).fetchone()[0]
        completed = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='done'").fetchone()[0]
        failed = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='error'").fetchone()[0]
        tiers = {}
        for row in conn.execute("SELECT COALESCE(subscription_tier,'free') AS t, COUNT(*) AS c FROM users GROUP BY t"):
            tiers[row["t"]] = row["c"]
        try:
            total_media = conn.execute("SELECT COUNT(*) FROM media_files").fetchone()[0]
            media_size = conn.execute("SELECT COALESCE(SUM(file_size),0) FROM media_files").fetchone()[0]
        except Exception:
            total_media, media_size = 0, 0
        try:
            total_campaigns = conn.execute("SELECT COUNT(*) FROM monetizer_campaigns").fetchone()[0]
        except Exception:
            total_campaigns = 0
        try:
            total_actions = conn.execute("SELECT COUNT(*) FROM agent_logs").fetchone()[0]
        except Exception:
            total_actions = 0
    return jsonify({
        "total_users": total_users, "new_users_today": new_today,
        "total_jobs": total_jobs, "jobs_today": jobs_today,
        "completed_jobs": completed, "failed_jobs": failed,
        "users_by_tier": tiers,
        "total_media": total_media, "media_size_bytes": media_size,
        "total_campaigns": total_campaigns, "total_actions": total_actions,
    })


# ── API: Revenue ─────────────────────────────────────────────────────────────

@admin_bp.route("/api/admin/revenue")
@login_required
def admin_revenue():
    _require_admin()
    tier_prices = {"free": 0, "starter": 29, "creator": 79, "agency": 199}
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT COALESCE(subscription_tier,'free') AS tier, COUNT(*) AS cnt FROM users GROUP BY tier"
        ).fetchall()
    breakdown = {}
    mrr = 0
    for r in rows:
        t, cnt = r["tier"], r["cnt"]
        price = tier_prices.get(t, 0)
        rev = price * cnt
        mrr += rev
        breakdown[t] = {"users": cnt, "price": price, "revenue": rev}
    return jsonify({"mrr": mrr, "arr": mrr * 12, "breakdown": breakdown})


# ── API: Users (paginated) ───────────────────────────────────────────────────

@admin_bp.route("/api/admin/users")
@login_required
def admin_users_api():
    _require_admin()
    limit = int(request.args.get("limit", 25))
    offset = int(request.args.get("offset", 0))
    search = request.args.get("search", "").strip()
    tier_filter = request.args.get("tier", "").strip()
    with db.get_conn() as conn:
        where, params = [], []
        if search:
            where.append("(name LIKE ? OR email LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])
        if tier_filter:
            where.append("COALESCE(subscription_tier,'free') = ?")
            params.append(tier_filter)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        total = conn.execute(f"SELECT COUNT(*) FROM users {clause}", params).fetchone()[0]
        users = conn.execute(
            f"SELECT * FROM users {clause} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [limit, offset]
        ).fetchall()
    return jsonify({
        "total": total,
        "users": [{
            "id": u["id"], "name": u["name"], "email": u["email"],
            "tier": u["subscription_tier"] or "free",
            "videos_used_this_month": u["videos_used"] or 0,
            "is_admin": u["is_admin"] or 0,
            "created_at": u["created_at"] or "",
        } for u in users],
    })


@admin_bp.route("/api/admin/users/<int:uid>", methods=["PATCH"])
@login_required
def admin_update_user(uid):
    _require_admin()
    data = request.get_json(silent=True) or {}
    updates = {}
    if "tier" in data:
        updates["subscription_tier"] = data["tier"]
    if "is_admin" in data:
        updates["is_admin"] = int(data["is_admin"])
    if "name" in data:
        updates["name"] = data["name"]
    if updates:
        db.update_user(uid, **updates)
    return jsonify({"ok": True})


# ── API: Jobs / Content ──────────────────────────────────────────────────────

@admin_bp.route("/api/admin/jobs")
@login_required
def admin_jobs_api():
    _require_admin()
    with db.get_conn() as conn:
        by_status = {}
        for row in conn.execute("SELECT status, COUNT(*) AS c FROM jobs GROUP BY status"):
            by_status[row["status"]] = row["c"]
        top_niches = {}
        for row in conn.execute("SELECT COALESCE(format,'general') AS n, COUNT(*) AS c FROM jobs GROUP BY n ORDER BY c DESC LIMIT 10"):
            top_niches[row["n"]] = row["c"]
        daily = []
        for row in conn.execute(
            "SELECT DATE(created_at) AS date, COUNT(*) AS count FROM jobs "
            "WHERE created_at >= DATE('now','-7 days') GROUP BY DATE(created_at) ORDER BY date"
        ):
            daily.append({"date": row["date"], "count": row["count"]})
    return jsonify({"by_status": by_status, "top_niches": top_niches, "daily_7d": daily})


# ── API: Growth ──────────────────────────────────────────────────────────────

@admin_bp.route("/api/admin/growth")
@login_required
def admin_growth_api():
    _require_admin()
    with db.get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        paid = conn.execute(
            "SELECT COUNT(*) FROM users WHERE subscription_tier IN ('starter','creator','agency')"
        ).fetchone()[0]
        rate = round(paid / max(total, 1) * 100, 1)
        signups_7d, signups_30d = [], []
        for row in conn.execute(
            "SELECT DATE(created_at) AS date, COUNT(*) AS count FROM users "
            "WHERE created_at >= DATE('now','-7 days') GROUP BY DATE(created_at) ORDER BY date"
        ):
            signups_7d.append({"date": row["date"], "count": row["count"]})
        for row in conn.execute(
            "SELECT DATE(created_at) AS date, COUNT(*) AS count FROM users "
            "WHERE created_at >= DATE('now','-30 days') GROUP BY DATE(created_at) ORDER BY date"
        ):
            signups_30d.append({"date": row["date"], "count": row["count"]})
    return jsonify({
        "total_users": total, "paid_users": paid, "conversion_rate": rate,
        "signups_7d": signups_7d, "signups_30d": signups_30d,
    })


# ── API: System Health ───────────────────────────────────────────────────────

@admin_bp.route("/api/admin/health")
@login_required
def admin_health_api():
    _require_admin()
    db_path = os.path.join(os.path.dirname(__file__), "social_optimize.db")
    db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    upload_dir = os.path.join(os.path.dirname(__file__), "static", "uploads")
    upload_size = 0
    if os.path.isdir(upload_dir):
        for root, _, files in os.walk(upload_dir):
            for f in files:
                upload_size += os.path.getsize(os.path.join(root, f))
    disk = shutil.disk_usage("/")
    return jsonify({
        "db_size_bytes": db_size,
        "upload_size_bytes": upload_size,
        "disk_total_bytes": disk.total,
        "disk_used_bytes": disk.used,
        "disk_free_bytes": disk.free,
        "disk_pct_used": round(disk.used / disk.total * 100, 1),
    })


# ── API: Config ──────────────────────────────────────────────────────────────

@admin_bp.route("/api/admin/config")
@login_required
def admin_config_api():
    _require_admin()
    api_keys = {}
    for _, vlist in _ENV_VAR_MAP:
        for var_name, _ in vlist:
            val = os.getenv(var_name, "") or db.get_setting(f"env:{var_name}") or ""
            api_keys[var_name] = "configured" if val else "missing"
    tiers = {
        "free":    {"label": "Free",    "price_monthly": 0,      "videos_per_month": 3,   "higgsfield_credits": 10,   "features": ["3 videos/mo", "3 platforms", "Basic AI scripts", "Editing Room"]},
        "basic":   {"label": "Basic",   "price_monthly": 9.99,  "videos_per_month": 7,   "higgsfield_credits": 50,   "features": ["5 platforms", "7 videos/mo", "Template Library", "Editing Room"]},
        "starter": {"label": "Starter", "price_monthly": 29.99, "videos_per_month": 15,  "higgsfield_credits": 150,  "features": ["8 platforms", "15 videos/mo", "Production Studio", "Commercial Studio", "Music Studio"]},
        "creator": {"label": "Creator", "price_monthly": 79.99, "videos_per_month": 50,  "higgsfield_credits": 500,  "features": ["Everything in Starter", "50 videos/mo", "Hollywood AI", "AI Clipper", "Advanced analytics"]},
        "agency":  {"label": "Agency",  "price_monthly": 199.99,"videos_per_month": 125, "higgsfield_credits": 2000, "features": ["Everything in Creator", "125 videos/mo", "White-label", "API access", "Team (5 seats)"]},
    }
    return jsonify({"api_keys": api_keys, "tiers": tiers})


# ── API: Agents ──────────────────────────────────────────────────────────────

@admin_bp.route("/api/admin/agents")
@login_required
def admin_agents_api():
    _require_admin()
    agents = db.get_agents()
    stats = db.get_agent_stats()
    return jsonify({"agents": agents, "stats": stats})


@admin_bp.route("/api/admin/system-status")
@login_required
def admin_system_status():
    _require_admin()
    return jsonify(get_system_status())


@admin_bp.route("/api/admin/agents/<agent_id>")
@login_required
def admin_agent_detail(agent_id):
    _require_admin()
    agent = db.get_agent(agent_id)
    if not agent:
        return jsonify({"error": "Agent not found"}), 404
    logs = db.get_agent_logs(agent_id, limit=20)
    return jsonify({"agent": agent, "logs": logs})


@admin_bp.route("/api/admin/agents/<agent_id>/status", methods=["PATCH"])
@login_required
def admin_agent_set_status(agent_id):
    _require_admin()
    data = request.get_json(silent=True) or {}
    status = data.get("status", "online")
    db.update_agent(agent_id, status=status)
    return jsonify({"ok": True})


@admin_bp.route("/api/admin/agents/<agent_id>/dispatch", methods=["POST"])
@login_required
def admin_agent_dispatch(agent_id):
    _require_admin()
    data = request.get_json(silent=True) or {}
    task = data.get("task", "")
    db.add_agent_log(agent_id, "task_dispatched", task)
    return jsonify({"ok": True})


@admin_bp.route("/api/admin/agents/logs")
@login_required
def admin_agent_logs():
    _require_admin()
    limit = int(request.args.get("limit", 30))
    with db.get_conn() as conn:
        try:
            logs = conn.execute(
                "SELECT * FROM agent_logs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return jsonify({"logs": [dict(l) for l in logs]})
        except Exception:
            return jsonify({"logs": []})
